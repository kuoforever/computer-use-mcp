"""Fail fast when current-state documentation drifts from the reviewed tool registry.

The reviewed registry in ``computer_use_agent.tool_registry`` is the canonical
source for the desktop MCP tool surface. Documents that describe the *current*
state must agree with it. Retained evidence records are deliberately excluded:
they freeze what a specific dated run observed and must never be "updated" to
the latest numbers.

This checker never rewrites documentation. It reports the file, the expected
value, and the actual value, and leaves the fix to a commit.

Run locally with::

    python scripts/check_docs_consistency.py
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from computer_use_agent.tool_registry import REVIEWED_TOOLS  # noqa: E402

# Documents that state the *current* tool surface. Dated evidence records
# (docs/BOSS_EVIDENCE.md, docs/OPERATOR_SESSION_NOTES.md, docs/E3_EVIDENCE.md,
# docs/E4_EVIDENCE.md, docs/archive/**) are intentionally absent: their fixed
# numbers are immutable observations, not claims about today.
CURRENT_STATE_DOCS: tuple[str, ...] = (
    "README.md",
    "README.zh-CN.md",
    "HANDOFF.md",
    "docs/TOOLS.md",
    "docs/DESIGN.md",
    "docs/AGENT.md",
    "docs/AGENT_IMPLEMENTATION_PLAN.md",
    "docs/CAPABILITY_STATUS.md",
    "docs/EVALUATION.md",
    "docs/LONG_RUNNING_TASKS.md",
)

# Documents that must enumerate every reviewed tool name.
TOOL_ENUMERATING_DOCS: tuple[str, ...] = (
    "README.md",
    "README.zh-CN.md",
    "docs/TOOLS.md",
)

ENGLISH_NUMBERS: dict[str, int] = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
}
CHINESE_NUMBERS: dict[str, int] = {
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
    "十一": 11,
    "十二": 12,
}

# "nine tools", "nine-tool server", "the current eight MCP tools". Singular bare
# phrases such as "one tool-free final response" describe a single call, not the
# surface, so the bare form requires the plural.
_ENGLISH_WORDS = "|".join(ENGLISH_NUMBERS)
_ENGLISH_COUNT = re.compile(
    r"\b(?P<word>" + _ENGLISH_WORDS + r")(?:"
    r" (?:MCP|reviewed) tools?"
    r"|-tool\b"
    r"| tools\b"
    r")",
    re.IGNORECASE,
)
# "九个 MCP 工具", "九个工具".
_CHINESE_COUNT = re.compile(
    r"(?P<word>" + "|".join(sorted(CHINESE_NUMBERS, key=len, reverse=True)) + r")个\s*(?:MCP\s*)?工具"
)
# Hand-maintained pytest totals such as "903 passed, 5 skipped".
_TEST_TOTAL = re.compile(r"\b\d{2,}\s+passed\b")


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    expected: str
    actual: str
    detail: str

    def render(self) -> str:
        return (
            f"{self.path}:{self.line}: {self.detail}\n"
            f"    expected: {self.expected}\n"
            f"    actual:   {self.actual}"
        )


def _read_lines(relative_path: str) -> list[str]:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8").splitlines()


def check_tool_counts(expected_count: int) -> list[Finding]:
    """Every spelled-out tool count in a current-state doc must match the registry."""
    findings: list[Finding] = []
    for relative_path in CURRENT_STATE_DOCS:
        for line_number, line in enumerate(_read_lines(relative_path), start=1):
            for match in _ENGLISH_COUNT.finditer(line):
                word = match.group("word").lower()
                if ENGLISH_NUMBERS[word] != expected_count:
                    findings.append(
                        Finding(
                            path=relative_path,
                            line=line_number,
                            expected=f"a tool count of {expected_count}",
                            actual=f"{match.group(0)!r} (={ENGLISH_NUMBERS[word]})",
                            detail="documented tool count disagrees with the reviewed registry",
                        )
                    )
            for match in _CHINESE_COUNT.finditer(line):
                word = match.group("word")
                if CHINESE_NUMBERS[word] != expected_count:
                    findings.append(
                        Finding(
                            path=relative_path,
                            line=line_number,
                            expected=f"a tool count of {expected_count}",
                            actual=f"{match.group(0)!r} (={CHINESE_NUMBERS[word]})",
                            detail="documented tool count disagrees with the reviewed registry",
                        )
                    )
    return findings


def check_tool_names(expected_names: tuple[str, ...]) -> list[Finding]:
    """Docs that enumerate the tool surface must name every reviewed tool."""
    findings: list[Finding] = []
    for relative_path in TOOL_ENUMERATING_DOCS:
        text = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        missing = [name for name in expected_names if f"`{name}`" not in text]
        if missing:
            findings.append(
                Finding(
                    path=relative_path,
                    line=1,
                    expected="every reviewed tool name in backticks: "
                    + ", ".join(f"`{name}`" for name in expected_names),
                    actual="missing " + ", ".join(f"`{name}`" for name in missing),
                    detail="documented tool surface omits a reviewed tool",
                )
            )
    return findings


def check_no_handwritten_test_totals() -> list[Finding]:
    """Current-state docs must not hand-maintain a pytest total.

    The total changes on nearly every feature commit. Retained evidence files
    keep their dated totals; current dashboards link CI instead.
    """
    findings: list[Finding] = []
    for relative_path in CURRENT_STATE_DOCS:
        for line_number, line in enumerate(_read_lines(relative_path), start=1):
            match = _TEST_TOTAL.search(line)
            if match:
                findings.append(
                    Finding(
                        path=relative_path,
                        line=line_number,
                        expected="no hand-written pytest total in a current-state document",
                        actual=repr(match.group(0)),
                        detail=(
                            "move the running total to CI, or move the claim into a dated "
                            "evidence record"
                        ),
                    )
                )
    return findings


def run_checks() -> list[Finding]:
    expected_names = tuple(tool.name for tool in REVIEWED_TOOLS)
    return [
        *check_tool_counts(len(expected_names)),
        *check_tool_names(expected_names),
        *check_no_handwritten_test_totals(),
    ]


def main() -> int:
    findings = run_checks()
    if not findings:
        print(f"docs consistency: OK ({len(REVIEWED_TOOLS)} reviewed tools)")
        return 0
    print(f"docs consistency: {len(findings)} problem(s) found", file=sys.stderr)
    for finding in findings:
        print(finding.render(), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
