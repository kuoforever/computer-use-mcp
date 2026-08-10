from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType

import pytest

from computer_use_agent.config import ConfigError, ProviderConfig, load_agent_config
from computer_use_agent.provider_catalog import (
    ProviderProtocol,
    SUPPORTED_PROVIDERS,
    provider_profile,
    resolve_provider_route,
    supported_provider_regions,
)
import computer_use_agent.provider_setup as provider_setup
from computer_use_agent.provider_setup import inspect_provider_setup


EXPECTED = {
    "openai": (ProviderProtocol.OPENAI_RESPONSES, "OPENAI_API_KEY", "openai"),
    "anthropic": (
        ProviderProtocol.ANTHROPIC_MESSAGES,
        "ANTHROPIC_API_KEY",
        "anthropic",
    ),
    "qwen": (ProviderProtocol.OPENAI_RESPONSES, "DASHSCOPE_API_KEY", "openai"),
    "doubao": (ProviderProtocol.OPENAI_RESPONSES, "ARK_API_KEY", "openai"),
    "kimi": (
        ProviderProtocol.OPENAI_CHAT_COMPLETIONS,
        "MOONSHOT_API_KEY",
        "openai",
    ),
    "deepseek": (
        ProviderProtocol.OPENAI_CHAT_COMPLETIONS,
        "DEEPSEEK_API_KEY",
        "openai",
    ),
    "glm": (ProviderProtocol.OPENAI_CHAT_COMPLETIONS, "ZAI_API_KEY", "openai"),
    "minimax": (
        ProviderProtocol.ANTHROPIC_MESSAGES,
        "MINIMAX_API_KEY",
        "anthropic",
    ),
}


def test_catalog_separates_vendor_protocol_credential_and_sdk_identity() -> None:
    assert SUPPORTED_PROVIDERS == frozenset(EXPECTED)
    for name, (protocol, credential, sdk) in EXPECTED.items():
        profile = provider_profile(name)
        setup = inspect_provider_setup(
            name,
            environ={credential: "present"},
            module_finder=lambda module: object() if module == sdk else None,
        )
        assert profile.protocol is protocol
        assert setup.credential_environment == credential
        assert setup.sdk_module == sdk
        assert setup.ready is True


def test_qwen_requires_one_reviewed_workspace_https_endpoint() -> None:
    endpoint = (
        "https://workspace123.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/"
    )
    config = ProviderConfig("qwen", "qwen3.7-plus", base_url=endpoint)
    assert config.effective_base_url == endpoint.rstrip("/")
    assert config.effective_region == "cn-beijing"
    assert config.effective_workspace_id == "workspace123"
    assert config.uses_legacy_credentials is True
    assert config.protocol is ProviderProtocol.OPENAI_RESPONSES

    with pytest.raises(ConfigError, match="required"):
        ProviderConfig("qwen", "qwen3.7-plus")
    for invalid in (
        "http://workspace123.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
        "https://workspace123.example.com/compatible-mode/v1",
        "https://user:secret@workspace123.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
        "https://workspace123.cn-beijing.maas.aliyuncs.com/api/v1",
    ):
        with pytest.raises(ConfigError, match="reviewed endpoint"):
            ProviderConfig("qwen", "qwen3.7-plus", base_url=invalid)


