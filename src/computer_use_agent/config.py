"""Configuration contract for the planned local Agent Host.

Configuration contains no credentials. The fixed MCP child gets a reviewed,
host-generated environment rather than inherited process variables.
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from math import isfinite
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from .types import (
    DEFAULT_PROVIDER_CONTEXT_TOKENS,
    DEFAULT_PROVIDER_OUTPUT_TOKENS,
    DEFAULT_PROVIDER_REQUEST_BYTES,
    MAX_PROVIDER_CONTEXT_TOKENS,
    MAX_PROVIDER_REQUEST_BYTES,
    MIN_PROVIDER_CONTEXT_TOKENS,
    MIN_PROVIDER_REQUEST_BYTES,
)


class ConfigError(ValueError):
    """Raised when a host configuration violates a fail-closed invariant."""


READ_ONLY_MODE = "read_only"
APPROVED_ACTIONS_MODE = "approved_actions"
AGENTIC_ACTIONS_MODE = "agentic_actions"
ACTION_CAPABLE_MODES = frozenset({APPROVED_ACTIONS_MODE, AGENTIC_ACTIONS_MODE})
DEFAULT_PROVIDER_TIMEOUT_SECONDS = 120
MIN_PROVIDER_TIMEOUT_SECONDS = 1
MAX_PROVIDER_TIMEOUT_SECONDS = 600
SUPPORTED_PROVIDERS = frozenset({"openai", "anthropic"})
SUPPORTED_PRIVACY_DETECTORS = frozenset(
    {"email", "phone", "ipv4", "cn_id", "bank_card", "secret"}
)
MINIMUM_HUMAN_IDLE_SECONDS = 2.5
MINIMUM_HUMAN_POLL_INTERVAL_SECONDS = 0.05
MAXIMUM_HUMAN_POLL_INTERVAL_SECONDS = 5.0
MINIMUM_HUMAN_MAX_WAIT_SECONDS = 1.0
MAXIMUM_HUMAN_MAX_WAIT_SECONDS = 300.0
MAXIMUM_HUMAN_STABLE_SAMPLES = 20
MAXIMUM_TYPE_WAIT_SECONDS = 0.1

# These are the only server configuration inputs the host is willing to pass
# through. Audit and screenshot-redaction destinations remain server defaults so
# configuration cannot disable or redirect those safety records.
REVIEWED_MCP_ENVIRONMENT_NAMES = frozenset(
    {
        "CUMCP_ALLOWLIST",
        "CUMCP_MODE",
        "CUMCP_HUMAN_IDLE_SECONDS",
        "CUMCP_HUMAN_STABLE_SAMPLES",
        "CUMCP_HUMAN_POLL_INTERVAL_SECONDS",
        "CUMCP_HUMAN_MAX_WAIT_SECONDS",
        "CUMCP_INTERACTION_SPEED",
        "CUMCP_ACTION_FEEDBACK",
        "CUMCP_TYPE_WAIT_SECONDS",
        "CUMCP_DANGEROUS_CONFIRM",
    }
)
REQUIRED_SAFE_CHILD_ENVIRONMENT = MappingProxyType(
    {
        "CUMCP_MODE": "safe_local",
        "CUMCP_HUMAN_IDLE_SECONDS": str(MINIMUM_HUMAN_IDLE_SECONDS),
        "CUMCP_DANGEROUS_CONFIRM": "1",
        "CUMCP_ESTOP": "ctrl+alt+q",
    }
)


def default_state_dir(environ: Mapping[str, str] | None = None) -> Path:
    """Return the user-local application root for all host state."""

    environment = os.environ if environ is None else environ
    local_app_data = environment.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "computer-use-agent"
    return Path.home() / ".local" / "state" / "computer-use-agent"


def _require_absolute_path(value: str, field_name: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{field_name} must be a non-empty absolute path")
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ConfigError(f"{field_name} must be absolute")
    return path


def _require_user_local_state_dir(path: Path) -> Path:
    root = default_state_dir().resolve(strict=False)
    candidate = path.resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ConfigError("agent state_dir must be inside the user-local application directory") from exc
    return candidate


def _validate_allowlist(value: str) -> None:
    names = [name.strip() for name in value.split(",")]
    if not names or any(not name or not name.lower().endswith(".exe") for name in names):
        raise ConfigError("CUMCP_ALLOWLIST must be a non-empty comma-separated list of .exe names")
    if any("*" in name or "/" in name or "\\" in name for name in names):
        raise ConfigError("CUMCP_ALLOWLIST entries must be literal executable names")


def _validate_mcp_environment_value(key: str, value: str) -> None:
    if key == "CUMCP_ALLOWLIST":
        _validate_allowlist(value)
    elif key == "CUMCP_MODE" and value.strip().lower() != "safe_local":
        raise ConfigError("CUMCP_MODE must remain safe_local")
    elif key == "CUMCP_DANGEROUS_CONFIRM" and value.strip().lower() not in {
        "1",
        "true",
        "yes",
        "on",
    }:
        raise ConfigError("CUMCP_DANGEROUS_CONFIRM must remain enabled")
    elif key == "CUMCP_HUMAN_IDLE_SECONDS":
        try:
            seconds = float(value)
        except ValueError as exc:
            raise ConfigError("CUMCP_HUMAN_IDLE_SECONDS must be numeric") from exc
        if not isfinite(seconds) or seconds < MINIMUM_HUMAN_IDLE_SECONDS:
            raise ConfigError(
                f"CUMCP_HUMAN_IDLE_SECONDS must be at least {MINIMUM_HUMAN_IDLE_SECONDS}"
            )
    elif key == "CUMCP_HUMAN_STABLE_SAMPLES":
        try:
            samples = int(value)
        except ValueError as exc:
            raise ConfigError(
                "CUMCP_HUMAN_STABLE_SAMPLES must be an integer"
            ) from exc
        if not 1 <= samples <= MAXIMUM_HUMAN_STABLE_SAMPLES:
            raise ConfigError(
                "CUMCP_HUMAN_STABLE_SAMPLES must be between "
                f"1 and {MAXIMUM_HUMAN_STABLE_SAMPLES}"
            )
    elif key == "CUMCP_HUMAN_POLL_INTERVAL_SECONDS":
        try:
            seconds = float(value)
        except ValueError as exc:
            raise ConfigError(
                "CUMCP_HUMAN_POLL_INTERVAL_SECONDS must be numeric"
            ) from exc
        if (
            not isfinite(seconds)
            or not MINIMUM_HUMAN_POLL_INTERVAL_SECONDS
            <= seconds
            <= MAXIMUM_HUMAN_POLL_INTERVAL_SECONDS
        ):
            raise ConfigError(
                "CUMCP_HUMAN_POLL_INTERVAL_SECONDS must be between "
                f"{MINIMUM_HUMAN_POLL_INTERVAL_SECONDS} and "
                f"{MAXIMUM_HUMAN_POLL_INTERVAL_SECONDS}"
            )
    elif key == "CUMCP_HUMAN_MAX_WAIT_SECONDS":
        try:
            seconds = float(value)
        except ValueError as exc:
            raise ConfigError(
                "CUMCP_HUMAN_MAX_WAIT_SECONDS must be numeric"
            ) from exc
        if (
            not isfinite(seconds)
            or not MINIMUM_HUMAN_MAX_WAIT_SECONDS
            <= seconds
            <= MAXIMUM_HUMAN_MAX_WAIT_SECONDS
        ):
            raise ConfigError(
                "CUMCP_HUMAN_MAX_WAIT_SECONDS must be between "
                f"{MINIMUM_HUMAN_MAX_WAIT_SECONDS} and "
                f"{MAXIMUM_HUMAN_MAX_WAIT_SECONDS}"
            )
    elif key == "CUMCP_TYPE_WAIT_SECONDS":
        try:
            seconds = float(value)
        except ValueError as exc:
            raise ConfigError("CUMCP_TYPE_WAIT_SECONDS must be numeric") from exc
        if not isfinite(seconds) or not 0.0 <= seconds <= MAXIMUM_TYPE_WAIT_SECONDS:
            raise ConfigError(
                f"CUMCP_TYPE_WAIT_SECONDS must be between 0 and "
                f"{MAXIMUM_TYPE_WAIT_SECONDS}"
            )
    elif key == "CUMCP_INTERACTION_SPEED" and value.strip().lower() not in {
        "fast",
        "normal",
        "deliberate",
    }:
        raise ConfigError(
            "CUMCP_INTERACTION_SPEED must be fast, normal, or deliberate"
        )
    elif key == "CUMCP_ACTION_FEEDBACK" and value.strip().lower() not in {
        "0",
        "1",
        "false",
        "true",
        "no",
        "yes",
        "off",
        "on",
    }:
        raise ConfigError("CUMCP_ACTION_FEEDBACK must be boolean")


def _read_table(document: Mapping[str, object], name: str, *, required: bool) -> Mapping[str, object]:
    value = document.get(name)
    if value is None:
        if required:
            raise ConfigError(f"missing [{name}] section")
        return {}
    if not isinstance(value, Mapping):
        raise ConfigError(f"[{name}] must be a table")
    return value


def _reject_unknown(table: Mapping[str, object], allowed: set[str], section: str) -> None:
    unknown = sorted(set(table) - allowed)
    if unknown:
        raise ConfigError(f"unknown [{section}] key(s): {', '.join(unknown)}")


def _read_nonempty_string(table: Mapping[str, object], key: str, section: str) -> str:
    value = table.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"[{section}].{key} must be a non-empty string")
    return value


def _read_nonnegative_int(table: Mapping[str, object], key: str, section: str, default: int) -> int:
    value = table.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ConfigError(f"[{section}].{key} must be a non-negative integer")
    return value


def _read_positive_int(table: Mapping[str, object], key: str, section: str) -> int:
    value = table.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ConfigError(f"[{section}].{key} must be a positive integer")
    return value


def _read_string_array(
    table: Mapping[str, object], key: str, section: str, default: tuple[str, ...]
) -> tuple[str, ...]:
    value = table.get(key, list(default))
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ConfigError(f"[{section}].{key} must be an array of strings")
    return tuple(value)


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    model: str
    max_request_bytes: int = DEFAULT_PROVIDER_REQUEST_BYTES
    context_window_tokens: int = DEFAULT_PROVIDER_CONTEXT_TOKENS
    output_token_reserve: int = DEFAULT_PROVIDER_OUTPUT_TOKENS
    request_timeout_seconds: int = DEFAULT_PROVIDER_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or self.name not in SUPPORTED_PROVIDERS:
            choices = ", ".join(sorted(SUPPORTED_PROVIDERS))
            raise ConfigError(f"provider name must be one of: {choices}")
        if not isinstance(self.model, str) or not self.model.strip():
            raise ConfigError("provider model must be a non-empty string")
        if (
            isinstance(self.max_request_bytes, bool)
            or not isinstance(self.max_request_bytes, int)
            or not MIN_PROVIDER_REQUEST_BYTES
            <= self.max_request_bytes
            <= MAX_PROVIDER_REQUEST_BYTES
        ):
            raise ConfigError(
                "provider max_request_bytes must be between "
                f"{MIN_PROVIDER_REQUEST_BYTES} and {MAX_PROVIDER_REQUEST_BYTES}"
            )
        if (
            isinstance(self.context_window_tokens, bool)
            or not isinstance(self.context_window_tokens, int)
            or not MIN_PROVIDER_CONTEXT_TOKENS
            <= self.context_window_tokens
            <= MAX_PROVIDER_CONTEXT_TOKENS
        ):
            raise ConfigError(
                "provider context_window_tokens must be between "
                f"{MIN_PROVIDER_CONTEXT_TOKENS} and {MAX_PROVIDER_CONTEXT_TOKENS}"
            )
        if (
            isinstance(self.output_token_reserve, bool)
            or not isinstance(self.output_token_reserve, int)
            or self.output_token_reserve <= 0
            or self.output_token_reserve >= self.context_window_tokens
        ):
            raise ConfigError(
                "provider output_token_reserve must be positive and smaller than "
                "context_window_tokens"
            )
        if (
            isinstance(self.request_timeout_seconds, bool)
            or not isinstance(self.request_timeout_seconds, int)
            or not MIN_PROVIDER_TIMEOUT_SECONDS
            <= self.request_timeout_seconds
            <= MAX_PROVIDER_TIMEOUT_SECONDS
        ):
            raise ConfigError(
                "provider request_timeout_seconds must be between "
                f"{MIN_PROVIDER_TIMEOUT_SECONDS} and {MAX_PROVIDER_TIMEOUT_SECONDS}"
            )


@dataclass(frozen=True)
class MCPLaunchConfig:
    """Fixed stdio child-process launch inputs; no shell or inherited env."""

    executable: Path
    args: tuple[str, ...]
    cwd: Path
    environment: Mapping[str, str]

    def __post_init__(self) -> None:
        if not isinstance(self.executable, Path):
            raise ConfigError("mcp executable must be a Path")
        if not isinstance(self.cwd, Path):
            raise ConfigError("mcp cwd must be a Path")
        if not self.executable.is_absolute():
            raise ConfigError("mcp executable must be absolute")
        if not self.cwd.is_absolute():
            raise ConfigError("mcp cwd must be absolute")
        if not isinstance(self.args, tuple) or not all(isinstance(arg, str) for arg in self.args):
            raise ConfigError("mcp args must be a tuple of strings")
        if not isinstance(self.environment, Mapping):
            raise ConfigError("mcp environment must be a string mapping")
        copied: dict[str, str] = {}
        for key, value in self.environment.items():
            if not isinstance(key, str) or not key:
                raise ConfigError("mcp environment names must be non-empty strings")
            if not isinstance(value, str):
                raise ConfigError("mcp environment values must be strings")
            if key not in REVIEWED_MCP_ENVIRONMENT_NAMES:
                raise ConfigError(f"mcp environment key is not reviewed: {key}")
            _validate_mcp_environment_value(key, value)
            copied[key] = value
        object.__setattr__(self, "environment", MappingProxyType(copied))

    def child_environment(self) -> dict[str, str]:
        """Return reviewed server controls, excluding credentials and arbitrary host variables.

        The MCP SDK adds only its fixed platform-bootstrap allowlist (for example
        SYSTEMROOT, PATH, and TEMP) when creating the child process.
        """

        return {**REQUIRED_SAFE_CHILD_ENVIRONMENT, **self.environment}


@dataclass(frozen=True)
class PolicyConfig:
    mode: str = READ_ONLY_MODE
    require_approval_for_actions: bool = True
    max_model_turns: int = 12
    max_tool_calls: int = 32
    max_side_effects: int = 8
    max_context_events: int = 128
    max_input_tokens: int = 1_000_000

    def __post_init__(self) -> None:
        if not isinstance(self.mode, str) or self.mode not in {
            READ_ONLY_MODE,
            APPROVED_ACTIONS_MODE,
            AGENTIC_ACTIONS_MODE,
        }:
            raise ConfigError(
                "policy mode must be read_only, approved_actions, or agentic_actions"
            )
        if not isinstance(self.require_approval_for_actions, bool):
            raise ConfigError("require_approval_for_actions must be boolean")
        if self.mode == APPROVED_ACTIONS_MODE and not self.require_approval_for_actions:
            raise ConfigError("approved_actions mode requires per-action host approval")
        if self.mode == AGENTIC_ACTIONS_MODE and self.require_approval_for_actions:
            raise ConfigError(
                "agentic_actions mode requires require_approval_for_actions=false"
            )
        for field_name, value in (
            ("max_model_turns", self.max_model_turns),
            ("max_tool_calls", self.max_tool_calls),
            ("max_side_effects", self.max_side_effects),
            ("max_context_events", self.max_context_events),
            ("max_input_tokens", self.max_input_tokens),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ConfigError(f"{field_name} must be a non-negative integer")
        if self.max_context_events == 0:
            raise ConfigError("max_context_events must be a positive integer")


@dataclass(frozen=True)
class ContinuationConfig:
    enabled: bool = False
    ttl_seconds: int = 900

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise ConfigError("continuation enabled must be boolean")
        if (
            isinstance(self.ttl_seconds, bool)
            or not isinstance(self.ttl_seconds, int)
            or not 60 <= self.ttl_seconds <= 86_400
        ):
            raise ConfigError("continuation ttl_seconds must be between 60 and 86400")


@dataclass(frozen=True)
class PrivacyConfig:
    """Disabled-by-default local privacy package configuration."""

    enabled: bool = False
    detectors: tuple[str, ...] = (
        "email",
        "phone",
        "ipv4",
        "cn_id",
        "bank_card",
        "secret",
    )
    terms: tuple[str, ...] = ()
    image_redaction: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise ConfigError("privacy enabled must be boolean")
        if not isinstance(self.image_redaction, bool):
            raise ConfigError("privacy image_redaction must be boolean")
        if not isinstance(self.detectors, tuple) or not all(
            isinstance(item, str) for item in self.detectors
        ):
            raise ConfigError("privacy detectors must be a tuple of strings")
        unknown = sorted(set(self.detectors) - SUPPORTED_PRIVACY_DETECTORS)
        if unknown:
            raise ConfigError(f"unknown privacy detector(s): {', '.join(unknown)}")
        if len(set(self.detectors)) != len(self.detectors):
            raise ConfigError("privacy detectors must not contain duplicates")
        if not isinstance(self.terms, tuple) or not all(
            isinstance(item, str) for item in self.terms
        ):
            raise ConfigError("privacy terms must be a tuple of strings")
        if len(self.terms) > 64 or len(set(self.terms)) != len(self.terms):
            raise ConfigError("privacy terms must be unique and contain at most 64 values")
        if any(
            not 2 <= len(item) <= 256
            or any(ord(char) < 32 for char in item)
            or "[[PRIVATE:" in item
            for item in self.terms
        ):
            raise ConfigError("privacy terms must be bounded printable text outside token syntax")


@dataclass(frozen=True)
class OperatorConfig:
    """Local operator-interface preferences."""

    presence_enabled: bool = False
    progress_enabled: bool = False
    reduced_motion: bool = False
    high_contrast: bool = False
    decision_cards_enabled: bool = False
    decision_timeout_seconds: int = 300
    decision_card_corner: str = "bottom_right"

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, bool)
            for value in (
                self.presence_enabled,
                self.progress_enabled,
                self.reduced_motion,
                self.high_contrast,
                self.decision_cards_enabled,
            )
        ):
            raise ConfigError("operator boolean settings must be boolean")
        if (
            isinstance(self.decision_timeout_seconds, bool)
            or not isinstance(self.decision_timeout_seconds, int)
            or not 5 <= self.decision_timeout_seconds <= 3_600
        ):
            raise ConfigError(
                "operator decision_timeout_seconds must be between 5 and 3600"
            )
        if self.decision_card_corner not in {
            "top_left",
            "top_right",
            "bottom_left",
            "bottom_right",
        }:
            raise ConfigError(
                "operator decision_card_corner must be one of "
                "top_left, top_right, bottom_left, bottom_right"
            )


@dataclass(frozen=True)
class AgentConfig:
    """Complete Phase-0 configuration model; parsing performs no desktop I/O."""

    state_dir: Path
    policy_version: str
    provider: ProviderConfig
    mcp: MCPLaunchConfig
    policy: PolicyConfig
    continuation: ContinuationConfig = field(default_factory=ContinuationConfig)
    privacy: PrivacyConfig = field(default_factory=PrivacyConfig)
    operator: OperatorConfig = field(default_factory=OperatorConfig)
    _application_state_dir: Path = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.state_dir, Path):
            raise ConfigError("agent state_dir must be a Path")
        if not self.state_dir.is_absolute():
            raise ConfigError("agent state_dir must be absolute and user-local")
        application_state_dir = default_state_dir().resolve(strict=False)
        object.__setattr__(self, "_application_state_dir", application_state_dir)
        object.__setattr__(self, "state_dir", _require_user_local_state_dir(self.state_dir))
        if not isinstance(self.policy_version, str) or not self.policy_version.strip():
            raise ConfigError("policy_version must be a non-empty string")
        if not isinstance(self.continuation, ContinuationConfig):
            raise ConfigError("continuation must be a ContinuationConfig")
        if not isinstance(self.privacy, PrivacyConfig):
            raise ConfigError("privacy must be a PrivacyConfig")
        if not isinstance(self.operator, OperatorConfig):
            raise ConfigError("operator must be an OperatorConfig")
        if self.privacy.enabled and self.continuation.enabled:
            raise ConfigError(
                "ephemeral privacy vault cannot be combined with continuation"
            )

    @property
    def application_state_dir(self) -> Path:
        """Canonical per-user root shared by run locks across all state scopes."""

        return self._application_state_dir

    @property
    def trace_dir(self) -> Path:
        return self.state_dir / "traces"

    @property
    def memory_database(self) -> Path:
        return self.state_dir / "memory.sqlite3"


def load_agent_config(path: str | Path) -> AgentConfig:
    """Load the documented TOML shape and reject credentials or unsafe child settings."""

    config_path = Path(path)
    with config_path.open("rb") as file:
        document = tomllib.load(file)
    _reject_unknown(
        document,
        {"agent", "provider", "mcp", "policy", "continuation", "privacy", "operator"},
        "root",
    )

    agent = _read_table(document, "agent", required=False)
    provider = _read_table(document, "provider", required=True)
    mcp = _read_table(document, "mcp", required=True)
    policy = _read_table(document, "policy", required=False)
    continuation = _read_table(document, "continuation", required=False)
    privacy = _read_table(document, "privacy", required=False)
    operator = _read_table(document, "operator", required=False)

    _reject_unknown(agent, {"state_dir", "policy_version"}, "agent")
    _reject_unknown(
        provider,
        {
            "name",
            "model",
            "max_request_bytes",
            "context_window_tokens",
            "output_token_reserve",
            "request_timeout_seconds",
        },
        "provider",
    )
    _reject_unknown(mcp, {"executable", "args", "cwd", "environment"}, "mcp")
    _reject_unknown(
        policy,
        {
            "mode",
            "require_approval_for_actions",
            "max_model_turns",
            "max_tool_calls",
            "max_side_effects",
            "max_context_events",
            "max_input_tokens",
        },
        "policy",
    )
    _reject_unknown(continuation, {"enabled", "ttl_seconds"}, "continuation")
    _reject_unknown(
        privacy,
        {"enabled", "detectors", "terms", "image_redaction"},
        "privacy",
    )
    _reject_unknown(
        operator,
        {
            "presence_enabled",
            "progress_enabled",
            "reduced_motion",
            "high_contrast",
            "decision_cards_enabled",
            "decision_timeout_seconds",
            "decision_card_corner",
        },
        "operator",
    )

    state_dir_value = agent.get("state_dir")
    state_dir = default_state_dir() if state_dir_value is None else _require_absolute_path(
        state_dir_value, "agent state_dir"
    )
    policy_version = agent.get("policy_version", "phase0")
    if not isinstance(policy_version, str) or not policy_version.strip():
        raise ConfigError("[agent].policy_version must be a non-empty string")

    provider_config = ProviderConfig(
        name=_read_nonempty_string(provider, "name", "provider"),
        model=_read_nonempty_string(provider, "model", "provider"),
        max_request_bytes=_read_nonnegative_int(
            provider,
            "max_request_bytes",
            "provider",
            DEFAULT_PROVIDER_REQUEST_BYTES,
        ),
        context_window_tokens=_read_positive_int(
            provider, "context_window_tokens", "provider"
        ),
        output_token_reserve=_read_positive_int(
            provider, "output_token_reserve", "provider"
        ),
        request_timeout_seconds=provider.get(
            "request_timeout_seconds", DEFAULT_PROVIDER_TIMEOUT_SECONDS
        ),
    )

    raw_args = mcp.get("args", [])
    if not isinstance(raw_args, list) or not all(isinstance(arg, str) for arg in raw_args):
        raise ConfigError("[mcp].args must be an array of strings")
    raw_environment = mcp.get("environment", {})
    if not isinstance(raw_environment, Mapping):
        raise ConfigError("[mcp].environment must be a table or inline table")
    mcp_environment: dict[str, str] = {}
    for key, value in raw_environment.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise ConfigError("[mcp].environment must map strings to strings")
        mcp_environment[key] = value
    launch_config = MCPLaunchConfig(
        executable=_require_absolute_path(
            _read_nonempty_string(mcp, "executable", "mcp"), "mcp executable"
        ),
        args=tuple(raw_args),
        cwd=_require_absolute_path(_read_nonempty_string(mcp, "cwd", "mcp"), "mcp cwd"),
        environment=mcp_environment,
    )

    approval_required = policy.get("require_approval_for_actions", True)
    if not isinstance(approval_required, bool):
        raise ConfigError("[policy].require_approval_for_actions must be boolean")
    policy_config = PolicyConfig(
        mode=policy.get("mode", READ_ONLY_MODE),
        require_approval_for_actions=approval_required,
        max_model_turns=_read_nonnegative_int(policy, "max_model_turns", "policy", 12),
        max_tool_calls=_read_nonnegative_int(policy, "max_tool_calls", "policy", 32),
        max_side_effects=_read_nonnegative_int(policy, "max_side_effects", "policy", 8),
        max_context_events=_read_nonnegative_int(
            policy, "max_context_events", "policy", 128
        ),
        max_input_tokens=_read_nonnegative_int(
            policy, "max_input_tokens", "policy", 1_000_000
        ),
    )
    continuation_enabled = continuation.get("enabled", False)
    if not isinstance(continuation_enabled, bool):
        raise ConfigError("[continuation].enabled must be boolean")
    continuation_config = ContinuationConfig(
        enabled=continuation_enabled,
        ttl_seconds=_read_nonnegative_int(
            continuation, "ttl_seconds", "continuation", 900
        ),
    )
    privacy_enabled = privacy.get("enabled", False)
    if not isinstance(privacy_enabled, bool):
        raise ConfigError("[privacy].enabled must be boolean")
    image_redaction = privacy.get("image_redaction", True)
    if not isinstance(image_redaction, bool):
        raise ConfigError("[privacy].image_redaction must be boolean")
    privacy_config = PrivacyConfig(
        enabled=privacy_enabled,
        detectors=_read_string_array(
            privacy,
            "detectors",
            "privacy",
            ("email", "phone", "ipv4", "cn_id", "bank_card", "secret"),
        ),
        terms=_read_string_array(privacy, "terms", "privacy", ()),
        image_redaction=image_redaction,
    )
    operator_values: dict[str, bool] = {}
    for key in (
        "presence_enabled",
        "progress_enabled",
        "reduced_motion",
        "high_contrast",
        "decision_cards_enabled",
    ):
        value = operator.get(key, False)
        if not isinstance(value, bool):
            raise ConfigError(f"[operator].{key} must be boolean")
        operator_values[key] = value
    decision_card_corner = operator.get(
        "decision_card_corner",
        "bottom_right",
    )
    if not isinstance(decision_card_corner, str):
        raise ConfigError("[operator].decision_card_corner must be a string")
    return AgentConfig(
        state_dir=state_dir,
        policy_version=policy_version,
        provider=provider_config,
        mcp=launch_config,
        policy=policy_config,
        continuation=continuation_config,
        privacy=privacy_config,
        operator=OperatorConfig(
            **operator_values,
            decision_timeout_seconds=_read_nonnegative_int(
                operator,
                "decision_timeout_seconds",
                "operator",
                300,
            ),
            decision_card_corner=decision_card_corner,
        ),
    )
