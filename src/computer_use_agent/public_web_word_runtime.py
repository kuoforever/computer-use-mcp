"""Installed runtime for the fixed public-web-to-disposable-Word workflow."""

from __future__ import annotations

import hashlib
import math
import os
import shutil
import subprocess
import time
import zipfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from importlib.resources import files
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree

from PIL import Image as PILImage

from .config import (
    AgentConfig,
    ContinuationConfig,
    OperatorConfig,
    PolicyConfig,
)
from .cooperative_control import CooperativeControlPort, LocalCooperativeControl
from .disposable_process import (
    DisposableCleanup,
    DisposableProcess,
    ProcessHandle,
    ProcessWindows,
    Win32ProcessWindows,
    cleanup_disposable_processes,
)
from .public_web_word import (
    ModelDrivenPublicWebWordProvider,
    PUBLIC_WEB_WORD_ALLOWED_TOOLS,
    PUBLIC_WEB_WORD_BULLET_PREFIX,
    PUBLIC_WEB_WORD_COMPLETE_TEXT,
    PUBLIC_WEB_WORD_MARKER,
    PUBLIC_WEB_WORD_SOURCE_TITLE,
    PUBLIC_WEB_WORD_SOURCE_URL,
    PublicWebWordError,
    _contains_required_text,
    _document_text_semantically_contains_required,
    _successful_results,
    _unique_window_id,
    public_web_word_contract_error,
    public_web_word_task,
)
from .runner import AgentRunner, RunnerPorts
from .tool_registry import ToolSpec
from .types import (
    JSONValue,
    ApprovalPort,
    CallIdentity,
    DesktopMCPPort,
    ImageContent,
    LedgerEvent,
    MCPToolDescriptor,
    MemoryContextItem,
    ModelProviderPort,
    ModelTurn,
    ProviderContinuationStrategy,
    ToolCall,
    ToolResult,
)

_WORD_NAMESPACE = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_TEMPLATE_RESOURCE = "assets/public-web-word.docx"
_VISION_PREVIEW_SIZES = (
    (160, 120),
    (128, 96),
    (96, 72),
    (64, 48),
    (32, 24),
    (16, 12),
    (8, 6),
    (1, 1),
)
_VISION_PREVIEW_MAX_BYTES = 64 * 1024


@dataclass(frozen=True)
class PublicWebWordRequest:
    """One fixed-source workflow request with an explicit new DOCX target."""

    output: Path
    chrome_executable: Path | None = None
    word_executable: Path | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.output, Path) or not self.output.is_absolute():
            raise ValueError("public-web-word output must be an absolute Path")
        if self.output.suffix.lower() != ".docx":
            raise ValueError("public-web-word output must use the .docx suffix")
        for value in (self.chrome_executable, self.word_executable):
            if value is not None and (
                not isinstance(value, Path) or not value.is_absolute()
            ):
                raise ValueError("application overrides must be absolute Paths")


@dataclass(frozen=True)
class PublicWebWordFixture:
    run_id: str
    run_root: Path
    browser_profile: Path
    document: Path
    template_sha256: str


@dataclass(frozen=True)
class PublicWebWordLaunch:
    processes: tuple[DisposableProcess, ...]
    chrome_window_id: str
    word_window_id: str


@dataclass(frozen=True)
class PublicWebWordResult:
    """Bounded metadata for one durable installed-workflow result."""

    run_id: str
    provider: str
    model: str
    artifact: Path
    artifact_sha256: str
    template_sha256: str
    brief_sha256: str
    brief_characters: int
    bullet_count: int
    proposal_corrections: int
    tool_calls: int
    side_effects: int
    post_save_verified: bool
    reopen_verified: bool
    fixture_cleanup: tuple[DisposableCleanup, ...]
    verifier_cleanup: tuple[DisposableCleanup, ...]

    def as_json(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "provider": self.provider,
            "model": self.model,
            "source": {
                "title": PUBLIC_WEB_WORD_SOURCE_TITLE,
                "url": PUBLIC_WEB_WORD_SOURCE_URL,
            },
            "artifact": str(self.artifact),
            "artifact_sha256": self.artifact_sha256,
            "template_sha256": self.template_sha256,
            "brief_sha256": self.brief_sha256,
            "brief_characters": self.brief_characters,
            "bullet_count": self.bullet_count,
            "proposal_corrections": self.proposal_corrections,
            "tool_calls": self.tool_calls,
            "side_effects": self.side_effects,
            "post_save_verified": self.post_save_verified,
            "reopen_verified": self.reopen_verified,
            "fixture_cleanup": [asdict(item) for item in self.fixture_cleanup],
            "verifier_cleanup": [asdict(item) for item in self.verifier_cleanup],
        }


