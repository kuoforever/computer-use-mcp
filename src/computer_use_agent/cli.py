"""CLI foundation for the planned local Agent Host."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from .config import ConfigError, load_agent_config
from .runner import AgentRunner
from .run_lock import RunLockError
from .types import AGENT_CONTRACT_VERSION


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="computer-use-agent",
        description="Safe local Agent Host foundation (provider and MCP bridge not implemented yet).",
    )
    parser.add_argument("--version", action="version", version=AGENT_CONTRACT_VERSION)
    commands = parser.add_subparsers(dest="command")

    config = commands.add_parser("config", help="Inspect Agent Host configuration.")
    config_commands = config.add_subparsers(dest="config_command", required=True)
    validate = config_commands.add_parser("validate", help="Validate TOML without starting anything.")
    validate.add_argument("--config", required=True, type=Path)

    run = commands.add_parser("run", help="Prepare a run; execution is not available in Phase 2.")
    run.add_argument("--config", required=True, type=Path)
    run.add_argument("--task", required=True)
    run.add_argument(
        "--dry-run",
        action="store_true",
        help="Build and print safe initial-state metadata without calling any external port.",
    )
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
            if not args.dry_run:
                print(
                    "run is unavailable until provider and desktop MCP bridge phases are implemented",
                    file=sys.stderr,
                )
                return 2
            return _run_dry(args.config, args.task)
    except (ConfigError, RunLockError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    parser.error("unsupported command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
