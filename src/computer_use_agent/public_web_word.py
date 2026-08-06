"""Model-driven public-web-to-Word product workflow guard.

The wrapped provider chooses every desktop step and authors the brief.  This
module only constrains those proposals to the fixed public source, the exact
disposable Chrome and Word windows, and a durable save-verification sequence.
Runner remains the sole policy, approval, persistence, and MCP dispatch path.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from typing import Mapping, Sequence

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
)

PUBLIC_WEB_WORD_COMPLETE_TEXT = "PUBLIC_WEB_WORD_COMPLETE"
PUBLIC_WEB_WORD_MARKER = "VERIFIED SOURCE BRIEF"
PUBLIC_WEB_WORD_BULLET_PREFIX = "• "
PUBLIC_WEB_WORD_SOURCE_TITLE = (
    "Collaborate on Word documents with real-time co-authoring"
)
PUBLIC_WEB_WORD_SOURCE_URL = (
    "https://support.microsoft.com/en-US/Word/training/"
    "collaborate-on-word-documents-with-real-time-co-authoring"
)
PUBLIC_WEB_WORD_ALLOWED_TOOLS = frozenset(
    {
        "list_windows",
        "ui_snapshot",
        "document_text",
        "ocr",
        "screenshot",
        "activate_window",
        "click",
        "type",
        "key",
    }
)
PUBLIC_WEB_WORD_TASK = f"""Review the fixed public Microsoft Support page in the
fresh Chrome fixture, then append and save a source-grounded brief in the
disposable Word document. Use only exact numeric window scopes. The `type`
payload must be 220-900 characters and start with two newline characters,
followed immediately by {PUBLIC_WEB_WORD_MARKER!r}, then contain exactly
`Source: {PUBLIC_WEB_WORD_SOURCE_TITLE}`,
`URL: {PUBLIC_WEB_WORD_SOURCE_URL}`, and two to four concise
`{PUBLIC_WEB_WORD_BULLET_PREFIX}` bullets.
Each bullet must be 24-180 characters and appear on its own line.
Author the bullets only from fresh page observations; no findings are supplied
in this task. Verify the Word text before saving and again after Ctrl+S, then
finish without another tool call."""


def public_web_word_task(word_title_fragment: str) -> str:
    """Bind the model-visible task to this run's exact disposable artifact."""

    if not isinstance(word_title_fragment, str) or not word_title_fragment:
        raise ValueError("word_title_fragment must be non-empty")
    return (
        f"{PUBLIC_WEB_WORD_TASK}\nThe exact disposable Word window title contains "
        f"{json.dumps(word_title_fragment, ensure_ascii=True)}."
    )

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
_WORD_EDIT_LINE = re.compile(
    r'^(ref_[1-9][0-9]*) \| edit "([^"]*)" \| '
    r'\((-?[0-9]+),(-?[0-9]+),([1-9][0-9]*),([1-9][0-9]*)\) \| '
    r'([^|\r\n]+)(?: \| [^\r\n]*)?$',
    re.MULTILINE,
)
_WORD_DOCUMENT_LINE = re.compile(
    r'^(ref_[1-9][0-9]*) \| document "([^"]*)" \| '
    r'\((-?[0-9]+),(-?[0-9]+),([1-9][0-9]*),([1-9][0-9]*)\) \| '
    r'([^|\r\n]+)(?: \| [^\r\n]*)?$',
    re.MULTILINE,
)
_WORD_EDITOR_NAME = re.compile(
    r"(?:Page [1-9][0-9]* content|页面 [1-9][0-9]* 内容)",
    re.IGNORECASE,
)
_PROPOSAL_CORRECTION_HINTS = {
    "PUBLIC_WEB_WORD_SCREENSHOT_OUT_OF_SCOPE": (
        "Screenshot is allowed once, after Word activation and a fresh editor "
        "snapshot, before the first editor click. After a successful editor click "
        "and fresh snapshot reporting the main editor focused, request only key "
        "with combo Ctrl+End; do not request another screenshot."
    ),
    "PUBLIC_WEB_WORD_EDITOR_COORDINATE_INVALID": (
        "A successful main-editor click must not be repeated. Re-observe the exact "
        "Word window; Word may report keyboard focus on the containing document "
        "named for the disposable file while the Page content edit remains enabled. "
        "When that fresh focus evidence is present, request only key with combo "
        "Ctrl+End; do not click again."
    ),
}


