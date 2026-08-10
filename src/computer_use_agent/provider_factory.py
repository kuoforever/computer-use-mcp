"""Single reviewed construction path for every supported model provider."""
from __future__ import annotations

from .config import ProviderConfig
from .executor_final import FinalResponsePort
from .planner import PlannerPort
from .provider_catalog import ProviderProtocol
from .provider_instructions import ActionInstructionProfile
from .types import ModelProviderPort


def create_model_provider(
    config: ProviderConfig,
    *,
    allow_actions: bool,
    action_instruction_profile: ActionInstructionProfile = (
        ActionInstructionProfile.GENERAL
    ),
) -> ModelProviderPort:
    """Create one ordinary provider adapter from the strict provider profile."""

    if config.protocol is ProviderProtocol.OPENAI_RESPONSES:
        from .providers.openai import OpenAIResponsesProvider

        return OpenAIResponsesProvider.from_environment(
            config.model,
            provider_name=config.name,
            base_url=config.base_url,
            allow_actions=allow_actions,
            action_instruction_profile=action_instruction_profile,
            max_request_bytes=config.max_request_bytes,
            context_window_tokens=config.context_window_tokens,
            output_token_reserve=config.output_token_reserve,
        )
    if config.protocol is ProviderProtocol.ANTHROPIC_MESSAGES:
        from .providers.anthropic import AnthropicMessagesProvider

        return AnthropicMessagesProvider.from_environment(
            config.model,
            provider_name=config.name,
            allow_actions=allow_actions,
            action_instruction_profile=action_instruction_profile,
            max_request_bytes=config.max_request_bytes,
            context_window_tokens=config.context_window_tokens,
            output_token_reserve=config.output_token_reserve,
        )
    if config.protocol is ProviderProtocol.OPENAI_CHAT_COMPLETIONS:
        from .providers.openai_chat import OpenAIChatCompletionsProvider

        return OpenAIChatCompletionsProvider.from_environment(
            config.model,
            provider_name=config.name,
            supports_images=config.supports_images,
            allow_actions=allow_actions,
            action_instruction_profile=action_instruction_profile,
            max_request_bytes=config.max_request_bytes,
            context_window_tokens=config.context_window_tokens,
            output_token_reserve=config.output_token_reserve,
        )
    raise ValueError("PROVIDER_NOT_IMPLEMENTED")


def create_planner(config: ProviderConfig) -> PlannerPort:
    """Create one tool-free Planner adapter from the strict provider profile."""

    common = {
        "max_request_bytes": config.max_request_bytes,
        "context_window_tokens": config.context_window_tokens,
        "output_token_reserve": config.output_token_reserve,
    }
    if config.protocol is ProviderProtocol.OPENAI_RESPONSES:
        from .providers.openai_planner import OpenAIPlanner

        return OpenAIPlanner.from_environment(
            config.model,
            provider_name=config.name,
            base_url=config.base_url,
            **common,
        )
    if config.protocol is ProviderProtocol.ANTHROPIC_MESSAGES:
        from .providers.anthropic_planner import AnthropicPlanner

        return AnthropicPlanner.from_environment(
            config.model,
            provider_name=config.name,
            **common,
        )
    if config.protocol is ProviderProtocol.OPENAI_CHAT_COMPLETIONS:
        from .providers.openai_chat_planner import OpenAIChatPlanner

        return OpenAIChatPlanner.from_environment(
            config.model,
            provider_name=config.name,
            **common,
        )
    raise ValueError("PROVIDER_NOT_IMPLEMENTED")


def create_final_response_adapter(config: ProviderConfig) -> FinalResponsePort:
    """Create one tool-free final-response adapter from the strict profile."""

    common = {
        "max_request_bytes": config.max_request_bytes,
        "context_window_tokens": config.context_window_tokens,
        "output_token_reserve": config.output_token_reserve,
    }
    if config.protocol is ProviderProtocol.OPENAI_RESPONSES:
        from .providers.openai_final import OpenAIFinalResponseAdapter

        return OpenAIFinalResponseAdapter.from_environment(
            config.model,
            provider_name=config.name,
            base_url=config.base_url,
            **common,
        )
    if config.protocol is ProviderProtocol.ANTHROPIC_MESSAGES:
        from .providers.anthropic_final import AnthropicFinalResponseAdapter

        return AnthropicFinalResponseAdapter.from_environment(
            config.model,
            provider_name=config.name,
            **common,
        )
    if config.protocol is ProviderProtocol.OPENAI_CHAT_COMPLETIONS:
        from .providers.openai_chat_final import OpenAIChatFinalResponseAdapter

        return OpenAIChatFinalResponseAdapter.from_environment(
            config.model,
            provider_name=config.name,
            supports_images=config.supports_images,
            **common,
        )
    raise ValueError("PROVIDER_NOT_IMPLEMENTED")


__all__ = [
    "create_final_response_adapter",
    "create_model_provider",
    "create_planner",
]
