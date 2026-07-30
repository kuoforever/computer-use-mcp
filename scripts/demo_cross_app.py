"""Run the real Chrome-to-Word interview Demo on disposable local fixtures.

Fixture setup launches installed applications, but every observed or mutating
desktop operation is requested through AgentRunner and StdioDesktopMCP.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import subprocess
import sys
import time
import zipfile
from xml.etree import ElementTree
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from computer_use_agent.approvals import DecisionCardApprovalPort  # noqa: E402
from computer_use_agent.config import (  # noqa: E402
    APPROVED_ACTIONS_MODE,
    AgentConfig,
    MCPLaunchConfig,
    OperatorConfig,
    PolicyConfig,
    ProviderConfig,
    default_state_dir,
)
from computer_use_agent.decision_card_window import (  # noqa: E402
    DecisionCardWindow,
    OperatorStepContext,
)
from computer_use_agent.decision_card_window_win32 import (  # noqa: E402
    Win32DecisionCardWindowApi,
)
from computer_use_agent.demo_cross_app import (  # noqa: E402
    DEMO_COMPLETE_TEXT,
    DEMO_TYPED_MARKER,
    CrossAppDemoProvider,
)
from computer_use_agent.desktop_mcp import StdioDesktopMCP  # noqa: E402
from computer_use_agent.presence import PresencePreferences  # noqa: E402
from computer_use_agent.presence_lifecycle import RunPresenceCoordinator  # noqa: E402
from computer_use_agent.presence_window import PassivePresenceWindow  # noqa: E402
from computer_use_agent.presence_window_win32 import Win32PresenceWindowApi  # noqa: E402
from computer_use_agent.progress_lifecycle import RunProgressCoordinator  # noqa: E402
from computer_use_agent.progress_poller import ProgressPoller  # noqa: E402
from computer_use_agent.progress_window import PassiveProgressWindow  # noqa: E402
from computer_use_agent.progress_window_win32 import Win32ProgressWindowApi  # noqa: E402
from computer_use_agent.runner import AgentRunner, RunnerPorts  # noqa: E402
from computer_use_agent.types import (  # noqa: E402
    ApprovalRequest,
    PolicyDecision,
)

CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
WORD = Path(r"C:\Program Files\Microsoft Office\root\Office16\WINWORD.EXE")
MCP = ROOT / ".venv" / "Scripts" / "guarded-desktop-mcp.exe"
WORD_TEMPLATE = ROOT / "demo_templates" / "word-collaboration-research.docx"
HUMAN_IDLE_SECONDS = 2.5
HUMAN_STABLE_SAMPLES = 3
HUMAN_POLL_INTERVAL_SECONDS = 0.25
HUMAN_MAX_WAIT_SECONDS = 60.0
SOURCE_URL = (
    "https://support.microsoft.com/en-US/Word/training/"
    "collaborate-on-word-documents-with-real-time-co-authoring"
)
SOURCE_TITLE = "Collaborate on Word documents with real-time co-authoring"

SUMMARY = (
    "\n\nVERIFIED PORTAL FOLLOW-UP\n"
    "Source: Microsoft Support - Collaborate on Word documents\n"
    "Finding: Word supports real-time co-authoring in a shared document.\n"
    "Workflow: Comments and mentions support review and follow-up.\n"
    "Practical note: Keep changes in one reviewable file instead of extra copies.\n"
)


class DemoDecisionCards:
    """Add trusted Demo context without duplicating dispatch readiness."""

    focus_taking = True

    def __init__(
        self,
        inner: DecisionCardApprovalPort,
        *,
        step_context: list[OperatorStepContext | None],
    ) -> None:
        self._inner = inner
        self._step_context = step_context
        self._approval_index = 0

    async def request_approval(self, request: ApprovalRequest) -> PolicyDecision:
        labels = (
            ("Open the public source", "Chrome"),
            ("Scroll to the next article section", "Chrome"),
            ("Switch to the research notes", "Microsoft Word"),
            ("Focus the document editor", "Microsoft Word"),
            ("Move to the follow-up section", "Microsoft Word"),
            ("Type the verified source summary", "Microsoft Word"),
            ("Save and preserve the document", "Microsoft Word"),
        )
        if self._approval_index >= len(labels):
            raise RuntimeError("DEMO_APPROVAL_STEP_OVERFLOW")
        label, application = labels[self._approval_index]
        self._approval_index += 1
        self._step_context[0] = OperatorStepContext(
            self._approval_index,
            len(labels),
            label,
            application,
        )
        decision = await self._inner.request_approval(request)
        return decision


def _fixtures() -> tuple[Path, Path, str]:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    root = ROOT / "out" / "cross-app-demo" / "runs" / stamp
    root.mkdir(parents=True, exist_ok=False)
    document = root / f"word-collaboration-research-{stamp}.docx"
    profile = root / "chrome-profile"
    profile.mkdir()
    if not WORD_TEMPLATE.is_file():
        raise RuntimeError("DEMO_WORD_TEMPLATE_NOT_FOUND")
    shutil.copy2(WORD_TEMPLATE, document)
    if any(profile.iterdir()):
        raise RuntimeError("DEMO_BROWSER_PROFILE_NOT_CLEAN")
    if document.read_bytes() != WORD_TEMPLATE.read_bytes():
        raise RuntimeError("DEMO_WORD_TEMPLATE_COPY_MISMATCH")
    with zipfile.ZipFile(document) as package:
        document_xml = package.read("word/document.xml")
    initial_text = "".join(ElementTree.fromstring(document_xml).itertext())
    if DEMO_TYPED_MARKER in initial_text:
        raise RuntimeError("DEMO_WORD_TEMPLATE_ALREADY_MODIFIED")
    initial_state = {
        "browser_profile_empty": True,
        "browser_window": {"x": 80, "y": 80, "width": 1280, "height": 900},
        "document_marker_present": False,
        "source_url": SOURCE_URL,
        "template_sha256": hashlib.sha256(document.read_bytes()).hexdigest(),
    }
    (root / "initial-state.json").write_text(
        json.dumps(initial_state, ensure_ascii=True, sort_keys=True),
        encoding="utf-8",
    )
    return document, profile, stamp


def _launch_fixtures(
    page_url: str,
    document: Path,
    profile: Path,
) -> None:
    for executable in (CHROME, WORD, MCP):
        if not executable.is_file():
            raise RuntimeError("DEMO_REQUIRED_EXECUTABLE_NOT_FOUND")
    subprocess.Popen([str(WORD), "/q", "/n", str(document)])
    time.sleep(3)
    subprocess.Popen(
        [
            str(CHROME),
            f"--user-data-dir={profile}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-default-apps",
            "--disable-extensions",
            "--disable-session-crashed-bubble",
            "--disable-sync",
            "--force-renderer-accessibility",
            "--window-position=80,80",
            "--window-size=1280,900",
            "--new-window",
            page_url,
        ]
    )
    time.sleep(5)


def _config(stamp: str) -> AgentConfig:
    state_dir = default_state_dir() / f"demo-cross-app-{stamp}"
    return AgentConfig(
        state_dir=state_dir,
        policy_version="cross-app-demo-v1",
        provider=ProviderConfig("openai", "controlled-demo-provider"),
        mcp=MCPLaunchConfig(
            executable=MCP.resolve(),
            args=(),
            cwd=ROOT.resolve(),
            environment={
                "CUMCP_ALLOWLIST": "chrome.exe,winword.exe",
                "CUMCP_HUMAN_IDLE_SECONDS": str(HUMAN_IDLE_SECONDS),
                "CUMCP_HUMAN_STABLE_SAMPLES": str(HUMAN_STABLE_SAMPLES),
                "CUMCP_HUMAN_POLL_INTERVAL_SECONDS": str(
                    HUMAN_POLL_INTERVAL_SECONDS
                ),
                "CUMCP_HUMAN_MAX_WAIT_SECONDS": str(
                    HUMAN_MAX_WAIT_SECONDS
                ),
                "CUMCP_TYPE_WAIT_SECONDS": "0.035",
            },
        ),
        policy=PolicyConfig(
            mode=APPROVED_ACTIONS_MODE,
            max_model_turns=20,
            max_tool_calls=17,
            max_side_effects=7,
        ),
        operator=OperatorConfig(
            presence_enabled=True,
            progress_enabled=True,
            decision_cards_enabled=True,
            decision_timeout_seconds=180,
            decision_card_corner="bottom_right",
        ),
    )


def _presence() -> RunPresenceCoordinator:
    return RunPresenceCoordinator(
        PassivePresenceWindow(Win32PresenceWindowApi()),
        preferences=PresencePreferences(enabled=True),
    )


def _progress(config: AgentConfig) -> RunProgressCoordinator:
    api = Win32ProgressWindowApi()
    poller = ProgressPoller(
        config.state_dir,
        PassiveProgressWindow(api),
        interval_seconds=0.5,
    )
    return RunProgressCoordinator(poller, pump=api.pump)


async def _run() -> dict[str, object]:
    document, profile, stamp = _fixtures()
    _launch_fixtures(SOURCE_URL, document, profile)
    config = _config(stamp)
    provider = CrossAppDemoProvider(
        chrome_title_fragment=SOURCE_TITLE,
        word_title_fragment=document.name,
        summary_text=SUMMARY,
    )
    step_context: list[OperatorStepContext | None] = [None]
    inner_cards = DecisionCardApprovalPort(
        DecisionCardWindow(
            Win32DecisionCardWindowApi(
                corner=config.operator.decision_card_corner,
            ),
            step_context=lambda: step_context[0],
        ),
        timeout_seconds=config.operator.decision_timeout_seconds,
    )
    approvals = DemoDecisionCards(
        inner_cards,
        step_context=step_context,
    )
    desktop = StdioDesktopMCP(config.mcp)
    outcome = await AgentRunner(
        config,
        RunnerPorts(
            provider=provider,
            desktop=desktop,
            approvals=approvals,
            presence=_presence(),
            progress=_progress(config),
        ),
    ).run(
        "Review the public Microsoft Support page in Chrome, update the "
        "disposable Word research notes, and save only after exact local approvals.",
        run_id=f"cross-app-demo-{stamp}",
        allowed_tool_names=frozenset(
            {
                "list_windows",
                "document_text",
                "ocr",
                "activate_window",
                "ui_snapshot",
                "click",
                "type",
                "key",
            }
        ),
    )
    with zipfile.ZipFile(document) as package:
        document_xml = package.read("word/document.xml")
    body = "".join(ElementTree.fromstring(document_xml).itertext())
    if outcome.text != DEMO_COMPLETE_TEXT or DEMO_TYPED_MARKER not in body:
        raise RuntimeError("DEMO_DURABLE_ARTIFACT_VERIFICATION_FAILED")
    return {
        "document": str(document),
        "result": "PASS",
        "run_id": outcome.state.run_id,
        "side_effects": outcome.state.budgets.side_effects_used,
        "tool_calls": outcome.state.budgets.tool_calls_used,
    }


def main() -> int:
    try:
        result = asyncio.run(_run())
    except KeyboardInterrupt:
        return 130
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
