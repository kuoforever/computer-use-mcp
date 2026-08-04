"""CLI foundation for the planned local Agent Host."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence
from uuid import uuid4

from .config import (
    ACTION_CAPABLE_MODES,
    APPROVED_ACTIONS_MODE,
    AgentConfig,
    ConfigError,
    load_agent_config,
)
from .discovery_adapters import DEFAULT_DISCOVERY_ADAPTERS
from .presence_lifecycle import (
    FailSilentLifecycle,
    PresenceLifecyclePort,
    ProgressLifecyclePort,
)
from .runner import AgentRunner, RunnerError, RunnerPorts
from .run_lock import RunLockError
from .types import (
    AGENT_CONTRACT_VERSION,
    ApprovalPort,
    ProviderContinuationStrategy,
    ToolResult,
)


def _presence_lifecycle(config: AgentConfig) -> PresenceLifecyclePort | None:
    """Create the Win32 presence surface only for explicit operator opt-in."""

    operator = config.operator
    if not operator.presence_enabled:
        return None
    from .presence import PresencePreferences
    from .presence_lifecycle import RunPresenceCoordinator
    from .presence_window import PassivePresenceWindow
    from .presence_window_win32 import Win32PresenceWindowApi

    return RunPresenceCoordinator(
        PassivePresenceWindow(Win32PresenceWindowApi()),
        preferences=PresencePreferences(
            enabled=True,
            reduced_motion=operator.reduced_motion,
            high_contrast=operator.high_contrast,
        ),
    )


def _progress_lifecycle(config: AgentConfig) -> ProgressLifecyclePort | None:
    """Create the passive progress worker only for explicit operator opt-in."""

    if not config.operator.progress_enabled:
        return None
    try:
        from .progress_lifecycle import RunProgressCoordinator
        from .progress_poller import ProgressPoller
        from .progress_window import PassiveProgressWindow
        from .progress_window_win32 import Win32ProgressWindowApi

        api = Win32ProgressWindowApi()
        window = PassiveProgressWindow(api)
        poller = ProgressPoller(config.state_dir, window)
        return RunProgressCoordinator(poller, pump=api.pump)
    except Exception:
        # This surface is observational only. Native construction, imports, or
        # thread setup must never stop an otherwise valid Agent run.
        return None


def _active_progress_lifecycle(config: AgentConfig) -> FailSilentLifecycle:
    """Start the passive poller for one bounded non-run CLI lifecycle."""

    progress = FailSilentLifecycle(_progress_lifecycle(config))
    progress.wake()
    return progress


def _apply_recovery_presence_result(
    presence: FailSilentLifecycle,
    result: ToolResult | None,
) -> None:
    """Close recovery presence immediately after a desktop authority loss."""

    if result is None:
        return
    if result.code == "ABORTED":
        presence.estop()
    elif result.code == "HUMAN_ACTIVE":
        presence.release()


def _approval_port(config: AgentConfig) -> ApprovalPort:
    """Build the configured local approval surface without eager native imports."""

    from .approvals import ConsoleApprovalPort, ReadOnlyApprovalPort

    if config.policy.mode != APPROVED_ACTIONS_MODE:
        return ReadOnlyApprovalPort()
    if not config.operator.decision_cards_enabled:
        return ConsoleApprovalPort(input_fn=_console_input, output_fn=_console_output)
    from .approvals import DecisionCardApprovalPort
    from .decision_card_window import DecisionCardWindow
    from .decision_card_window_win32 import Win32DecisionCardWindowApi

    return DecisionCardApprovalPort(
        DecisionCardWindow(
            Win32DecisionCardWindowApi(
                corner=config.operator.decision_card_corner,
            )
        ),
        timeout_seconds=config.operator.decision_timeout_seconds,
    )


class _ForbiddenCampaignProvider:
    """Fail closed if a provider boundary is entered by the fixed campaign CLI."""

    name = "campaign-provider-forbidden"
    continuation_strategy = ProviderContinuationStrategy.STATELESS_REPLAY

    async def create_turn(self, **_kwargs: object) -> None:
        raise RunnerError("CAMPAIGN_PROVIDER_FORBIDDEN")

    def export_continuation(self, _run_id: str) -> None:
        raise RunnerError("CAMPAIGN_PROVIDER_FORBIDDEN")

    def restore_continuation(self, _run_id: str, _state: object) -> None:
        raise RunnerError("CAMPAIGN_PROVIDER_FORBIDDEN")


class _ForbiddenPlannedProvider:
    """Keep the plan CLI outside the ordinary provider continuation loop."""

    name = "planned-provider-forbidden"
    continuation_strategy = ProviderContinuationStrategy.STATELESS_REPLAY

    async def create_turn(self, **_kwargs: object) -> None:
        raise RunnerError("PLANNED_PROVIDER_FORBIDDEN")

    def export_continuation(self, _run_id: str) -> None:
        raise RunnerError("PLANNED_PROVIDER_FORBIDDEN")

    def restore_continuation(self, _run_id: str, _state: object) -> None:
        raise RunnerError("PLANNED_PROVIDER_FORBIDDEN")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="guarded-desktop-agent",
        description="Guarded Desktop Agent with a reviewed local MCP bridge.",
    )
    parser.add_argument("--version", action="version", version=AGENT_CONTRACT_VERSION)
    commands = parser.add_subparsers(dest="command")

    config = commands.add_parser("config", help="Inspect Agent Host configuration.")
    config_commands = config.add_subparsers(dest="config_command", required=True)
    validate = config_commands.add_parser(
        "validate", help="Validate TOML without starting anything."
    )
    validate.add_argument("--config", required=True, type=Path)

    run = commands.add_parser("run", help="Run the bounded Agent workflow.")
    run.add_argument("--config", required=True, type=Path)
    run.add_argument("--task", required=True)
    run.add_argument(
        "--memory-scope",
        help="Explicitly include active user-confirmed memories from this exact scope.",
    )
    run.add_argument(
        "--dry-run",
        action="store_true",
        help="Build and print safe initial-state metadata without calling any external port.",
    )

    plan = commands.add_parser(
        "plan", help="Run one bounded observation-only Planner/Executor workflow."
    )
    plan_commands = plan.add_subparsers(dest="plan_command", required=True)
    plan_run = plan_commands.add_parser(
        "run", help="Plan and execute one to four observations, then answer."
    )
    plan_run.add_argument("--config", required=True, type=Path)
    plan_run.add_argument("--task", required=True)

    evaluate = commands.add_parser("eval", help="Run deterministic offline E1/E2 cases.")
    evaluate.add_argument("--cases", required=True, type=Path)
    evaluate.add_argument("--report", type=Path)
    manifest_group = evaluate.add_mutually_exclusive_group()
    manifest_group.add_argument("--manifest", type=Path)
    manifest_group.add_argument("--write-manifest", type=Path)

    release = commands.add_parser("release", help="Run offline release-readiness checks.")
    release_commands = release.add_subparsers(dest="release_command", required=True)
    preflight = release_commands.add_parser(
        "preflight", help="Run fail-closed offline gates and write sanitized evidence."
    )
    preflight.add_argument("--root", type=Path, default=Path.cwd())
    preflight.add_argument("--artifacts", type=Path, default=Path("out/release-preflight"))
    preflight.add_argument("--report", type=Path, default=Path("out/release-preflight.json"))

    fullcycle = commands.add_parser(
        "fullcycle", help="Export bounded runtime contracts and redacted run evidence."
    )
    fullcycle_commands = fullcycle.add_subparsers(dest="fullcycle_command", required=True)
    fullcycle_manifest = fullcycle_commands.add_parser(
        "manifest", help="Write the versioned reviewed runtime manifest."
    )
    fullcycle_manifest.add_argument("--output", required=True, type=Path)
    fullcycle_export = fullcycle_commands.add_parser(
        "export-run", help="Write one validated redacted run bundle."
    )
    fullcycle_export.add_argument("--config", required=True, type=Path)
    fullcycle_export.add_argument("--run-id", required=True)
    fullcycle_export.add_argument("--output", required=True, type=Path)

    trace = commands.add_parser("trace", help="Inspect one redacted run record.")
    trace.add_argument("run_id")
    trace.add_argument("--config", required=True, type=Path)

    report = commands.add_parser("report", help="Aggregate safe local run metrics.")
    report.add_argument("--config", required=True, type=Path)

    resume = commands.add_parser("resume", help="Resume a crash-safe initial run only.")
    resume.add_argument("run_id")
    resume.add_argument("--config", required=True, type=Path)
    resume.add_argument("--task", required=True)

    cancel = commands.add_parser("cancel", help="Cancel one persisted non-terminal run.")
    cancel.add_argument("run_id")
    cancel.add_argument("--config", required=True, type=Path)

    recovery = commands.add_parser("recovery", help="Classify one persisted run safely.")
    recovery.add_argument("run_id")
    recovery.add_argument("--config", required=True, type=Path)

    recover = commands.add_parser(
        "recover", help="Execute bounded reviewed read-only continuation steps."
    )
    recover.add_argument("run_id")
    recover.add_argument("--config", required=True, type=Path)
    recover.add_argument("--task", required=True)
    recover.add_argument(
        "--execute-read-only",
        action="store_true",
        help="Explicitly authorize bounded reviewed read-only continuation calls.",
    )
    recover.add_argument(
        "--max-steps",
        type=int,
        default=1,
        help="Maximum reviewed external calls while holding the run lock (1-4).",
    )
    recover.add_argument(
        "--stateless-replay",
        action="store_true",
        help="Explicitly replace the current OpenAI remote continuation once.",
    )

    campaign = commands.add_parser(
        "campaign", help="Run one bounded fixed campaign control operation."
    )
    campaign_commands = campaign.add_subparsers(dest="campaign_command", required=True)
    campaign_resume = campaign_commands.add_parser(
        "resume-synthetic",
        help="Resume only the fixed finished synthetic campaign from durable state.",
    )
    campaign_resume.add_argument("--config", required=True, type=Path)
    campaign_resume.add_argument("--campaign-id", required=True)
    campaign_resume.add_argument("--run-id", required=True)
    campaign_run = campaign_commands.add_parser(
        "run-claimed-synthetic",
        help="Execute only the fixed durable claimed synthetic item through handoff.",
    )
    campaign_run.add_argument("--config", required=True, type=Path)
    campaign_run.add_argument("--campaign-id", required=True)
    campaign_run.add_argument("--run-id", required=True)
    campaign_prepare = campaign_commands.add_parser(
        "prepare-synthetic",
        help="Prepare only the fixed one-item synthetic campaign and claim.",
    )
    campaign_prepare.add_argument("--config", required=True, type=Path)
    campaign_prepare.add_argument("--campaign-id", required=True)
    campaign_prepare.add_argument("--run-id", required=True)
    campaign_prepare_boss = campaign_commands.add_parser(
        "prepare-boss-discovery",
        help="Prepare only the fixed read-only BOSS discovery campaign.",
    )
    campaign_prepare_boss.add_argument("--config", required=True, type=Path)
    campaign_prepare_boss.add_argument("--campaign-id", required=True)
    campaign_prepare_boss.add_argument("--run-id", required=True)
    campaign_observe_boss = campaign_commands.add_parser(
        "observe-boss-page",
        help="Observe one foreground BOSS discovery page through the reviewed MCP path.",
    )
    campaign_observe_boss.add_argument("--config", required=True, type=Path)
    campaign_observe_boss.add_argument("--campaign-id", required=True)
    campaign_observe_boss.add_argument("--run-id", required=True)
    campaign_start_boss = campaign_commands.add_parser(
        "start-boss-batch",
        help="Start only the fixed first read-only BOSS batch and claim.",
    )
    campaign_start_boss.add_argument("--config", required=True, type=Path)
    campaign_start_boss.add_argument("--campaign-id", required=True)
    campaign_start_boss.add_argument("--run-id", required=True)
    campaign_run_boss = campaign_commands.add_parser(
        "run-claimed-boss",
        help="Verify and commit only the exact claimed BOSS identity, then hand off.",
    )
    campaign_run_boss.add_argument("--config", required=True, type=Path)
    campaign_run_boss.add_argument("--campaign-id", required=True)
    campaign_run_boss.add_argument("--run-id", required=True)
    campaign_resume_boss = campaign_commands.add_parser(
        "resume-boss-batch",
        help="Transfer a finished BOSS batch and claim its exact next item.",
    )
    campaign_resume_boss.add_argument("--config", required=True, type=Path)
    campaign_resume_boss.add_argument("--campaign-id", required=True)
    campaign_resume_boss.add_argument("--run-id", required=True)
    campaign_start_boss_semantic = campaign_commands.add_parser(
        "start-boss-semantic-batch",
        help="Start one fixed single-item BOSS semantic batch and claim.",
    )
    campaign_start_boss_semantic.add_argument("--config", required=True, type=Path)
    campaign_start_boss_semantic.add_argument("--campaign-id", required=True)
    campaign_start_boss_semantic.add_argument("--run-id", required=True)
    campaign_run_boss_semantic = campaign_commands.add_parser(
        "run-claimed-boss-semantic",
        help="Extract and commit only the exact claimed BOSS item, then hand off.",
    )
    campaign_run_boss_semantic.add_argument("--config", required=True, type=Path)
    campaign_run_boss_semantic.add_argument("--campaign-id", required=True)
    campaign_run_boss_semantic.add_argument("--run-id", required=True)
    campaign_resume_boss_semantic = campaign_commands.add_parser(
        "resume-boss-semantic-batch",
        help="Transfer one committed semantic batch and claim its exact next item.",
    )
    campaign_resume_boss_semantic.add_argument("--config", required=True, type=Path)
    campaign_resume_boss_semantic.add_argument("--campaign-id", required=True)
    campaign_resume_boss_semantic.add_argument("--run-id", required=True)

    campaign_start_registered = campaign_commands.add_parser(
        "start",
        help="Start the reviewed worker selected by the durable campaign manifest.",
    )
    campaign_start_registered.add_argument("--config", required=True, type=Path)
    campaign_start_registered.add_argument("--campaign-id", required=True)
    campaign_start_registered.add_argument("--run-id", required=True)
    campaign_run_registered = campaign_commands.add_parser(
        "run-claimed",
        help="Execute the exact durable claim with its registered campaign worker.",
    )
    campaign_run_registered.add_argument("--config", required=True, type=Path)
    campaign_run_registered.add_argument("--campaign-id", required=True)
    campaign_run_registered.add_argument("--run-id", required=True)
    campaign_resume_registered = campaign_commands.add_parser(
        "resume",
        help="Resume the registered campaign worker from durable handoff state.",
    )
    campaign_resume_registered.add_argument("--config", required=True, type=Path)
    campaign_resume_registered.add_argument("--campaign-id", required=True)
    campaign_resume_registered.add_argument("--run-id", required=True)
    campaign_prepare_application = campaign_commands.add_parser(
        "prepare-application",
        help="Prepare one reviewed application scenario from a JSON stable-item list.",
    )
    campaign_prepare_application.add_argument("--config", required=True, type=Path)
    campaign_prepare_application.add_argument("--campaign-id", required=True)
    campaign_prepare_application.add_argument("--run-id", required=True)
    campaign_prepare_application.add_argument(
        "--scenario",
        required=True,
        choices=tuple(f"A{index}" for index in range(1, 20)),
    )
    campaign_prepare_application.add_argument(
        "--items-file",
        required=True,
        type=Path,
        help="JSON array of stable item keys; content is not printed or traced.",
    )
    campaign_prepare_discovery = campaign_commands.add_parser(
        "prepare-discovery",
        help="Prepare one empty reviewed campaign for a registered discovery adapter.",
    )
    campaign_prepare_discovery.add_argument("--config", required=True, type=Path)
    campaign_prepare_discovery.add_argument("--campaign-id", required=True)
    campaign_prepare_discovery.add_argument("--run-id", required=True)
    campaign_prepare_discovery.add_argument(
        "--kind",
        required=True,
        choices=DEFAULT_DISCOVERY_ADAPTERS.kinds,
        help="Registered campaign kind; it selects the reviewed adapter.",
    )
    campaign_observe_discovery = campaign_commands.add_parser(
        "observe-discovery-page",
        help="Observe one foreground discovery source for a durable adapter campaign.",
    )
    campaign_observe_discovery.add_argument("--config", required=True, type=Path)
    campaign_observe_discovery.add_argument("--campaign-id", required=True)
    campaign_observe_discovery.add_argument("--run-id", required=True)

    remember = commands.add_parser("remember", help="Manage explicit local memories.")
    remember_commands = remember.add_subparsers(dest="remember_command", required=True)
    remember_add = remember_commands.add_parser("add", help="Add one confirmed memory.")
    remember_add.add_argument("--config", required=True, type=Path)
    remember_add.add_argument("--kind", required=True, choices=["preference", "verified_procedure"])
    remember_add.add_argument("--content", required=True)
    remember_add.add_argument("--scope", required=True)
    remember_add.add_argument("--expires-at", required=True)
    remember_add.add_argument("--confirmed", action="store_true")
    remember_list = remember_commands.add_parser("list", help="List local memories.")
    remember_list.add_argument("--config", required=True, type=Path)
    remember_list.add_argument("--scope")
    remember_list.add_argument("--include-expired", action="store_true")
    remember_delete = remember_commands.add_parser("delete", help="Delete one local memory.")
    remember_delete.add_argument("memory_id")
    remember_delete.add_argument("--config", required=True, type=Path)
    return parser


def _print_json(value: object) -> None:
    print(json.dumps(value, sort_keys=True))


def _console_input(prompt: str) -> str:
    print(prompt, end="", file=sys.stderr, flush=True)
    line = sys.stdin.readline()
    if not line:
        raise EOFError
    return line.rstrip("\r\n")


def _console_output(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _validate_config(path: Path) -> int:
    config = load_agent_config(path)
    _print_json(
        {
            "valid": True,
            "provider": config.provider.name,
            "policy_mode": config.policy.mode,
            "policy_version": config.policy_version,
        }
    )
    return 0


def _run_dry(path: Path, task: str) -> int:
    config = load_agent_config(path)
    runner = AgentRunner(config)
    with runner.prepare(task) as prepared:
        budget = prepared.state.budgets
        _print_json(
            {
                "dry_run": True,
                "run_id": prepared.state.run_id,
                "policy_mode": config.policy.mode,
                "task_length": len(task),
                "budgets": {
                    "model_turns": budget.max_model_turns,
                    "tool_calls": budget.max_tool_calls,
                    "side_effects": budget.max_side_effects,
                    "context_events": config.policy.max_context_events,
                    "input_tokens": budget.max_input_tokens,
                },
            }
        )
    return 0


async def _run_live_async(
    path: Path,
    task: str,
    memory_scope: str | None = None,
    *,
    run_id: str | None = None,
    resume_initial: bool = False,
) -> int:
    from .desktop_mcp import StdioDesktopMCP
    from .privacy import LocalPrivacyImageRedactor, WindowsPrivacyImageRecognizer

    config = load_agent_config(path)
    memories = ()
    if memory_scope is not None:
        from .memory import MemoryStore, build_memory_context

        memories = build_memory_context(
            MemoryStore(config.memory_database).list(scope=memory_scope)
        )
    if config.provider.name == "openai":
        from .providers.openai import OpenAIResponsesProvider

        provider = OpenAIResponsesProvider.from_environment(
            config.provider.model,
            allow_actions=config.policy.mode in ACTION_CAPABLE_MODES,
            max_request_bytes=config.provider.max_request_bytes,
            context_window_tokens=config.provider.context_window_tokens,
            output_token_reserve=config.provider.output_token_reserve,
        )
    elif config.provider.name == "anthropic":
        from .providers.anthropic import AnthropicMessagesProvider

        provider = AnthropicMessagesProvider.from_environment(
            config.provider.model,
            allow_actions=config.policy.mode in ACTION_CAPABLE_MODES,
            max_request_bytes=config.provider.max_request_bytes,
            context_window_tokens=config.provider.context_window_tokens,
            output_token_reserve=config.provider.output_token_reserve,
        )
    else:
        raise RunnerError("PROVIDER_NOT_IMPLEMENTED")
    desktop = StdioDesktopMCP(config.mcp)
    presence = _presence_lifecycle(config)
    progress = _progress_lifecycle(config)
    approvals = _approval_port(config)
    runner = AgentRunner(
        config,
        RunnerPorts(
            provider=provider,
            desktop=desktop,
            approvals=approvals,
            image_redactor=(
                LocalPrivacyImageRedactor(WindowsPrivacyImageRecognizer())
                if config.privacy.enabled and config.privacy.image_redaction
                else None
            ),
            presence=presence,
            progress=progress,
        ),
    )
    outcome = await runner.run(
        task, memories=memories, run_id=run_id, resume_initial=resume_initial
    )
    _print_json(
        {
            "run_id": outcome.state.run_id,
            "text": outcome.text,
            "usage": {
                "model_turns": outcome.state.budgets.model_turns_used,
                "tool_calls": outcome.state.budgets.tool_calls_used,
                "memories": len(memories),
                "input_tokens": outcome.state.budgets.input_tokens_used,
            },
        }
    )
    return 0


def _run_live(path: Path, task: str, memory_scope: str | None = None) -> int:
    return asyncio.run(_run_live_async(path, task, memory_scope))


async def _run_planned_observation_async(path: Path, task: str) -> int:
    from .approvals import ReadOnlyApprovalPort
    from .desktop_mcp import StdioDesktopMCP
    from .planned_observation_runtime import run_planned_observation

    config = load_agent_config(path)
    if not isinstance(task, str) or not task:
        raise RunnerError("PLANNED_OBSERVATION_INPUT_INVALID")
    if not config.continuation.enabled:
        raise RunnerError("PLANNED_OBSERVATION_WAL_REQUIRED")
    if config.policy.max_model_turns < 1:
        raise RunnerError("PLANNED_OBSERVATION_MODEL_BUDGET_INVALID")
    if config.provider.name == "openai":
        from .providers.openai_final import OpenAIFinalResponseAdapter
        from .providers.openai_planner import OpenAIPlanner

        planner = OpenAIPlanner.from_environment(
            config.provider.model,
            max_request_bytes=config.provider.max_request_bytes,
            context_window_tokens=config.provider.context_window_tokens,
            output_token_reserve=config.provider.output_token_reserve,
        )
        final_port = OpenAIFinalResponseAdapter.from_environment(
            config.provider.model,
            max_request_bytes=config.provider.max_request_bytes,
            context_window_tokens=config.provider.context_window_tokens,
            output_token_reserve=config.provider.output_token_reserve,
        )
    elif config.provider.name == "anthropic":
        from .providers.anthropic_final import AnthropicFinalResponseAdapter
        from .providers.anthropic_planner import AnthropicPlanner

        planner = AnthropicPlanner.from_environment(
            config.provider.model,
            max_request_bytes=config.provider.max_request_bytes,
            context_window_tokens=config.provider.context_window_tokens,
            output_token_reserve=config.provider.output_token_reserve,
        )
        final_port = AnthropicFinalResponseAdapter.from_environment(
            config.provider.model,
            max_request_bytes=config.provider.max_request_bytes,
            context_window_tokens=config.provider.context_window_tokens,
            output_token_reserve=config.provider.output_token_reserve,
        )
    else:
        raise RunnerError("PROVIDER_NOT_IMPLEMENTED")
    runner = AgentRunner(
        config,
        RunnerPorts(
            provider=_ForbiddenPlannedProvider(),
            desktop=StdioDesktopMCP(config.mcp),
            approvals=ReadOnlyApprovalPort(),
            presence=_presence_lifecycle(config),
            progress=_progress_lifecycle(config),
        ),
    )
    outcome = await run_planned_observation(
        runner,
        planner,
        final_port,
        task=task,
        run_id=uuid4().hex,
        plan_id=f"plan_{uuid4().hex}",
    )
    state = outcome.final.state
    _print_json(
        {
            "run_id": state.run_id,
            "plan_id": outcome.plan_id,
            "observation_steps": outcome.observation_steps,
            "text": outcome.final.text,
            "usage": {
                "planner_calls": 1,
                "final_model_turns": state.budgets.model_turns_used,
                "tool_calls": state.budgets.tool_calls_used,
                "final_input_tokens": state.budgets.input_tokens_used,
            },
        }
    )
    return 0


def _run_planned_observation(path: Path, task: str) -> int:
    return asyncio.run(_run_planned_observation_async(path, task))


def _resume_live(path: Path, run_id: str, task: str) -> int:
    return asyncio.run(_run_live_async(path, task, run_id=run_id, resume_initial=True))


def _campaign_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _resume_synthetic_campaign(path: Path, campaign_id: str, run_id: str) -> int:
    from .campaign_observation_runtime import (
        resume_finished_synthetic_campaign_after_restart,
    )

    config = load_agent_config(path)
    outcome = resume_finished_synthetic_campaign_after_restart(
        AgentRunner(config),
        campaign_id=campaign_id,
        replacement_run_id=run_id,
        now=_campaign_now(),
    )
    _print_json(
        {
            "campaign_id": outcome.resume.campaign_id,
            "finished_run_id": outcome.resume.finished_run_id,
            "next_item_ordinal": outcome.resume.next_item_ordinal,
            "replacement_run_id": outcome.resume.replacement_run_id,
            "resume_state": outcome.resume.state.value,
        }
    )
    return 0


def _prepare_synthetic_campaign(path: Path, campaign_id: str, run_id: str) -> int:
    from .campaign_observation_runtime import prepare_synthetic_campaign

    config = load_agent_config(path)
    outcome = prepare_synthetic_campaign(
        AgentRunner(config),
        campaign_id=campaign_id,
        run_id=run_id,
        now=_campaign_now(),
    )
    _print_json(
        {
            "batch_id": outcome.session.batch_id,
            "campaign_id": outcome.manifest.campaign_id,
            "campaign_kind": outcome.manifest.kind,
            "item_key": outcome.claimed.item_key,
            "item_ordinal": outcome.claimed.ordinal,
            "item_status": outcome.claimed.status.value,
            "run_id": outcome.session.run_id,
        }
    )
    return 0


async def _run_claimed_synthetic_campaign_async(
    path: Path,
    campaign_id: str,
    run_id: str,
) -> int:
    from .approvals import ReadOnlyApprovalPort
    from .campaign_observation_runtime import (
        execute_persisted_claimed_synthetic_item_through_handoff,
    )
    from .desktop_mcp import StdioDesktopMCP

    config = load_agent_config(path)
    progress = _active_progress_lifecycle(config)
    try:
        runner = AgentRunner(
            config,
            RunnerPorts(
                provider=_ForbiddenCampaignProvider(),
                desktop=StdioDesktopMCP(config.mcp),
                approvals=ReadOnlyApprovalPort(),
                presence=_presence_lifecycle(config),
            ),
        )
        outcome = await execute_persisted_claimed_synthetic_item_through_handoff(
            runner,
            campaign_id=campaign_id,
            run_id=run_id,
            now=_campaign_now(),
        )
        _print_json(
            {
                "campaign_id": campaign_id,
                "content_digest": outcome.content_digest,
                "item_key": outcome.committed.item_key,
                "item_status": outcome.committed.status.value,
                "next_item_ordinal": outcome.handoff["next_item_ordinal"],
                "run_id": outcome.state.run_id,
                "stop_code": outcome.stop_code,
                "usage": {
                    "elapsed_seconds": outcome.usage.elapsed_seconds,
                    "input_tokens": outcome.usage.input_tokens,
                    "provider_turns": outcome.usage.provider_turns,
                    "tool_calls": outcome.usage.tool_calls,
                },
                "window_count": outcome.window_count,
            }
        )
        return 0
    finally:
        progress.release()


def _run_claimed_synthetic_campaign(
    path: Path,
    campaign_id: str,
    run_id: str,
) -> int:
    return asyncio.run(_run_claimed_synthetic_campaign_async(path, campaign_id, run_id))


def _prepare_boss_discovery_campaign(path: Path, campaign_id: str, run_id: str) -> int:
    from .boss_campaign_observation_runtime import prepare_boss_discovery_campaign

    config = load_agent_config(path)
    outcome = prepare_boss_discovery_campaign(
        AgentRunner(config),
        campaign_id=campaign_id,
        run_id=run_id,
        now=_campaign_now(),
    )
    _print_json(
        {
            "campaign_id": outcome.campaign_id,
            "campaign_kind": outcome.campaign_kind,
            "discovered_count": 0,
            "run_id": outcome.run_id,
        }
    )
    return 0


async def _observe_boss_discovery_page_async(path: Path, campaign_id: str, run_id: str) -> int:
    from .approvals import ReadOnlyApprovalPort
    from .boss_campaign_observation_runtime import execute_boss_discovery_page
    from .desktop_mcp import StdioDesktopMCP

    config = load_agent_config(path)
    progress = _active_progress_lifecycle(config)
    try:
        runner = AgentRunner(
            config,
            RunnerPorts(
                provider=_ForbiddenCampaignProvider(),
                desktop=StdioDesktopMCP(config.mcp),
                approvals=ReadOnlyApprovalPort(),
                presence=_presence_lifecycle(config),
            ),
        )
        outcome = await execute_boss_discovery_page(
            runner,
            campaign_id=campaign_id,
            run_id=run_id,
            now=_campaign_now(),
        )
        _print_json(
            {
                "campaign_id": campaign_id,
                "discovered_count": outcome.discovery.discovered_count,
                "duplicate_count": outcome.discovery.duplicate_count,
                "new_item_count": len(outcome.discovery.new_item_keys),
                "pass_sequence": outcome.discovery.pass_sequence,
                "pass_added_nothing": outcome.discovery.added_nothing,
                "run_id": outcome.state.run_id,
                "tool_calls": outcome.state.budgets.tool_calls_used,
            }
        )
        return 0
    finally:
        progress.release()


def _observe_boss_discovery_page(path: Path, campaign_id: str, run_id: str) -> int:
    return asyncio.run(_observe_boss_discovery_page_async(path, campaign_id, run_id))


def _start_boss_read_only_batch(path: Path, campaign_id: str, run_id: str) -> int:
    from .boss_campaign_batch_runtime import start_boss_read_only_batch

    config = load_agent_config(path)
    outcome = start_boss_read_only_batch(
        AgentRunner(config),
        campaign_id=campaign_id,
        run_id=run_id,
        now=_campaign_now(),
    )
    _print_json(
        {
            "batch_id": outcome.batch_id,
            "campaign_id": outcome.campaign_id,
            "claimed_item_ordinal": outcome.claimed_item_ordinal,
            "discovered_count": outcome.discovered_count,
            "discovery_pass_count": outcome.discovery_pass_count,
            "lease_expires_at": outcome.lease_expires_at,
            "planned_item_count": outcome.planned_item_count,
            "run_id": outcome.run_id,
        }
    )
    return 0


async def _run_claimed_boss_identity_async(
    path: Path,
    campaign_id: str,
    run_id: str,
) -> int:
    from .approvals import ReadOnlyApprovalPort
    from .boss_campaign_item_runtime import (
        execute_claimed_boss_identity_through_handoff,
    )
    from .desktop_mcp import StdioDesktopMCP

    config = load_agent_config(path)
    progress = _active_progress_lifecycle(config)
    try:
        runner = AgentRunner(
            config,
            RunnerPorts(
                provider=_ForbiddenCampaignProvider(),
                desktop=StdioDesktopMCP(config.mcp),
                approvals=ReadOnlyApprovalPort(),
                presence=_presence_lifecycle(config),
            ),
        )
        outcome = await execute_claimed_boss_identity_through_handoff(
            runner,
            campaign_id=campaign_id,
            run_id=run_id,
            now=_campaign_now(),
        )
        _print_json(
            {
                "campaign_id": campaign_id,
                "claimed_item_ordinal": outcome.claimed_item_ordinal,
                "content_digest": outcome.content_digest,
                "next_item_ordinal": outcome.handoff["next_item_ordinal"],
                "run_id": outcome.state.run_id,
                "stop_code": outcome.stop_code,
                "usage": {
                    "elapsed_seconds": outcome.usage.elapsed_seconds,
                    "input_tokens": outcome.usage.input_tokens,
                    "provider_turns": outcome.usage.provider_turns,
                    "tool_calls": outcome.usage.tool_calls,
                },
            }
        )
        return 0
    finally:
        progress.release()


def _run_claimed_boss_identity(path: Path, campaign_id: str, run_id: str) -> int:
    return asyncio.run(
        _run_claimed_boss_identity_async(path, campaign_id, run_id)
    )


def _resume_finished_boss_batch(
    path: Path,
    campaign_id: str,
    replacement_run_id: str,
) -> int:
    from .boss_campaign_restart_runtime import (
        resume_finished_boss_batch_after_restart,
    )

    config = load_agent_config(path)
    outcome = resume_finished_boss_batch_after_restart(
        AgentRunner(config),
        campaign_id=campaign_id,
        replacement_run_id=replacement_run_id,
        now=_campaign_now(),
    )
    _print_json(
        {
            "batch_id": outcome.batch_id,
            "campaign_id": outcome.campaign_id,
            "claimed_item_ordinal": outcome.claimed_item_ordinal,
            "lease_expires_at": outcome.lease_expires_at,
            "planned_item_count": outcome.planned_item_count,
            "prior_run_id": outcome.prior_run_id,
            "run_id": outcome.replacement_run_id,
        }
    )
    return 0


def _start_boss_semantic_batch(path: Path, campaign_id: str, run_id: str) -> int:
    from .boss_campaign_batch_runtime import start_boss_semantic_batch

    config = load_agent_config(path)
    outcome = start_boss_semantic_batch(
        AgentRunner(config),
        campaign_id=campaign_id,
        run_id=run_id,
        now=_campaign_now(),
    )
    _print_json(
        {
            "batch_id": outcome.batch_id,
            "campaign_id": outcome.campaign_id,
            "claimed_item_ordinal": outcome.claimed_item_ordinal,
            "discovered_count": outcome.discovered_count,
            "discovery_pass_count": outcome.discovery_pass_count,
            "lease_expires_at": outcome.lease_expires_at,
            "planned_item_count": outcome.planned_item_count,
            "run_id": outcome.run_id,
        }
    )
    return 0


async def _run_claimed_boss_semantic_async(
    path: Path,
    campaign_id: str,
    run_id: str,
) -> int:
    from .approvals import ReadOnlyApprovalPort
    from .boss_semantic_item_runtime import (
        execute_claimed_boss_semantics_through_handoff,
    )
    from .desktop_mcp import StdioDesktopMCP
    from .privacy import LocalPrivacyImageRedactor, WindowsPrivacyImageRecognizer

    config = load_agent_config(path)
    if config.provider.name == "openai":
        from .providers.openai import OpenAIResponsesProvider

        provider = OpenAIResponsesProvider.from_environment(
            config.provider.model,
            allow_actions=False,
            max_request_bytes=config.provider.max_request_bytes,
            context_window_tokens=config.provider.context_window_tokens,
            output_token_reserve=config.provider.output_token_reserve,
        )
    elif config.provider.name == "anthropic":
        from .providers.anthropic import AnthropicMessagesProvider

        provider = AnthropicMessagesProvider.from_environment(
            config.provider.model,
            allow_actions=False,
            max_request_bytes=config.provider.max_request_bytes,
            context_window_tokens=config.provider.context_window_tokens,
            output_token_reserve=config.provider.output_token_reserve,
        )
    else:
        raise RunnerError("PROVIDER_NOT_IMPLEMENTED")
    runner = AgentRunner(
        config,
        RunnerPorts(
            provider=provider,
            desktop=StdioDesktopMCP(config.mcp),
            approvals=ReadOnlyApprovalPort(),
            image_redactor=(
                LocalPrivacyImageRedactor(WindowsPrivacyImageRecognizer())
                if config.privacy.enabled and config.privacy.image_redaction
                else None
            ),
        ),
    )
    outcome = await execute_claimed_boss_semantics_through_handoff(
        runner,
        campaign_id=campaign_id,
        run_id=run_id,
        now=_campaign_now(),
    )
    semantic = outcome.semantic_result
    _print_json(
        {
            "attempt_count": len(outcome.attempts),
            "campaign_id": campaign_id,
            "claimed_item_ordinal": outcome.claimed_item_ordinal,
            "content_digest": (
                None if semantic is None else semantic.content_digest
            ),
            "next_item_ordinal": outcome.handoff["next_item_ordinal"],
            "run_id": outcome.state.run_id,
            "semantic_committed": semantic is not None,
            "source": None if semantic is None else semantic.source.value,
            "stop_code": outcome.stop_code,
            "usage": {
                "elapsed_seconds": outcome.usage.elapsed_seconds,
                "input_tokens": outcome.usage.input_tokens,
                "ocr_regions": outcome.usage.ocr_regions,
                "output_tokens": outcome.usage.output_tokens,
                "provider_turns": outcome.usage.provider_turns,
                "screenshots": outcome.usage.screenshots,
                "tool_calls": outcome.usage.tool_calls,
            },
        }
    )
    return 0


def _run_claimed_boss_semantic(
    path: Path,
    campaign_id: str,
    run_id: str,
) -> int:
    return asyncio.run(
        _run_claimed_boss_semantic_async(path, campaign_id, run_id)
    )


def _resume_finished_boss_semantic_batch(
    path: Path,
    campaign_id: str,
    replacement_run_id: str,
) -> int:
    from .boss_campaign_restart_runtime import (
        resume_finished_boss_semantic_batch_after_restart,
    )

    config = load_agent_config(path)
    outcome = resume_finished_boss_semantic_batch_after_restart(
        AgentRunner(config),
        campaign_id=campaign_id,
        replacement_run_id=replacement_run_id,
        now=_campaign_now(),
    )
    _print_json(
        {
            "batch_id": outcome.batch_id,
            "campaign_id": outcome.campaign_id,
            "claimed_item_ordinal": outcome.claimed_item_ordinal,
            "lease_expires_at": outcome.lease_expires_at,
            "planned_item_count": outcome.planned_item_count,
            "prior_run_id": outcome.prior_run_id,
            "run_id": outcome.replacement_run_id,
        }
    )
    return 0


def _start_registered_campaign(path: Path, campaign_id: str, run_id: str) -> int:
    from .campaign_worker import start_campaign_batch

    config = load_agent_config(path)
    result = start_campaign_batch(
        AgentRunner(config),
        campaign_id=campaign_id,
        run_id=run_id,
        now=_campaign_now(),
    )
    _print_json(
        {
            "campaign_kind": result.campaign_kind,
            "operation": result.operation,
            **result.summary,
        }
    )
    return 0


async def _run_registered_campaign_async(
    path: Path,
    campaign_id: str,
    run_id: str,
) -> int:
    from .approvals import ReadOnlyApprovalPort
    from .campaign_worker import (
        execute_claimed_campaign_item,
        resolve_campaign_worker,
    )
    from .desktop_mcp import StdioDesktopMCP
    from .privacy import LocalPrivacyImageRedactor, WindowsPrivacyImageRecognizer

    config = load_agent_config(path)
    selected = resolve_campaign_worker(
        AgentRunner(config),
        campaign_id=campaign_id,
    )
    if selected.provider_required:
        if config.provider.name == "openai":
            from .providers.openai import OpenAIResponsesProvider

            provider = OpenAIResponsesProvider.from_environment(
                config.provider.model,
                allow_actions=config.policy.mode in ACTION_CAPABLE_MODES,
                max_request_bytes=config.provider.max_request_bytes,
                context_window_tokens=config.provider.context_window_tokens,
                output_token_reserve=config.provider.output_token_reserve,
            )
        elif config.provider.name == "anthropic":
            from .providers.anthropic import AnthropicMessagesProvider

            provider = AnthropicMessagesProvider.from_environment(
                config.provider.model,
                allow_actions=config.policy.mode in ACTION_CAPABLE_MODES,
                max_request_bytes=config.provider.max_request_bytes,
                context_window_tokens=config.provider.context_window_tokens,
                output_token_reserve=config.provider.output_token_reserve,
            )
        else:
            raise RunnerError("PROVIDER_NOT_IMPLEMENTED")
        approvals = _approval_port(config)
        image_redactor = (
            LocalPrivacyImageRedactor(WindowsPrivacyImageRecognizer())
            if config.privacy.enabled and config.privacy.image_redaction
            else None
        )
    else:
        provider = _ForbiddenCampaignProvider()
        approvals = ReadOnlyApprovalPort()
        image_redactor = None
    progress = _active_progress_lifecycle(config)
    try:
        result = await execute_claimed_campaign_item(
            AgentRunner(
                config,
                RunnerPorts(
                    provider=provider,
                    desktop=StdioDesktopMCP(config.mcp),
                    approvals=approvals,
                    image_redactor=image_redactor,
                    presence=_presence_lifecycle(config),
                ),
            ),
            campaign_id=campaign_id,
            run_id=run_id,
            now=_campaign_now(),
        )
        _print_json(
            {
                "campaign_kind": result.campaign_kind,
                "operation": result.operation,
                **result.summary,
            }
        )
        return 0
    finally:
        progress.release()


def _run_registered_campaign(path: Path, campaign_id: str, run_id: str) -> int:
    return asyncio.run(_run_registered_campaign_async(path, campaign_id, run_id))


def _resume_registered_campaign(path: Path, campaign_id: str, run_id: str) -> int:
    from .campaign_worker import resume_campaign_batch

    config = load_agent_config(path)
    result = resume_campaign_batch(
        AgentRunner(config),
        campaign_id=campaign_id,
        replacement_run_id=run_id,
        now=_campaign_now(),
    )
    _print_json(
        {
            "campaign_kind": result.campaign_kind,
            "operation": result.operation,
            **result.summary,
        }
    )
    return 0


def _prepare_application_campaign(
    path: Path,
    campaign_id: str,
    run_id: str,
    scenario_id: str,
    items_file: Path,
) -> int:
    from .application_campaign_runtime import prepare_application_campaign
    from .application_worker_catalog import APPLICATION_WORKERS_BY_SCENARIO

    try:
        raw = items_file.read_bytes()
    except OSError as exc:
        raise RunnerError("APPLICATION_ITEMS_FILE_READ_FAILED") from exc
    if not raw or len(raw) > 256 * 1024:
        raise RunnerError("APPLICATION_ITEMS_FILE_INVALID")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RunnerError("APPLICATION_ITEMS_FILE_INVALID") from exc
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item for item in value)
    ):
        raise RunnerError("APPLICATION_ITEMS_FILE_INVALID")
    spec = APPLICATION_WORKERS_BY_SCENARIO[scenario_id]
    config = load_agent_config(path)
    outcome = prepare_application_campaign(
        AgentRunner(config),
        spec=spec,
        campaign_id=campaign_id,
        run_id=run_id,
        item_keys=tuple(value),
        now=_campaign_now(),
    )
    _print_json(
        {
            "campaign_id": outcome.campaign_id,
            "campaign_kind": outcome.campaign_kind,
            "item_count": outcome.item_count,
            "run_id": outcome.run_id,
            "scenario_id": outcome.scenario_id,
        }
    )
    return 0


def _prepare_discovery_campaign(
    path: Path,
    campaign_id: str,
    run_id: str,
    campaign_kind: str,
) -> int:
    from .application_discovery_runtime import prepare_application_discovery_campaign

    config = load_agent_config(path)
    outcome = prepare_application_discovery_campaign(
        AgentRunner(config),
        campaign_kind=campaign_kind,
        campaign_id=campaign_id,
        run_id=run_id,
        now=_campaign_now(),
    )
    _print_json(
        {
            "adapter_id": outcome.adapter_id,
            "campaign_id": outcome.campaign_id,
            "campaign_kind": outcome.campaign_kind,
            "discovered_count": 0,
            "run_id": outcome.run_id,
        }
    )
    return 0


async def _observe_discovery_page_async(path: Path, campaign_id: str, run_id: str) -> int:
    from .application_discovery_runtime import execute_application_discovery_pass
    from .approvals import ReadOnlyApprovalPort
    from .desktop_mcp import StdioDesktopMCP

    config = load_agent_config(path)
    progress = _active_progress_lifecycle(config)
    try:
        runner = AgentRunner(
            config,
            RunnerPorts(
                provider=_ForbiddenCampaignProvider(),
                desktop=StdioDesktopMCP(config.mcp),
                approvals=ReadOnlyApprovalPort(),
                presence=_presence_lifecycle(config),
            ),
        )
        outcome = await execute_application_discovery_pass(
            runner,
            campaign_id=campaign_id,
            run_id=run_id,
            now=_campaign_now(),
        )
        _print_json(
            {
                "adapter_id": outcome.discovery.adapter_id,
                "campaign_id": campaign_id,
                "campaign_kind": outcome.discovery.campaign_kind,
                "discovered_count": outcome.discovery.discovered_count,
                "duplicate_count": outcome.discovery.duplicate_count,
                "new_item_count": len(outcome.discovery.new_item_keys),
                "pass_added_nothing": outcome.discovery.added_nothing,
                "pass_sequence": outcome.discovery.pass_sequence,
                "run_id": outcome.state.run_id,
                "tool_calls": outcome.state.budgets.tool_calls_used,
            }
        )
        return 0
    finally:
        progress.release()


def _observe_discovery_page(path: Path, campaign_id: str, run_id: str) -> int:
    return asyncio.run(_observe_discovery_page_async(path, campaign_id, run_id))


def _cancel(path: Path, run_id: str) -> int:
    from .run_lock import RunLock
    from .trace import cancel_run_record

    config = load_agent_config(path)
    lock = RunLock(config.application_state_dir)
    lock.acquire(recover_stale=True)
    try:
        checkpoint = cancel_run_record(config.state_dir, run_id)
    finally:
        lock.release()
    _print_json({"run_id": run_id, "phase": checkpoint["phase"]})
    return 0


def _run_eval(
    cases: Path,
    report_path: Path | None,
    manifest_path: Path | None,
    write_manifest_path: Path | None,
) -> int:
    from .evaluation import (
        run_evaluations,
        verify_case_manifest,
        write_case_manifest,
        write_report,
    )

    if manifest_path is not None:
        verify_case_manifest(cases, manifest_path)
    report = run_evaluations(cases)
    if report_path is not None:
        write_report(report, report_path)
    if write_manifest_path is not None and report.passed:
        write_case_manifest(cases, write_manifest_path)
    _print_json(report.as_json())
    return 0 if report.passed else 1


def _run_release_preflight(root: Path, artifacts: Path, report: Path) -> int:
    from .release import run_release_preflight

    payload = run_release_preflight(root, artifacts, report)
    _print_json(payload)
    return 0 if payload["passed"] else 1


def _show_trace(path: Path, run_id: str) -> int:
    from .trace import read_run_record

    config = load_agent_config(path)
    _print_json(read_run_record(config.state_dir, run_id))
    return 0


def _write_fullcycle_manifest(output: Path) -> int:
    from .fullcycle_export import build_fullcycle_manifest, write_new_fullcycle_json

    payload = build_fullcycle_manifest()
    write_new_fullcycle_json(output, payload)
    _print_json(
        {
            "fullcycle_manifest_version": payload["fullcycle_manifest_version"],
            "written": True,
        }
    )
    return 0


def _write_fullcycle_run(path: Path, run_id: str, output: Path) -> int:
    from .fullcycle_export import build_fullcycle_run_export, write_new_fullcycle_json

    config = load_agent_config(path)
    payload = build_fullcycle_run_export(config.state_dir, run_id)
    write_new_fullcycle_json(output, payload)
    _print_json(
        {
            "fullcycle_run_export_version": payload["fullcycle_run_export_version"],
            "run_id": run_id,
            "written": True,
        }
    )
    return 0


def _show_report(path: Path) -> int:
    from .report import build_run_report

    config = load_agent_config(path)
    _print_json(build_run_report(config.state_dir))
    return 0


def _show_recovery(path: Path, run_id: str) -> int:
    from .trace import classify_run_recovery, read_run_record

    config = load_agent_config(path)
    checkpoint = read_run_record(config.state_dir, run_id)["state"]
    task_length = checkpoint.get("task_length")
    if isinstance(task_length, bool) or not isinstance(task_length, int) or task_length <= 0:
        raise ValueError("CHECKPOINT_TASK_LENGTH_INVALID")
    decision = classify_run_recovery(
        checkpoint, task_length=task_length, policy_version=config.policy_version
    )
    _print_json(
        {
            "run_id": run_id,
            "phase": checkpoint.get("phase"),
            "action": decision.action,
            "reason": decision.reason,
            "resume_allowed": decision.resume_allowed,
            "task_length": task_length,
        }
    )
    return 0


async def _recover_live_async(
    path: Path,
    run_id: str,
    task: str,
    *,
    max_steps: int = 1,
    stateless_replay: bool = False,
) -> int:
    from .continuation import read_continuation
    from .desktop_mcp import StdioDesktopMCP
    from .reconstruction import ReconstructionAction
    from .recovery import (
        LockedRecoveryPersistence,
        execute_read_only_recovery_step,
        plan_read_only_recovery,
    )
    from .run_lock import RunLock
    from .tool_registry import verify_discovered_tools
    from .trace import RunPhase, read_run_checkpoint

    config = load_agent_config(path)
    if not config.continuation.enabled:
        raise RunnerError("CONTINUATION_DISABLED")
    if stateless_replay and config.provider.name != "openai":
        raise RunnerError("STATELESS_REPLAY_OPENAI_ONLY")
    presence = FailSilentLifecycle(_presence_lifecycle(config))
    progress = FailSilentLifecycle(_progress_lifecycle(config))

    def publish_operator_phase(phase: RunPhase) -> None:
        presence.on_phase(phase)
        progress.on_phase(phase)

    lock = RunLock(config.application_state_dir)
    try:
        lock.acquire(recover_stale=True)
    except BaseException:
        try:
            presence.release()
        finally:
            progress.release()
        raise
    desktop = None
    provider = None
    lifecycle_started = False
    try:
        step_outputs: list[dict[str, object]] = []
        terminal_failure = False
        for _ in range(max_steps):
            checkpoint = read_run_checkpoint(config.state_dir, run_id)
            envelope = read_continuation(config.state_dir, run_id)
            plan = plan_read_only_recovery(checkpoint, envelope, config, task=task)
            if not lifecycle_started:
                lifecycle_started = True
                try:
                    publish_operator_phase(RunPhase(str(checkpoint["phase"])))
                except (KeyError, ValueError):
                    pass
            blocked_call_count: int | None = None
            if (
                stateless_replay
                and not step_outputs
                and plan.decision.action is not ReconstructionAction.CONTINUE_PROVIDER
            ):
                raise RunnerError("STATELESS_REPLAY_NOT_APPLICABLE")
            if plan.decision.action in {
                ReconstructionAction.DISPATCH_OBSERVATION,
                ReconstructionAction.MANDATORY_REOBSERVE,
            }:
                if desktop is None:
                    desktop = StdioDesktopMCP(config.mcp)
                    verify_discovered_tools(await desktop.discover_tools())
            elif plan.decision.action is ReconstructionAction.CONTINUE_PROVIDER:
                if provider is None:
                    if config.provider.name == "openai":
                        from .providers.openai import OpenAIResponsesProvider

                        provider = OpenAIResponsesProvider.from_environment(
                            config.provider.model,
                            allow_actions=False,
                            max_request_bytes=config.provider.max_request_bytes,
                            context_window_tokens=config.provider.context_window_tokens,
                            output_token_reserve=config.provider.output_token_reserve,
                        )
                    elif config.provider.name == "anthropic":
                        from .providers.anthropic import AnthropicMessagesProvider

                        provider = AnthropicMessagesProvider.from_environment(
                            config.provider.model,
                            allow_actions=False,
                            max_request_bytes=config.provider.max_request_bytes,
                            context_window_tokens=config.provider.context_window_tokens,
                            output_token_reserve=config.provider.output_token_reserve,
                        )
                    else:
                        raise RunnerError("PROVIDER_NOT_IMPLEMENTED")
            elif plan.decision.action in {
                ReconstructionAction.FINALIZE_SUCCESS,
                ReconstructionAction.FINALIZE_BLOCKED,
            }:
                pass
            else:
                if step_outputs:
                    break
                raise RunnerError(f"RECOVERY_NOT_EXECUTABLE:{plan.decision.reason}")
            persistence = LockedRecoveryPersistence(
                state_dir=config.state_dir,
                checkpoint=checkpoint,
                envelope=envelope,
                config=config,
                task=task,
                lock=lock,
                phase_observer=publish_operator_phase,
            )
            if plan.decision.action is ReconstructionAction.FINALIZE_SUCCESS:
                sequence = envelope.payload["checkpoint_sequence"]
                assert isinstance(sequence, int) and not isinstance(sequence, bool)
                text, completed_checkpoint = persistence.finalize_success(sequence)
                step_outputs.append(
                    {
                        "action": plan.decision.action.value,
                        "reason": plan.decision.reason,
                        "checkpoint_sequence": completed_checkpoint["checkpoint_sequence"],
                        "next_step": "stop",
                        "text": text,
                        "tool_call_count": 0,
                    }
                )
                break
            if plan.decision.action is ReconstructionAction.FINALIZE_BLOCKED:
                sequence = envelope.payload["checkpoint_sequence"]
                assert isinstance(sequence, int) and not isinstance(sequence, bool)
                blocked_count, completed_checkpoint = persistence.finalize_blocked_action(sequence)
                terminal_failure = True
                step_outputs.append(
                    {
                        "action": plan.decision.action.value,
                        "reason": plan.decision.reason,
                        "checkpoint_sequence": completed_checkpoint["checkpoint_sequence"],
                        "next_step": "stop",
                        "failure_code": "RECOVERED_ACTION_REQUESTED",
                        "tool_call_count": blocked_count,
                    }
                )
                break
            step = await execute_read_only_recovery_step(
                checkpoint,
                envelope,
                config,
                task=task,
                provider=provider,
                desktop=desktop,
                commit_intent=persistence.commit_intent,
                commit_completion=persistence.commit_completion,
                use_stateless_replay=stateless_replay and not step_outputs,
            )
            _apply_recovery_presence_result(presence, step.tool_result)
            completed = read_continuation(config.state_dir, run_id)
            boundary = completed.payload["boundary"]
            assert isinstance(boundary, dict)
            completed_sequence = completed.payload["checkpoint_sequence"]
            assert isinstance(completed_sequence, int) and not isinstance(completed_sequence, bool)
            if step.model_turn is not None and not step.model_turn.tool_calls:
                text, completed_checkpoint = persistence.finalize_success(completed_sequence)
                checkpoint_sequence = completed_checkpoint["checkpoint_sequence"]
            elif (
                step.model_turn is not None
                and step.model_turn.tool_calls
                and boundary.get("effect") == "side_effect"
            ):
                blocked_call_count, completed_checkpoint = persistence.finalize_blocked_action(
                    completed_sequence
                )
                terminal_failure = True
                text = None
                checkpoint_sequence = completed_checkpoint["checkpoint_sequence"]
            else:
                text = None
                checkpoint_sequence = completed_sequence
            item: dict[str, object] = {
                "action": plan.decision.action.value,
                "reason": plan.decision.reason,
                "checkpoint_sequence": checkpoint_sequence,
                "next_step": boundary["next_step"],
            }
            if step.tool_result is not None:
                item["tool_status"] = step.tool_result.status.value
                item["tool_code"] = step.tool_result.code
            if step.model_turn is not None:
                item["text"] = step.model_turn.text if text is None else text
                item["tool_call_count"] = len(step.model_turn.tool_calls)
                if blocked_call_count is not None:
                    item["reason"] = "RECOVERED_ACTION_REQUESTED"
                    item["failure_code"] = "RECOVERED_ACTION_REQUESTED"
                    item["tool_call_count"] = blocked_call_count
            step_outputs.append(item)
            if boundary["next_step"] == "stop":
                break
        if not step_outputs:
            raise RunnerError("RECOVERY_NOT_EXECUTABLE")
        output: dict[str, object] = {"run_id": run_id, **step_outputs[-1]}
        if max_steps > 1:
            output["steps_executed"] = len(step_outputs)
            output["steps"] = step_outputs
        _print_json(output)
        return 1 if terminal_failure else 0
    finally:
        active_error = sys.exc_info()[0] is not None
        try:
            if desktop is not None:
                try:
                    await desktop.close()
                except Exception:
                    if not active_error:
                        raise
        finally:
            try:
                presence.release()
            finally:
                try:
                    progress.release()
                finally:
                    lock.release()


def _recover_live(
    path: Path,
    run_id: str,
    task: str,
    *,
    max_steps: int = 1,
    stateless_replay: bool = False,
) -> int:
    return asyncio.run(
        _recover_live_async(
            path,
            run_id,
            task,
            max_steps=max_steps,
            stateless_replay=stateless_replay,
        )
    )


def _remember(args: argparse.Namespace) -> int:
    from .memory import MemoryKind, MemoryStore

    config = load_agent_config(args.config)
    store = MemoryStore(config.memory_database)
    if args.remember_command == "add":
        record = store.add(
            kind=MemoryKind(args.kind),
            content=args.content,
            source="user_confirmed",
            scope=args.scope,
            expires_at=args.expires_at,
            confirmed=args.confirmed,
        )
        _print_json(record.as_json())
        return 0
    if args.remember_command == "list":
        records = store.list(scope=args.scope, include_expired=args.include_expired)
        _print_json({"memories": [record.as_json() for record in records]})
        return 0
    if args.remember_command == "delete":
        _print_json({"deleted": store.delete(args.memory_id), "id": args.memory_id})
        return 0
    raise RuntimeError("MEMORY_COMMAND_UNSUPPORTED")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    try:
        if args.command == "config" and args.config_command == "validate":
            return _validate_config(args.config)
        if args.command == "run":
            if args.dry_run:
                if args.memory_scope is not None:
                    raise ValueError("DRY_RUN_MEMORY_CONTEXT_UNAVAILABLE")
                return _run_dry(args.config, args.task)
            return _run_live(args.config, args.task, args.memory_scope)
        if args.command == "plan" and args.plan_command == "run":
            return _run_planned_observation(args.config, args.task)
        if args.command == "eval":
            return _run_eval(args.cases, args.report, args.manifest, args.write_manifest)
        if args.command == "release" and args.release_command == "preflight":
            return _run_release_preflight(args.root, args.artifacts, args.report)
        if args.command == "fullcycle" and args.fullcycle_command == "manifest":
            return _write_fullcycle_manifest(args.output)
        if args.command == "fullcycle" and args.fullcycle_command == "export-run":
            return _write_fullcycle_run(args.config, args.run_id, args.output)
        if args.command == "trace":
            return _show_trace(args.config, args.run_id)
        if args.command == "report":
            return _show_report(args.config)
        if args.command == "recovery":
            return _show_recovery(args.config, args.run_id)
        if args.command == "recover":
            if not args.execute_read_only:
                raise ValueError("RECOVERY_EXECUTION_CONFIRMATION_REQUIRED")
            if not 1 <= args.max_steps <= 4:
                raise ValueError("RECOVERY_MAX_STEPS_INVALID")
            return _recover_live(
                args.config,
                args.run_id,
                args.task,
                max_steps=args.max_steps,
                stateless_replay=args.stateless_replay,
            )
        if args.command == "resume":
            return _resume_live(args.config, args.run_id, args.task)
        if args.command == "campaign" and args.campaign_command == "resume-synthetic":
            return _resume_synthetic_campaign(
                args.config,
                args.campaign_id,
                args.run_id,
            )
        if args.command == "campaign" and args.campaign_command == "run-claimed-synthetic":
            return _run_claimed_synthetic_campaign(
                args.config,
                args.campaign_id,
                args.run_id,
            )
        if args.command == "campaign" and args.campaign_command == "prepare-synthetic":
            return _prepare_synthetic_campaign(
                args.config,
                args.campaign_id,
                args.run_id,
            )
        if args.command == "campaign" and args.campaign_command == "prepare-boss-discovery":
            return _prepare_boss_discovery_campaign(
                args.config,
                args.campaign_id,
                args.run_id,
            )
        if args.command == "campaign" and args.campaign_command == "observe-boss-page":
            return _observe_boss_discovery_page(
                args.config,
                args.campaign_id,
                args.run_id,
            )
        if args.command == "campaign" and args.campaign_command == "start-boss-batch":
            return _start_boss_read_only_batch(
                args.config,
                args.campaign_id,
                args.run_id,
            )
        if args.command == "campaign" and args.campaign_command == "run-claimed-boss":
            return _run_claimed_boss_identity(
                args.config,
                args.campaign_id,
                args.run_id,
            )
        if args.command == "campaign" and args.campaign_command == "resume-boss-batch":
            return _resume_finished_boss_batch(
                args.config,
                args.campaign_id,
                args.run_id,
            )
        if (
            args.command == "campaign"
            and args.campaign_command == "start-boss-semantic-batch"
        ):
            return _start_boss_semantic_batch(
                args.config,
                args.campaign_id,
                args.run_id,
            )
        if (
            args.command == "campaign"
            and args.campaign_command == "run-claimed-boss-semantic"
        ):
            return _run_claimed_boss_semantic(
                args.config,
                args.campaign_id,
                args.run_id,
            )
        if (
            args.command == "campaign"
            and args.campaign_command == "resume-boss-semantic-batch"
        ):
            return _resume_finished_boss_semantic_batch(
                args.config,
                args.campaign_id,
                args.run_id,
            )
        if args.command == "campaign" and args.campaign_command == "start":
            return _start_registered_campaign(
                args.config,
                args.campaign_id,
                args.run_id,
            )
        if args.command == "campaign" and args.campaign_command == "run-claimed":
            return _run_registered_campaign(
                args.config,
                args.campaign_id,
                args.run_id,
            )
        if args.command == "campaign" and args.campaign_command == "resume":
            return _resume_registered_campaign(
                args.config,
                args.campaign_id,
                args.run_id,
            )
        if (
            args.command == "campaign"
            and args.campaign_command == "prepare-application"
        ):
            return _prepare_application_campaign(
                args.config,
                args.campaign_id,
                args.run_id,
                args.scenario,
                args.items_file,
            )
        if args.command == "campaign" and args.campaign_command == "prepare-discovery":
            return _prepare_discovery_campaign(
                args.config,
                args.campaign_id,
                args.run_id,
                args.kind,
            )
        if (
            args.command == "campaign"
            and args.campaign_command == "observe-discovery-page"
        ):
            return _observe_discovery_page(
                args.config,
                args.campaign_id,
                args.run_id,
            )
        if args.command == "cancel":
            return _cancel(args.config, args.run_id)
        if args.command == "remember":
            return _remember(args)
    except (ConfigError, RunLockError, RunnerError, OSError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    parser.error("unsupported command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
