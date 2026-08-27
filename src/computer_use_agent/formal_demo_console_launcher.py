"""Independent no-key launcher for the Review-only Formal Demo Console."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from uuid import uuid4

from .formal_demo_console import (
    FormalDemoConsoleSession,
    FormalDemoConsoleWindow,
    build_console_route,
)


_FIXED_ERROR_CODE = re.compile(r"[A-Z][A-Z0-9_]{2,127}\Z")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="guarded-desktop-agent-console",
        description=(
            "Launch the local Review-only Formal Demo Console. This command reads "
            "no config, credential, or provider environment variable and starts no "
            "provider, Runner, MCP, desktop automation, application, or durable run."
        ),
    )
    parser.add_argument("--provider", required=True, help="Reviewed provider identity.")
    parser.add_argument("--model", required=True, help="Exact model identity to display.")
    parser.add_argument(
        "--region",
        help="Reviewed provider region; omitted values use the static catalog default.",
    )
    parser.add_argument(
        "--workspace-id",
        help="Required only by reviewed Qwen workspace routes.",
    )
    parser.add_argument(
        "--base-url",
        help="Reviewed Qwen route or loopback-only local_openai /v1 URL.",
    )
    parser.add_argument(
        "--describe",
        action="store_true",
        help=(
            "Print the same static route/profile and zero-authority boundary as JSON "
            "without opening a window."
        ),
    )
    return parser


def _identity() -> str:
    return uuid4().hex


def _fixed_error(error: BaseException) -> str:
    try:
        code = str(error)
    except BaseException:
        return "FORMAL_DEMO_CONSOLE_LAUNCH_FAILED"
    return code if _FIXED_ERROR_CODE.fullmatch(code) else "FORMAL_DEMO_CONSOLE_LAUNCH_FAILED"


def _describe(session: FormalDemoConsoleSession) -> int:
    view = session.view()
    payload = {
        "mode": "review_only",
        "stage": view.stage.value,
        "provider": view.provider_id,
        "region": view.region,
        "model": view.model_id,
        "protocol": view.protocol,
        "endpoint": view.endpoint,
        "workspace_id": view.workspace_id,
        "disclosure_profile": view.disclosure_profile_id,
        "role_profiles": [
            {
                "role": summary.role,
                "application": summary.application_label,
                "binding_state": summary.binding_state,
                "note": summary.note,
            }
            for summary in view.role_summaries
        ],
        "credential_readiness_checked": False,
        "provider_request_started": False,
        "permit_issued": False,
        "scope_available": False,
        "start_enabled": False,
        "runner_started": False,
        "mcp_started": False,
        "desktop_automation_started": False,
        "application_started": False,
        "durable_run_started": False,
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        route = build_console_route(
            provider_id=args.provider,
            model_id=args.model,
            region=args.region,
            workspace_id=args.workspace_id,
            base_url=args.base_url,
        )
        session = FormalDemoConsoleSession(route, identity_factory=_identity)
        if args.describe:
            return _describe(session)
        if sys.platform != "win32":
            raise RuntimeError("FORMAL_DEMO_CONSOLE_WINDOWS_REQUIRED")
        from .formal_demo_console_win32 import Win32FormalDemoConsoleApi

        api = Win32FormalDemoConsoleApi()
        try:
            return FormalDemoConsoleWindow(session, api).run()
        finally:
            api.dispose()
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"error: {_fixed_error(exc)}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_parser", "main"]
