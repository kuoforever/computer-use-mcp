"""CLI foundation for the planned local Agent Host."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from .config import APPROVED_ACTIONS_MODE, ConfigError, load_agent_config
from .runner import AgentRunner, RunnerError, RunnerPorts
from .run_lock import RunLockError
from .types import AGENT_CONTRACT_VERSION


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="computer-use-agent",
        description="Safe local Agent Host foundation with a reviewed desktop MCP bridge.",
    )
    parser.add_argument("--version", action="version", version=AGENT_CONTRACT_VERSION)
    commands = parser.add_subparsers(dest="command")

    config = commands.add_parser("config", help="Inspect Agent Host configuration.")
    config_commands = config.add_subparsers(dest="config_command", required=True)
    validate = config_commands.add_parser("validate", help="Validate TOML without starting anything.")
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
    campaign_commands = campaign.add_subparsers(
        dest="campaign_command", required=True
    )
    campaign_resume = campaign_commands.add_parser(
        "resume-synthetic",
        help="Resume only the fixed finished synthetic campaign from durable state.",
    )
    campaign_resume.add_argument("--config", required=True, type=Path)
    campaign_resume.add_argument("--campaign-id", required=True)
    campaign_resume.add_argument("--run-id", required=True)

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
    from .approvals import ConsoleApprovalPort, ReadOnlyApprovalPort
    from .desktop_mcp import StdioDesktopMCP

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
            allow_actions=config.policy.mode == APPROVED_ACTIONS_MODE,
            max_request_bytes=config.provider.max_request_bytes,
            context_window_tokens=config.provider.context_window_tokens,
            output_token_reserve=config.provider.output_token_reserve,
        )
    elif config.provider.name == "anthropic":
        from .providers.anthropic import AnthropicMessagesProvider

        provider = AnthropicMessagesProvider.from_environment(
            config.provider.model,
            allow_actions=config.policy.mode == APPROVED_ACTIONS_MODE,
            max_request_bytes=config.provider.max_request_bytes,
            context_window_tokens=config.provider.context_window_tokens,
            output_token_reserve=config.provider.output_token_reserve,
        )
    else:
        raise RunnerError("PROVIDER_NOT_IMPLEMENTED")
    desktop = StdioDesktopMCP(config.mcp)
    approvals = (
        ConsoleApprovalPort(input_fn=_console_input, output_fn=_console_output)
        if config.policy.mode == APPROVED_ACTIONS_MODE
        else ReadOnlyApprovalPort()
    )
    runner = AgentRunner(
        config,
        RunnerPorts(
            provider=provider,
            desktop=desktop,
            approvals=approvals,
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


def _resume_live(path: Path, run_id: str, task: str) -> int:
    return asyncio.run(
        _run_live_async(path, task, run_id=run_id, resume_initial=True)
    )


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
    from .trace import read_run_checkpoint

    config = load_agent_config(path)
    if not config.continuation.enabled:
        raise RunnerError("CONTINUATION_DISABLED")
    if stateless_replay and config.provider.name != "openai":
        raise RunnerError("STATELESS_REPLAY_OPENAI_ONLY")
    lock = RunLock(config.application_state_dir)
    lock.acquire(recover_stale=True)
    desktop = None
    provider = None
    try:
        step_outputs: list[dict[str, object]] = []
        terminal_failure = False
        for _ in range(max_steps):
            checkpoint = read_run_checkpoint(config.state_dir, run_id)
            envelope = read_continuation(config.state_dir, run_id)
            plan = plan_read_only_recovery(checkpoint, envelope, config, task=task)
            blocked_call_count: int | None = None
            if stateless_replay and not step_outputs and plan.decision.action is not ReconstructionAction.CONTINUE_PROVIDER:
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
            )
            if plan.decision.action is ReconstructionAction.FINALIZE_SUCCESS:
                sequence = envelope.payload["checkpoint_sequence"]
                assert isinstance(sequence, int) and not isinstance(sequence, bool)
                text, completed_checkpoint = persistence.finalize_success(sequence)
                step_outputs.append(
                    {
                        "action": plan.decision.action.value,
                        "reason": plan.decision.reason,
                        "checkpoint_sequence": completed_checkpoint[
                            "checkpoint_sequence"
                        ],
                        "next_step": "stop",
                        "text": text,
                        "tool_call_count": 0,
                    }
                )
                break
            if plan.decision.action is ReconstructionAction.FINALIZE_BLOCKED:
                sequence = envelope.payload["checkpoint_sequence"]
                assert isinstance(sequence, int) and not isinstance(sequence, bool)
                blocked_count, completed_checkpoint = (
                    persistence.finalize_blocked_action(sequence)
                )
                terminal_failure = True
                step_outputs.append(
                    {
                        "action": plan.decision.action.value,
                        "reason": plan.decision.reason,
                        "checkpoint_sequence": completed_checkpoint[
                            "checkpoint_sequence"
                        ],
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
            completed = read_continuation(config.state_dir, run_id)
            boundary = completed.payload["boundary"]
            assert isinstance(boundary, dict)
            completed_sequence = completed.payload["checkpoint_sequence"]
            assert isinstance(completed_sequence, int) and not isinstance(
                completed_sequence, bool
            )
            if step.model_turn is not None and not step.model_turn.tool_calls:
                text, completed_checkpoint = persistence.finalize_success(
                    completed_sequence
                )
                checkpoint_sequence = completed_checkpoint["checkpoint_sequence"]
            elif (
                step.model_turn is not None
                and step.model_turn.tool_calls
                and boundary.get("effect") == "side_effect"
            ):
                blocked_call_count, completed_checkpoint = (
                    persistence.finalize_blocked_action(completed_sequence)
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
        if desktop is not None:
            try:
                await desktop.close()
            except Exception:
                if not active_error:
                    raise
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
        if args.command == "eval":
            return _run_eval(
                args.cases, args.report, args.manifest, args.write_manifest
            )
        if args.command == "release" and args.release_command == "preflight":
            return _run_release_preflight(args.root, args.artifacts, args.report)
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
        if (
            args.command == "campaign"
            and args.campaign_command == "resume-synthetic"
        ):
            return _resume_synthetic_campaign(
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
