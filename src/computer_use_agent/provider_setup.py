"""Actionable provider setup checks for installed product commands."""
from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from importlib.util import find_spec
from typing import Any

from .provider_catalog import (
    ProviderProtocol,
    provider_credential_environment,
    provider_profile,
    resolve_provider_route,
)

class ProviderSetupError(RuntimeError):
    """A fixed, actionable provider installation or initialization failure."""


@dataclass(frozen=True)
class SetupIssue:
    """One safe readiness failure plus the operator action that resolves it."""

    code: str
    action: str

    def as_json(self) -> dict[str, str]:
        return {"code": self.code, "action": self.action}


@dataclass(frozen=True)
class ProviderSetup:
    """Non-secret provider package and credential-presence facts."""

    name: str
    sdk_module: str
    install_extra: str
    credential_environment: str
    credential_required: bool
    sdk_installed: bool
    credential_present: bool

    @property
    def ready(self) -> bool:
        return self.sdk_installed and (
            self.credential_present or not self.credential_required
        )

    @property
    def sdk_issue(self) -> SetupIssue:
        return SetupIssue(
            code=f"{self.name.upper()}_SDK_NOT_INSTALLED",
            action=(
                'Install with: python -m pip install '
                f'"guarded-desktop-agent[{self.install_extra}]"'
            ),
        )

    @property
    def credential_issue(self) -> SetupIssue:
        return SetupIssue(
            code=f"{self.credential_environment}_MISSING",
            action=f"Set {self.credential_environment} in the current shell.",
        )


ModuleFinder = Callable[[str], object | None]


def inspect_provider_setup(
    provider: str,
    *,
    region: str | None = None,
    workspace_id: str | None = None,
    base_url: str | None = None,
    legacy_credentials: bool = False,
    environ: Mapping[str, str] | None = None,
    module_finder: ModuleFinder | None = None,
) -> ProviderSetup:
    """Inspect only package presence and the documented credential variable."""

    try:
        profile = provider_profile(provider)
    except ValueError as exc:
        raise ProviderSetupError("PROVIDER_NOT_IMPLEMENTED") from exc
    sdk_module = profile.sdk_module
    install_extra = profile.install_extra
    try:
        credential_environment = (
            provider_credential_environment(provider, region)
            if provider == "qwen" and workspace_id is None and base_url is None
            else resolve_provider_route(
                provider,
                region=region,
                workspace_id=workspace_id,
                base_url=base_url,
                legacy_credentials=legacy_credentials,
            ).credential_environment
        )
    except ValueError as exc:
        raise ProviderSetupError("PROVIDER_ROUTE_INVALID") from exc
    finder = find_spec if module_finder is None else module_finder
    try:
        sdk_installed = finder(sdk_module) is not None
    except (AttributeError, ImportError, ValueError):
        sdk_installed = False
    environment = os.environ if environ is None else environ
    credential = environment.get(credential_environment)
    return ProviderSetup(
        name=provider,
        sdk_module=sdk_module,
        install_extra=install_extra,
        credential_environment=credential_environment,
        credential_required=profile.credential_required,
        sdk_installed=sdk_installed,
        credential_present=isinstance(credential, str) and bool(credential.strip()),
    )


def require_provider_setup(
    provider: str,
    *,
    region: str | None = None,
    workspace_id: str | None = None,
    base_url: str | None = None,
    legacy_credentials: bool = False,
) -> ProviderSetup:
    """Require the documented local setup before constructing an SDK client."""

    setup = inspect_provider_setup(
        provider,
        region=region,
        workspace_id=workspace_id,
        base_url=base_url,
        legacy_credentials=legacy_credentials,
    )
    issue = (
        setup.sdk_issue
        if not setup.sdk_installed
        else setup.credential_issue
        if setup.credential_required and not setup.credential_present
        else None
    )
    if issue is not None:
        raise ProviderSetupError(f"{issue.code}: {issue.action}")
    return setup


def _client_initialization_error(
    provider: str,
    *,
    region: str | None,
    workspace_id: str | None,
    base_url: str | None,
    legacy_credentials: bool,
) -> ProviderSetupError:
    setup = inspect_provider_setup(
        provider,
        region=region,
        workspace_id=workspace_id,
        base_url=base_url,
        legacy_credentials=legacy_credentials,
    )
    action = (
        f"check {setup.credential_environment} and the provider environment"
        if setup.credential_required
        else (
            "check the loopback OpenAI-compatible service and optional "
            f"{setup.credential_environment}"
        )
    )
    return ProviderSetupError(f"{provider.upper()}_CLIENT_INIT_FAILED: {action}.")


