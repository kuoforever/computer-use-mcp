from __future__ import annotations

from types import SimpleNamespace

import pytest

from computer_use_agent.config import ProviderConfig
from computer_use_agent.provider_factory import (
    create_final_response_adapter,
    create_model_provider,
    create_planner,
)
from computer_use_agent.providers import (
    anthropic,
    anthropic_final,
    anthropic_planner,
    openai,
    openai_chat,
    openai_chat_final,
    openai_chat_planner,
    openai_final,
    openai_planner,
)


PROVIDERS = (
    (
        "openai",
        "gpt-test",
        {},
        "global",
        "https://api.openai.com/v1",
        False,
    ),
    (
        "anthropic",
        "claude-test",
        {},
        "global",
        "https://api.anthropic.com",
        False,
    ),
    (
        "qwen",
        "qwen3.7-plus",
        {"region": "cn-beijing", "workspace_id": "ws1"},
        "cn-beijing",
        "https://ws1.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
        False,
    ),
    (
        "doubao",
        "doubao-test",
        {},
        "cn-beijing",
        "https://ark.cn-beijing.volces.com/api/v3",
        False,
    ),
    (
        "kimi",
        "kimi-k2.6",
        {},
        "global",
        "https://api.moonshot.ai/v1",
        False,
    ),
    (
        "kimi",
        "kimi-k2.6",
        {"region": "cn"},
        "cn",
        "https://api.moonshot.cn/v1",
        False,
    ),
    (
        "deepseek",
        "deepseek-v4-pro",
        {},
        "global",
        "https://api.deepseek.com",
        False,
    ),
    (
        "glm",
        "glm-5.2",
        {},
        "cn",
        "https://open.bigmodel.cn/api/paas/v4",
        False,
    ),
    (
        "minimax",
        "MiniMax-M2.7",
        {},
        "cn",
        "https://api.minimaxi.com/anthropic",
        False,
    ),
)


@pytest.mark.parametrize(
    (
        "name",
        "model",
        "config_kwargs",
        "expected_region",
        "expected_base_url",
        "expected_legacy_credentials",
    ),
    PROVIDERS,
)
def test_factory_routes_every_provider_through_its_reviewed_protocol_family(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    model: str,
    config_kwargs: dict[str, str],
    expected_region: str,
    expected_base_url: str,
    expected_legacy_credentials: bool,
) -> None:
    client = SimpleNamespace(
        responses=object(),
        messages=object(),
        chat=SimpleNamespace(completions=object()),
    )
    client_calls: list[tuple[str, str, str, bool]] = []

    def openai_client(
        provider: str = "openai",
        *,
        region: str,
        base_url: str,
        legacy_credentials: bool,
    ) -> object:
        client_calls.append((provider, region, base_url, legacy_credentials))
        return client

    def anthropic_client(
        provider: str = "anthropic",
        *,
        region: str,
        base_url: str,
        legacy_credentials: bool,
    ) -> object:
        client_calls.append((provider, region, base_url, legacy_credentials))
        return client

    for module in (openai, openai_planner, openai_final):
        monkeypatch.setattr(module, "openai_client_from_environment", openai_client)
    for module in (openai_chat, openai_chat_planner, openai_chat_final):
        monkeypatch.setattr(module, "openai_client_from_environment", openai_client)
    for module in (anthropic, anthropic_planner, anthropic_final):
        monkeypatch.setattr(
            module, "anthropic_client_from_environment", anthropic_client
        )

    config = ProviderConfig(name, model, **config_kwargs)
    ordinary = create_model_provider(config, allow_actions=False)
    planner = create_planner(config)
    final = create_final_response_adapter(config)

    assert ordinary.name == planner.name == getattr(final, "name") == name
    assert getattr(ordinary, "supports_images") == config.supports_images
    expected_thinking_disabled = (
        name == "kimi" and model == "kimi-k2.6" and expected_region == "cn"
    )
    assert getattr(planner, "thinking_disabled", False) is expected_thinking_disabled
    assert getattr(final, "thinking_disabled", False) is expected_thinking_disabled
    expected_arguments_field = (
        "arguments"
        if name == "glm" and model == "glm-5.2" and expected_region == "cn"
        else "arguments_json"
    )
    assert getattr(planner, "arguments_field", "arguments_json") == expected_arguments_field
    expected_fence_strip = (
        name == "qwen" and model == "qwen3.7-plus" and expected_region == "cn-beijing"
    )
    assert getattr(planner, "strip_exact_json_fence", False) is expected_fence_strip
    assert getattr(final, "strip_exact_json_fence", False) is False
    expected_call = (
        name,
        expected_region,
        expected_base_url,
        expected_legacy_credentials,
    )
    assert client_calls == [expected_call, expected_call, expected_call]


