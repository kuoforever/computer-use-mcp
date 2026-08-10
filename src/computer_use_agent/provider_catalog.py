"""Reviewed provider identities, protocols, endpoints, and capabilities.

Provider identity is intentionally separate from wire compatibility.  A
vendor may use an OpenAI- or Anthropic-compatible protocol without inheriting
that vendor's credential, endpoint, continuation, or evidence identity.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Mapping
from urllib.parse import urlsplit


class ProviderProtocol(str, Enum):
    """Reviewed wire families implemented by the Host."""

    OPENAI_RESPONSES = "openai_responses"
    OPENAI_CHAT_COMPLETIONS = "openai_chat_completions"
    ANTHROPIC_MESSAGES = "anthropic_messages"


class StructuredOutputMode(str, Enum):
    """Provider-specific one-shot structured-output request shape."""

    JSON_SCHEMA = "json_schema"
    JSON_OBJECT = "json_object"
    PROMPT_ONLY = "prompt_only"


@dataclass(frozen=True)
class ProviderProfile:
    """One immutable reviewed provider routing profile."""

    name: str
    protocol: ProviderProtocol
    sdk_module: str
    install_extra: str
    structured_output: StructuredOutputMode
    supports_images: bool
    supports_tool_calling: bool = True
    credential_required: bool = True
    include_responses_reasoning: bool = False
    chat_max_tokens_parameter: str = "max_tokens"


@dataclass(frozen=True)
class ProviderRegionProfile:
    """One reviewed service region and its credential/endpoint boundary."""

    region: str
    credential_environment: str
    fixed_base_url: str | None
    qwen_workspace: bool = False


@dataclass(frozen=True)
class ProviderRoute:
    """One resolved provider/region route safe to hand to an SDK client."""

    name: str
    region: str
    credential_environment: str
    base_url: str
    workspace_id: str | None = None


_PROFILES: Mapping[str, ProviderProfile] = MappingProxyType(
    {
        "openai": ProviderProfile(
            name="openai",
            protocol=ProviderProtocol.OPENAI_RESPONSES,
            sdk_module="openai",
            install_extra="agent-openai",
            structured_output=StructuredOutputMode.JSON_SCHEMA,
            supports_images=True,
            include_responses_reasoning=True,
        ),
        "anthropic": ProviderProfile(
            name="anthropic",
            protocol=ProviderProtocol.ANTHROPIC_MESSAGES,
            sdk_module="anthropic",
            install_extra="agent-anthropic",
            structured_output=StructuredOutputMode.JSON_SCHEMA,
            supports_images=True,
        ),
        "qwen": ProviderProfile(
            name="qwen",
            protocol=ProviderProtocol.OPENAI_RESPONSES,
            sdk_module="openai",
            install_extra="agent-openai",
            structured_output=StructuredOutputMode.PROMPT_ONLY,
            supports_images=True,
        ),
        "doubao": ProviderProfile(
            name="doubao",
            protocol=ProviderProtocol.OPENAI_RESPONSES,
            sdk_module="openai",
            install_extra="agent-openai",
            structured_output=StructuredOutputMode.PROMPT_ONLY,
            supports_images=True,
        ),
        "kimi": ProviderProfile(
            name="kimi",
            protocol=ProviderProtocol.OPENAI_CHAT_COMPLETIONS,
            sdk_module="openai",
            install_extra="agent-openai",
            structured_output=StructuredOutputMode.JSON_OBJECT,
            supports_images=True,
            chat_max_tokens_parameter="max_completion_tokens",
        ),
        "deepseek": ProviderProfile(
            name="deepseek",
            protocol=ProviderProtocol.OPENAI_CHAT_COMPLETIONS,
            sdk_module="openai",
            install_extra="agent-openai",
            structured_output=StructuredOutputMode.JSON_OBJECT,
            supports_images=False,
        ),
        "glm": ProviderProfile(
            name="glm",
            protocol=ProviderProtocol.OPENAI_CHAT_COMPLETIONS,
            sdk_module="openai",
            install_extra="agent-openai",
            structured_output=StructuredOutputMode.JSON_OBJECT,
            supports_images=False,
        ),
        "minimax": ProviderProfile(
            name="minimax",
            protocol=ProviderProtocol.ANTHROPIC_MESSAGES,
            sdk_module="anthropic",
            install_extra="agent-anthropic",
            structured_output=StructuredOutputMode.PROMPT_ONLY,
            supports_images=False,
        ),
        "local_openai": ProviderProfile(
            name="local_openai",
            protocol=ProviderProtocol.OPENAI_CHAT_COMPLETIONS,
            sdk_module="openai",
            install_extra="agent-openai",
            structured_output=StructuredOutputMode.PROMPT_ONLY,
            supports_images=False,
            supports_tool_calling=False,
            credential_required=False,
        ),
    }
)

SUPPORTED_PROVIDERS = frozenset(_PROFILES)


def _region(
    region: str,
    credential_environment: str,
    fixed_base_url: str | None = None,
    *,
    qwen_workspace: bool = False,
) -> ProviderRegionProfile:
    return ProviderRegionProfile(
        region=region,
        credential_environment=credential_environment,
        fixed_base_url=fixed_base_url,
        qwen_workspace=qwen_workspace,
    )


_REGIONS: Mapping[str, Mapping[str, ProviderRegionProfile]] = MappingProxyType(
    {
        "openai": MappingProxyType(
            {"global": _region("global", "OPENAI_API_KEY", "https://api.openai.com/v1")}
        ),
        "anthropic": MappingProxyType(
            {
                "global": _region(
                    "global", "ANTHROPIC_API_KEY", "https://api.anthropic.com"
                )
            }
        ),
        "qwen": MappingProxyType(
            {
                "cn-beijing": _region(
                    "cn-beijing", "DASHSCOPE_API_KEY", qwen_workspace=True
                ),
                "ap-southeast-1": _region(
                    "ap-southeast-1",
                    "DASHSCOPE_AP_SOUTHEAST_1_API_KEY",
                    qwen_workspace=True,
                ),
                "ap-northeast-1": _region(
                    "ap-northeast-1",
                    "DASHSCOPE_AP_NORTHEAST_1_API_KEY",
                    qwen_workspace=True,
                ),
                "eu-central-1": _region(
                    "eu-central-1",
                    "DASHSCOPE_EU_CENTRAL_1_API_KEY",
                    qwen_workspace=True,
                ),
            }
        ),
        "doubao": MappingProxyType(
            {
                "cn-beijing": _region(
                    "cn-beijing",
                    "ARK_API_KEY",
                    "https://ark.cn-beijing.volces.com/api/v3",
                ),
                "ap-southeast-1": _region(
                    "ap-southeast-1",
                    "BYTEPLUS_ARK_API_KEY",
                    "https://ark.ap-southeast.bytepluses.com/api/v3",
                ),
            }
        ),
        "kimi": MappingProxyType(
            {
                "global": _region(
                    "global", "MOONSHOT_API_KEY", "https://api.moonshot.ai/v1"
                )
            }
        ),
        "deepseek": MappingProxyType(
            {
                "global": _region(
                    "global", "DEEPSEEK_API_KEY", "https://api.deepseek.com"
                )
            }
        ),
        "glm": MappingProxyType(
            {
                "cn": _region(
                    "cn", "ZAI_API_KEY", "https://open.bigmodel.cn/api/paas/v4"
                ),
                "global": _region(
                    "global", "ZAI_GLOBAL_API_KEY", "https://api.z.ai/api/paas/v4"
                ),
            }
        ),
        "minimax": MappingProxyType(
            {
                "cn": _region(
                    "cn", "MINIMAX_API_KEY", "https://api.minimaxi.com/anthropic"
                ),
                "global": _region(
                    "global",
                    "MINIMAX_GLOBAL_API_KEY",
                    "https://api.minimax.io/anthropic",
                ),
            }
        ),
        "local_openai": MappingProxyType(
            {"local": _region("local", "LOCAL_OPENAI_API_KEY")}
        ),
    }
)

_DEFAULT_REGIONS: Mapping[str, str] = MappingProxyType(
    {
        "openai": "global",
        "anthropic": "global",
        "qwen": "cn-beijing",
        "doubao": "cn-beijing",
        "kimi": "global",
        "deepseek": "global",
        "glm": "cn",
        "minimax": "cn",
        "local_openai": "local",
    }
)
_WORKSPACE_ID = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\Z")


def provider_profile(name: str) -> ProviderProfile:
    """Return one reviewed profile or fail without interpreting arbitrary input."""

    try:
        return _PROFILES[name]
    except (KeyError, TypeError) as exc:
        raise ValueError("PROVIDER_NOT_IMPLEMENTED") from exc


def supported_provider_regions(name: str) -> tuple[str, ...]:
    """Return reviewed region names in stable catalog order."""

    provider_profile(name)
    return tuple(_REGIONS[name])


def default_provider_region(name: str) -> str:
    """Return the legacy-compatible default region for one provider."""

    provider_profile(name)
    return _DEFAULT_REGIONS[name]


def provider_credential_environment(name: str, region: str | None = None) -> str:
    """Return the documented credential variable for one reviewed region."""

    selected = default_provider_region(name) if region is None else region
    try:
        return _REGIONS[name][selected].credential_environment
    except (KeyError, TypeError) as exc:
        raise ValueError("PROVIDER_REGION_INVALID") from exc


def _validated_qwen_base_url(
    value: str, *, expected_region: str | None = None
) -> tuple[str, str, str]:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except (TypeError, ValueError) as exc:
        raise ValueError("PROVIDER_BASE_URL_INVALID") from exc
    hostname = parsed.hostname or ""
    labels = hostname.split(".")
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or parsed.query
        or parsed.fragment
        or len(labels) != 5
        or labels[2:] != ["maas", "aliyuncs", "com"]
        or _WORKSPACE_ID.fullmatch(labels[0]) is None
        or labels[1] not in _REGIONS["qwen"]
        or (expected_region is not None and labels[1] != expected_region)
        or parsed.path.rstrip("/") != "/compatible-mode/v1"
    ):
        raise ValueError("PROVIDER_BASE_URL_INVALID")
    return f"https://{hostname}/compatible-mode/v1", labels[0], labels[1]


def _validated_local_openai_base_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except (TypeError, ValueError) as exc:
        raise ValueError("PROVIDER_BASE_URL_INVALID") from exc
    hostname = parsed.hostname
    if (
        parsed.scheme != "http"
        or hostname not in {"127.0.0.1", "::1"}
        or parsed.username is not None
        or parsed.password is not None
        or port is None
        or port < 1
        or parsed.query
        or parsed.fragment
        or parsed.path.rstrip("/") != "/v1"
    ):
        raise ValueError("PROVIDER_BASE_URL_INVALID")
    authority = f"[{hostname}]:{port}" if hostname == "::1" else f"{hostname}:{port}"
    return f"http://{authority}/v1"


def resolve_provider_route(
    name: str,
    *,
    region: str | None = None,
    workspace_id: str | None = None,
    base_url: str | None = None,
    legacy_credentials: bool = False,
) -> ProviderRoute:
    """Resolve one reviewed region, endpoint, and credential identity."""

    provider_profile(name)
    if region is not None and (not isinstance(region, str) or not region):
        raise ValueError("PROVIDER_REGION_INVALID")
    inferred_workspace: str | None = None
    if name == "qwen" and region is None and base_url is not None:
        _, inferred_workspace, selected_region = _validated_qwen_base_url(base_url)
    else:
        selected_region = default_provider_region(name) if region is None else region
    try:
        region_profile = _REGIONS[name][selected_region]
    except KeyError as exc:
        raise ValueError("PROVIDER_REGION_INVALID") from exc

    effective_workspace: str | None
    if name == "local_openai":
        if workspace_id is not None:
            raise ValueError("PROVIDER_WORKSPACE_INVALID")
        if base_url is None:
            raise ValueError("PROVIDER_BASE_URL_REQUIRED")
        endpoint = _validated_local_openai_base_url(base_url)
        effective_workspace = None
    elif region_profile.qwen_workspace:
        if workspace_id is not None and (
            not isinstance(workspace_id, str)
            or _WORKSPACE_ID.fullmatch(workspace_id) is None
        ):
            raise ValueError("PROVIDER_WORKSPACE_INVALID")
        if base_url is not None:
            endpoint, endpoint_workspace, _ = _validated_qwen_base_url(
                base_url, expected_region=selected_region
            )
            if workspace_id is not None and workspace_id != endpoint_workspace:
                raise ValueError("PROVIDER_WORKSPACE_INVALID")
            effective_workspace = endpoint_workspace
        else:
            effective_workspace = workspace_id or inferred_workspace
            if effective_workspace is None:
                raise ValueError("PROVIDER_WORKSPACE_REQUIRED")
            endpoint = (
                f"https://{effective_workspace}.{selected_region}.maas.aliyuncs.com"
                "/compatible-mode/v1"
            )
    else:
        if workspace_id is not None:
            raise ValueError("PROVIDER_WORKSPACE_INVALID")
        fixed_base_url = region_profile.fixed_base_url
        if fixed_base_url is None:
            raise ValueError("PROVIDER_BASE_URL_INVALID")
        endpoint = fixed_base_url
        if base_url is not None and base_url.rstrip("/") != endpoint:
            raise ValueError("PROVIDER_BASE_URL_INVALID")
        effective_workspace = None

    credential_environment = region_profile.credential_environment
    if legacy_credentials and name == "qwen":
        credential_environment = _REGIONS["qwen"]["cn-beijing"].credential_environment
    return ProviderRoute(
        name=name,
        region=selected_region,
        credential_environment=credential_environment,
        base_url=endpoint,
        workspace_id=effective_workspace,
    )


def resolve_provider_base_url(
    name: str,
    configured: str | None = None,
    *,
    region: str | None = None,
    workspace_id: str | None = None,
) -> str:
    """Resolve one effective endpoint without permitting arbitrary rerouting."""

    return resolve_provider_route(
        name,
        region=region,
        workspace_id=workspace_id,
        base_url=configured,
    ).base_url


def provider_supports_images(name: str, model: str) -> bool:
    """Return the reviewed model-aware image-input capability."""

    profile = provider_profile(name)
    if name == "glm":
        normalized = model.strip().lower()
        return normalized.startswith("glm-") and "v" in normalized.split("-")[1]
    return profile.supports_images


def provider_supports_tool_calling(name: str) -> bool:
    """Return whether ordinary native tool calling is reviewed for this profile."""

    return provider_profile(name).supports_tool_calling


__all__ = [
    "ProviderProfile",
    "ProviderRegionProfile",
    "ProviderRoute",
    "ProviderProtocol",
    "StructuredOutputMode",
    "SUPPORTED_PROVIDERS",
    "default_provider_region",
    "provider_profile",
    "provider_credential_environment",
    "provider_supports_images",
    "provider_supports_tool_calling",
    "resolve_provider_base_url",
    "resolve_provider_route",
    "supported_provider_regions",
]