ProcessLauncher = Callable[[Sequence[str]], ProcessHandle]
DesktopFactory = Callable[[AgentConfig], DesktopMCPPort]


def _bounded_vision_preview(image: ImageContent) -> ImageContent:
    """Pixelate one redacted screenshot while retaining screen coordinates."""

    try:
        with PILImage.open(BytesIO(image.data)) as source:
            original_size = source.size
            grayscale = source.convert("L")
            encoded: bytes | None = None
            for sample_size in _VISION_PREVIEW_SIZES:
                samples = grayscale.copy()
                samples.thumbnail(sample_size, PILImage.Resampling.LANCZOS)
                preview = samples.resize(original_size, PILImage.Resampling.NEAREST)
                output = BytesIO()
                preview.save(output, format="PNG", optimize=True)
                candidate = output.getvalue()
                if len(candidate) <= _VISION_PREVIEW_MAX_BYTES:
                    encoded = candidate
                    break
    except (OSError, ValueError) as exc:
        raise PublicWebWordError("PUBLIC_WEB_WORD_SCREENSHOT_INVALID") from exc
    if encoded is None:
        raise PublicWebWordError("PUBLIC_WEB_WORD_SCREENSHOT_INVALID")
    return ImageContent(
        "image/png",
        encoded,
        image.width,
        image.height,
    )


class _PublicWebWordVisionDesktop:
    """Keep PRODUCT004 vision evidence inside its provider request window."""

    def __init__(self, inner: DesktopMCPPort) -> None:
        self._inner = inner

    @property
    def generation(self) -> int:
        return self._inner.generation

    @property
    def satisfied_safety_baselines(self) -> frozenset[str]:
        return self._inner.satisfied_safety_baselines

    async def discover_tools(self) -> tuple[MCPToolDescriptor, ...]:
        return await self._inner.discover_tools()

    async def call_tool(self, call: ToolCall) -> ToolResult:
        result = await self._inner.call_tool(call)
        if call.name != "screenshot" or not result.ok:
            return result
        if len(result.images) != 1:
            raise PublicWebWordError("PUBLIC_WEB_WORD_SCREENSHOT_INVALID")
        return replace(
            result,
            images=(_bounded_vision_preview(result.images[0]),),
        )

    async def close(self) -> None:
        await self._inner.close()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _document_text(document: Path) -> str:
    try:
        with zipfile.ZipFile(document) as package:
            raw = package.read("word/document.xml")
        root = ElementTree.fromstring(raw)
    except (KeyError, OSError, ElementTree.ParseError, zipfile.BadZipFile) as exc:
        raise PublicWebWordError("PUBLIC_WEB_WORD_DOCUMENT_INVALID") from exc
    paragraphs: list[str] = []
    for paragraph in root.iter(f"{{{_WORD_NAMESPACE}}}p"):
        paragraphs.append(
            "".join(
                node.text or ""
                for node in paragraph.iter(f"{{{_WORD_NAMESPACE}}}t")
            )
        )
    return "\n".join(paragraphs)


def verify_public_web_word_document(document: Path, accepted_note: str) -> str:
    """Reopen the OOXML package and require the complete ephemeral note."""

    text = _document_text(document)
    if not _contains_required_text(text, accepted_note):
        raise PublicWebWordError("PUBLIC_WEB_WORD_DURABLE_NOTE_MISSING")
    return _sha256_bytes(document.read_bytes())


