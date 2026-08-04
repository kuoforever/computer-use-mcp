"""Deterministic provider script for the bounded Chrome-to-Word Demo.

The provider is deliberately not a model. It translates only fixed, controlled
fixture evidence into the next reviewed tool call. Runner remains the sole
policy, approval, grounding, budget, persistence, and MCP dispatch authority.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from typing import Callable, Mapping, Sequence

from .tool_registry import ToolSpec
from .types import (
    JSONValue,
    CallIdentity,
    DispatchCertainty,
    LedgerEvent,
    LedgerEventKind,
    MemoryContextItem,
    ModelProviderPort,
    ModelTurn,
    ModelUsage,
    ProviderContinuationStrategy,
    ToolCall,
    ToolResult,
    ToolResultStatus,
    to_json_value,
)
from .workflow_checklist import (
    WorkflowChecklist,
    WorkflowDefinition,
    WorkflowStatus,
    WorkflowStepDefinition,
)

DEMO_COMPLETE_TEXT = "CONTROLLED_CROSS_APP_DEMO_COMPLETE"
DEMO_TYPED_MARKER = "VERIFIED SOURCE BRIEF"
DEMO_MAX_PROPOSAL_CORRECTIONS = 2
_NOTE_TOKEN = re.compile(r"[a-z0-9]{4,}")
_NOTE_STOP_WORDS = frozenset(
    {
        "about",
        "after",
        "before",
        "document",
        "from",
        "into",
        "microsoft",
        "source",
        "their",
        "there",
        "these",
        "this",
        "using",
        "with",
        "word",
    }
)
DEMO_WORKFLOW = WorkflowDefinition(
    workflow_id="chrome_word_research",
    title="Public-source research brief update",
    steps=(
        WorkflowStepDefinition(
            "prepare_workspace",
            "Prepare the controlled demo workspace",
            "Demo setup",
        ),
        WorkflowStepDefinition(
            "review_public_source",
            "Review the public collaboration guide",
            "Google Chrome",
        ),
        WorkflowStepDefinition(
            "open_research_brief",
            "Open the research brief",
            "Microsoft Word",
        ),
        WorkflowStepDefinition(
            "add_verified_note",
            "Add the verified source note",
            "Microsoft Word",
        ),
        WorkflowStepDefinition(
            "save_research_brief",
            "Save the research brief",
            "Microsoft Word",
        ),
        WorkflowStepDefinition(
            "verify_saved_document",
            "Verify the saved document",
            "Microsoft Word",
        ),
    ),
)
_REF = re.compile(r'^(ref_[1-9][0-9]*) \| edit "页面 1 内容" \|', re.MULTILINE)

_DEMO_STEP_IDS = tuple(step.step_id for step in DEMO_WORKFLOW.steps)


def _demo_completed_count(provider_step: int) -> int:
    """Return how many fixed chapters one provider boundary has resolved."""

    if provider_step == 18:
        return len(_DEMO_STEP_IDS)
    if provider_step <= 5:
        return 1
    if provider_step <= 8:
        return 2
    if provider_step <= 14:
        return 3
    if provider_step == 15:
        return 4
    return 5


def project_demo_workflow(
    provider_step: int,
    *,
    status: WorkflowStatus = WorkflowStatus.RUNNING,
) -> WorkflowChecklist:
    """Map one fixed provider boundary to the six Host-owned Demo chapters."""

    if (
        isinstance(provider_step, bool)
        or not isinstance(provider_step, int)
        or not 0 <= provider_step <= 18
    ):
        raise ValueError("controlled Demo provider step is invalid")
    if not isinstance(status, WorkflowStatus):
        raise ValueError("controlled Demo workflow status is invalid")
    completed_count = _demo_completed_count(provider_step)
    if status is WorkflowStatus.CANCELLED:
        # A cancelled Demo keeps its resolved prefix and claims no current
        # chapter. It must never promote the interrupted chapter to completed.
        return DEMO_WORKFLOW.project(
            status,
            completed_step_ids=_DEMO_STEP_IDS[:completed_count],
        )
    if provider_step == 18:
        if status is not WorkflowStatus.READY:
            raise ValueError("completed controlled Demo must be ready")
        return DEMO_WORKFLOW.project(
            status,
            completed_step_ids=_DEMO_STEP_IDS,
        )
    if status is WorkflowStatus.READY:
        raise ValueError("incomplete controlled Demo cannot be ready")
    return DEMO_WORKFLOW.project(
        status,
        completed_step_ids=_DEMO_STEP_IDS[:completed_count],
        current_step_id=_DEMO_STEP_IDS[completed_count],
    )


class CrossAppDemoError(RuntimeError):
    """Fixed failure that never embeds desktop or typed content."""


class ModelDrivenDemoError(RuntimeError):
    """Fail-closed rejection of an out-of-contract model Demo turn."""


@dataclass(frozen=True)
class DemoProposalRejection:
    """One bounded, content-free Host rejection before desktop dispatch."""

    attempt: int
    max_attempts: int
    code: str
    tool_names: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            isinstance(self.attempt, bool)
            or not isinstance(self.attempt, int)
            or isinstance(self.max_attempts, bool)
            or not isinstance(self.max_attempts, int)
            or not 1 <= self.attempt <= self.max_attempts
            or not isinstance(self.code, str)
            or not self.code.startswith("DEMO_MODEL_")
            or not isinstance(self.tool_names, tuple)
            or not self.tool_names
            or not all(isinstance(name, str) and name for name in self.tool_names)
        ):
            raise ValueError("Demo proposal rejection is invalid")


def _latest_result(ledger: Sequence[LedgerEvent]) -> ToolResult | None:
    for event in reversed(ledger):
        if event.kind is LedgerEventKind.TOOL_RESULT:
            return event.tool_result
    return None


def _calls_by_identity(
    ledger: Sequence[LedgerEvent],
) -> dict[CallIdentity, LedgerEvent]:
    calls: dict[CallIdentity, LedgerEvent] = {}
    for event in ledger:
        if event.kind is LedgerEventKind.TOOL_CALL and event.identity is not None:
            calls[event.identity] = event
    return calls


def _successful_results(
    ledger: Sequence[LedgerEvent],
) -> list[tuple[int, ToolResult, LedgerEvent | None]]:
    calls = _calls_by_identity(ledger)
    results: list[tuple[int, ToolResult, LedgerEvent | None]] = []
    for index, event in enumerate(ledger):
        if (
            event.kind is LedgerEventKind.TOOL_RESULT
            and event.identity is not None
            and event.tool_result is not None
            and event.tool_result.ok
        ):
            results.append((index, event.tool_result, calls.get(event.identity)))
    return results


def _summary_values(call_event: LedgerEvent | None) -> Mapping[str, object]:
    if call_event is None or call_event.safe_argument_summary is None:
        return {}
    return call_event.safe_argument_summary.values


def _last_exact_windows(
    ledger: Sequence[LedgerEvent],
    *,
    chrome_title_fragment: str,
    word_title_fragment: str,
) -> tuple[str, str] | None:
    for _, result, _ in reversed(_successful_results(ledger)):
        if result.tool_name != "list_windows":
            continue
        try:
            return (
                _window_id(
                    result.sanitized_text,
                    owner="chrome.exe",
                    title_fragment=chrome_title_fragment,
                ),
                _window_id(
                    result.sanitized_text,
                    owner="winword.exe",
                    title_fragment=word_title_fragment,
                ),
            )
        except CrossAppDemoError:
            return None
    return None


def _latest_scoped_observation(
    ledger: Sequence[LedgerEvent],
) -> tuple[str, str, str] | None:
    for _, result, call_event in reversed(_successful_results(ledger)):
        if result.tool_name not in {"ui_snapshot", "document_text"}:
            continue
        scope = _summary_values(call_event).get("scope")
        if isinstance(scope, str):
            return result.tool_name, scope, result.sanitized_text
    return None


def _successful_key_indexes(
    ledger: Sequence[LedgerEvent], combo: str
) -> list[int]:
    return [
        index
        for index, result, call_event in _successful_results(ledger)
        if result.tool_name == "key"
        and _summary_values(call_event).get("combo") == combo
    ]


def _contains_required_text(observed: str, required: str) -> bool:
    return required.replace("\r\n", "\n").replace("\r", "\n").strip() in observed.replace(
        "\r\n", "\n"
    ).replace("\r", "\n")


def _post_save_verified(
    ledger: Sequence[LedgerEvent],
    *,
    word_window_id: str | None = None,
    required_text: str = DEMO_TYPED_MARKER,
) -> bool:
    saves = _successful_key_indexes(ledger, "Ctrl+S")
    if not saves:
        return False
    save_index = saves[-1]
    return any(
        index > save_index
        and result.tool_name == "document_text"
        and _contains_required_text(result.sanitized_text, required_text)
        and (
            word_window_id is None
            or _summary_values(call_event).get("scope") == word_window_id
        )
        for index, result, call_event in _successful_results(ledger)
    )


def _valid_demo_ocr(text: str) -> bool:
    try:
        payload = json.loads(text)
    except (TypeError, ValueError):
        return False
    runs = payload.get("runs") if isinstance(payload, dict) else None
    return bool(
        isinstance(payload, dict)
        and payload.get("source") == "ocr"
        and payload.get("coordinate_space")
        == "primary_display_physical_pixels"
        and isinstance(runs, list)
        and runs
        and all(
            isinstance(run, dict)
            and isinstance(run.get("text"), str)
            and bool(run["text"])
            for run in runs
        )
    )


def _source_verified(
    ledger: Sequence[LedgerEvent],
    *,
    chrome_title_fragment: str,
    chrome_window_id: str,
) -> bool:
    results = _successful_results(ledger)
    return any(
        result.tool_name == "ui_snapshot"
        and chrome_title_fragment in result.sanitized_text
        for _, result, _ in results
    ) and any(
        result.tool_name == "ocr" and _valid_demo_ocr(result.sanitized_text)
        or result.tool_name == "document_text"
        and _summary_values(call_event).get("scope") == chrome_window_id
        and bool(result.sanitized_text.strip())
        for _, result, call_event in results
    )


@dataclass
class ModelDrivenCrossAppDemoProvider:
    """Let a real provider choose steps inside one Host-owned Demo envelope.

    The wrapped model sees fresh tool results and chooses the next call. This
    guard does not choreograph that sequence, but it rejects any turn that
    escapes the exact disposable fixtures, reviewed key set, semantic-click
    rule, bounded source-brief contract, or durable completion condition.
    """

    inner: ModelProviderPort
    chrome_title_fragment: str
    word_title_fragment: str
    source_url: str
    on_provider_step: Callable[[int], None] | None = None
    on_proposal_rejected: Callable[[DemoProposalRejection], None] | None = None
    max_proposal_corrections: int = DEMO_MAX_PROPOSAL_CORRECTIONS
    name: str = field(init=False)
    continuation_strategy: ProviderContinuationStrategy = field(init=False)
    _accepted_notes: dict[str, str] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.inner, ModelProviderPort):
            raise ValueError("model-driven Demo provider is invalid")
        if (
            not isinstance(self.chrome_title_fragment, str)
            or not self.chrome_title_fragment
            or not isinstance(self.word_title_fragment, str)
            or not self.word_title_fragment
            or not isinstance(self.source_url, str)
            or not self.source_url.startswith("https://")
            or len(self.source_url) > 512
            or isinstance(self.max_proposal_corrections, bool)
            or not isinstance(self.max_proposal_corrections, int)
            or not 0 <= self.max_proposal_corrections <= 4
        ):
            raise ValueError("model-driven Demo inputs are invalid")
        self.name = f"bounded-demo-{self.inner.name}"
        self.continuation_strategy = self.inner.continuation_strategy

    async def create_turn(
        self,
        *,
        run_id: str,
        turn_id: str,
        task: str,
        ledger: Sequence[LedgerEvent],
        tools: Sequence[ToolSpec],
        memories: Sequence[MemoryContextItem] = (),
    ) -> ModelTurn:
        self._notify_progress(ledger)
        feedback_ledger = tuple(ledger)
        input_tokens: int | None = 0
        output_tokens: int | None = 0
        for correction_index in range(self.max_proposal_corrections + 1):
            turn = await self.inner.create_turn(
                run_id=run_id,
                turn_id=turn_id,
                task=task,
                ledger=feedback_ledger,
                tools=tools,
                memories=memories,
            )
            input_tokens = self._sum_usage(input_tokens, turn.usage.input_tokens)
            output_tokens = self._sum_usage(output_tokens, turn.usage.output_tokens)
            if not turn.tool_calls:
                windows = _last_exact_windows(
                    ledger,
                    chrome_title_fragment=self.chrome_title_fragment,
                    word_title_fragment=self.word_title_fragment,
                )
                accepted_note = self._accepted_notes.get(run_id)
                if windows is None or accepted_note is None or not _source_verified(
                    ledger,
                    chrome_title_fragment=self.chrome_title_fragment,
                    chrome_window_id=windows[0],
                ) or not _post_save_verified(
                    ledger,
                    word_window_id=windows[1],
                    required_text=accepted_note,
                ):
                    raise ModelDrivenDemoError(
                        "DEMO_MODEL_FINISHED_BEFORE_VERIFICATION"
                    )
                self._notify(18)
                return replace(
                    turn,
                    text=DEMO_COMPLETE_TEXT,
                    usage=ModelUsage(input_tokens, output_tokens),
                )

            calls = tuple(
                self._normalize_reviewed_key_alias(call)
                for call in turn.tool_calls
            )
            try:
                if len(calls) > 1:
                    raise ModelDrivenDemoError("DEMO_MODEL_MULTIPLE_CALLS")
                self._validate_call(calls[0], ledger)
            except ModelDrivenDemoError as exc:
                if correction_index >= self.max_proposal_corrections:
                    raise
                rejection = DemoProposalRejection(
                    attempt=correction_index + 1,
                    max_attempts=self.max_proposal_corrections,
                    code=str(exc),
                    tool_names=tuple(call.name for call in calls),
                )
                self._notify_rejection(rejection)
                feedback_ledger = (
                    *ledger,
                    *self._proposal_feedback_events(calls, rejection),
                )
                continue

            call = calls[0]
            self._notify_requested_chapter(call, ledger)
            # Provider prose is display-irrelevant and never becomes the trusted
            # Demo completion signal. Only the verified no-call turn above does.
            return replace(
                turn,
                text="",
                tool_calls=(call,),
                usage=ModelUsage(input_tokens, output_tokens),
            )
        raise AssertionError("bounded proposal correction loop did not terminate")

    @staticmethod
    def _sum_usage(total: int | None, value: int | None) -> int | None:
        if total is None or value is None:
            return None
        return total + value

    @staticmethod
    def _proposal_feedback_events(
        calls: Sequence[ToolCall], rejection: DemoProposalRejection
    ) -> tuple[LedgerEvent, ...]:
        events: list[LedgerEvent] = []
        for index, call in enumerate(calls, start=1):
            explanation = (
                ""
                if call.name == "type"
                else "Host rejected this model proposal before desktop dispatch: "
                f"{rejection.code}. Replan from the reviewed Demo instructions and "
                "fresh Host evidence."
            )
            result = ToolResult(
                identity=call.identity,
                tool_name=call.name,
                status=ToolResultStatus.REJECTED,
                dispatch=DispatchCertainty.NOT_DISPATCHED,
                sanitized_text=explanation,
                code="POLICY_DENIED",
            )
            events.append(
                LedgerEvent(
                    event_id=(
                        f"demo_proposal_rejected_{rejection.attempt}_{index}_"
                        f"{call.identity.call_id}"
                    ),
                    kind=LedgerEventKind.TOOL_RESULT,
                    identity=call.identity,
                    tool_result=result,
                )
            )
        return tuple(events)

    def _notify_rejection(self, rejection: DemoProposalRejection) -> None:
        observer = self.on_proposal_rejected
        if observer is None:
            return
        try:
            observer(rejection)
        except Exception:
            self.on_proposal_rejected = None

    @staticmethod
    def _normalize_reviewed_key_alias(call: ToolCall) -> ToolCall:
        """Canonicalize spelling only; never widen the reviewed key set."""

        if call.name != "key":
            return call
        combo = call.arguments.get("combo")
        if not isinstance(combo, str):
            return call
        canonical = {
            "pagedown": "PageDown",
            "page_down": "PageDown",
            "page down": "PageDown",
            "ctrl+end": "Ctrl+End",
            "control+end": "Ctrl+End",
            "ctrl+s": "Ctrl+S",
            "control+s": "Ctrl+S",
        }.get(combo.strip().lower())
        if canonical is None or canonical == combo:
            return call
        return replace(call, arguments={"combo": canonical})

    def _validate_call(
        self, call: ToolCall, ledger: Sequence[LedgerEvent]
    ) -> None:
        name = call.name
        arguments = dict(call.arguments)
        if name == "list_windows":
            if arguments:
                raise ModelDrivenDemoError("DEMO_MODEL_ARGUMENTS_OUT_OF_SCOPE")
            return

        windows = _last_exact_windows(
            ledger,
            chrome_title_fragment=self.chrome_title_fragment,
            word_title_fragment=self.word_title_fragment,
        )
        if windows is None:
            raise ModelDrivenDemoError("DEMO_MODEL_FIXTURES_NOT_OBSERVED")
        chrome_id, word_id = windows

        if name == "activate_window":
            if arguments != {"window_id": arguments.get("window_id")} or arguments.get(
                "window_id"
            ) not in {chrome_id, word_id}:
                raise ModelDrivenDemoError("DEMO_MODEL_WINDOW_OUT_OF_SCOPE")
            if arguments.get("window_id") == word_id and not _source_verified(
                ledger,
                chrome_title_fragment=self.chrome_title_fragment,
                chrome_window_id=chrome_id,
            ):
                raise ModelDrivenDemoError("DEMO_MODEL_SOURCE_NOT_VERIFIED")
            return
        if name == "ui_snapshot":
            if arguments.get("scope") in {"foreground", "all"}:
                raise ModelDrivenDemoError("DEMO_MODEL_AMBIENT_SCOPE_FORBIDDEN")
            if arguments != {"scope": arguments.get("scope")} or arguments.get(
                "scope"
            ) not in {chrome_id, word_id}:
                raise ModelDrivenDemoError("DEMO_MODEL_WINDOW_OUT_OF_SCOPE")
            return
        if name == "document_text":
            if arguments.get("scope") in {"foreground", "all"}:
                raise ModelDrivenDemoError("DEMO_MODEL_AMBIENT_SCOPE_FORBIDDEN")
            if arguments not in ({"scope": chrome_id}, {"scope": word_id}):
                raise ModelDrivenDemoError("DEMO_MODEL_DOCUMENT_OUT_OF_SCOPE")
            return
        if name == "ocr":
            if arguments != {"x": 0, "y": 0, "w": 1920, "h": 1080}:
                raise ModelDrivenDemoError("DEMO_MODEL_OCR_OUT_OF_SCOPE")
            if not self._has_recent_chrome_observation(ledger, chrome_id):
                raise ModelDrivenDemoError("DEMO_MODEL_CHROME_NOT_GROUNDED")
            return
        if name == "click":
            ref = arguments.get("ref")
            observation = _latest_scoped_observation(ledger)
            if (
                set(arguments) != {"ref"}
                or not isinstance(ref, str)
                or observation is None
                or observation[0] != "ui_snapshot"
                or observation[1] != word_id
                or re.search(
                    rf"^{re.escape(ref)} \| edit \"页面 1 内容\" \|",
                    observation[2],
                    re.MULTILINE,
                )
                is None
            ):
                raise ModelDrivenDemoError("DEMO_MODEL_EDITOR_REF_INVALID")
            return
        if name == "type":
            observation = _latest_scoped_observation(ledger)
            ctrl_end = _successful_key_indexes(ledger, "Ctrl+End")
            text = arguments.get("text")
            if (
                set(arguments) != {"text"}
                or not isinstance(text, str)
                or not self._valid_source_brief(text, ledger, chrome_id)
                or not ctrl_end
                or observation is None
                or observation[0] != "ui_snapshot"
                or observation[1] != word_id
                or not self._observation_after_index(ledger, observation, ctrl_end[-1])
            ):
                raise ModelDrivenDemoError("DEMO_MODEL_TYPED_PAYLOAD_INVALID")
            self._accepted_notes[call.identity.run_id] = text
            return
        if name == "key":
            combo = arguments.get("combo")
            if arguments != {"combo": combo}:
                raise ModelDrivenDemoError("DEMO_MODEL_KEY_OUT_OF_SCOPE")
            observation = _latest_scoped_observation(ledger)
            if combo == "PageDown":
                if observation is None or observation[1] != chrome_id:
                    raise ModelDrivenDemoError("DEMO_MODEL_CHROME_NOT_GROUNDED")
                return
            if combo == "Ctrl+End":
                if (
                    observation is None
                    or observation[0] != "ui_snapshot"
                    or observation[1] != word_id
                    or _REF.search(observation[2]) is None
                ):
                    raise ModelDrivenDemoError("DEMO_MODEL_EDITOR_NOT_GROUNDED")
                return
            if combo == "Ctrl+S":
                accepted_note = self._accepted_notes.get(call.identity.run_id)
                if not any(
                    result.tool_name == "document_text"
                    and accepted_note is not None
                    and _contains_required_text(result.sanitized_text, accepted_note)
                    for _, result, _ in _successful_results(ledger)
                ):
                    raise ModelDrivenDemoError("DEMO_MODEL_SAVE_NOT_VERIFIED")
                return
            raise ModelDrivenDemoError("DEMO_MODEL_KEY_OUT_OF_SCOPE")
        raise ModelDrivenDemoError("DEMO_MODEL_TOOL_OUT_OF_SCOPE")

    def _valid_source_brief(
        self,
        text: str,
        ledger: Sequence[LedgerEvent],
        chrome_window_id: str,
    ) -> bool:
        if (
            not 220 <= len(text) <= 900
            or not text.startswith("\n\n")
            or any(
                ord(character) < 32 and character not in {"\n", "\r"}
                for character in text
            )
        ):
            return False
        lines = text.strip().splitlines()
        if (
            len(lines) not in {5, 6, 7}
            or lines[0] != DEMO_TYPED_MARKER
            or lines[1] != f"Source: {self.chrome_title_fragment}"
            or lines[2] != f"URL: {self.source_url}"
        ):
            return False
        bullets = lines[3:]
        if not 2 <= len(bullets) <= 4 or any(
            not line.startswith("- ") or not 24 <= len(line) <= 180
            for line in bullets
        ):
            return False
        source_text = "\n".join(
            result.sanitized_text
            for _, result, call_event in _successful_results(ledger)
            if result.tool_name in {"document_text", "ocr"}
            and (
                result.tool_name == "ocr"
                or _summary_values(call_event).get("scope") == chrome_window_id
            )
        ).lower()
        source_tokens = set(_NOTE_TOKEN.findall(source_text)) - _NOTE_STOP_WORDS
        return bool(source_tokens) and all(
            len(
                (set(_NOTE_TOKEN.findall(bullet.lower())) - _NOTE_STOP_WORDS)
                & source_tokens
            )
            >= 2
            for bullet in bullets
        )

    def accepted_note(self, run_id: str) -> str | None:
        """Return the validated ephemeral note for final artifact verification."""

        return self._accepted_notes.get(run_id)

    def _notify_requested_chapter(
        self, call: ToolCall, ledger: Sequence[LedgerEvent]
    ) -> None:
        """Project the Host-reviewed requested effect before its approval UI."""

        windows = _last_exact_windows(
            ledger,
            chrome_title_fragment=self.chrome_title_fragment,
            word_title_fragment=self.word_title_fragment,
        )
        if windows is None:
            return
        _, word_id = windows
        arguments = call.arguments
        if call.name == "activate_window" and arguments.get("window_id") == word_id:
            self._notify(6)
        elif call.name in {"click", "type"} or (
            call.name == "key" and arguments.get("combo") == "Ctrl+End"
        ):
            self._notify(9)
        elif call.name == "key" and arguments.get("combo") == "Ctrl+S":
            self._notify(15)
        elif call.name == "document_text" and _successful_key_indexes(
            ledger, "Ctrl+S"
        ):
            self._notify(16)

    @staticmethod
    def _observation_after_index(
        ledger: Sequence[LedgerEvent],
        observation: tuple[str, str, str],
        boundary: int,
    ) -> bool:
        return any(
            index > boundary
            and result.tool_name == observation[0]
            and result.sanitized_text == observation[2]
            for index, result, _ in _successful_results(ledger)
        )

    def _has_recent_chrome_observation(
        self, ledger: Sequence[LedgerEvent], chrome_id: str
    ) -> bool:
        observation = _latest_scoped_observation(ledger)
        return observation is not None and observation[1] == chrome_id

    def _notify_progress(self, ledger: Sequence[LedgerEvent]) -> None:
        step = 0
        windows = _last_exact_windows(
            ledger,
            chrome_title_fragment=self.chrome_title_fragment,
            word_title_fragment=self.word_title_fragment,
        )
        if windows is not None:
            step = 1
        observations = _successful_results(ledger)
        if any(
            result.tool_name in {"ui_snapshot", "ocr"}
            and self.chrome_title_fragment in result.sanitized_text
            for _, result, _ in observations
        ):
            step = 5
        if windows is not None and any(
            result.tool_name == "activate_window"
            and _summary_values(call_event).get("window_id") == windows[1]
            for _, result, call_event in observations
        ):
            step = 6
        if any(
            result.tool_name == "ui_snapshot" and _REF.search(result.sanitized_text)
            for _, result, _ in observations
        ):
            step = 8
        if any(
            result.tool_name == "click"
            or result.tool_name == "key"
            and _summary_values(call_event).get("combo") == "Ctrl+End"
            for _, result, call_event in observations
        ):
            step = 9
        if any(result.tool_name == "type" for _, result, _ in observations):
            step = 14
        if any(
            result.tool_name == "document_text"
            and DEMO_TYPED_MARKER in result.sanitized_text
            for _, result, _ in observations
        ):
            step = 15
        if _successful_key_indexes(ledger, "Ctrl+S"):
            step = 16
        if _post_save_verified(
            ledger,
            word_window_id=None if windows is None else windows[1],
        ):
            step = 17
        self._notify(step)

    def _notify(self, step: int) -> None:
        observer = self.on_provider_step
        if observer is None:
            return
        try:
            observer(step)
        except Exception:
            self.on_provider_step = None

    def export_continuation(self, run_id: str) -> Mapping[str, JSONValue]:
        return self.inner.export_continuation(run_id)

    def restore_continuation(
        self, run_id: str, state: Mapping[str, JSONValue]
    ) -> None:
        self.inner.restore_continuation(run_id, state)


def _window_id(
    text: str,
    *,
    owner: str,
    title_fragment: str,
    require_foreground: bool = False,
) -> str:
    for line in text.splitlines():
        is_foreground = line.startswith("* ")
        if require_foreground and not is_foreground:
            continue
        fields = line.split(" | ", maxsplit=2)
        if len(fields) != 3 or fields[1].lower() != owner.lower():
            continue
        title = fields[2].strip()
        if title_fragment not in title:
            continue
        candidate = fields[0].lstrip("* ").strip()
        if candidate.isdigit():
            return candidate
    raise CrossAppDemoError("DEMO_CONTROLLED_WINDOW_NOT_FOUND")


@dataclass
class CrossAppDemoProvider:
    """One fixed, result-driven Chrome read -> Word edit -> save workflow."""

    chrome_title_fragment: str
    word_title_fragment: str
    summary_text: str
    name: str = "controlled-cross-app-demo"
    continuation_strategy: ProviderContinuationStrategy = (
        ProviderContinuationStrategy.STATELESS_REPLAY
    )
    #: Optional passive observer of the fixed provider boundary. It receives one
    #: integer and nothing else: no prose, tool result, window id, or typed text.
    #: It carries no authority and can never change what the provider requests.
    on_provider_step: Callable[[int], None] | None = None
    _step: int = field(default=0, init=False, repr=False)
    _chrome_window_id: str | None = field(default=None, init=False, repr=False)
    _word_window_id: str | None = field(default=None, init=False, repr=False)
    _continuation: dict[str, Mapping[str, JSONValue]] = field(
        default_factory=dict, init=False, repr=False
    )

    def __post_init__(self) -> None:
        if (
            not isinstance(self.word_title_fragment, str)
            or not self.word_title_fragment
            or not isinstance(self.chrome_title_fragment, str)
            or not self.chrome_title_fragment
            or not isinstance(self.summary_text, str)
            or DEMO_TYPED_MARKER not in self.summary_text
        ):
            raise ValueError("controlled Demo inputs are invalid")

    @staticmethod
    def _call(
        run_id: str,
        turn_id: str,
        name: str,
        arguments: Mapping[str, JSONValue],
    ) -> ToolCall:
        return ToolCall(
            CallIdentity(run_id, turn_id, f"call_{turn_id.removeprefix('turn_')}"),
            name,
            arguments,
        )

    @staticmethod
    def _require_ok(result: ToolResult | None, expected_name: str) -> str:
        if (
            result is None
            or result.tool_name != expected_name
            or not result.ok
        ):
            raise CrossAppDemoError("DEMO_TOOL_RESULT_FAILED")
        return result.sanitized_text

    async def create_turn(
        self,
        *,
        run_id: str,
        turn_id: str,
        task: str,
        ledger: Sequence[LedgerEvent],
        tools: Sequence[ToolSpec],
        memories: Sequence[MemoryContextItem] = (),
    ) -> ModelTurn:
        del task, memories
        advertised = {tool.name for tool in tools}
        result = _latest_result(ledger)
        call: ToolCall | None

        if self._step == 0:
            call = self._call(run_id, turn_id, "list_windows", {})
        elif self._step == 1:
            text = self._require_ok(result, "list_windows")
            self._chrome_window_id = _window_id(
                text,
                owner="chrome.exe",
                title_fragment=self.chrome_title_fragment,
                require_foreground=True,
            )
            self._word_window_id = _window_id(
                text,
                owner="winword.exe",
                title_fragment=self.word_title_fragment,
            )
            call = self._call(
                run_id,
                turn_id,
                "activate_window",
                {"window_id": self._required_chrome_id()},
            )
        elif self._step == 2:
            self._require_ok(result, "activate_window")
            call = self._call(
                run_id,
                turn_id,
                "ui_snapshot",
                {"scope": self._chrome_window_id},
            )
        elif self._step == 3:
            text = self._require_ok(result, "ui_snapshot")
            if self.chrome_title_fragment not in text:
                raise CrossAppDemoError("DEMO_SOURCE_WINDOW_MISMATCH")
            call = self._call(
                run_id,
                turn_id,
                "ocr",
                {"x": 0, "y": 0, "w": 1920, "h": 1080},
            )
        elif self._step == 4:
            text = self._require_ok(result, "ocr")
            if not _valid_demo_ocr(text):
                raise CrossAppDemoError("DEMO_SOURCE_EVIDENCE_MISMATCH")
            call = self._call(run_id, turn_id, "key", {"combo": "PageDown"})
        elif self._step == 5:
            self._require_ok(result, "key")
            call = self._call(
                run_id,
                turn_id,
                "ui_snapshot",
                {"scope": self._required_chrome_id()},
            )
        elif self._step == 6:
            text = self._require_ok(result, "ui_snapshot")
            if self.chrome_title_fragment not in text:
                raise CrossAppDemoError("DEMO_SOURCE_WINDOW_MISMATCH")
            call = self._call(run_id, turn_id, "list_windows", {})
        elif self._step == 7:
            text = self._require_ok(result, "list_windows")
            self._word_window_id = _window_id(
                text,
                owner="winword.exe",
                title_fragment=self.word_title_fragment,
            )
            call = self._call(
                run_id,
                turn_id,
                "activate_window",
                {"window_id": self._required_word_id()},
            )
        elif self._step == 8:
            self._require_ok(result, "activate_window")
            call = self._call(
                run_id,
                turn_id,
                "ui_snapshot",
                {"scope": self._required_word_id()},
            )
        elif self._step == 9:
            text = self._require_ok(result, "ui_snapshot")
            match = _REF.search(text)
            if match is None:
                raise CrossAppDemoError("DEMO_WORD_EDITOR_REF_NOT_FOUND")
            call = self._call(
                run_id,
                turn_id,
                "click",
                {"ref": match.group(1)},
            )
        elif self._step == 10:
            self._require_ok(result, "click")
            call = self._call(
                run_id,
                turn_id,
                "ui_snapshot",
                {"scope": self._required_word_id()},
            )
        elif self._step == 11:
            self._require_ok(result, "ui_snapshot")
            call = self._call(run_id, turn_id, "key", {"combo": "Ctrl+End"})
        elif self._step == 12:
            self._require_ok(result, "key")
            call = self._call(
                run_id,
                turn_id,
                "ui_snapshot",
                {"scope": self._required_word_id()},
            )
        elif self._step == 13:
            self._require_ok(result, "ui_snapshot")
            call = self._call(
                run_id,
                turn_id,
                "type",
                {"text": self.summary_text},
            )
        elif self._step == 14:
            self._require_ok(result, "type")
            call = self._call(
                run_id,
                turn_id,
                "document_text",
                {"scope": self._required_word_id()},
            )
        elif self._step == 15:
            text = self._require_ok(result, "document_text")
            if DEMO_TYPED_MARKER not in text:
                raise CrossAppDemoError("DEMO_WORD_EDIT_NOT_VERIFIED")
            call = self._call(run_id, turn_id, "key", {"combo": "Ctrl+S"})
        elif self._step == 16:
            self._require_ok(result, "key")
            call = self._call(
                run_id,
                turn_id,
                "document_text",
                {"scope": self._required_word_id()},
            )
        elif self._step == 17:
            text = self._require_ok(result, "document_text")
            if DEMO_TYPED_MARKER not in text:
                raise CrossAppDemoError("DEMO_SAVE_VERIFICATION_FAILED")
            call = None
        else:
            raise CrossAppDemoError("DEMO_PROVIDER_STEP_INVALID")

        if call is not None and call.name not in advertised:
            raise CrossAppDemoError("DEMO_REQUIRED_TOOL_NOT_ADVERTISED")
        response_id = f"demo_response_{turn_id}"
        self._continuation[run_id] = {
            "step": self._step,
            "response_id": response_id,
        }
        self._step += 1
        self._notify_step()
        return ModelTurn(
            run_id,
            turn_id,
            response_id,
            DEMO_COMPLETE_TEXT if call is None else "",
            () if call is None else (call,),
        )

    def _notify_step(self) -> None:
        """Tell a passive observer which fixed boundary the provider reached.

        The observer is a display surface, so its failure must never change the
        Demo. Any exception is swallowed and the observer is dropped rather than
        retried, matching the fail-silent contract of the other passive surfaces.
        """

        observer = self.on_provider_step
        if observer is None:
            return
        try:
            observer(self._step)
        except Exception:
            self.on_provider_step = None

    def _required_word_id(self) -> str:
        if self._word_window_id is None:
            raise CrossAppDemoError("DEMO_WORD_WINDOW_ID_UNAVAILABLE")
        return self._word_window_id

    def _required_chrome_id(self) -> str:
        if self._chrome_window_id is None:
            raise CrossAppDemoError("DEMO_CHROME_WINDOW_ID_UNAVAILABLE")
        return self._chrome_window_id

    def export_continuation(self, run_id: str) -> Mapping[str, JSONValue]:
        return to_json_value(self._continuation.get(run_id, {}))  # type: ignore[return-value]

    def restore_continuation(
        self, run_id: str, state: Mapping[str, JSONValue]
    ) -> None:
        self._continuation[run_id] = to_json_value(state)  # type: ignore[assignment]


__all__ = [
    "CrossAppDemoError",
    "CrossAppDemoProvider",
    "DEMO_COMPLETE_TEXT",
    "DEMO_TYPED_MARKER",
    "DEMO_WORKFLOW",
    "ModelDrivenCrossAppDemoProvider",
    "ModelDrivenDemoError",
    "project_demo_workflow",
]
