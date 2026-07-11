"""CLI foundation for the planned local Agent Host."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Sequence

from .config import ConfigError, load_agent_config
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

    run = commands.add_parser("run", help="Run the bounded read-only Agent workflow.")
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
    return parser


def _print_json(value: object) -> None:
    print(json.dumps(value, sort_keys=True))


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
                },
            }
        )
    return 0


async def _run_live_async(path: Path, task: str) -> int:
    from .approvals import ReadOnlyApprovalPort
    from .desktop_mcp import StdioDesktopMCP

    config = load_agent_config(path)
    if config.provider.name == "openai":
        from .providers.openai import OpenAIResponsesProvider

        provider = OpenAIResponsesProvider.from_environment(config.provider.model)
    elif config.provider.name == "anthropic":
        from .providers.anthropic import AnthropicMessagesProvider

        provider = AnthropicMessagesProvider.from_environment(config.provider.model)
    else:
        raise RunnerError("PROVIDER_NOT_IMPLEMENTED")
    desktop = StdioDesktopMCP(config.mcp)
    runner = AgentRunner(
        config,
        RunnerPorts(
            provider=provider,
            desktop=desktop,
            approvals=ReadOnlyApprovalPort(),
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
    except (ConfigError, RunLockError, RunnerError, OSError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    parser.error("unsupported command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