def _wait_for_durable_document(
    document: Path,
    accepted_note: str,
    *,
    timeout_seconds: float = 5.0,
    poll_interval_seconds: float = 0.1,
    sleep: Callable[[float], None] = time.sleep,
) -> str:
    if (
        not math.isfinite(timeout_seconds)
        or timeout_seconds <= 0
        or not math.isfinite(poll_interval_seconds)
        or poll_interval_seconds <= 0
    ):
        raise ValueError("document durability timing must be finite and positive")
    observations = max(1, math.floor(timeout_seconds / poll_interval_seconds) + 1)
    for index in range(observations):
        try:
            return verify_public_web_word_document(document, accepted_note)
        except PublicWebWordError as exc:
            if str(exc) not in {
                "PUBLIC_WEB_WORD_DOCUMENT_INVALID",
                "PUBLIC_WEB_WORD_DURABLE_NOTE_MISSING",
            }:
                raise
        if index + 1 < observations:
            sleep(poll_interval_seconds)
    raise PublicWebWordError("PUBLIC_WEB_WORD_SAVE_NOT_DURABLE")


def _packaged_template_bytes() -> bytes:
    try:
        value = files("computer_use_agent").joinpath(_TEMPLATE_RESOURCE).read_bytes()
    except (FileNotFoundError, ModuleNotFoundError, OSError) as exc:
        raise PublicWebWordError("PUBLIC_WEB_WORD_TEMPLATE_NOT_FOUND") from exc
    if not value:
        raise PublicWebWordError("PUBLIC_WEB_WORD_TEMPLATE_INVALID")
    return value


def prepare_public_web_word_fixture(
    config: AgentConfig,
    request: PublicWebWordRequest,
    *,
    run_id: str,
) -> PublicWebWordFixture:
    """Create a unique profile and exclusive output from the packaged template."""

    if request.output.exists():
        raise PublicWebWordError("PUBLIC_WEB_WORD_OUTPUT_EXISTS")
    if not request.output.parent.is_dir():
        raise PublicWebWordError("PUBLIC_WEB_WORD_OUTPUT_PARENT_NOT_FOUND")
    run_root = config.state_dir / "workflows" / "public-web-word" / run_id
    try:
        run_root.mkdir(parents=True, exist_ok=False)
        browser_profile = run_root / "chrome-profile"
        browser_profile.mkdir()
        template = _packaged_template_bytes()
        with request.output.open("xb") as output:
            output.write(template)
    except FileExistsError as exc:
        raise PublicWebWordError("PUBLIC_WEB_WORD_FIXTURE_EXISTS") from exc
    except OSError as exc:
        raise PublicWebWordError("PUBLIC_WEB_WORD_FIXTURE_CREATE_FAILED") from exc
    if PUBLIC_WEB_WORD_MARKER in _document_text(request.output):
        raise PublicWebWordError("PUBLIC_WEB_WORD_TEMPLATE_ALREADY_COMPLETED")
    return PublicWebWordFixture(
        run_id=run_id,
        run_root=run_root,
        browser_profile=browser_profile,
        document=request.output,
        template_sha256=_sha256_bytes(template),
    )


def _candidate_paths(application: str) -> tuple[Path, ...]:
    program_files = os.environ.get("ProgramFiles")
    program_files_x86 = os.environ.get("ProgramFiles(x86)")
    local_app_data = os.environ.get("LOCALAPPDATA")
    roots = tuple(
        Path(value)
        for value in (program_files, program_files_x86, local_app_data)
        if value
    )
    if application == "chrome":
        relative = Path("Google/Chrome/Application/chrome.exe")
        return tuple(root / relative for root in roots)
    if application == "word":
        relatives = (
            Path("Microsoft Office/root/Office16/WINWORD.EXE"),
            Path("Microsoft Office/Office16/WINWORD.EXE"),
        )
        return tuple(root / relative for root in roots for relative in relatives)
    raise ValueError("unknown application")


def resolve_public_web_word_application(
    application: str,
    explicit: Path | None = None,
) -> Path:
    """Resolve Chrome or Word without any repository-relative assumption."""

    candidates: list[Path] = []
    if explicit is not None:
        candidates.append(explicit.expanduser().resolve(strict=False))
    else:
        executable_name = "chrome.exe" if application == "chrome" else "winword.exe"
        discovered = shutil.which(executable_name)
        if discovered:
            candidates.append(Path(discovered))
        candidates.extend(_candidate_paths(application))
    for candidate in candidates:
        resolved = candidate.expanduser().resolve(strict=False)
        if resolved.is_file():
            return resolved
    raise PublicWebWordError(
        f"PUBLIC_WEB_WORD_{application.upper()}_EXECUTABLE_NOT_FOUND"
    )