class PublicWebWordError(RuntimeError):
    """Fixed product-workflow failure that never embeds observed or typed text."""


@dataclass(frozen=True)
class PublicWebWordProposalRejection:
    """One bounded, content-free model-proposal rejection before dispatch."""

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
            or not self.code.startswith("PUBLIC_WEB_WORD_")
            or not isinstance(self.tool_names, tuple)
            or not self.tool_names
            or not all(isinstance(name, str) and name for name in self.tool_names)
        ):
            raise ValueError("public-web-word proposal rejection is invalid")


def _calls_by_identity(
    ledger: Sequence[LedgerEvent],
) -> dict[CallIdentity, LedgerEvent]:
    return {
        event.identity: event
        for event in ledger
        if event.kind is LedgerEventKind.TOOL_CALL and event.identity is not None
    }


def _successful_results(
    ledger: Sequence[LedgerEvent],
) -> list[tuple[int, ToolResult, LedgerEvent | None]]:
    calls = _calls_by_identity(ledger)
    return [
        (index, event.tool_result, calls.get(event.identity))
        for index, event in enumerate(ledger)
        if event.kind is LedgerEventKind.TOOL_RESULT
        and event.identity is not None
        and event.tool_result is not None
        and event.tool_result.ok
    ]


def _summary_values(call_event: LedgerEvent | None) -> Mapping[str, object]:
    if call_event is None or call_event.safe_argument_summary is None:
        return {}
    return call_event.safe_argument_summary.values


def _unique_window_id(
    text: str,
    *,
    owner: str,
    title_fragment: str,
    expected_window_id: str,
) -> str:
    matches: list[str] = []
    for line in text.splitlines():
        fields = line.split(" | ", maxsplit=2)
        if len(fields) != 3 or fields[1].strip().lower() != owner.lower():
            continue
        if title_fragment not in fields[2]:
            continue
        candidate = fields[0].lstrip("* ").strip()
        if candidate == expected_window_id and candidate.isdigit():
            matches.append(candidate)
    if len(matches) != 1:
        raise PublicWebWordError("PUBLIC_WEB_WORD_CONTROLLED_WINDOW_NOT_UNIQUE")
    return matches[0]


def _last_exact_windows(
    ledger: Sequence[LedgerEvent],
    *,
    chrome_title_fragment: str,
    word_title_fragment: str,
    chrome_window_id: str,
    word_window_id: str,
) -> tuple[str, str] | None:
    for _index, result, _call_event in reversed(_successful_results(ledger)):
        if result.tool_name != "list_windows":
            continue
        try:
            return (
                _unique_window_id(
                    result.sanitized_text,
                    owner="chrome.exe",
                    title_fragment=chrome_title_fragment,
                    expected_window_id=chrome_window_id,
                ),
                _unique_window_id(
                    result.sanitized_text,
                    owner="winword.exe",
                    title_fragment=word_title_fragment,
                    expected_window_id=word_window_id,
                ),
            )
        except PublicWebWordError:
            return None
    return None


def _latest_scoped_observation(
    ledger: Sequence[LedgerEvent],
) -> tuple[int, str, str, str] | None:
    for index, result, call_event in reversed(_successful_results(ledger)):
        if result.tool_name not in {"ui_snapshot", "document_text"}:
            continue
        scope = _summary_values(call_event).get("scope")
        if isinstance(scope, str):
            return index, result.tool_name, scope, result.sanitized_text
    return None


