from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "ci.yml"


def _workflow_text() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def test_required_check_contexts_and_compatibility_matrix_are_preserved() -> None:
    workflow = _workflow_text()

    assert "name: Offline quality (Python ${{ matrix.python-version }})" in workflow
    assert 'python-version: ["3.11", "3.12", "3.13"]' in workflow
    assert "name: Wheel build and clean install" in workflow


def test_actions_are_pinned_to_immutable_commits() -> None:
    uses = re.findall(r"^\s*- uses: (?P<action>[^@\s]+)@(?P<revision>[^\s#]+)", _workflow_text(), re.MULTILINE)

    assert uses
    for action, revision in uses:
        assert re.fullmatch(r"[0-9a-f]{40}", revision), f"{action}@{revision} is mutable"


def test_locked_primary_gate_and_floating_canary_are_separate() -> None:
    workflow = _workflow_text()

    assert "--require-hashes --requirement requirements\\dev-py313-windows.lock" in workflow
    assert "--no-build-isolation --no-deps --editable ." in workflow
    assert "if: matrix.python-version == '3.13'" in workflow
    assert "if: matrix.python-version != '3.13'" in workflow
    assert "floating-canary:" in workflow
    assert "if: github.event_name == 'schedule' || github.event_name == 'workflow_dispatch'" in workflow
    assert "Install floating development dependencies" in workflow
    assert "Offline compatibility canary" in workflow


def test_static_and_report_gates_run_only_once_on_python_313() -> None:
    workflow = _workflow_text()

    for step in ("Ruff", "Types", "Documentation consistency"):
        assert workflow.count(f"- name: {step}\n") == 1
        assert re.search(
            rf"- name: {re.escape(step)}\n\s+if: matrix\.python-version == '3\.13'",
            workflow,
        )
    for step in (
        "Crash reconstruction E2 gate",
        "OpenAI stateless replay E2 gate",
        "Deterministic E1/E2 gate",
    ):
        assert re.search(
            rf"- name: {re.escape(step)}\n\s+if: matrix\.python-version == '3\.13'",
            workflow,
        )


def test_repository_eol_and_binary_contract_is_explicit() -> None:
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()

    assert "* text=auto eol=lf" in attributes
    assert "*.png binary" in attributes
    assert "*.docx binary" in attributes