def _default_launcher(arguments: Sequence[str]) -> ProcessHandle:
    return subprocess.Popen(list(arguments))


def _wait_for_visible_window(
    process: ProcessHandle,
    windows: ProcessWindows,
    *,
    timeout_seconds: float = 15.0,
    poll_interval_seconds: float = 0.25,
    sleep: Callable[[float], None] = time.sleep,
) -> str:
    if (
        not math.isfinite(timeout_seconds)
        or timeout_seconds <= 0
        or not math.isfinite(poll_interval_seconds)
        or poll_interval_seconds <= 0
    ):
        raise ValueError("fixture readiness timing must be finite and positive")
    observations = max(1, math.floor(timeout_seconds / poll_interval_seconds) + 1)
    for index in range(observations):
        if process.poll() is not None:
            raise PublicWebWordError("PUBLIC_WEB_WORD_APPLICATION_EXITED_DURING_STARTUP")
        snapshot = windows.snapshot(process.pid)
        if (
            snapshot.unowned_count == 1
            and len(snapshot.unowned_window_ids) == 1
            and snapshot.unowned_window_ids[0].isdigit()
        ):
            return snapshot.unowned_window_ids[0]
        if index + 1 < observations:
            sleep(poll_interval_seconds)
    raise PublicWebWordError("PUBLIC_WEB_WORD_APPLICATION_WINDOW_NOT_READY")


