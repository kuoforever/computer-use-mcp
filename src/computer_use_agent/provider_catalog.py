"""Reviewed provider identities, protocols, endpoints, and capabilities.

Provider identity is intentionally separate from wire compatibility.  A
vendor may use an OpenAI- or Anthropic-compatible protocol without inheriting
that vendor's credential, endpoint, continuation, or evidence identity.
"""
from __future__ import annotations

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
    credential_environment: str
    fixed_base_url: str | None
    structured_output: StructuredOutputMode
    supports_images: bool
    include_responses_reasoning: bool = False
    chat_max_tokens_parameter: str = "max_tokens"

    @property
    def requires_configured_base_url(self) -> bool:
        return self.fixed_base_url is None


_PROFILES: Mapping[str, ProviderProfile] = MappingProxyType(
    {
        "openai": ProviderProfile(
            name="openai",
            protocol=ProviderProtocol.OPENAI_RESPONSES,
            sdk_module="openai",
            install_extra="agent-openai",
            credential_environment="OPENAI_API_KEY",
            fixed_base_url="https://api.openai.com/v1",
            structured_output=StructuredOutputMode.JSON_SCHEMA,
            supports_images=True,
            include_responses_reasoning=True,
        ),
        "anthropic": ProviderProfile(
            name="anthropic",
            protocol=ProviderProtocol.ANTHROPIC_MESSAGES,
            sdk_module="anthropic",
            install_extra="agent-anthropic",
            credential_environment="ANTHROPIC_API_KEY",
            fixed_base_url="https://api.anthropic.com",
            structured_output=StructuredOutputMode.JSON_SCHEMA,
            supports_images=True,
        ),
        "qwen": ProviderProfile(
            name="qwen",
            protocol=ProviderProtocol.OPENAI_RESPONSES,
            sdk_module="openai",
            install_extra="agent-openai",
            credential_environment="DASHSCOPE_API_KEY",
            fixed_base_url=None,
            structured_output=StructuredOutputMode.PROMPT_ONLY,
            supports_images=True,
        ),
        "doubao": ProviderProfile(
            name="doubao",
            protocol=ProviderProtocol.OPENAI_RESPONSES,
            sdk_module="openai",
            install_extra="agent-openai",
            credential_environment="ARK_API_KEY",
            fixed_base_url="https://ark.cn-beijing.volces.com/api/v3",
            structured_output=StructuredOutputMode.PROMPT_ONLY,
            supports_images=True,
        ),
        "kimi": ProviderProfile(
            name="kimi",
            protocol=ProviderProtocol.OPENAI_CHAT_COMPLETIONS,
            sdk_module="openai",
            install_extra="agent-openai",
            credential_environment="MOONSHOT_API_KEY",
            fixed_base_url="https://api.moonshot.ai/v1",
            structured_output=StructuredOutputMode.JSON_OBJECT,
            supports_images=True,
            chat_max_tokens_parameter="max_completion_tokens",
        ),
        "deepseek": ProviderProfile(
            name="deepseek",
            protocol=ProviderProtocol.OPENAI_CHAT_COMPLETIONS,
            sdk_module="openai",
            install_extra="agent-openai",
            credential_environment="DEEPSEEK_API_KEY",
            fixed_base_url="https://api.deepseek.com",
            structured_output=StructuredOutputMode.JSON_OBJECT,
            supports_images=False,
        ),
        "glm": ProviderProfile(
            name="glm",
            protocol=ProviderProtocol.OPENAI_CHAT_COMPLETIONS,
            sdk_module="openai",
            install_extra="agent-openai",
            credential_environment="ZAI_API_KEY",
            fixed_base_url="https://open.bigmodel.cn/api/paas/v4",
            structured_output=StructuredOutputMode.JSON_OBJECT,
            supports_images=False,
        ),
        "minimax": ProviderProfile(
            name="minimax",
            protocol=ProviderProtocol.ANTHROPIC_MESSAGES,
            sdk_module="anthropic",
            install_extra="agent-anthropic",
            credential_environment="MINIMAX_API_KEY",
            fixed_base_url="https://api.minimaxi.com/anthropic",
            structured_output=StructuredOutputMode.PROMPT_ONLY,
            supports_images=False,
        ),
    }
)

SUPPORTED_PROVIDERS = frozenset(_PROFILES)


def provider_profile(name: str) -> ProviderProfile:
    """Return one reviewed profile or fail without interpreting arbitrary input."""

    try:
        return _PROFILES[name]
    except (KeyError, TypeError) as exc:
        raise ValueError("PROVIDER_NOT_IMPLEMENTED") from exc


def _validated_qwen_base_url(value: str) -> str:
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
        or len(labels) < 5
        or not hostname.endswith(".maas.aliyuncs.com")
        or not labels[0]
        or parsed.path.rstrip("/") != "/compatible-mode/v1"
    ):
        raise ValueError("PROVIDER_BASE_URL_INVALID")
    return f"https://{hostname}/compatible-mode/v1"


def resolve_provider_base_url(name: str, configured: str | None = None) -> str:
    """Resolve one effective endpoint without permitting arbitrary rerouting."""

    profile = provider_profile(name)
    if profile.fixed_base_url is not None:
        if configured is not None:
            raise ValueError("PROVIDER_BASE_URL_FIXED")
        return profile.fixed_base_url
    if not isinstance(configured, str) or not configured.strip():
        raise ValueError("PROVIDER_BASE_URL_REQUIRED")
    if name == "qwen":
        return _validated_qwen_base_url(configured.strip())
    raise ValueError("PROVIDER_BASE_URL_INVALID")


def provider_supports_images(name: str, model: str) -> bool:
    """Return the reviewed model-aware image-input capability."""

    profile = provider_profile(name)
    if name == "glm":
        normalized = model.strip().lower()
        return normalized.startswith("glm-") and "v" in normalized.split("-")[1]
    return profile.supports_images


__all__ = [
    "ProviderProfile",
    "ProviderProtocol",
    "StructuredOutputMode",
    "SUPPORTED_PROVIDERS",
    "provider_profile",
    "provider_supports_images",
    "resolve_provider_base_url",
]