@pytest.mark.parametrize(
    ("name", "model", "config_kwargs", "expected_region", "expected_base_url"),
    (
        (
            "qwen",
            "qwen3.7-plus",
            {"region": "eu-central-1", "workspace_id": "workspace-eu"},
            "eu-central-1",
            "https://workspace-eu.eu-central-1.maas.aliyuncs.com/compatible-mode/v1",
        ),
        (
            "doubao",
            "doubao-test",
            {"region": "ap-southeast-1"},
            "ap-southeast-1",
            "https://ark.ap-southeast.bytepluses.com/api/v3",
        ),
        (
            "glm",
            "glm-5.2",
            {"region": "global"},
            "global",
            "https://api.z.ai/api/paas/v4",
        ),
        (
            "minimax",
            "MiniMax-M2.7",
            {"region": "global"},
            "global",
            "https://api.minimax.io/anthropic",
        ),
    ),
)
def test_factory_resolves_nondefault_regions_before_adapter_construction(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    model: str,
    config_kwargs: dict[str, str],
    expected_region: str,
    expected_base_url: str,
) -> None:
    captured: list[tuple[str, str, bool]] = []
    client = SimpleNamespace(
        responses=object(),
        messages=object(),
        chat=SimpleNamespace(completions=object()),
    )

    def openai_client(
        _provider: str,
        *,
        region: str,
        base_url: str,
        legacy_credentials: bool,
    ) -> object:
        captured.append((region, base_url, legacy_credentials))
        return client

    def anthropic_client(
        _provider: str,
        *,
        region: str,
        base_url: str,
        legacy_credentials: bool,
    ) -> object:
        captured.append((region, base_url, legacy_credentials))
        return client

    for module in (openai, openai_planner, openai_final):
        monkeypatch.setattr(module, "openai_client_from_environment", openai_client)
    for module in (openai_chat, openai_chat_planner, openai_chat_final):
        monkeypatch.setattr(module, "openai_client_from_environment", openai_client)
    for module in (anthropic, anthropic_planner, anthropic_final):
        monkeypatch.setattr(
            module, "anthropic_client_from_environment", anthropic_client
        )

    config = ProviderConfig(name, model, **config_kwargs)
    create_model_provider(config, allow_actions=False)

    assert captured == [(expected_region, expected_base_url, False)]


def test_local_openai_constructs_only_planner_and_final_before_tool_e3(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    endpoint = "http://127.0.0.1:11434/v1"
    client = SimpleNamespace(chat=SimpleNamespace(completions=object()))
    calls: list[tuple[str, str, str, bool]] = []

    def openai_client(
        provider: str,
        *,
        region: str,
        base_url: str,
        legacy_credentials: bool,
    ) -> object:
        calls.append((provider, region, base_url, legacy_credentials))
        return client

    for module in (openai_chat, openai_chat_planner, openai_chat_final):
        monkeypatch.setattr(module, "openai_client_from_environment", openai_client)

    config = ProviderConfig(
        "local_openai",
        "qwen3:8b",
        base_url=endpoint,
    )
    with pytest.raises(ValueError, match="PROVIDER_TOOL_CALLING_UNVERIFIED"):
        create_model_provider(config, allow_actions=False)
    planner = create_planner(config)
    final = create_final_response_adapter(config)

    assert planner.name == final.name == "local_openai"
    assert final.supports_images is False
    assert calls == [
        ("local_openai", "local", endpoint, False),
        ("local_openai", "local", endpoint, False),
    ]
