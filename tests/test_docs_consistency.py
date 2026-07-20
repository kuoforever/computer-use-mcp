"""Documentation drift gate.

These tests run the same checker CI runs, plus negative cases proving the
checker actually fails when the tool surface or a stale running total drifts.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_checker():
    module_path = REPO_ROOT / "scripts" / "check_docs_consistency.py"
    spec = importlib.util.spec_from_file_location("check_docs_consistency", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


checker = _load_checker()


def test_current_state_docs_match_the_reviewed_registry() -> None:
    findings = checker.run_checks()
    assert findings == [], "\n".join(finding.render() for finding in findings)


def test_missing_tool_name_is_reported(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Deleting a tool name from an enumerating doc must fail with a readable error."""
    doc = tmp_path / "TOOLS.md"
    kept = tuple(tool.name for tool in checker.REVIEWED_TOOLS)[:-1]
    doc.write_text("\n".join(f"- `{name}`" for name in kept), encoding="utf-8")
    monkeypatch.setattr(checker, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(checker, "TOOL_ENUMERATING_DOCS", ("TOOLS.md",))

    findings = checker.check_tool_names(tuple(tool.name for tool in checker.REVIEWED_TOOLS))

    assert len(findings) == 1
    rendered = findings[0].render()
    assert "TOOLS.md" in rendered
    assert checker.REVIEWED_TOOLS[-1].name in rendered
    assert "missing" in rendered


def test_stale_tool_count_is_reported(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    doc = tmp_path / "README.md"
    doc.write_text("- Eight MCP tools: see the reference.\n- 八个 MCP 工具。\n", encoding="utf-8")
    monkeypatch.setattr(checker, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(checker, "CURRENT_STATE_DOCS", ("README.md",))

    findings = checker.check_tool_counts(9)

    assert [finding.line for finding in findings] == [1, 2]
    assert all("expected: a tool count of 9" in finding.render() for finding in findings)


def test_singular_tool_phrases_are_not_counts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """"one tool call" describes a single call, not the surface."""
    doc = tmp_path / "AGENT.md"
    doc.write_text("one final model turn, one tool call, and one tool-free response\n", "utf-8")
    monkeypatch.setattr(checker, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(checker, "CURRENT_STATE_DOCS", ("AGENT.md",))

    assert checker.check_tool_counts(9) == []


def test_handwritten_test_total_is_reported(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    doc = tmp_path / "CAPABILITY_STATUS.md"
    doc.write_text("python -m pytest -q    903 passed, 5 skipped\n", encoding="utf-8")
    monkeypatch.setattr(checker, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(checker, "CURRENT_STATE_DOCS", ("CAPABILITY_STATUS.md",))

    findings = checker.check_no_handwritten_test_totals()

    assert len(findings) == 1
    assert "903 passed" in findings[0].render()


def test_retained_evidence_records_are_not_checked() -> None:
    """Dated evidence keeps the numbers its own run observed."""
    for excluded in ("docs/BOSS_EVIDENCE.md", "docs/OPERATOR_SESSION_NOTES.md"):
        assert excluded not in checker.CURRENT_STATE_DOCS
    # Guard the specific historical claims this PR deliberately left alone.
    boss = (REPO_ROOT / "docs" / "BOSS_EVIDENCE.md").read_text(encoding="utf-8")
    assert "reviewed eight tools" in boss
