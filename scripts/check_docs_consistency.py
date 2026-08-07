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
    # Every other document whose own status banner claims implemented or
    # current behavior. Left out of the original list, these described the live
    # runtime while being exempt from the checks written for exactly that.
    "docs/APPROVALS.md",
    "docs/BOSS_SEMANTIC_EXTRACTION_CONTRACT.md",
    "docs/CONFIGURATION.md",
    "docs/CONTEXT_MEMORY.md",
    "docs/CONTINUATION.md",
    "docs/DEVELOPMENT.md",
    "docs/DRIVER_CONTRACT.md",
    "docs/FULLCYCLE_INTEGRATION.md",
    "docs/OBSERVATION_CONTRACT.md",
    "docs/OPERATOR_EXPERIENCE.md",
    "docs/PLANNING.md",
    "docs/PROGRESS_VIEWER.md",
    "docs/PROJECT_OVERVIEW.md",
    "docs/PUBLIC_WEB_WORD_WORKFLOW.md",
    "docs/RELEASE.md",
    "docs/STATELESS_REPLAY.md",
    "docs/TECH_STACK.md",
    "docs/TELEMETRY.md",
    "docs/TRACE.md",
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
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
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
    "十三": 13,
    "十四": 14,
    "十五": 15,
    "十六": 16,
    "十七": 17,
    "十八": 18,
    "十九": 19,
    "二十": 20,
}

