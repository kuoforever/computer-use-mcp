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
    DEFAULT_PROVIDER_REQUEST_BYTES,
    MAX_PROVIDER_REQUEST_BYTES,
    MIN_PROVIDER_REQUEST_BYTES,
)


class ConfigError(ValueError):
    """Raised when a host configuration violates a fail-closed invariant."""


READ_ONLY_MODE = "read_only"
APPROVED_ACTIONS_MODE = "approved_actions"
SUPPORTED_PROVIDERS = frozenset({"openai", "anthropic"})
MINIMUM_HUMAN_IDLE_SECONDS = 2.5

# These are the only server configuration inputs the host is willing to pass
# through. Audit and screenshot-redaction destinations remain server defaults so
# configuration cannot disable or redirect those safety records.
REVIEWED_MCP_ENVIRONMENT_NAMES = frozenset(
    {
        "CUMCP_ALLOWLIST",
        "CUMCP_MODE",
        "CUMCP_HUMAN_IDLE_SECONDS",
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


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    model: str
    max_request_bytes: int = DEFAULT_PROVIDER_REQUEST_BYTES

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

    def __post_init__(self) -> None:
        if not isinstance(self.mode, str) or self.mode not in {READ_ONLY_MODE, APPROVED_ACTIONS_MODE}:
            raise ConfigError(
                f"policy mode must be {READ_ONLY_MODE!r} or {APPROVED_ACTIONS_MODE!r}"
            )
        if not isinstance(self.require_approval_for_actions, bool):
            raise ConfigError("require_approval_for_actions must be boolean")
        if self.mode == APPROVED_ACTIONS_MODE and not self.require_approval_for_actions:
            raise ConfigError("approved_actions mode still requires host approval in the MVP")
        for field_name, value in (
            ("max_model_turns", self.max_model_turns),
            ("max_tool_calls", self.max_tool_calls),
            ("max_side_effects", self.max_side_effects),
            ("max_context_events", self.max_context_events),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ConfigError(f"{field_name} must be a non-negative integer")
        if self.max_context_events == 0:
            raise ConfigError("max_context_events must be a positive integer")


@dataclass(frozen=True)
class AgentConfig:
    """Complete Phase-0 configuration model; parsing performs no desktop I/O."""

    state_dir: Path
    policy_version: str
    provider: ProviderConfig
    mcp: MCPLaunchConfig
    policy: PolicyConfig
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
    _reject_unknown(document, {"agent", "provider", "mcp", "policy"}, "root")

    agent = _read_table(document, "agent", required=False)
    provider = _read_table(document, "provider", required=True)
    mcp = _read_table(document, "mcp", required=True)
    policy = _read_table(document, "policy", required=False)

    _reject_unknown(agent, {"state_dir", "policy_version"}, "agent")
    _reject_unknown(provider, {"name", "model", "max_request_bytes"}, "provider")
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
        },
        "policy",
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
    )
    return AgentConfig(
        state_dir=state_dir,
        policy_version=policy_version,
        provider=provider_config,
        mcp=launch_config,
        policy=policy_config,
    )
