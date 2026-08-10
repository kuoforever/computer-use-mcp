"""Installed-runtime readiness inspection without provider or MCP tool calls."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Protocol

from .config import AgentConfig, ConfigError, MCPLaunchConfig, load_agent_config
from .desktop_mcp import MCPBridgeError, StdioDesktopMCP
from .provider_setup import (
    ModuleFinder,
    SetupIssue,
    inspect_provider_setup,
)
from .tool_registry import (
    ToolRegistryMismatchError,
    configured_optional_tool_names,
    verify_discovered_tools,
)
from .types import MCPToolDescriptor


_CHECK_NAMES = (
    "config",
    "provider_sdk",
    "provider_credential",
    "mcp_executable",
    "mcp_cwd",
    "mcp_discovery",
)
_CHECK_STATES = frozenset({"pass", "fail", "not_run"})


class DesktopDiscoveryPort(Protocol):
    async def discover_tools(self) -> tuple[MCPToolDescriptor, ...]: ...

    async def close(self) -> None: ...


DesktopFactory = Callable[[MCPLaunchConfig], DesktopDiscoveryPort]


@dataclass(frozen=True)
class RuntimeDoctorReport:
    """One complete, fixed-shape, non-secret readiness result."""

    provider: str | None
    checks: Mapping[str, str]
    tool_names: tuple[str, ...] = ()
    failure: SetupIssue | None = None
    doctor_version: int = 1

    def __post_init__(self) -> None:
        if self.doctor_version != 1:
            raise ValueError("doctor_version must be 1")
        if tuple(self.checks) != _CHECK_NAMES or any(
            state not in _CHECK_STATES for state in self.checks.values()
        ):
            raise ValueError("doctor checks are invalid")
        if not isinstance(self.tool_names, tuple) or not all(
            isinstance(name, str) and name for name in self.tool_names
        ):
            raise ValueError("doctor tool names are invalid")
        object.__setattr__(self, "checks", MappingProxyType(dict(self.checks)))

    @property
    def ready(self) -> bool:
        return self.failure is None and all(
            state == "pass" for state in self.checks.values()
        )

    def as_json(self) -> dict[str, object]:
        return {
            "doctor_version": self.doctor_version,
            "ready": self.ready,
            "provider": self.provider,
            "checks": dict(self.checks),
            "mcp": {
                "tool_count": len(self.tool_names) if self.ready else None,
                "tool_names": list(self.tool_names),
            },
            "failure": None if self.failure is None else self.failure.as_json(),
        }


def _desktop_factory(launch: MCPLaunchConfig) -> DesktopDiscoveryPort:
    return StdioDesktopMCP(launch)


def _fresh_checks() -> dict[str, str]:
    return {name: "not_run" for name in _CHECK_NAMES}


def _report(
    *,
    provider: str | None,
    checks: Mapping[str, str],
    tool_names: tuple[str, ...] = (),
    failure: SetupIssue | None = None,
) -> RuntimeDoctorReport:
    return RuntimeDoctorReport(
        provider=provider,
        checks=checks,
        tool_names=tool_names,
        failure=failure,
    )


def _mcp_failure(code: str) -> SetupIssue:
    if code == "SCHEMA_MISMATCH":
        action = (
            "Install guarded-desktop-agent and guarded-desktop-mcp "
            "from the same wheel."
        )
    else:
        action = "Reinstall the wheel, regenerate the config, and rerun config doctor."
    return SetupIssue(code=code, action=action)


async def diagnose_config(
    path: Path,
    *,
    environ: Mapping[str, str] | None = None,
    module_finder: ModuleFinder | None = None,
    desktop_factory: DesktopFactory = _desktop_factory,
) -> RuntimeDoctorReport:
    """Run ordered installed checks, stopping at one actionable failure."""

    checks = _fresh_checks()
    if not isinstance(path, Path) or not path.is_file():
        checks["config"] = "fail"
        return _report(
            provider=None,
            checks=checks,
            failure=SetupIssue(
                code="CONFIG_NOT_FOUND",
                action="Create a config with guarded-desktop-agent config init.",
            ),
        )
    try:
        config: AgentConfig = load_agent_config(path)
    except (ConfigError, OSError, ValueError):
        checks["config"] = "fail"
        return _report(
            provider=None,
            checks=checks,
            failure=SetupIssue(
                code="CONFIG_INVALID",
                action="Regenerate the config with guarded-desktop-agent config init.",
            ),
        )
    checks["config"] = "pass"

    setup = inspect_provider_setup(
        config.provider.name,
        region=config.provider.region,
        workspace_id=config.provider.workspace_id,
        base_url=config.provider.base_url,
        legacy_credentials=config.provider.uses_legacy_credentials,
        environ=environ,
        module_finder=module_finder,
    )
    if not setup.sdk_installed:
        checks["provider_sdk"] = "fail"
        return _report(
            provider=setup.name,
            checks=checks,
            failure=setup.sdk_issue,
        )
    checks["provider_sdk"] = "pass"
    if not setup.credential_present:
        checks["provider_credential"] = "fail"
        return _report(
            provider=setup.name,
            checks=checks,
            failure=setup.credential_issue,
        )
    checks["provider_credential"] = "pass"

    if not config.mcp.executable.is_file():
        checks["mcp_executable"] = "fail"
        return _report(
            provider=setup.name,
            checks=checks,
            failure=SetupIssue(
                code="MCP_EXECUTABLE_NOT_FOUND",
                action="Regenerate the config with guarded-desktop-agent config init.",
            ),
        )
    checks["mcp_executable"] = "pass"
    if not config.mcp.cwd.is_dir():
        checks["mcp_cwd"] = "fail"
        return _report(
            provider=setup.name,
            checks=checks,
            failure=SetupIssue(
                code="MCP_CWD_NOT_FOUND",
                action="Create the configured MCP cwd or regenerate the config.",
            ),
        )
    checks["mcp_cwd"] = "pass"

    desktop: DesktopDiscoveryPort | None = None
    descriptors: tuple[MCPToolDescriptor, ...] = ()
    discovery_failure: SetupIssue | None = None
    try:
        desktop = desktop_factory(config.mcp)
        descriptors = await desktop.discover_tools()
        verify_discovered_tools(
            descriptors,
            configured_optional_tool_names(config.mcp.environment),
        )
    except ToolRegistryMismatchError:
        discovery_failure = _mcp_failure("SCHEMA_MISMATCH")
    except MCPBridgeError as exc:
        discovery_failure = _mcp_failure(exc.code)
    except Exception:
        discovery_failure = _mcp_failure("MCP_DISCOVERY_FAILED")
    finally:
        if desktop is not None:
            try:
                await desktop.close()
            except Exception:
                if discovery_failure is None:
                    discovery_failure = _mcp_failure("MCP_TRANSPORT_ERROR")

    if discovery_failure is not None:
        checks["mcp_discovery"] = "fail"
        return _report(
            provider=setup.name,
            checks=checks,
            failure=discovery_failure,
        )
    checks["mcp_discovery"] = "pass"
    return _report(
        provider=setup.name,
        checks=checks,
        tool_names=tuple(sorted(descriptor.name for descriptor in descriptors)),
    )


__all__ = [
    "DesktopDiscoveryPort",
    "RuntimeDoctorReport",
    "diagnose_config",
]
