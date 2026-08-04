from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "capture_operator_hud_evidence.py"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "capture_operator_hud_evidence",
        SCRIPT,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_capture_slots_use_fixed_titles_and_dated_repository_paths() -> None:
    module = _load_script()
    capture_date = date(2026, 7, 30)

    assert set(module.TARGETS) == {
        "decision-card-compact",
        "decision-card-expanded",
        "progress-compact",
        "progress-expanded",
    }
    assert {
        target.title for target in module.TARGETS.values()
    } == {
        "Decision required · action blocked",
        "Progress HUD visual review",
    }
    assert module._output_path(
        "decision-card-compact",
        capture_date=capture_date,
    ) == (
        ROOT
        / "docs"
        / "evidence"
        / "operator-hud"
        / "2026-07-30"
        / "decision-card-compact.png"
    )


def test_capture_rejects_missing_or_ambiguous_exact_title(
    monkeypatch,
) -> None:
    module = _load_script()

    for matches in ((), (101, 202)):
        monkeypatch.setattr(
            module,
            "_matching_visible_windows",
            lambda _title, result=matches: result,
        )
        try:
            module.capture(
                "progress-compact",
                overwrite=True,
                settle_seconds=0,
            )
        except RuntimeError as error:
            assert "EXPECTED_ONE_EXACT_WINDOW" in str(error)
        else:
            raise AssertionError("capture accepted a non-unique title")


def test_capture_slots_require_compact_or_expanded_geometry() -> None:
    module = _load_script()

    assert module._matches_surface_geometry(
        "decision-card-compact",
        (0, 0, 560, 309),
    )
    assert not module._matches_surface_geometry(
        "decision-card-compact",
        (0, 0, 720, 659),
    )
    assert module._matches_surface_geometry(
        "progress-expanded",
        (0, 0, 520, 560),
    )
    assert not module._matches_surface_geometry(
        "progress-expanded",
        (0, 0, 460, 250),
    )
