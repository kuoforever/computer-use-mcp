"""Replay synthetic producer output through the pinned RAML consumer; no desktop IO."""

from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
from pathlib import Path
import runpy
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
CONSUMER_HEAD = "924c07db6c72cbcae4ae941d1191272f0ffc9e14"
CONSUMER_FILES = {
    "gui_observation_projection.py": "395d1694d1e5fc285e4e304068045a4c6966709ce8698c757e909f941f77c038",
    "native_gui_proposal.py": "ffac645aaf402d225f44d982fe5bc0b97e65c9dd51bf5ade79a2bd26e15205a0",
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--consumer-root", type=Path, required=True)
    args = parser.parse_args()
    consumer = args.consumer_root.resolve()
    head = subprocess.check_output(
        ["git", "-C", str(consumer), "rev-parse", "HEAD"], text=True
    ).strip()
    if head != CONSUMER_HEAD:
        raise SystemExit("CONSUMER_HEAD_MISMATCH")
    for name, expected in CONSUMER_FILES.items():
        source = consumer / "src" / "fullcycle_bridge" / name
        if hashlib.sha256(source.read_text(encoding="utf-8").encode()).hexdigest() != expected:
            raise SystemExit("CONSUMER_SOURCE_MISMATCH")
    sys.path[:0] = [str(ROOT / "src"), str(consumer / "src")]
    from computer_use_agent.gui_observation import collect_gui_observation
    from fullcycle_bridge.gui_observation_projection import (
        ObservationProjectionError,
        project_observation,
    )
    from fullcycle_bridge.native_gui_proposal import (
        NativeProposalError,
        compile_native_response,
        context_digest,
    )

    fixtures = runpy.run_path(str(ROOT / "tests" / "agent" / "test_gui_observation.py"))
    bundle = asyncio.run(
        collect_gui_observation(fixtures["TASK"], fixtures["FakeSource"](), clock=lambda: 1.0)
    )
    payload = bundle.to_dict()
    task, results, facts = (payload[key] for key in ("task", "results", "host_facts"))
    incomplete = project_observation(task, results, bundle.image)
    assert incomplete["status"] == "incomplete" and len(incomplete["missing"]) == 4
    projection = project_observation(task, results, bundle.image, facts)
    assert projection["status"] == "projected" and projection["missing"] == []
    context = projection["context"]
    reply = dict(
        request_id=task["request_id"],
        context_digest=context_digest(context),
        raw_output='<tool_call>{"name":"computer_use","arguments":{"action":"left_click","coordinate":[500,500]}}</tool_call>',
    )
    proposal = compile_native_response(context, context, reply).to_dict()
    assert proposal["action"] == "click_ref" and proposal["arguments"] == {"ref": "ref_1"}
    assert not any(
        row["execution_authorized"] for row in (payload, incomplete, projection, proposal)
    )
    negatives = []
    for kind in ("image", "task", "result"):
        changed_task, changed_results, changed_image = (
            copy.deepcopy(task),
            copy.deepcopy(results),
            bundle.image,
        )
        if kind == "image":
            changed_image += b"changed"
        elif kind == "task":
            changed_task["request_id"] = "changed"
        else:
            changed_results["windows"]["text"] = '* 314 | e | "Changed"'
        try:
            project_observation(changed_task, changed_results, changed_image, facts)
        except ObservationProjectionError as exc:
            assert str(exc) == "HOST_FACT_BINDING_MISMATCH"
            negatives.append(kind)
        else:
            raise AssertionError("CHANGED_OBSERVATION_ACCEPTED")
    current = copy.deepcopy(context)
    current["current_epoch"] += 1
    try:
        compile_native_response(context, current, reply)
    except NativeProposalError as exc:
        assert str(exc) == "CONTEXT_CHANGED"
        negatives.append("current_epoch")
    else:
        raise AssertionError("STALE_CONTEXT_ACCEPTED")
    print(
        json.dumps(
            dict(
                version=1,
                evidence="synthetic_offline_only",
                consumer_head=head,
                consumer_source_sha256=CONSUMER_FILES,
                missing_facts_before=4,
                missing_facts_after=0,
                proposal_action=proposal["action"],
                rejected_mutations=negatives,
                execution_authorized=False,
                live_desktop=False,
                model_inference=False,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