def _latest_word_editor(
    ledger: Sequence[LedgerEvent],
    *,
    word_window_id: str,
    word_title_fragment: str,
) -> tuple[int, tuple[int, int], bool] | None:
    for index, result, call_event in reversed(_successful_results(ledger)):
        if (
            result.tool_name != "ui_snapshot"
            or _summary_values(call_event).get("scope") != word_window_id
        ):
            continue
        editors: list[tuple[str, int, int, int, int, bool]] = []
        for match in _WORD_EDIT_LINE.finditer(result.sanitized_text):
            states = {value.strip() for value in match.group(7).split(",")}
            if "enabled" not in states or "offscreen" in states:
                continue
            x, y, width, height = (int(match.group(value)) for value in range(3, 7))
            editors.append(
                (match.group(2), x, y, width, height, "focused" in states)
            )
        named = [item for item in editors if _WORD_EDITOR_NAME.fullmatch(item[0])]
        if len(named) == 1:
            selected = named[0]
        elif named:
            return None
        else:
            by_area = sorted(
                editors,
                key=lambda item: item[3] * item[4],
                reverse=True,
            )
            if not by_area or by_area[0][3] < 400 or by_area[0][4] < 300:
                return None
            if (
                len(by_area) > 1
                and by_area[0][3] * by_area[0][4]
                < 4 * by_area[1][3] * by_area[1][4]
            ):
                return None
            selected = by_area[0]
        _name, x, y, width, height, selected_focused = selected
        center = (x + width // 2, y + height // 2)
        other_editor_focused = any(item != selected and item[5] for item in editors)
        containing_documents: list[str] = []
        for match in _WORD_DOCUMENT_LINE.finditer(result.sanitized_text):
            states = {value.strip() for value in match.group(7).split(",")}
            if (
                "enabled" not in states
                or "focused" not in states
                or "offscreen" in states
                or word_title_fragment.casefold() not in match.group(2).casefold()
            ):
                continue
            document_x, document_y, document_width, document_height = (
                int(match.group(value)) for value in range(3, 7)
            )
            if (
                document_x <= center[0] < document_x + document_width
                and document_y <= center[1] < document_y + document_height
            ):
                containing_documents.append(match.group(1))
        focused = (
            selected_focused or len(containing_documents) == 1
        ) and not other_editor_focused
        return index, center, focused
    return None


def _latest_activation(ledger: Sequence[LedgerEvent]) -> tuple[int, str] | None:
    for index, result, call_event in reversed(_successful_results(ledger)):
        if result.tool_name != "activate_window":
            continue
        target = _summary_values(call_event).get("window_id")
        if isinstance(target, str):
            return index, target
    return None


def _latest_side_effect_index(ledger: Sequence[LedgerEvent]) -> int | None:
    return next(
        (
            index
            for index, result, _event in reversed(_successful_results(ledger))
            if result.tool_name in {"activate_window", "click", "type", "key"}
        ),
        None,
    )


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
    normalized_observed = observed.replace("\r\n", "\n").replace("\r", "\n")
    normalized_required = required.replace("\r\n", "\n").replace("\r", "\n")
    return normalized_required.strip() in normalized_observed


def _document_text_content(
    observed: str,
    *,
    require_complete: bool = False,
) -> str | None:
    try:
        payload = json.loads(observed)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict) or payload.get("source") != "document_text":
        return None
    complete = payload.get("complete")
    truncated = payload.get("truncated")
    omitted = payload.get("omitted_blocks")
    if (
        not isinstance(complete, bool)
        or not isinstance(truncated, bool)
        or complete == truncated
        or isinstance(omitted, bool)
        or not isinstance(omitted, int)
        or omitted < 0
        or (complete and omitted != 0)
        or (require_complete and not complete)
    ):
        return None
    blocks = payload.get("blocks")
    if not isinstance(blocks, list):
        return None
    texts: list[str] = []
    orders: set[int] = set()
    for block in blocks:
        order = block.get("order") if isinstance(block, dict) else None
        if (
            not isinstance(block, dict)
            or isinstance(order, bool)
            or not isinstance(order, int)
            or order in orders
            or not isinstance(block.get("text"), str)
        ):
            return None
        orders.add(order)
        texts.append(block["text"])
    return "\n".join(texts)