def launch_public_web_word_fixtures(
    fixture: PublicWebWordFixture,
    request: PublicWebWordRequest,
    *,
    ownership: list[DisposableProcess] | None = None,
    launcher: ProcessLauncher = _default_launcher,
    windows: ProcessWindows | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> PublicWebWordLaunch:
    """Launch exact Word and fresh-profile Chrome processes and await windows."""

    process_windows = windows or Win32ProcessWindows()
    word = resolve_public_web_word_application("word", request.word_executable)
    chrome = resolve_public_web_word_application("chrome", request.chrome_executable)
    launched = ownership if ownership is not None else []
    word_process = launcher((str(word), "/q", "/x", str(fixture.document)))
    launched.append(DisposableProcess("Microsoft Word", word_process))
    word_window_id = _wait_for_visible_window(
        word_process,
        process_windows,
        sleep=sleep,
    )
    chrome_process = launcher(
        (
            str(chrome),
            f"--user-data-dir={fixture.browser_profile}",
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
            PUBLIC_WEB_WORD_SOURCE_URL,
        )
    )
    launched.append(DisposableProcess("Google Chrome", chrome_process))
    chrome_window_id = _wait_for_visible_window(
        chrome_process,
        process_windows,
        sleep=sleep,
    )
    return PublicWebWordLaunch(
        processes=tuple(launched),
        chrome_window_id=chrome_window_id,
        word_window_id=word_window_id,
    )


def _launch_word_verifier(
    document: Path,
    request: PublicWebWordRequest,
    *,
    ownership: list[DisposableProcess] | None = None,
    launcher: ProcessLauncher,
    windows: ProcessWindows,
    sleep: Callable[[float], None],
) -> tuple[DisposableProcess, str]:
    word = resolve_public_web_word_application("word", request.word_executable)
    process = launcher((str(word), "/q", "/x", str(document)))
    fixture = DisposableProcess("Microsoft Word verifier", process)
    if ownership is not None:
        ownership.append(fixture)
    window_id = _wait_for_visible_window(process, windows, sleep=sleep)
    return fixture, window_id


def _cleanup_complete(cleanup: Sequence[DisposableCleanup]) -> bool:
    return bool(cleanup) and all(item.window_cleanup_verified for item in cleanup)


def _cleanup(
    launched: Sequence[DisposableProcess],
    *,
    windows: ProcessWindows,
    sleep: Callable[[float], None],
) -> tuple[DisposableCleanup, ...]:
    return cleanup_disposable_processes(launched, windows=windows, sleep=sleep)


@dataclass
class _ReopenVerifierProvider:
    word_title_fragment: str
    expected_word_window_id: str
    accepted_note: str
    name: str = "public-web-word-reopen-verifier"
    continuation_strategy: ProviderContinuationStrategy = (
        ProviderContinuationStrategy.STATELESS_REPLAY
    )
    _step: int = 0
    _word_window_id: str | None = None

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
        if self._step == 0:
            call = self._call(run_id, turn_id, "list_windows", {})
            text = ""
        elif self._step == 1:
            results = _successful_results(ledger)
            if not results or results[-1][1].tool_name != "list_windows":
                raise PublicWebWordError("PUBLIC_WEB_WORD_REOPEN_WINDOW_LIST_FAILED")
            self._word_window_id = _unique_window_id(
                results[-1][1].sanitized_text,
                owner="winword.exe",
                title_fragment=self.word_title_fragment,
                expected_window_id=self.expected_word_window_id,
            )
            call = self._call(
                run_id,
                turn_id,
                "document_text",
                {"scope": self._word_window_id},
            )
            text = ""
        elif self._step in {2, 3}:
            results = _successful_results(ledger)
            matches = (
                bool(results)
                and results[-1][1].tool_name == "document_text"
                and _document_text_semantically_contains_required(
                    results[-1][1].sanitized_text, self.accepted_note
                )
            )
            if not matches and self._step == 2:
                if self._word_window_id is None:
                    raise PublicWebWordError("PUBLIC_WEB_WORD_REOPEN_PROVIDER_INVALID")
                call = self._call(
                    run_id,
                    turn_id,
                    "document_text",
                    {"scope": self._word_window_id},
                )
                text = ""
            elif not matches:
                raise PublicWebWordError("PUBLIC_WEB_WORD_REOPEN_TEXT_MISMATCH")
            else:
                call = None
                text = "PUBLIC_WEB_WORD_REOPEN_VERIFIED"
        else:
            raise PublicWebWordError("PUBLIC_WEB_WORD_REOPEN_PROVIDER_INVALID")
        if call is not None and call.name not in advertised:
            raise PublicWebWordError("PUBLIC_WEB_WORD_REOPEN_TOOL_NOT_ADVERTISED")
        self._step += 1
        return ModelTurn(
            run_id,
            turn_id,
            f"reopen_{turn_id}",
            text,
            () if call is None else (call,),
        )

    def export_continuation(self, run_id: str) -> Mapping[str, JSONValue]:
        del run_id
        return {"step": self._step}

    def restore_continuation(
        self,
        run_id: str,
        state: Mapping[str, JSONValue],
        *,
        tools: Sequence[ToolSpec],
    ) -> None:
        del run_id, state, tools
        raise PublicWebWordError("PUBLIC_WEB_WORD_REOPEN_CONTINUATION_FORBIDDEN")


def _reopen_config(config: AgentConfig, run_id: str) -> AgentConfig:
    state_dir = config.state_dir / "workflows" / "public-web-word" / run_id / "reopen"
    state_dir.mkdir(parents=True, exist_ok=False)
    return replace(
        config,
        state_dir=state_dir,
        policy_version="public-web-word-reopen-v1",
        policy=PolicyConfig(
            max_model_turns=4,
            max_tool_calls=3,
            max_side_effects=0,
        ),
        continuation=ContinuationConfig(enabled=False),
        operator=OperatorConfig(),
    )


def _real_provider(config: AgentConfig) -> ModelProviderPort:
    from .provider_instructions import ActionInstructionProfile

    if config.provider.name == "openai":
        from .providers.openai import OpenAIResponsesProvider

        return OpenAIResponsesProvider.from_environment(
            config.provider.model,
            allow_actions=True,
            action_instruction_profile=ActionInstructionProfile.PUBLIC_WEB_WORD,
            max_request_bytes=config.provider.max_request_bytes,
            context_window_tokens=config.provider.context_window_tokens,
            output_token_reserve=config.provider.output_token_reserve,
        )
    if config.provider.name == "anthropic":
        from .providers.anthropic import AnthropicMessagesProvider

        return AnthropicMessagesProvider.from_environment(
            config.provider.model,
            allow_actions=True,
            action_instruction_profile=ActionInstructionProfile.PUBLIC_WEB_WORD,
            max_request_bytes=config.provider.max_request_bytes,
            context_window_tokens=config.provider.context_window_tokens,
            output_token_reserve=config.provider.output_token_reserve,
        )
    raise PublicWebWordError("PUBLIC_WEB_WORD_PROVIDER_NOT_IMPLEMENTED")


def _default_desktop(config: AgentConfig) -> DesktopMCPPort:
    from .desktop_mcp import StdioDesktopMCP

    return StdioDesktopMCP(config.mcp)


async def run_public_web_word_workflow(
    config: AgentConfig,
    request: PublicWebWordRequest,
    *,
    provider: ModelProviderPort | None = None,
    desktop_factory: DesktopFactory = _default_desktop,
    approvals: ApprovalPort | None = None,
    launcher: ProcessLauncher = _default_launcher,
    windows: ProcessWindows | None = None,
    sleep: Callable[[float], None] = time.sleep,
    run_id: str | None = None,
    control: CooperativeControlPort | None = None,
) -> PublicWebWordResult:
    """Run, save, close, reopen, and independently re-read one disposable DOCX."""

    contract_error = public_web_word_contract_error(config)
    if contract_error is not None:
        raise PublicWebWordError(contract_error)
    if approvals is None:
        from .approvals import ConsoleApprovalPort

        approvals = ConsoleApprovalPort()
    resolved_run_id = run_id or f"public-web-word-{os.urandom(16).hex()}"
    cooperative_control = control or LocalCooperativeControl(
        config.state_dir,
        config.application_state_dir,
    )
    fixture = prepare_public_web_word_fixture(config, request, run_id=resolved_run_id)
    process_windows = windows or Win32ProcessWindows()
    ownership: list[DisposableProcess] = []
    fixture_cleanup: tuple[DisposableCleanup, ...] = ()
    inner_provider = provider or _real_provider(config)
    wrapper: ModelDrivenPublicWebWordProvider | None = None
    outcome = None
    accepted_note: str | None = None
    try:
        launch = launch_public_web_word_fixtures(
            fixture,
            request,
            ownership=ownership,
            launcher=launcher,
            windows=process_windows,
            sleep=sleep,
        )
        wrapper = ModelDrivenPublicWebWordProvider(
            inner_provider,
            chrome_title_fragment=PUBLIC_WEB_WORD_SOURCE_TITLE,
            word_title_fragment=fixture.document.name,
            chrome_window_id=launch.chrome_window_id,
            word_window_id=launch.word_window_id,
        )
        outcome = await AgentRunner(
            config,
            RunnerPorts(
                provider=wrapper,
                desktop=_PublicWebWordVisionDesktop(desktop_factory(config)),
                approvals=approvals,
                action_risk_classifier=wrapper,
                control=cooperative_control,
            ),
        ).run(
            public_web_word_task(fixture.document.name),
            run_id=resolved_run_id,
            allowed_tool_names=PUBLIC_WEB_WORD_ALLOWED_TOOLS,
        )
        accepted_note = wrapper.accepted_note(resolved_run_id)
        if outcome.text != PUBLIC_WEB_WORD_COMPLETE_TEXT or accepted_note is None:
            raise PublicWebWordError("PUBLIC_WEB_WORD_RUN_NOT_VERIFIED")
        _wait_for_durable_document(
            fixture.document,
            accepted_note,
            sleep=sleep,
        )
    except BaseException as exc:
        if ownership:
            fixture_cleanup = _cleanup(
                ownership,
                windows=process_windows,
                sleep=sleep,
            )
            if not _cleanup_complete(fixture_cleanup):
                raise PublicWebWordError(
                    "PUBLIC_WEB_WORD_FIXTURE_CLEANUP_INCOMPLETE"
                ) from exc
        raise
    else:
        fixture_cleanup = _cleanup(
            ownership,
            windows=process_windows,
            sleep=sleep,
        )
    if not _cleanup_complete(fixture_cleanup):
        raise PublicWebWordError("PUBLIC_WEB_WORD_FIXTURE_CLEANUP_INCOMPLETE")
    if outcome is None or accepted_note is None or wrapper is None:
        raise PublicWebWordError("PUBLIC_WEB_WORD_RESULT_UNAVAILABLE")

    verifier_ownership: list[DisposableProcess] = []
    verifier_cleanup: tuple[DisposableCleanup, ...] = ()
    verifier_outcome = None
    try:
        _verifier_fixture, verifier_window_id = _launch_word_verifier(
            fixture.document,
            request,
            ownership=verifier_ownership,
            launcher=launcher,
            windows=process_windows,
            sleep=sleep,
        )
        verifier_config = _reopen_config(config, resolved_run_id)
        verifier_outcome = await AgentRunner(
            verifier_config,
            RunnerPorts(
                provider=_ReopenVerifierProvider(
                    word_title_fragment=fixture.document.name,
                    expected_word_window_id=verifier_window_id,
                    accepted_note=accepted_note,
                ),
                desktop=desktop_factory(verifier_config),
                approvals=approvals,
                control=cooperative_control,
            ),
        ).run(
            "Reopen and verify the exact disposable Word artifact.",
            run_id=f"{resolved_run_id}-reopen",
            allowed_tool_names=frozenset({"list_windows", "document_text"}),
        )
        if verifier_outcome.text != "PUBLIC_WEB_WORD_REOPEN_VERIFIED":
            raise PublicWebWordError("PUBLIC_WEB_WORD_REOPEN_NOT_VERIFIED")
        artifact_sha256 = verify_public_web_word_document(
            fixture.document,
            accepted_note,
        )
    except BaseException as exc:
        if verifier_ownership:
            verifier_cleanup = _cleanup(
                verifier_ownership,
                windows=process_windows,
                sleep=sleep,
            )
            if not _cleanup_complete(verifier_cleanup):
                raise PublicWebWordError(
                    "PUBLIC_WEB_WORD_VERIFIER_CLEANUP_INCOMPLETE"
                ) from exc
        raise
    else:
        verifier_cleanup = _cleanup(
            verifier_ownership,
            windows=process_windows,
            sleep=sleep,
        )
    if not _cleanup_complete(verifier_cleanup):
        raise PublicWebWordError("PUBLIC_WEB_WORD_VERIFIER_CLEANUP_INCOMPLETE")
    if verifier_outcome is None:
        raise PublicWebWordError("PUBLIC_WEB_WORD_REOPEN_RESULT_UNAVAILABLE")

    lines = accepted_note.strip().splitlines()
    bullet_count = sum(
        line.startswith(PUBLIC_WEB_WORD_BULLET_PREFIX) for line in lines[3:]
    )
    result = PublicWebWordResult(
        run_id=resolved_run_id,
        provider=config.provider.name,
        model=config.provider.model,
        artifact=fixture.document,
        artifact_sha256=artifact_sha256,
        template_sha256=fixture.template_sha256,
        brief_sha256=_sha256_bytes(accepted_note.encode("utf-8")),
        brief_characters=len(accepted_note),
        bullet_count=bullet_count,
        proposal_corrections=wrapper.correction_count(resolved_run_id),
        tool_calls=(
            outcome.state.budgets.tool_calls_used
            + verifier_outcome.state.budgets.tool_calls_used
        ),
        side_effects=(
            outcome.state.budgets.side_effects_used
            + verifier_outcome.state.budgets.side_effects_used
        ),
        post_save_verified=True,
        reopen_verified=True,
        fixture_cleanup=fixture_cleanup,
        verifier_cleanup=verifier_cleanup,
    )
    # Publish the product receipt only after durable save, independent reopen,
    # exact digest, and both exact-window cleanup checks have passed.  The
    # receipt has no execution port and is not part of the automatic Full Cycle
    # export.
    from .product_receipt import write_public_web_word_receipt

    write_public_web_word_receipt(config.state_dir, result)
    return result


__all__ = [
    "PublicWebWordFixture",
    "PublicWebWordLaunch",
    "PublicWebWordRequest",
    "PublicWebWordResult",
    "launch_public_web_word_fixtures",
    "prepare_public_web_word_fixture",
    "resolve_public_web_word_application",
    "run_public_web_word_workflow",
    "verify_public_web_word_document",
]
