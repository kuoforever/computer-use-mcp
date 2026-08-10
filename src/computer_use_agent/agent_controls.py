"""Human-first quick setup and safe Agent Controls settings projection.

This module is configuration presentation only.  It creates one ordinary
configuration through the existing non-overwriting initializer and projects
the same strict ``AgentConfig`` into bounded human/JSON views.  It never reads
credential values, starts a provider/MCP/application/desktop port, registers a
shortcut, or owns approval, control, retry, replay, or dispatch authority.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from .config import (
    DEFAULT_PAUSE_SHORTCUT,
    HIGH_RISK_ONLY_APPROVAL,
    READ_ONLY_MODE,
    REQUIRED_SAFE_CHILD_ENVIRONMENT,
    AgentConfig,
    default_state_dir,
    load_agent_config,
)
from .config_init import (
    DESKTOP_ASK_PROFILE,
    PUBLIC_WEB_WORD_PROFILE,
    SUPPORTED_INIT_PROFILES,
    InitializedConfig,
    initialize_agent_config,
)
from .provider_setup import ModuleFinder, inspect_provider_setup


RECOMMENDED_MODELS: Mapping[str, str] = MappingProxyType(
    {
        "anthropic": "claude-sonnet-5",
        "deepseek": "deepseek-v4-pro",
        "doubao": "doubao-seed-2-0-lite-260215",
        "glm": "glm-5.2",
        "kimi": "kimi-k2.6",
        "minimax": "MiniMax-M2.7",
        "openai": "gpt-5.6-terra",
        "qwen": "qwen3.7-plus",
    }
)
_PURPOSES = MappingProxyType(
    {
        DESKTOP_ASK_PROFILE: "Read-only desktop questions",
        PUBLIC_WEB_WORD_PROFILE: "Supervised browser-to-Word workflow",
        "advanced": "Advanced custom configuration",
    }
)
_CONFIG_NAME = "agent.toml"
OPEN_CONTROLS_SHORTCUT = "ctrl+alt+g"
REQUEST_PAUSE_SHORTCUT = DEFAULT_PAUSE_SHORTCUT


def default_config_path(environ: Mapping[str, str] | None = None) -> Path:
    """Return the one user-local ordinary product configuration path."""

    return (default_state_dir(environ) / _CONFIG_NAME).expanduser().resolve(
        strict=False
    )


def _quoted_path(path: Path) -> str:
    return f'"{path}"'


def _profile_for(config: AgentConfig) -> str:
    if config.policy_version == "public-web-word-v2":
        return PUBLIC_WEB_WORD_PROFILE
    if config.policy_version == "readonly-v1" and config.policy.mode == READ_ONLY_MODE:
        return DESKTOP_ASK_PROFILE
    return "advanced"


def _allowed_applications(config: AgentConfig) -> tuple[str, ...]:
    raw = config.mcp.environment.get("CUMCP_ALLOWLIST", "")
    return tuple(item.strip() for item in raw.split(",") if item.strip())


@dataclass(frozen=True)
class AgentControlsSnapshot:
    """One bounded, non-authoritative settings projection."""

    config_path: Path
    config: AgentConfig
    profile: str
    provider_sdk_installed: bool
    provider_credential_present: bool
    credential_environment: str
    agent_controls_version: int = 1

    def __post_init__(self) -> None:
        if self.agent_controls_version != 1:
            raise ValueError("agent_controls_version must be 1")
        if self.profile not in {*SUPPORTED_INIT_PROFILES, "advanced"}:
            raise ValueError("agent controls profile is invalid")

    @property
    def purpose(self) -> str:
        return _PURPOSES[self.profile]

    @property
    def doctor_command(self) -> str:
        return (
            "guarded-desktop-agent config doctor --config "
            f"{_quoted_path(self.config_path)}"
        )

    @property
    def shortcuts_command(self) -> str:
        return (
            "guarded-desktop-agent shortcuts run --config "
            f"{_quoted_path(self.config_path)}"
        )

    def as_json(self) -> dict[str, object]:
        operator = self.config.operator
        approval_policy = (
            "not_applicable_read_only"
            if self.config.policy.mode == READ_ONLY_MODE
            else self.config.policy.action_approval_policy
        )
        return {
            "agent_controls_version": self.agent_controls_version,
            "configuration": {
                "config_path": str(self.config_path),
                "model": self.config.provider.model,
                "policy_mode": self.config.policy.mode,
                "profile": self.profile,
                "provider": self.config.provider.name,
                "purpose": self.purpose,
                "state_dir": str(self.config.state_dir),
            },
            "provider_setup": {
                "credential_environment": self.credential_environment,
                "credential_present": self.provider_credential_present,
                "sdk_installed": self.provider_sdk_installed,
            },
            "safety": {
                "allowed_applications": list(_allowed_applications(self.config)),
                "approval_policy": approval_policy,
                "emergency_stop": REQUIRED_SAFE_CHILD_ENVIRONMENT["CUMCP_ESTOP"],
            },
            "interface": {
                "approval_notifications_enabled": operator.approval_notifications_enabled,
                "decision_card_corner": operator.decision_card_corner,
                "decision_cards_enabled": operator.decision_cards_enabled,
                "decision_timeout_seconds": operator.decision_timeout_seconds,
                "high_contrast": operator.high_contrast,
                "locale": operator.locale,
                "presence_enabled": operator.presence_enabled,
                "progress_enabled": operator.progress_enabled,
                "reduced_motion": operator.reduced_motion,
                "theme": operator.theme,
            },
            "shortcuts": {
                "emergency_stop": REQUIRED_SAFE_CHILD_ENVIRONMENT["CUMCP_ESTOP"],
                "open_controls": OPEN_CONTROLS_SHORTCUT,
                "request_pause": operator.pause_shortcut,
                "global_approve": None,
                "global_resume": None,
                "registered_by_this_view": False,
            },
            "commands": {
                "doctor": self.doctor_command,
                "shortcuts": self.shortcuts_command,
            },
            "authority": {
                "can_approve": False,
                "can_control_task": False,
                "can_dispatch": False,
                "can_retry_or_replay": False,
                "shortcuts_registered": False,
            },
        }


@dataclass(frozen=True)
class QuickSetupResult:
    """One created config plus its safe controls projection."""

    initialized: InitializedConfig
    controls: AgentControlsSnapshot
    setup_version: int = 1

    def as_json(self) -> dict[str, object]:
        return {
            "setup_version": self.setup_version,
            "created": True,
            **self.controls.as_json(),
        }


def load_agent_controls(
    path: Path,
    *,
    environ: Mapping[str, str] | None = None,
    module_finder: ModuleFinder | None = None,
) -> AgentControlsSnapshot:
    """Load one strict config and inspect only non-secret provider presence."""

    config_path = path.expanduser().resolve(strict=True)
    config = load_agent_config(config_path)
    setup = inspect_provider_setup(
        config.provider.name,
        environ=environ,
        module_finder=module_finder,
    )
    return AgentControlsSnapshot(
        config_path=config_path,
        config=config,
        profile=_profile_for(config),
        provider_sdk_installed=setup.sdk_installed,
        provider_credential_present=setup.credential_present,
        credential_environment=setup.credential_environment,
    )


def create_quick_setup(
    *,
    profile: str = DESKTOP_ASK_PROFILE,
    provider: str = "openai",
    model: str | None = None,
    output: Path | None = None,
    allowlist: str | None = None,
    mcp_executable: Path | None = None,
    pause_shortcut: str = DEFAULT_PAUSE_SHORTCUT,
    environ: Mapping[str, str] | None = None,
    module_finder: ModuleFinder | None = None,
    base_url: str | None = None,
) -> QuickSetupResult:
    """Create one recommended config without starting any runtime port."""

    if profile not in SUPPORTED_INIT_PROFILES:
        raise ValueError("CONFIG_PROFILE_NOT_IMPLEMENTED")
    recommended = RECOMMENDED_MODELS.get(provider)
    if recommended is None:
        raise ValueError("PROVIDER_NOT_IMPLEMENTED")
    effective_model = recommended if model is None else model
    if not isinstance(effective_model, str) or not effective_model.strip():
        raise ValueError("MODEL_MUST_BE_NONEMPTY")

    if output is None:
        output_path = default_config_path(environ)
        output_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        output_path = output
    initialized = initialize_agent_config(
        profile=profile,
        provider=provider,
        model=effective_model,
        output=output_path,
        allowlist=allowlist,
        mcp_executable=mcp_executable,
        pause_shortcut=pause_shortcut,
        base_url=base_url,
    )
    controls = load_agent_controls(
        initialized.output,
        environ=os.environ if environ is None else environ,
        module_finder=module_finder,
    )
    return QuickSetupResult(initialized=initialized, controls=controls)


def _state(value: bool, *, enabled: str = "on", disabled: str = "off") -> str:
    return enabled if value else disabled


def render_agent_controls(snapshot: AgentControlsSnapshot) -> str:
    """Render one human-first settings view with an exact next command."""

    config = snapshot.config
    operator = config.operator
    applications = _allowed_applications(config)
    application_text = ", ".join(applications) if applications else "none configured"
    credential = _state(
        snapshot.provider_credential_present,
        enabled="configured",
        disabled="not configured",
    )
    sdk = _state(snapshot.provider_sdk_installed, enabled="installed", disabled="not installed")
    approval = (
        "No desktop changes"
        if config.policy.mode == READ_ONLY_MODE
        else "High-risk steps require the Decision Card"
        if config.policy.action_approval_policy == HIGH_RISK_ONLY_APPROVAL
        else "Every side effect requires the Decision Card"
    )
    return "\n".join(
        (
            "AGENT CONTROLS",
            "CONFIGURED · THIS VIEW CANNOT START OR APPROVE WORK",
            "",
            "PURPOSE",
            f"  {snapshot.purpose}",
            "",
            "CONNECTION",
            f"  Provider: {config.provider.name}",
            f"  Model: {config.provider.model}",
            f"  SDK: {sdk}",
            f"  Credential: {credential} ({snapshot.credential_environment})",
            "",
            "SAFETY",
            f"  Mode: {config.policy.mode}",
            f"  Approval: {approval}",
            f"  Allowed applications: {application_text}",
            f"  Emergency stop: {REQUIRED_SAFE_CHILD_ENVIRONMENT['CUMCP_ESTOP']}",
            "",
            "INTERFACE",
            f"  Presence: {_state(operator.presence_enabled)}",
            f"  Progress: {_state(operator.progress_enabled)}",
            f"  Decision Card: {_state(operator.decision_cards_enabled)}",
            f"  Approval notifications: {_state(operator.approval_notifications_enabled)}",
            f"  Locale / theme: {operator.locale} / {operator.theme}",
            f"  Decision timeout: {operator.decision_timeout_seconds}s",
            "",
            "SHORTCUTS",
            f"  Open Agent Controls: {OPEN_CONTROLS_SHORTCUT}",
            f"  Request safe pause: {operator.pause_shortcut}",
            f"  Emergency stop: {REQUIRED_SAFE_CHILD_ENVIRONMENT['CUMCP_ESTOP']}",
            "  Global approve / resume: not assigned",
            "  Registration: owned only by an explicit shortcuts run host",
            f"  Start: {snapshot.shortcuts_command}",
            "",
            "NEXT",
            f"  {snapshot.doctor_command}",
            "",
            "ADVANCED",
            f"  Configuration: {snapshot.config_path}",
            f"  Local state: {config.state_dir}",
        )
    )


def render_quick_setup(result: QuickSetupResult) -> str:
    """Render the bounded creation result and exact readiness action."""

    snapshot = result.controls
    provider_action = (
        f"Set {snapshot.credential_environment} in the current shell."
        if not snapshot.provider_credential_present
        else "The documented credential environment variable is configured."
    )
    sdk_action = (
        "The provider SDK is installed."
        if snapshot.provider_sdk_installed
        else f'Install the "agent-{snapshot.config.provider.name}" package extra.'
    )
    return "\n".join(
        (
            "SETUP CREATED",
            "",
            f"Purpose: {snapshot.purpose}",
            f"Provider / model: {snapshot.config.provider.name} / {snapshot.config.provider.model}",
            f"Configuration: {result.initialized.output}",
            "No credential was written to the configuration.",
            "",
            "SETUP STATUS",
            f"  {sdk_action}",
            f"  {provider_action}",
            f"  Safe pause shortcut: {snapshot.config.operator.pause_shortcut}",
            "",
            "NEXT",
            f"  {snapshot.doctor_command}",
        )
    )


__all__ = [
    "AgentControlsSnapshot",
    "OPEN_CONTROLS_SHORTCUT",
    "QuickSetupResult",
    "RECOMMENDED_MODELS",
    "REQUEST_PAUSE_SHORTCUT",
    "create_quick_setup",
    "default_config_path",
    "load_agent_controls",
    "render_agent_controls",
    "render_quick_setup",
]