def _document_text_contains_required(observed: str, required: str) -> bool:
    content = _document_text_content(observed, require_complete=True)
    return content is not None and _contains_required_text(content, required)


def _post_save_verified(
    ledger: Sequence[LedgerEvent],
    *,
    word_window_id: str,
    required_text: str,
) -> bool:
    saves = _successful_key_indexes(ledger, "Ctrl+S")
    if not saves:
        return False
    return any(
        index > saves[-1]
        and result.tool_name == "document_text"
        and _summary_values(call_event).get("scope") == word_window_id
        and _document_text_contains_required(result.sanitized_text, required_text)
        for index, result, call_event in _successful_results(ledger)
    )


def _ocr_content(text: str) -> str | None:
    try:
        payload = json.loads(text)
    except (TypeError, ValueError):
        return None
    runs = payload.get("runs") if isinstance(payload, dict) else None
    if not (
        isinstance(payload, dict)
        and payload.get("source") == "ocr"
        and payload.get("coordinate_space")
        == "primary_display_physical_pixels"
        and isinstance(runs, list)
        and runs
        and all(
            isinstance(run, dict)
            and isinstance(run.get("text"), str)
            and bool(run["text"].strip())
            for run in runs
        )
    ):
        return None
    return "\n".join(run["text"] for run in runs)


def _valid_ocr(text: str) -> bool:
    return bool((_ocr_content(text) or "").strip())


def _source_verified(
    ledger: Sequence[LedgerEvent],
    *,
    chrome_title_fragment: str,
    chrome_window_id: str,
) -> bool:
    results = _successful_results(ledger)
    title_seen = any(
        result.tool_name == "ui_snapshot"
        and _summary_values(call_event).get("scope") == chrome_window_id
        and chrome_title_fragment in result.sanitized_text
        for _index, result, call_event in results
    )
    content_seen = any(
        (
            result.tool_name == "document_text"
            and _summary_values(call_event).get("scope") == chrome_window_id
            and bool((_document_text_content(result.sanitized_text) or "").strip())
        )
        or (result.tool_name == "ocr" and _valid_ocr(result.sanitized_text))
        for _index, result, call_event in results
    )
    return title_seen and content_seen


