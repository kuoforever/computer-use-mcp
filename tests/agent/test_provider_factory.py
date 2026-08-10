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
    ("openai", "gpt-test", None),
    ("anthropic", "claude-test", None),
    (
        "qwen",
        "qwen3.7-plus",
        "https://ws1.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
    ),
    ("doubao", "doubao-test", None),
    ("kimi", "kimi-k2.6", None),
    ("deepseek", "deepseek-v4-pro", None),
    ("glm", "glm-5.2", None),
    ("minimax", "MiniMax-M2.7", None),
)


@pytest.mark.parametrize(("name", "model", "base_url"), PROVIDERS)
def test_factory_routes_every_provider_through_its_reviewed_protocol_family(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    model: str,
    base_url: str | None,
) -> None:
    client = SimpleNamespace(
        responses=object(),
        messages=object(),
        chat=SimpleNamespace(completions=object()),
    )
    openai_calls: list[tuple[str, str | None]] = []
    anthropic_calls: list[str] = []

    def openai_client(
        provider: str = "openai", *, base_url: str | None = None
    ) -> object:
        openai_calls.append((provider, base_url))
        return client

    def anthropic_client(provider: str = "anthropic") -> object:
        anthropic_calls.append(provider)
        return client

    for module in (openai, openai_planner, openai_final):
        monkeypatch.setattr(module, "openai_client_from_environment", openai_client)
    for module in (openai_chat, openai_chat_planner, openai_chat_final):
        monkeypatch.setattr(module, "openai_client_from_environment", openai_client)
    for module in (anthropic, anthropic_planner, anthropic_final):
        monkeypatch.setattr(
            module, "anthropic_client_from_environment", anthropic_client
        )

    config = ProviderConfig(name, model, base_url=base_url)
    ordinary = create_model_provider(config, allow_actions=False)
    planner = create_planner(config)
    final = create_final_response_adapter(config)

    assert ordinary.name == planner.name == getattr(final, "name") == name
    assert getattr(ordinary, "supports_images") == config.supports_images
    if name in {"anthropic", "minimax"}:
        assert anthropic_calls == [name, name, name]
        assert openai_calls == []
    else:
        assert openai_calls == [(name, base_url), (name, base_url), (name, base_url)]
        assert anthropic_calls == []