def openai_client_from_environment(
    provider: str = "openai",
    *,
    region: str | None = None,
    workspace_id: str | None = None,
    base_url: str | None = None,
    legacy_credentials: bool = False,
    max_retries: int | None = None,
) -> Any:
    """Construct an OpenAI-SDK client bound to one reviewed provider."""

    if max_retries is not None and (
        type(max_retries) is not int or max_retries < 0
    ):
        raise ProviderSetupError("PROVIDER_MAX_RETRIES_INVALID")
    profile = provider_profile(provider)
    if profile.protocol not in {
        ProviderProtocol.OPENAI_RESPONSES,
        ProviderProtocol.OPENAI_CHAT_COMPLETIONS,
    }:
        raise ProviderSetupError("PROVIDER_PROTOCOL_MISMATCH")
    route = resolve_provider_route(
        provider,
        region=region,
        workspace_id=workspace_id,
        base_url=base_url,
        legacy_credentials=legacy_credentials,
    )
    setup = require_provider_setup(
        provider,
        region=route.region,
        workspace_id=route.workspace_id,
        base_url=route.base_url,
        legacy_credentials=legacy_credentials,
    )
    try:
        from openai import AsyncOpenAI
    except ImportError as exc:
        setup = inspect_provider_setup(
            provider,
            region=route.region,
            workspace_id=route.workspace_id,
            base_url=route.base_url,
            legacy_credentials=legacy_credentials,
            module_finder=lambda _name: None,
        )
        raise ProviderSetupError(
            f"{setup.sdk_issue.code}: {setup.sdk_issue.action}"
        ) from exc
    try:
        credential = os.environ.get(setup.credential_environment)
        api_key = (
            credential.strip()
            if isinstance(credential, str) and credential.strip()
            else "local-openai-no-key"
        )
        if max_retries is None:
            return AsyncOpenAI(api_key=api_key, base_url=route.base_url)
        return AsyncOpenAI(
            api_key=api_key,
            base_url=route.base_url,
            max_retries=max_retries,
        )
    except Exception as exc:
        raise _client_initialization_error(
            provider,
            region=route.region,
            workspace_id=route.workspace_id,
            base_url=route.base_url,
            legacy_credentials=legacy_credentials,
        ) from exc


def anthropic_client_from_environment(
    provider: str = "anthropic",
    *,
    region: str | None = None,
    base_url: str | None = None,
    legacy_credentials: bool = False,
) -> Any:
    """Construct an Anthropic-SDK client bound to one reviewed provider."""

    profile = provider_profile(provider)
    if profile.protocol is not ProviderProtocol.ANTHROPIC_MESSAGES:
        raise ProviderSetupError("PROVIDER_PROTOCOL_MISMATCH")
    route = resolve_provider_route(
        provider,
        region=region,
        base_url=base_url,
        legacy_credentials=legacy_credentials,
    )
    setup = require_provider_setup(
        provider,
        region=route.region,
        base_url=route.base_url,
        legacy_credentials=legacy_credentials,
    )
    try:
        from anthropic import AsyncAnthropic
    except ImportError as exc:
        setup = inspect_provider_setup(
            provider,
            region=route.region,
            base_url=route.base_url,
            legacy_credentials=legacy_credentials,
            module_finder=lambda _name: None,
        )
        raise ProviderSetupError(
            f"{setup.sdk_issue.code}: {setup.sdk_issue.action}"
        ) from exc
    try:
        return AsyncAnthropic(
            api_key=os.environ[setup.credential_environment],
            base_url=route.base_url,
        )
    except Exception as exc:
        raise _client_initialization_error(
            provider,
            region=route.region,
            workspace_id=None,
            base_url=route.base_url,
            legacy_credentials=legacy_credentials,
        ) from exc


__all__ = [
    "ModuleFinder",
    "ProviderSetup",
    "ProviderSetupError",
    "SetupIssue",
    "anthropic_client_from_environment",
    "inspect_provider_setup",
    "openai_client_from_environment",
    "require_provider_setup",
]
