"""Deterministic provider script for the bounded Chrome-to-Word Demo.

The provider is deliberately not a model. It translates only fixed, controlled
fixture evidence into the next reviewed tool call. Runner remains the sole
policy, approval, grounding, budget, persistence, and MCP dispatch authority.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Mapping, Sequence

from .tool_registry import ToolSpec
from .types import (
    JSONValue,
    CallIdentity,
    LedgerEvent,
    LedgerEventKind,
    MemoryContextItem,
    ModelTurn,
    ProviderContinuationStrategy,
    ToolCall,
    ToolResult,
    to_json_value,
)
from .workflow_checklist import WorkflowDefinition, WorkflowStepDefinition

DEMO_COMPLETE_TEXT = "CONTROLLED_CROSS_APP_DEMO_COMPLETE"
DEMO_TYPED_MARKER = "VERIFIED PORTAL FOLLOW-UP"
DEMO_WORKFLOW = WorkflowDefinition(
    workflow_id="chrome_word_research",
    title="Review a public source and update the research brief",
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


class CrossAppDemoError(RuntimeError):
    """Fixed failure that never embeds desktop or typed content."""


def _latest_result(ledger: Sequence[LedgerEvent]) -> ToolResult | None:
    for event in reversed(ledger):
        if event.kind is LedgerEventKind.TOOL_RESULT:
            return event.tool_result
    return None


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
            try:
                payload = json.loads(text)
            except (TypeError, ValueError) as exc:
                raise CrossAppDemoError("DEMO_SOURCE_EVIDENCE_INVALID") from exc
            runs = payload.get("runs") if isinstance(payload, dict) else None
            if (
                not isinstance(payload, dict)
                or payload.get("source") != "ocr"
                or payload.get("coordinate_space")
                != "primary_display_physical_pixels"
                or not isinstance(runs, list)
                or not all(
                    isinstance(run, dict)
                    and isinstance(run.get("text"), str)
                    and bool(run["text"])
                    for run in runs
                )
            ):
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
        return ModelTurn(
            run_id,
            turn_id,
            response_id,
            DEMO_COMPLETE_TEXT if call is None else "",
            () if call is None else (call,),
        )

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
]
