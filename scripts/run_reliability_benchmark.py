"""Run the repeated reliability benchmark and write JSON plus a Markdown summary.

Offline: no desktop, no provider, no credentials, no network. The side effect is
a fake durable sink, so every scenario is repeatable.

Usage::

    python scripts/run_reliability_benchmark.py --root out/benchmark \\
        --items 100 --repetitions 5 \\
        --json out/benchmark-report.json --markdown out/benchmark-report.md

Exits non-zero if any duplicate side effect occurred, or if any item ended up
neither committed nor parked for human attention.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from computer_use_agent.benchmark import (  # noqa: E402
    DEFAULT_ITEM_COUNT,
    DEFAULT_REPETITIONS,
    render_markdown,
    run_benchmark,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--items", type=int, default=DEFAULT_ITEM_COUNT)
    parser.add_argument("--repetitions", type=int, default=DEFAULT_REPETITIONS)
    parser.add_argument("--json", dest="json_path", type=Path)
    parser.add_argument("--markdown", dest="markdown_path", type=Path)
    parser.add_argument("--quiet", action="store_true")
    arguments = parser.parse_args()

    def progress(scenario: str, repetition: int) -> None:
        if not arguments.quiet:
            print(f"  {scenario} run {repetition}", file=sys.stderr)

    report = run_benchmark(
        arguments.root,
        item_count=arguments.items,
        repetitions=arguments.repetitions,
        progress=progress,
    )

    payload = report.as_json()
    if arguments.json_path is not None:
        arguments.json_path.parent.mkdir(parents=True, exist_ok=True)
        arguments.json_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    if arguments.markdown_path is not None:
        arguments.markdown_path.parent.mkdir(parents=True, exist_ok=True)
        arguments.markdown_path.write_text(render_markdown(report), encoding="utf-8")
    if arguments.json_path is None and arguments.markdown_path is None:
        print(json.dumps(payload, indent=2, sort_keys=True))

    print(
        f"benchmark: {'PASS' if report.passed else 'FAIL'} "
        f"({payload['total_runs']} runs, "
        f"{payload['total_duplicate_side_effects']} duplicate side effects)",
        file=sys.stderr,
    )
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