def test_region_catalog_is_strict_and_constructs_only_reviewed_routes() -> None:
    assert supported_provider_regions("qwen") == (
        "cn-beijing",
        "ap-southeast-1",
        "ap-northeast-1",
        "eu-central-1",
    )
    assert supported_provider_regions("doubao") == (
        "cn-beijing",
        "ap-southeast-1",
    )
    assert supported_provider_regions("glm") == ("cn", "global")
    assert supported_provider_regions("minimax") == ("cn", "global")

    routes = (
        resolve_provider_route(
            "qwen", region="ap-northeast-1", workspace_id="workspace-jp"
        ),
        resolve_provider_route("doubao", region="ap-southeast-1"),
        resolve_provider_route("glm", region="global"),
        resolve_provider_route("minimax", region="global"),
    )
    assert [(route.region, route.credential_environment, route.base_url) for route in routes] == [
        (
            "ap-northeast-1",
            "DASHSCOPE_AP_NORTHEAST_1_API_KEY",
            "https://workspace-jp.ap-northeast-1.maas.aliyuncs.com/compatible-mode/v1",
        ),
        (
            "ap-southeast-1",
            "BYTEPLUS_ARK_API_KEY",
            "https://ark.ap-southeast.bytepluses.com/api/v3",
        ),
        ("global", "ZAI_GLOBAL_API_KEY", "https://api.z.ai/api/paas/v4"),
        (
            "global",
            "MINIMAX_GLOBAL_API_KEY",
            "https://api.minimax.io/anthropic",
        ),
    ]

    with pytest.raises(ConfigError, match="region is not reviewed"):
        ProviderConfig("minimax", "MiniMax-M2.7", region="eu")
    with pytest.raises(ConfigError, match="workspace_id is invalid"):
        ProviderConfig(
            "qwen",
            "qwen3.7-plus",
            region="cn-beijing",
            workspace_id="not_a_dns_label",
        )
    with pytest.raises(ConfigError, match="reviewed endpoint"):
        ProviderConfig(
            "qwen",
            "qwen3.7-plus",
            base_url=(
                "https://ws1.us-east-1.maas.aliyuncs.com/compatible-mode/v1"
            ),
        )
    with pytest.raises(ConfigError, match="cannot be combined"):
        ProviderConfig(
            "qwen",
            "qwen3.7-plus",
            region="cn-beijing",
            base_url=(
                "https://ws1.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
            ),
        )


def test_fixed_provider_rejects_config_endpoint_override() -> None:
    with pytest.raises(ConfigError, match="must be omitted"):
        ProviderConfig(
            "kimi",
            "kimi-k2.6",
            base_url="https://api.moonshot.ai/v1",
        )


def test_qwen_toml_round_trip_keeps_nonsecret_workspace_endpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    local = tmp_path / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    endpoint = "https://ws1.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1"
    path = tmp_path / "qwen.toml"
    path.write_text(
        f'''\
[agent]
state_dir = "{(local / "computer-use-agent" / "qwen").as_posix()}"

[provider]
name = "qwen"
model = "qwen3.7-plus"
base_url = "{endpoint}"
context_window_tokens = 1000000
output_token_reserve = 4096

[mcp]
executable = "{(tmp_path / "mcp.exe").as_posix()}"
args = []
cwd = "{tmp_path.as_posix()}"
environment = {{ CUMCP_ALLOWLIST = "notepad.exe" }}
''',
        encoding="utf-8",
    )
    provider = load_agent_config(path).provider
    assert provider.effective_base_url == endpoint
    assert provider.effective_region == "ap-southeast-1"
    assert provider.credential_environment == "DASHSCOPE_API_KEY"
    assert provider.uses_legacy_credentials is True


def test_model_aware_glm_image_capability_is_conservative() -> None:
    assert ProviderConfig("glm", "glm-5.2").supports_images is False
    assert ProviderConfig("glm", "glm-5v-turbo").supports_images is True
    assert ProviderConfig("minimax", "MiniMax-M2.7").supports_images is False


def test_compatible_clients_receive_vendor_key_and_reviewed_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    constructed: list[dict[str, object]] = []

    class RecordingClient:
        def __init__(self, **kwargs: object) -> None:
            constructed.append(kwargs)

    openai_module = ModuleType("openai")
    openai_module.AsyncOpenAI = RecordingClient  # type: ignore[attr-defined]
    anthropic_module = ModuleType("anthropic")
    anthropic_module.AsyncAnthropic = RecordingClient  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "openai", openai_module)
    monkeypatch.setitem(sys.modules, "anthropic", anthropic_module)
    monkeypatch.setattr(provider_setup, "find_spec", lambda _name: object())
    monkeypatch.setenv("DASHSCOPE_AP_SOUTHEAST_1_API_KEY", "qwen-secret")
    monkeypatch.setenv("MINIMAX_GLOBAL_API_KEY", "minimax-secret")

    qwen_endpoint = (
        "https://ws1.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1"
    )
    provider_setup.openai_client_from_environment(
        "qwen", region="ap-southeast-1", base_url=qwen_endpoint
    )
    provider_setup.anthropic_client_from_environment("minimax", region="global")

    assert constructed == [
        {"api_key": "qwen-secret", "base_url": qwen_endpoint},
        {
            "api_key": "minimax-secret",
            "base_url": "https://api.minimax.io/anthropic",
        },
    ]