# "nine tools", "nine-tool server", "the current eight MCP tools". Singular bare
# phrases such as "one tool-free final response" describe a single call, not the
# surface, so the bare form requires the plural. `-tool` must not be followed by
# another hyphenated word: "one-tool-call" and "one-tool-free" count calls, not
# the tool surface.
_ENGLISH_WORDS = "|".join(ENGLISH_NUMBERS)
_ENGLISH_COUNT = re.compile(
    r"\b(?P<word>" + _ENGLISH_WORDS + r")(?:"
    r" (?:MCP|reviewed) tools?"
    r"|-tool\b(?!-)"
    r"| tools\b"
    r")",
    re.IGNORECASE,
)
# "九个 MCP 工具", "九个工具".
_CHINESE_COUNT = re.compile(
    r"(?P<word>" + "|".join(sorted(CHINESE_NUMBERS, key=len, reverse=True)) + r")个\s*(?:MCP\s*)?工具"
)
# Arabic-digit forms the spelled-out patterns above cannot see: "13 个 MCP 工具",
# "13 reviewed tools", "13-tool server". The count reached 13 while the number
# tables stopped at twelve, so every such claim went unchecked; digits are the
# form the Chinese quick start actually uses.
_DIGIT_COUNT = re.compile(
    r"\b(?P<digits>\d{1,2})\s*(?:"
    r"个\s*(?:MCP\s*)?工具"
    r"|(?:reviewed|MCP)\s+tools?\b"
    r"|-tool\b(?!-)"
    r")"
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
            for match in _DIGIT_COUNT.finditer(line):
                value = int(match.group("digits"))
                if value != expected_count:
                    findings.append(
                        Finding(
                            path=relative_path,
                            line=line_number,
                            expected=f"a tool count of {expected_count}",
                            actual=f"{match.group(0)!r} (={value})",
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


# Markdown inline links, excluding images, which are checked the same way.
_LINK = re.compile(r"(?<!\!)\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_IMAGE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")


def _heading_slugs(text: str) -> set[str]:
    """GitHub's slug rules, reduced to what this repository actually uses."""

    slugs: set[str] = set()
    for heading in re.findall(r"^#{1,6}\s+(.+?)\s*$", text, re.M):
        # Strip inline code, emphasis, and links down to their text.
        plain = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", heading)
        plain = re.sub(r"[`*_]", "", plain)
        slug = re.sub(r"[^a-z0-9 \-]", "", plain.lower()).strip().replace(" ", "-")
        if slug:
            slugs.add(slug)
    return slugs


def check_relative_links() -> list[Finding]:
    """Every relative Markdown link and image target must exist.

    A broken link on a landing page costs more than a wrong sentence: it makes
    the evidence look unmaintained. Anchors are checked too, because a heading
    rename silently breaks them.
    """

    findings: list[Finding] = []
    for path in sorted(REPO_ROOT.rglob("*.md")):
        if any(part in {".venv", "node_modules", ".git", "out"} for part in path.parts):
            continue
        text = path.read_text(encoding="utf-8")
        relative_path = path.relative_to(REPO_ROOT).as_posix()
        slugs = _heading_slugs(text)
        for line_number, line in enumerate(text.splitlines(), start=1):
            for match in (*_LINK.finditer(line), *_IMAGE.finditer(line)):
                target = match.group(1)
                if target.startswith(("http://", "https://", "mailto:")):
                    continue
                file_part, _, anchor = target.partition("#")
                if not file_part:
                    if anchor and anchor not in slugs:
                        findings.append(
                            Finding(
                                path=relative_path,
                                line=line_number,
                                expected="an in-page anchor matching a heading",
                                actual=f"#{anchor}",
                                detail="in-page anchor does not match any heading",
                            )
                        )
                    continue
                resolved = (path.parent / file_part).resolve()
                if not resolved.exists():
                    findings.append(
                        Finding(
                            path=relative_path,
                            line=line_number,
                            expected="an existing relative target",
                            actual=file_part,
                            detail="relative link target does not exist",
                        )
                    )
    return findings


# --- checks that protect a coding agent's read path --------------------------
#
# A stale claim in a file the agent reads is worse than a long one: it does not
# slow the agent down, it sends it at the wrong work. The three checks below
# each pin a defect that actually reached `main`.

_ITEM_ID = re.compile(r"`?GDA-[A-Z]+-\d+`?")
# "is now the sole active closure item", "is the single active item".
_ACTIVE_CLAIM = re.compile(
    r"\b(?:is|becomes|remains)\b[^.]{0,40}?\b"
    r"(?:the\s+)?(?:single|sole|only|current)\s+active\b",
    re.IGNORECASE,
)
# Dated records and archives freeze what was true when written, so an active
# claim inside them is history, not a competing registry.
_FROZEN_PARTS = ("archive", "postmortems")


def check_single_active_item_registry() -> list[Finding]:
    """Only `PROJECT_STATUS.md` may name the active item.

    `HANDOFF.md` carried `GDA-FC-004` as "the sole active closure item" long
    after the tracker had moved on. Nothing detected it, because prose agreeing
    with prose is not something a human re-reads every session.
    """
    findings: list[Finding] = []
    for path in sorted(REPO_ROOT.rglob("*.md")):
        parts = set(path.parts)
        if parts & {".venv", "node_modules", ".git", "out"}:
            continue
        relative_path = path.relative_to(REPO_ROOT).as_posix()
        if relative_path == "PROJECT_STATUS.md":
            continue
        if parts & set(_FROZEN_PARTS) or "EVIDENCE" in path.name:
            continue
        for line_number, line in enumerate(_read_lines(relative_path), start=1):
            if _ACTIVE_CLAIM.search(line) and _ITEM_ID.search(line):
                findings.append(
                    Finding(
                        path=relative_path,
                        line=line_number,
                        expected="no active-item claim outside PROJECT_STATUS.md",
                        actual=line.strip()[:90],
                        detail=(
                            "only PROJECT_STATUS.md may name the active item; this copy "
                            "goes stale silently and misdirects the next session"
                        ),
                    )
                )
    return findings


# `**Status: ...**`, `Status: **executed**`, `Result: PASS`, `Date: 2026-...`,
# and the Chinese archived-plan form. Any of these tells a reader whether the
# page describes today.
_STATUS_MARKER = re.compile(
    r"(?im)^\s*>?\s*(?:\*\*)?(?:Status|Result|Date|归档状态)\s*[:：]"
)


def check_status_markers() -> list[Finding]:
    """Every top-level `docs/` page must say whether it describes today.

    `AGENTS.md` forbids resuming planned work. An agent can only obey that if
    each page states implemented / experimental / planned up front.
    """
    findings: list[Finding] = []
    for path in sorted((REPO_ROOT / "docs").glob("*.md")):
        relative_path = path.relative_to(REPO_ROOT).as_posix()
        if relative_path == "docs/README.md":  # the index itself defines the labels
            continue
        head = path.read_text(encoding="utf-8")[:1200]
        if not _STATUS_MARKER.search(head):
            findings.append(
                Finding(
                    path=relative_path,
                    line=1,
                    expected="a Status/Result/Date marker in the first lines",
                    actual="no status marker",
                    detail="a reader cannot tell whether this page describes current behavior",
                )
            )
    return findings


# The tracker reached 1365 lines, 76% of it closed work, while being the one
# file every session must read. A cap turns "should we clean this up?" into a
# failing check instead of a standing judgment call.
PROJECT_STATUS_MAX_LINES = 400


def check_project_status_budget() -> list[Finding]:
    """`PROJECT_STATUS.md` is read at every session start; keep it bounded."""
    actual = len(_read_lines("PROJECT_STATUS.md"))
    if actual <= PROJECT_STATUS_MAX_LINES:
        return []
    return [
        Finding(
            path="PROJECT_STATUS.md",
            line=actual,
            expected=f"at most {PROJECT_STATUS_MAX_LINES} lines",
            actual=f"{actual} lines",
            detail=(
                "move closed-work history to docs/archive/ and keep the active item, "
                "backlog, baseline, and gates here"
            ),
        )
    ]


def run_checks() -> list[Finding]:
    expected_names = tuple(tool.name for tool in REVIEWED_TOOLS)
    return [
        *check_tool_counts(len(expected_names)),
        *check_tool_names(expected_names),
        *check_no_handwritten_test_totals(),
        *check_relative_links(),
        *check_single_active_item_registry(),
        *check_status_markers(),
        *check_project_status_budget(),
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
