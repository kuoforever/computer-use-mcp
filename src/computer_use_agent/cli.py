"""CLI foundation for the planned local Agent Host."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
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
        "--dry-run",
        action="store_true",
        help="Build and print safe initial-state metadata without calling any external port.",
    )

    evaluate = commands.add_parser("eval", help="Run deterministic offline E1/E2 cases.")
    evaluate.add_argument("--cases", required=True, type=Path)
    evaluate.add_argument("--report", type=Path)

    trace = commands.add_parser("trace", help="Inspect one redacted run record.")
    trace.add_argument("run_id")
    trace.add_argument("--config", required=True, type=Path)

    report = commands.add_parser("report", help="Aggregate safe local run metrics.")
    report.add_argument("--config", required=True, type=Path)

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
                },
            }
        )
    return 0


async def _run_live_async(path: Path, task: str) -> int:
    from .approvals import ConsoleApprovalPort, ReadOnlyApprovalPort
    from .desktop_mcp import StdioDesktopMCP

    config = load_agent_config(path)
    if config.provider.name == "openai":
        from .providers.openai import OpenAIResponsesProvider

        provider = OpenAIResponsesProvider.from_environment(
            config.provider.model,
            allow_actions=config.policy.mode == APPROVED_ACTIONS_MODE,
        )
    elif config.provider.name == "anthropic":
        from .providers.anthropic import AnthropicMessagesProvider

        provider = AnthropicMessagesProvider.from_environment(
            config.provider.model,
            allow_actions=config.policy.mode == APPROVED_ACTIONS_MODE,
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
    outcome = await runner.run(task)
    _print_json(
        {
            "run_id": outcome.state.run_id,
            "text": outcome.text,
            "usage": {
                "model_turns": outcome.state.budgets.model_turns_used,
                "tool_calls": outcome.state.budgets.tool_calls_used,
            },
        }
    )
    return 0


def _run_live(path: Path, task: str) -> int:
    return asyncio.run(_run_live_async(path, task))


def _run_eval(cases: Path, report_path: Path | None) -> int:
    from .evaluation import run_evaluations, write_report

    report = run_evaluations(cases)
    if report_path is not None:
        write_report(report, report_path)
    _print_json(report.as_json())
    return 0 if report.passed else 1


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
                return _run_dry(args.config, args.task)
            return _run_live(args.config, args.task)
        if args.command == "eval":
            return _run_eval(args.cases, args.report)
        if args.command == "trace":
            return _show_trace(args.config, args.run_id)
        if args.command == "report":
            return _show_report(args.config)
        if args.command == "remember":
            return _remember(args)
    except (ConfigError, RunLockError, RunnerError, OSError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    parser.error("unsupported command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