@dataclass
class ModelDrivenPublicWebWordProvider:
    """Constrain a real provider to one installed public-web-to-Word workflow."""

    inner: ModelProviderPort
    chrome_title_fragment: str
    word_title_fragment: str
    chrome_window_id: str
    word_window_id: str
    source_url: str = PUBLIC_WEB_WORD_SOURCE_URL
    max_proposal_corrections: int = 2
    name: str = field(init=False)
    continuation_strategy: ProviderContinuationStrategy = field(init=False)
    _accepted_notes: dict[str, str] = field(default_factory=dict, init=False, repr=False)
    _correction_counts: dict[str, int] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.inner, ModelProviderPort):
            raise ValueError("public-web-word inner provider is invalid")
        if (
            not isinstance(self.chrome_title_fragment, str)
            or not self.chrome_title_fragment
            or not isinstance(self.word_title_fragment, str)
            or not self.word_title_fragment
            or not isinstance(self.chrome_window_id, str)
            or not self.chrome_window_id.isdigit()
            or not isinstance(self.word_window_id, str)
            or not self.word_window_id.isdigit()
            or not isinstance(self.source_url, str)
            or not self.source_url.startswith("https://")
            or len(self.source_url) > 512
            or isinstance(self.max_proposal_corrections, bool)
            or not isinstance(self.max_proposal_corrections, int)
            or not 0 <= self.max_proposal_corrections <= 4
        ):
            raise ValueError("public-web-word provider inputs are invalid")
        self.name = f"public-web-word-{self.inner.name}"
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
                self._require_complete(ledger, run_id)
                return replace(
                    turn,
                    text=PUBLIC_WEB_WORD_COMPLETE_TEXT,
                    usage=ModelUsage(input_tokens, output_tokens),
                )

            calls = tuple(self._normalize_key_alias(call) for call in turn.tool_calls)
            try:
                if len(calls) != 1:
                    raise PublicWebWordError("PUBLIC_WEB_WORD_MULTIPLE_CALLS")
                self._validate_call(calls[0], ledger)
            except PublicWebWordError as exc:
                if correction_index >= self.max_proposal_corrections:
                    raise
                rejection = PublicWebWordProposalRejection(
                    attempt=correction_index + 1,
                    max_attempts=self.max_proposal_corrections,
                    code=str(exc),
                    tool_names=tuple(call.name for call in calls),
                )
                self._correction_counts[run_id] = (
                    self._correction_counts.get(run_id, 0) + 1
                )
                feedback_ledger = (
                    *ledger,
                    *self._proposal_feedback_events(calls, rejection),
                )
                continue

            return replace(
                turn,
                text="",
                tool_calls=(calls[0],),
                usage=ModelUsage(input_tokens, output_tokens),
            )
        raise AssertionError("public-web-word correction loop did not terminate")

    def _require_complete(self, ledger: Sequence[LedgerEvent], run_id: str) -> None:
        windows = _last_exact_windows(
            ledger,
            chrome_title_fragment=self.chrome_title_fragment,
            word_title_fragment=self.word_title_fragment,
            chrome_window_id=self.chrome_window_id,
            word_window_id=self.word_window_id,
        )
        accepted = self._accepted_notes.get(run_id)
        if (
            windows is None
            or accepted is None
            or not _source_verified(
                ledger,
                chrome_title_fragment=self.chrome_title_fragment,
                chrome_window_id=windows[0],
            )
            or not _post_save_verified(
                ledger,
                word_window_id=windows[1],
                required_text=accepted,
            )
        ):
            raise PublicWebWordError("PUBLIC_WEB_WORD_FINISHED_BEFORE_VERIFICATION")

    @staticmethod
    def _sum_usage(total: int | None, value: int | None) -> int | None:
        if total is None or value is None:
            return None
        return total + value

    @staticmethod
    def _proposal_feedback_events(
        calls: Sequence[ToolCall], rejection: PublicWebWordProposalRejection
    ) -> tuple[LedgerEvent, ...]:
        guidance = _PROPOSAL_CORRECTION_HINTS.get(
            rejection.code,
            "Replan inside the fixed workflow.",
        )
        return tuple(
            LedgerEvent(
                event_id=(
                    f"public_web_word_rejected_{rejection.attempt}_{index}_"
                    f"{call.identity.call_id}"
                ),
                kind=LedgerEventKind.TOOL_RESULT,
                identity=call.identity,
                tool_result=ToolResult(
                    identity=call.identity,
                    tool_name=call.name,
                    status=ToolResultStatus.REJECTED,
                    dispatch=DispatchCertainty.NOT_DISPATCHED,
                    sanitized_text=(
                        ""
                        if call.name == "type"
                        else "Host rejected this proposal before desktop dispatch: "
                        f"{rejection.code}. {guidance}"
                    ),
                    code="POLICY_DENIED",
                ),
            )
            for index, call in enumerate(calls, start=1)
        )

    @staticmethod
    def _normalize_key_alias(call: ToolCall) -> ToolCall:
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

    def _validate_call(self, call: ToolCall, ledger: Sequence[LedgerEvent]) -> None:
        name = call.name
        arguments = dict(call.arguments)
        if name == "list_windows":
            if arguments:
                raise PublicWebWordError("PUBLIC_WEB_WORD_ARGUMENTS_OUT_OF_SCOPE")
            return

        windows = _last_exact_windows(
            ledger,
            chrome_title_fragment=self.chrome_title_fragment,
            word_title_fragment=self.word_title_fragment,
            chrome_window_id=self.chrome_window_id,
            word_window_id=self.word_window_id,
        )
        if windows is None:
            raise PublicWebWordError("PUBLIC_WEB_WORD_FIXTURES_NOT_OBSERVED")
        chrome_id, word_id = windows

        if name == "activate_window":
            target = arguments.get("window_id")
            if arguments != {"window_id": target} or target not in {chrome_id, word_id}:
                raise PublicWebWordError("PUBLIC_WEB_WORD_WINDOW_OUT_OF_SCOPE")
            results = _successful_results(ledger)
            listed = [
                index for index, result, _event in results if result.tool_name == "list_windows"
            ]
            side_effects = [
                index
                for index, result, _event in results
                if result.tool_name in {"activate_window", "click", "type", "key"}
            ]
            if not listed or side_effects and listed[-1] <= side_effects[-1]:
                raise PublicWebWordError("PUBLIC_WEB_WORD_WINDOW_LIST_STALE")
            if target == word_id and not _source_verified(
                ledger,
                chrome_title_fragment=self.chrome_title_fragment,
                chrome_window_id=chrome_id,
            ):
                raise PublicWebWordError("PUBLIC_WEB_WORD_SOURCE_NOT_VERIFIED")
            return
        if name in {"ui_snapshot", "document_text"}:
            scope = arguments.get("scope")
            if arguments != {"scope": scope} or scope not in {chrome_id, word_id}:
                raise PublicWebWordError("PUBLIC_WEB_WORD_WINDOW_OUT_OF_SCOPE")
            return
        if name == "ocr":
            if arguments != {"x": 0, "y": 0, "w": 1920, "h": 1080}:
                raise PublicWebWordError("PUBLIC_WEB_WORD_OCR_OUT_OF_SCOPE")
            observation = _latest_scoped_observation(ledger)
            if observation is None or observation[2] != chrome_id:
                raise PublicWebWordError("PUBLIC_WEB_WORD_CHROME_NOT_GROUNDED")
            return
        if name == "screenshot":
            editor = _latest_word_editor(
                ledger,
                word_window_id=word_id,
                word_title_fragment=self.word_title_fragment,
            )
            activation = _latest_activation(ledger)
            if (
                arguments
                or editor is None
                or activation is None
                or activation[1] != word_id
                or activation[0] != _latest_side_effect_index(ledger)
                or editor[0] <= activation[0]
            ):
                raise PublicWebWordError("PUBLIC_WEB_WORD_SCREENSHOT_OUT_OF_SCOPE")
            return
        if name == "click":
            editor = _latest_word_editor(
                ledger,
                word_window_id=word_id,
                word_title_fragment=self.word_title_fragment,
            )
            activation = _latest_activation(ledger)
            screenshots = [
                index
                for index, result, _event in _successful_results(ledger)
                if result.tool_name == "screenshot"
            ]
            point = (arguments.get("x"), arguments.get("y"))
            if (
                set(arguments) != {"x", "y"}
                or any(isinstance(value, bool) or not isinstance(value, int) for value in point)
                or editor is None
                or activation is None
                or activation[1] != word_id
                or activation[0] != _latest_side_effect_index(ledger)
                or editor[0] <= activation[0]
                or point != editor[1]
                or not screenshots
                or screenshots[-1] <= editor[0]
            ):
                raise PublicWebWordError("PUBLIC_WEB_WORD_EDITOR_COORDINATE_INVALID")
            return
        if name == "type":
            text = arguments.get("text")
            editor = _latest_word_editor(
                ledger,
                word_window_id=word_id,
                word_title_fragment=self.word_title_fragment,
            )
            ctrl_end = _successful_key_indexes(ledger, "Ctrl+End")
            if (
                set(arguments) != {"text"}
                or not isinstance(text, str)
                or not self._valid_source_brief(text, ledger, chrome_id)
                or not ctrl_end
                or editor is None
                or editor[0] <= ctrl_end[-1]
                or not editor[2]
            ):
                raise PublicWebWordError("PUBLIC_WEB_WORD_TYPED_PAYLOAD_INVALID")
            self._accepted_notes[call.identity.run_id] = text
            return
        if name == "key":
            combo = arguments.get("combo")
            if arguments != {"combo": combo}:
                raise PublicWebWordError("PUBLIC_WEB_WORD_KEY_OUT_OF_SCOPE")
            observation = _latest_scoped_observation(ledger)
            if combo == "PageDown":
                if observation is None or observation[2] != chrome_id:
                    raise PublicWebWordError("PUBLIC_WEB_WORD_CHROME_NOT_GROUNDED")
                return
            if combo == "Ctrl+End":
                clicks = [
                    index
                    for index, result, _event in _successful_results(ledger)
                    if result.tool_name == "click"
                ]
                editor = _latest_word_editor(
                    ledger,
                    word_window_id=word_id,
                    word_title_fragment=self.word_title_fragment,
                )
                if (
                    not clicks
                    or editor is None
                    or editor[0] <= clicks[-1]
                    or not editor[2]
                ):
                    raise PublicWebWordError("PUBLIC_WEB_WORD_EDITOR_NOT_GROUNDED")
                return
            if combo == "Ctrl+S":
                accepted = self._accepted_notes.get(call.identity.run_id)
                if accepted is None or not any(
                    result.tool_name == "document_text"
                    and _summary_values(call_event).get("scope") == word_id
                    and _document_text_contains_required(
                        result.sanitized_text,
                        accepted,
                    )
                    for _index, result, call_event in _successful_results(ledger)
                ):
                    raise PublicWebWordError("PUBLIC_WEB_WORD_SAVE_NOT_VERIFIED")
                return
            raise PublicWebWordError("PUBLIC_WEB_WORD_KEY_OUT_OF_SCOPE")
        raise PublicWebWordError("PUBLIC_WEB_WORD_TOOL_OUT_OF_SCOPE")

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
            or lines[0] != PUBLIC_WEB_WORD_MARKER
            or lines[1] != f"Source: {self.chrome_title_fragment}"
            or lines[2] != f"URL: {self.source_url}"
        ):
            return False
        bullets = lines[3:]
        if not 2 <= len(bullets) <= 4 or any(
            not line.startswith(PUBLIC_WEB_WORD_BULLET_PREFIX)
            or not 24 <= len(line) <= 180
            for line in bullets
        ):
            return False
        source_chunks: list[str] = []
        for _index, result, call_event in _successful_results(ledger):
            if (
                result.tool_name == "document_text"
                and _summary_values(call_event).get("scope") == chrome_window_id
            ):
                content = _document_text_content(result.sanitized_text)
            elif result.tool_name == "ocr":
                content = _ocr_content(result.sanitized_text)
            else:
                content = None
            if content:
                source_chunks.append(content)
        source_text = "\n".join(source_chunks).lower()
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

    def correction_count(self, run_id: str) -> int:
        return self._correction_counts.get(run_id, 0)

    def export_continuation(self, run_id: str) -> Mapping[str, JSONValue]:
        return self.inner.export_continuation(run_id)

    def restore_continuation(
        self,
        run_id: str,
        state: Mapping[str, JSONValue],
        *,
        tools: Sequence[ToolSpec],
    ) -> None:
        self.inner.restore_continuation(run_id, state, tools=tools)


__all__ = [
    "ModelDrivenPublicWebWordProvider",
    "PUBLIC_WEB_WORD_ALLOWED_TOOLS",
    "PUBLIC_WEB_WORD_BULLET_PREFIX",
    "PUBLIC_WEB_WORD_COMPLETE_TEXT",
    "PUBLIC_WEB_WORD_MARKER",
    "PUBLIC_WEB_WORD_SOURCE_TITLE",
    "PUBLIC_WEB_WORD_SOURCE_URL",
    "PUBLIC_WEB_WORD_TASK",
    "PublicWebWordError",
    "PublicWebWordProposalRejection",
    "public_web_word_task",
]
