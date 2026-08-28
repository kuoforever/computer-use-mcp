"""Pure-local controller for the Offline Scope Review Formal Demo Console.

The Console is intentionally narrower than a workflow launcher.  It collects
one in-memory draft, projects the existing reviewed intent disclosure, and may
consume one process-local ``COMPILE`` permit through the fixed Host-owned local
compiler to display a complete reviewed Scope Sheet.

Free-form task text binds identity but never selects roles, outputs, budgets,
adapters, or authority.  There is no provider request, credential access,
``START`` callback, persistence, Runner, MCP, Driver, desktop-automation, or
application surface.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from threading import RLock
from typing import Never, Protocol, SupportsIndex, runtime_checkable

from .formal_demo_contract import (
    FORMAL_DEMO_V1_ROLE_PROFILES,
    FormalDemoContractError,
    ProfileBindingState,
)
from .formal_demo_intent_gate import (
    FormalDemoIntentDisclosure,
    FormalDemoIntentGateError,
    INTENT_COMPILE_TOKEN,
    IntentCompileGate,
    IntentCompileGateState,
    ProviderIntentRoute,
    ReviewedIntentDisclosureProfile,
    compile_intent_disclosure,
    reviewed_intent_disclosure_profiles,
)
from .formal_demo_local_scope import (
    FormalDemoLocalScopeError,
    LocalScopeCompilation,
    compile_local_scope_once,
    render_local_scope_review,
)
from .provider_catalog import provider_profile, resolve_provider_route


CONSOLE_TITLE = "Guarded Desktop Agent - Formal Demo Scope Review"
CONSOLE_MODE_LABEL = "OFFLINE SCOPE REVIEW - EXTERNAL WORK: NO"
SCOPE_PENDING_TEXT = "\n".join(
    (
        "Local intent compiler: Host-fixed built-in Formal Demo mapping.",
        "Free-form interpretation: no; exact task text binds identity only.",
        "Scope Sheet: pending exact COMPILE acknowledgement.",
        "Provider request: disabled.",
        "Start: unavailable and disabled.",
        "External work started: no.",
    )
)
_FIXED_ERROR_CODE = re.compile(r"[A-Z][A-Z0-9_]{2,127}\Z")


class FormalDemoConsoleError(ValueError):
    """Fixed, content-free failure at the Review-only Console boundary."""


class FormalDemoConsoleStage(str, Enum):
    DRAFT = "draft"
    DISCLOSURE_READY = "disclosure_ready"
    PERMIT_ISSUED = "permit_issued"
    SCOPE_READY = "scope_ready"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class FormalDemoRoleSummary:
    """One non-authoritative built-in role-profile display row."""

    role: str
    application_label: str
    binding_state: str
    note: str

    def render(self) -> str:
        return (
            f"{self.role}: {self.application_label} - {self.binding_state}; "
            f"{self.note}"
        )


@dataclass(frozen=True, slots=True, repr=False)
class FormalDemoConsoleView:
    """Sensitive local pixels plus content-free capability flags for one frame."""

    stage: FormalDemoConsoleStage
    provider_id: str
    region: str
    model_id: str
    protocol: str
    endpoint: str
    workspace_id: str | None
    disclosure_profile_id: str
    role_summaries: tuple[FormalDemoRoleSummary, ...]
    task_text: str = field(repr=False)
    disclosure_text: str = field(repr=False)
    scope_text: str = field(default="", repr=False)
    validation_code: str | None = None
    start_enabled: bool = False
    scope_available: bool = False

    def __post_init__(self) -> None:
        expected_scope_available = self.stage is FormalDemoConsoleStage.SCOPE_READY
        if (
            type(self.stage) is not FormalDemoConsoleStage
            or type(self.task_text) is not str
            or type(self.disclosure_text) is not str
            or type(self.scope_text) is not str
            or type(self.scope_available) is not bool
            or self.scope_available != expected_scope_available
            or bool(self.scope_text) != self.scope_available
            or self.start_enabled is not False
            or (
                self.validation_code is not None
                and (
                    type(self.validation_code) is not str
                    or _FIXED_ERROR_CODE.fullmatch(self.validation_code) is None
                )
            )
        ):
            raise FormalDemoConsoleError("FORMAL_DEMO_CONSOLE_AUTHORITY_INVALID")

    @property
    def review_enabled(self) -> bool:
        return self.stage is FormalDemoConsoleStage.DRAFT

    @property
    def acknowledgement_enabled(self) -> bool:
        return self.stage is FormalDemoConsoleStage.DISCLOSURE_READY

    @property
    def task_editable(self) -> bool:
        return self.stage is FormalDemoConsoleStage.DRAFT

    @property
    def route_text(self) -> str:
        workspace = "none" if self.workspace_id is None else self.workspace_id
        return "\n".join(
            (
                "Configured identity only - credential and provider readiness unchecked.",
                f"Provider: {self.provider_id}",
                f"Region: {self.region}",
                f"Model: {self.model_id}",
                f"Protocol: {self.protocol}",
                f"Endpoint: {self.endpoint}",
                f"Workspace: {workspace}",
                f"Disclosure profile: {self.disclosure_profile_id}",
            )
        )

    @property
    def detail_text(self) -> str:
        role_text = "\n".join(summary.render() for summary in self.role_summaries)
        sections = [
            CONSOLE_MODE_LABEL,
            self.route_text,
            "Application-role design bindings (not readiness or evidence):\n" + role_text,
            (
                "This Console will consume COMPILE only through the fixed local "
                "Host compiler. The selected provider route remains future identity "
                "and disclosure context; no task text is sent in this slice."
            ),
        ]
        if self.disclosure_text:
            sections.append(self.disclosure_text.rstrip("\n"))
        if self.scope_text:
            sections.append(self.scope_text.rstrip("\n"))
        else:
            sections.append(SCOPE_PENDING_TEXT)
        if (
            self.stage is FormalDemoConsoleStage.PERMIT_ISSUED
            and self.validation_code is not None
        ):
            sections.append(
                "One process-local COMPILE permit was issued but no Scope result was "
                "returned. This attempt is terminal; close or reset to abandon it."
            )
        if self.validation_code is not None:
            sections.append(f"Validation stopped: {self.validation_code}")
        return "\n\n".join(sections) + "\n"

    def __repr__(self) -> str:
        return (
            "<FormalDemoConsoleView "
            f"stage={self.stage.value} provider={self.provider_id} "
            "local-sensitive>"
        )

    def __copy__(self) -> Never:
        raise FormalDemoConsoleError("FORMAL_DEMO_CONSOLE_VIEW_OPAQUE")

    def __deepcopy__(self, _memo: object) -> Never:
        raise FormalDemoConsoleError("FORMAL_DEMO_CONSOLE_VIEW_OPAQUE")

    def __reduce__(self) -> Never:
        raise FormalDemoConsoleError("FORMAL_DEMO_CONSOLE_VIEW_OPAQUE")

    def __reduce_ex__(self, _protocol: SupportsIndex) -> Never:
        raise FormalDemoConsoleError("FORMAL_DEMO_CONSOLE_VIEW_OPAQUE")


def _fixed_code(error: BaseException, fallback: str) -> str:
    try:
        candidate = str(error)
    except BaseException:
        return fallback
    return candidate if _FIXED_ERROR_CODE.fullmatch(candidate) is not None else fallback


def build_console_route(
    *,
    provider_id: str,
    model_id: str,
    region: str | None = None,
    workspace_id: str | None = None,
    base_url: str | None = None,
) -> ProviderIntentRoute:
    """Build one inert reviewed route identity from explicit non-secret arguments."""

    try:
        resolved = resolve_provider_route(
            provider_id,
            region=region,
            workspace_id=workspace_id,
            base_url=base_url,
            legacy_credentials=False,
        )
        protocol = provider_profile(provider_id).protocol
        return ProviderIntentRoute(
            provider_id=resolved.name,
            region=resolved.region,
            model_id=model_id,
            protocol=protocol,
            endpoint=resolved.base_url,
            workspace_id=resolved.workspace_id,
        )
    except FormalDemoIntentGateError:
        raise
    except Exception:
        raise FormalDemoConsoleError("FORMAL_DEMO_CONSOLE_ROUTE_INVALID") from None


def _reviewed_profile(provider_id: str) -> ReviewedIntentDisclosureProfile:
    matches = tuple(
        profile
        for profile in reviewed_intent_disclosure_profiles()
        if profile.provider_id == provider_id
    )
    if len(matches) != 1:
        raise FormalDemoConsoleError("FORMAL_DEMO_CONSOLE_PROFILE_UNAVAILABLE")
    return matches[0]


def _role_summaries() -> tuple[FormalDemoRoleSummary, ...]:
    summaries: list[FormalDemoRoleSummary] = []
    for profile in FORMAL_DEMO_V1_ROLE_PROFILES:
        selected = profile.binding_state is ProfileBindingState.SELECTED
        summaries.append(
            FormalDemoRoleSummary(
                role=profile.role.value,
                application_label=profile.application_label,
                binding_state=profile.binding_state.value,
                note=(
                    "inert design binding only; application readiness unchecked"
                    if selected
                    else "no adapter selected; this blocks the complete built-in scope"
                ),
            )
        )
    return tuple(summaries)


class FormalDemoConsoleSession:
    """One opaque in-memory Review-only attempt with no execution method."""

    def __init__(
        self,
        route: ProviderIntentRoute,
        *,
        identity_factory: Callable[[], str],
    ) -> None:
        if type(route) is not ProviderIntentRoute or not callable(identity_factory):
            raise FormalDemoConsoleError("FORMAL_DEMO_CONSOLE_SESSION_INVALID")
        try:
            self._route = ProviderIntentRoute(
                provider_id=route.provider_id,
                region=route.region,
                model_id=route.model_id,
                protocol=route.protocol,
                endpoint=route.endpoint,
                workspace_id=route.workspace_id,
            )
        except Exception:
            raise FormalDemoConsoleError("FORMAL_DEMO_CONSOLE_ROUTE_INVALID") from None
        if self._route.canonical_payload() != route.canonical_payload():
            raise FormalDemoConsoleError("FORMAL_DEMO_CONSOLE_ROUTE_INVALID")
        self._profile = _reviewed_profile(self._route.provider_id)
        self._identity_factory = identity_factory
        self._gate: IntentCompileGate | None = None
        self._task_text = ""
        self._disclosure: FormalDemoIntentDisclosure | None = None
        self._scope_result: LocalScopeCompilation | None = None
        self._validation_code: str | None = None
        self._cancelled = False
        self._lock = RLock()

    def __repr__(self) -> str:
        return (
            "<FormalDemoConsoleSession "
            f"stage={self.stage.value} provider={self._route.provider_id} opaque>"
        )

    def __copy__(self) -> Never:
        raise FormalDemoConsoleError("FORMAL_DEMO_CONSOLE_SESSION_OPAQUE")

    def __deepcopy__(self, _memo: object) -> Never:
        raise FormalDemoConsoleError("FORMAL_DEMO_CONSOLE_SESSION_OPAQUE")

    def __reduce__(self) -> Never:
        raise FormalDemoConsoleError("FORMAL_DEMO_CONSOLE_SESSION_OPAQUE")

    def __reduce_ex__(self, _protocol: SupportsIndex) -> Never:
        raise FormalDemoConsoleError("FORMAL_DEMO_CONSOLE_SESSION_OPAQUE")

    @property
    def stage(self) -> FormalDemoConsoleStage:
        with self._lock:
            if self._cancelled:
                return FormalDemoConsoleStage.CANCELLED
            if self._gate is None:
                return FormalDemoConsoleStage.DRAFT
            if self._scope_result is not None:
                return FormalDemoConsoleStage.SCOPE_READY
            state = self._gate.state
            if state is IntentCompileGateState.READY:
                return FormalDemoConsoleStage.DISCLOSURE_READY
            if state is IntentCompileGateState.PERMITTED:
                return FormalDemoConsoleStage.PERMIT_ISSUED
            return FormalDemoConsoleStage.CANCELLED

    def view(self) -> FormalDemoConsoleView:
        with self._lock:
            disclosure_text = (
                "" if self._disclosure is None else self._disclosure.render()
            )
            scope_text = (
                ""
                if self._scope_result is None
                else render_local_scope_review(self._scope_result)
            )
            return FormalDemoConsoleView(
                stage=self.stage,
                provider_id=self._route.provider_id,
                region=self._route.region,
                model_id=self._route.model_id,
                protocol=self._route.protocol.value,
                endpoint=self._route.endpoint,
                workspace_id=self._route.workspace_id,
                disclosure_profile_id=self._profile.profile_id,
                role_summaries=_role_summaries(),
                task_text=self._task_text,
                disclosure_text=disclosure_text,
                scope_text=scope_text,
                validation_code=self._validation_code,
                scope_available=self._scope_result is not None,
            )

    def review(self, task_text: object) -> FormalDemoConsoleView:
        """Bind one exact draft to the existing local disclosure contract."""

        with self._lock:
            if self._cancelled or self._gate is not None:
                self._validation_code = "FORMAL_DEMO_CONSOLE_ATTEMPT_TERMINAL"
                return self.view()
            if type(task_text) is not str:
                self._validation_code = "FORMAL_DEMO_CONSOLE_TASK_INVALID"
                return self.view()
            try:
                identity = self._identity_factory()
                if type(identity) is not str:
                    raise TypeError
                disclosure = compile_intent_disclosure(
                    disclosure_id=f"formal-demo-disclosure-{identity}",
                    resume_identity=f"formal-demo-review-{identity}",
                    source_task=task_text,
                    route=self._route,
                    profile_id=self._profile.profile_id,
                    profile_version=self._profile.version,
                    expected_profile_digest=self._profile.content_digest,
                )
                gate = IntentCompileGate(disclosure)
            except FormalDemoIntentGateError as exc:
                self._validation_code = _fixed_code(
                    exc,
                    "FORMAL_DEMO_CONSOLE_DISCLOSURE_INVALID",
                )
                return self.view()
            except Exception:
                self._validation_code = "FORMAL_DEMO_CONSOLE_DISCLOSURE_INVALID"
                return self.view()
            self._task_text = task_text
            self._disclosure = disclosure
            self._gate = gate
            self._validation_code = None
            return self.view()

    def acknowledge(self, token: object) -> FormalDemoConsoleView:
        """Issue and consume one permit through the fixed local Scope compiler."""

        with self._lock:
            if self._cancelled or self._gate is None:
                self._validation_code = "FORMAL_DEMO_CONSOLE_DISCLOSURE_REQUIRED"
                return self.view()
            try:
                permit = self._gate.acknowledge(token)
                if self._disclosure is None:
                    raise FormalDemoConsoleError(
                        "FORMAL_DEMO_CONSOLE_DISCLOSURE_REQUIRED"
                    )
                self._scope_result = compile_local_scope_once(
                    gate=self._gate,
                    permit=permit,
                    current_disclosure=self._disclosure,
                )
            except (
                FormalDemoConsoleError,
                FormalDemoContractError,
                FormalDemoIntentGateError,
                FormalDemoLocalScopeError,
            ) as exc:
                self._validation_code = _fixed_code(
                    exc,
                    "FORMAL_DEMO_CONSOLE_SCOPE_COMPILATION_FAILED",
                )
                return self.view()
            except Exception:
                self._validation_code = "FORMAL_DEMO_CONSOLE_SCOPE_COMPILATION_FAILED"
                return self.view()
            self._validation_code = None
            return self.view()

    def reset(self) -> FormalDemoConsoleView:
        """Abandon the entire process-local attempt and return to a fresh draft."""

        with self._lock:
            if self._gate is not None and self._gate.state is IntentCompileGateState.READY:
                try:
                    self._gate.cancel()
                except FormalDemoIntentGateError:
                    pass
            self._gate = None
            self._disclosure = None
            self._scope_result = None
            self._task_text = ""
            self._validation_code = None
            self._cancelled = False
            return self.view()

    def cancel(self) -> FormalDemoConsoleView:
        """Abandon all local review data without starting external work."""

        with self._lock:
            if self._gate is not None and self._gate.state is IntentCompileGateState.READY:
                try:
                    self._gate.cancel()
                except FormalDemoIntentGateError:
                    pass
            self._gate = None
            self._disclosure = None
            self._scope_result = None
            self._task_text = ""
            self._validation_code = None
            self._cancelled = True
            return self.view()


@dataclass(frozen=True, slots=True)
class FormalDemoConsoleCallbacks:
    on_review: Callable[[], None]
    on_acknowledge: Callable[[], None]
    on_reset: Callable[[], None]
    on_cancel: Callable[[], None]


@runtime_checkable
class FormalDemoConsoleWindowApi(Protocol):
    """UI-only surface; deliberately no start, dispatch, or provider callback."""

    def create(self, *, title: str, callbacks: FormalDemoConsoleCallbacks) -> int: ...

    def apply(self, hwnd: int, view: FormalDemoConsoleView) -> None: ...

    def read_task(self, hwnd: int) -> str: ...

    def read_acknowledgement(self, hwnd: int) -> str: ...

    def focus_task(self, hwnd: int) -> None: ...

    def show(self, hwnd: int) -> None: ...

    def run(self, hwnd: int) -> int: ...

    def destroy(self, hwnd: int) -> None: ...


class FormalDemoConsoleWindow:
    """Bind one session to a UI API without adding any execution transition."""

    def __init__(
        self,
        session: FormalDemoConsoleSession,
        api: FormalDemoConsoleWindowApi,
    ) -> None:
        if not isinstance(session, FormalDemoConsoleSession) or not isinstance(
            api, FormalDemoConsoleWindowApi
        ):
            raise FormalDemoConsoleError("FORMAL_DEMO_CONSOLE_WINDOW_INVALID")
        self._session = session
        self._api = api
        self._hwnd: int | None = None

    @property
    def hwnd(self) -> int | None:
        return self._hwnd

    def open(self) -> int:
        if self._hwnd is not None:
            existing_hwnd = self._hwnd
            try:
                self._api.apply(existing_hwnd, self._session.view())
                return existing_hwnd
            except Exception:
                self._discard_window(existing_hwnd)
                raise FormalDemoConsoleError(
                    "FORMAL_DEMO_CONSOLE_WINDOW_FAILED"
                ) from None
        callbacks = FormalDemoConsoleCallbacks(
            on_review=self._review,
            on_acknowledge=self._acknowledge,
            on_reset=self._reset,
            on_cancel=self.close,
        )
        hwnd: int | None = None
        try:
            hwnd = self._api.create(title=CONSOLE_TITLE, callbacks=callbacks)
            self._hwnd = hwnd
            self._api.apply(hwnd, self._session.view())
            self._api.show(hwnd)
            self._api.focus_task(hwnd)
            return hwnd
        except Exception:
            if hwnd is not None:
                self._discard_window(hwnd)
            else:
                self._session.cancel()
            raise FormalDemoConsoleError(
                "FORMAL_DEMO_CONSOLE_WINDOW_FAILED"
            ) from None

    def run(self) -> int:
        try:
            hwnd = self.open()
            return self._api.run(hwnd)
        except Exception:
            raise FormalDemoConsoleError(
                "FORMAL_DEMO_CONSOLE_WINDOW_FAILED"
            ) from None
        finally:
            self.close()

    def close(self) -> None:
        self._session.cancel()
        if self._hwnd is not None:
            hwnd = self._hwnd
            self._hwnd = None
            try:
                self._api.destroy(hwnd)
            except Exception:
                raise FormalDemoConsoleError(
                    "FORMAL_DEMO_CONSOLE_WINDOW_FAILED"
                ) from None

    def _discard_window(self, hwnd: int) -> None:
        self._session.cancel()
        self._hwnd = None
        try:
            self._api.destroy(hwnd)
        except Exception:
            pass

    def _review(self) -> None:
        if self._hwnd is None:
            return
        view = self._session.review(self._api.read_task(self._hwnd))
        self._api.apply(self._hwnd, view)

    def _acknowledge(self) -> None:
        if self._hwnd is None:
            return
        view = self._session.acknowledge(
            self._api.read_acknowledgement(self._hwnd)
        )
        self._api.apply(self._hwnd, view)

    def _reset(self) -> None:
        if self._hwnd is None:
            return
        view = self._session.reset()
        self._api.apply(self._hwnd, view)
        self._api.focus_task(self._hwnd)


__all__ = [
    "CONSOLE_MODE_LABEL",
    "CONSOLE_TITLE",
    "SCOPE_PENDING_TEXT",
    "FormalDemoConsoleCallbacks",
    "FormalDemoConsoleError",
    "FormalDemoConsoleSession",
    "FormalDemoConsoleStage",
    "FormalDemoConsoleView",
    "FormalDemoConsoleWindow",
    "FormalDemoConsoleWindowApi",
    "FormalDemoRoleSummary",
    "build_console_route",
    "INTENT_COMPILE_TOKEN",
]
