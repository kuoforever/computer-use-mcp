from __future__ import annotations

import importlib.util
import json
import zipfile
from pathlib import Path
from types import ModuleType


def _load_demo_script() -> ModuleType:
    path = Path(__file__).resolve().parents[2] / "scripts" / "demo_cross_app.py"
    spec = importlib.util.spec_from_file_location("demo_cross_app_script", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _minimal_docx(path: Path) -> None:
    path.parent.mkdir(parents=True)
    with zipfile.ZipFile(path, "w") as package:
        package.writestr(
            "word/document.xml",
            (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/'
                'wordprocessingml/2006/main"><w:body><w:p><w:r>'
                "<w:t>Clean research template</w:t>"
                "</w:r></w:p></w:body></w:document>"
            ),
        )


def test_each_demo_run_starts_from_a_fresh_profile_and_template(
    tmp_path: Path,
) -> None:
    demo = _load_demo_script()
    template = tmp_path / "demo_templates" / "word-collaboration-research.docx"
    _minimal_docx(template)
    demo.ROOT = tmp_path
    demo.WORD_TEMPLATE = template

    first_document, first_profile, first_stamp = demo._fixtures()
    second_document, second_profile, second_stamp = demo._fixtures()

    assert first_stamp != second_stamp
    assert first_document != second_document
    assert first_profile != second_profile
    assert not tuple(first_profile.iterdir())
    assert not tuple(second_profile.iterdir())
    assert first_document.read_bytes() == template.read_bytes()
    assert second_document.read_bytes() == template.read_bytes()
    for document in (first_document, second_document):
        state = json.loads((document.parent / "initial-state.json").read_text())
        assert state["browser_profile_empty"] is True
        assert state["document_marker_present"] is False
        assert state["browser_window"] == {
            "height": 900,
            "width": 1280,
            "x": 80,
            "y": 80,
        }
