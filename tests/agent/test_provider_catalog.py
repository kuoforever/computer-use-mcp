from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType

import pytest

from computer_use_agent.config import ConfigError, ProviderConfig, load_agent_config
from computer_use_agent.provider_catalog import (
    ProviderProtocol,
    SUPPORTED_PROVIDERS,
    provider_chat_planner_arguments_field,
    provider_disables_one_shot_thinking,
    provider_profile,
    provider_strips_exact_planner_json_fence,
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
    "local_openai": (
        ProviderProtocol.OPENAI_CHAT_COMPLETIONS,
        "LOCAL_OPENAI_API_KEY",
        "openai",
    ),
}


def test_catalog_separates_vendor_protocol_credential_and_sdk_identity() -> None:
    assert SUPPORTED_PROVIDERS == frozenset(EXPECTED)
    for name, (protocol, credential, sdk) in EXPECTED.items():
        profile = provider_profile(name)
        setup = inspect_provider_setup(
            name,
            base_url=(
                "http://127.0.0.1:11434/v1"
                if name == "local_openai"
                else None
            ),
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
    assert supported_provider_regions("kimi") == ("global", "cn")
    assert supported_provider_regions("glm") == ("cn", "global")
    assert supported_provider_regions("minimax") == ("cn", "global")

    routes = (
        resolve_provider_route(
            "qwen", region="ap-northeast-1", workspace_id="workspace-jp"
        ),
        resolve_provider_route("doubao", region="ap-southeast-1"),
        resolve_provider_route("kimi", region="cn"),
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
        ("cn", "MOONSHOT_CN_API_KEY", "https://api.moonshot.cn/v1"),
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


def test_kimi_one_shot_thinking_override_is_exact_route_and_model_scoped() -> None:
    assert provider_disables_one_shot_thinking("kimi", "kimi-k2.6", "cn") is True
    assert provider_disables_one_shot_thinking("kimi", "kimi-k2.6", "global") is False
    assert provider_disables_one_shot_thinking("kimi", "kimi-k2.5", "cn") is False
    assert provider_disables_one_shot_thinking("deepseek", "deepseek-v4-pro") is False


def test_glm_planner_arguments_field_is_exact_route_and_model_scoped() -> None:
    assert provider_chat_planner_arguments_field("glm", "glm-5.2", "cn") == "arguments"
    assert (
        provider_chat_planner_arguments_field("glm", "glm-5.2", "global")
        == "arguments_json"
    )
    assert (
        provider_chat_planner_arguments_field("glm", "glm-5.1", "cn")
        == "arguments_json"
    )
    assert (
        provider_chat_planner_arguments_field("deepseek", "deepseek-v4-pro")
        == "arguments_json"
    )


def test_qwen_planner_fence_normalization_is_exact_route_and_model_scoped() -> None:
    assert (
        provider_strips_exact_planner_json_fence(
            "qwen", "qwen3.7-plus", "cn-beijing"
        )
        is True
    )
    assert (
        provider_strips_exact_planner_json_fence(
            "qwen", "qwen3.7-plus", "ap-southeast-1"
        )
        is False
    )
    assert (
        provider_strips_exact_planner_json_fence(
            "qwen", "qwen3.7-turbo", "cn-beijing"
        )
        is False
    )
    assert (
        provider_strips_exact_planner_json_fence(
            "doubao", "doubao-seed-2-0-lite-260215", "cn-beijing"
        )
        is False
    )


def test_local_openai_requires_one_literal_loopback_v1_endpoint() -> None:
    ipv4 = ProviderConfig(
        "local_openai",
        "qwen3:8b",
        base_url="http://127.0.0.1:11434/v1/",
    )
    ipv6 = ProviderConfig(
        "local_openai",
        "local-model",
        region="local",
        base_url="http://[::1]:1234/v1",
    )

    assert ipv4.effective_base_url == "http://127.0.0.1:11434/v1"
    assert ipv6.effective_base_url == "http://[::1]:1234/v1"
    assert ipv4.effective_region == "local"
    assert ipv4.credential_environment == "LOCAL_OPENAI_API_KEY"
    assert ipv4.uses_legacy_credentials is False
    assert ipv4.supports_images is False
    assert ipv4.supports_tool_calling is False
    assert supported_provider_regions("local_openai") == ("local",)

    with pytest.raises(ConfigError, match="base_url is required"):
        ProviderConfig("local_openai", "local-model")
    for invalid in (
        "http://localhost:11434/v1",
        "http://127.0.0.2:11434/v1",
        "http://192.168.1.20:11434/v1",
        "https://127.0.0.1:11434/v1",
        "http://user:secret@127.0.0.1:11434/v1",
        "http://127.0.0.1:0/v1",
        "http://127.0.0.1/v1",
        "http://127.0.0.1:11434/",
        "http://127.0.0.1:11434/v1?target=remote",
        "http://127.0.0.1:11434/v1#fragment",
    ):
        with pytest.raises(ConfigError, match="reviewed endpoint"):
            ProviderConfig("local_openai", "local-model", base_url=invalid)

    with pytest.raises(ConfigError, match="region is not reviewed"):
        ProviderConfig(
            "local_openai",
            "local-model",
            region="global",
            base_url="http://127.0.0.1:11434/v1",
        )
    with pytest.raises(ConfigError, match="workspace_id is invalid"):
        ProviderConfig(
            "local_openai",
            "local-model",
            workspace_id="workspace",
            base_url="http://127.0.0.1:11434/v1",
        )


def test_local_openai_setup_and_client_use_an_optional_nonsecret_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    constructed: list[dict[str, object]] = []

    class RecordingClient:
        def __init__(self, **kwargs: object) -> None:
            constructed.append(kwargs)

    openai_module = ModuleType("openai")
    openai_module.AsyncOpenAI = RecordingClient  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "openai", openai_module)
    monkeypatch.setattr(provider_setup, "find_spec", lambda _name: object())
    monkeypatch.delenv("LOCAL_OPENAI_API_KEY", raising=False)
    endpoint = "http://127.0.0.1:11434/v1"

    setup = inspect_provider_setup(
        "local_openai",
        base_url=endpoint,
        environ={},
        module_finder=lambda _name: object(),
    )
    provider_setup.openai_client_from_environment(
        "local_openai",
        region="local",
        base_url=endpoint,
    )

    assert setup.credential_required is False
    assert setup.credential_present is False
    assert setup.ready is True
    assert constructed == [
        {"api_key": "local-openai-no-key", "base_url": endpoint}
    ]


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
    monkeypatch.setenv("MOONSHOT_CN_API_KEY", "kimi-cn-secret")
    monkeypatch.setenv("MINIMAX_GLOBAL_API_KEY", "minimax-secret")

    qwen_endpoint = (
        "https://ws1.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1"
    )
    provider_setup.openai_client_from_environment(
        "qwen", region="ap-southeast-1", base_url=qwen_endpoint
    )
    provider_setup.openai_client_from_environment("kimi", region="cn")
    provider_setup.anthropic_client_from_environment("minimax", region="global")

    assert constructed == [
        {"api_key": "qwen-secret", "base_url": qwen_endpoint},
        {
            "api_key": "kimi-cn-secret",
            "base_url": "https://api.moonshot.cn/v1",
        },
        {
            "api_key": "minimax-secret",
            "base_url": "https://api.minimax.io/anthropic",
        },
    ]
