"""Exercise real Host/MCP/Session code with fake desktop data through pinned RAML code."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile

from validate_gui_observation_handoff import CONSUMER_FILES

ROOT = Path(__file__).resolve().parents[1]
CONSUMER_HEAD = "42428dde8b706be9d70003358c183d16ab057e9a"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--consumer-root", required=True, type=Path)
    args = parser.parse_args()
    consumer = args.consumer_root.resolve()
    head = subprocess.check_output(
        ["git", "-C", str(consumer), "rev-parse", "HEAD"], text=True
    ).strip()
    if head != CONSUMER_HEAD:
        raise SystemExit("CONSUMER_HEAD_MISMATCH")
    for filename, expected in CONSUMER_FILES.items():
        source = consumer / "src" / "fullcycle_bridge" / filename
        if hashlib.sha256(source.read_text(encoding="utf-8").encode()).hexdigest() != expected:
            raise SystemExit("CONSUMER_SOURCE_MISMATCH")
    sys.path[:0] = [str(ROOT / "src"), str(consumer / "src")]
    import pytest
    from computer_use_agent.gui_host_source import collect_host_gui_observation
    from fullcycle_bridge.gui_observation_projection import project_observation
    from fullcycle_bridge.native_gui_proposal import compile_native_response, context_digest

    fixture = runpy.run_path(str(ROOT / "tests" / "agent" / "test_gui_host_source.py"))
    with (
        tempfile.TemporaryDirectory(prefix="gui-host-handoff-") as folder,
        pytest.MonkeyPatch.context() as patch,
    ):
        runner, desktop, driver, sessions = fixture["setup"](Path(folder), patch)
        outcome = asyncio.run(collect_host_gui_observation(runner, fixture["TASK"], max_seconds=5))
        payload = outcome.bundle.to_dict()
        projection = project_observation(
            payload["task"], payload["results"], outcome.bundle.image, payload["host_facts"]
        )
        assert projection["status"] == "projected"
        context = projection["context"]
        proposal = compile_native_response(
            context,
            context,
            dict(
                request_id=context["request_id"],
                context_digest=context_digest(context),
                raw_output='<tool_call>{"name":"computer_use","arguments":{"action":"left_click","coordinate":[500,500]}}</tool_call>',
            ),
        ).to_dict()
        assert proposal["arguments"] == {"ref": "ref_1"} and not proposal["execution_authorized"]
        assert desktop.closed and len(sessions) == 1
        assert outcome.state.observation_epoch == 3
        assert (
            outcome.state.budgets.model_turns_used == outcome.state.budgets.side_effects_used == 0
        )
        print(
            json.dumps(
                dict(
                    version=1,
                    consumer_head=head,
                    consumer_source_sha256=CONSUMER_FILES,
                    evidence="real_host_mcp_session_with_fake_desktop",
                    transport="sdk_memory_streams",
                    generation=desktop.generation,
                    ledger_epoch=outcome.state.observation_epoch,
                    tool_calls_used=outcome.state.budgets.tool_calls_used,
                    metadata_reads=driver.inspections,
                    proposal_action=proposal["action"],
                    execution_authorized=False,
                    model_inference=False,
                    live_desktop=False,
                    connection_closed=desktop.closed,
                ),
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
