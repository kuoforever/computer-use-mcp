from __future__ import annotations

import hashlib
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = ROOT / "requirements" / "dev-py313-windows.lock"
PYPROJECT_PATH = ROOT / "pyproject.toml"


def test_development_lock_is_bound_hashed_and_machine_independent() -> None:
    lock_text = LOCK_PATH.read_text(encoding="utf-8")
    match = re.search(
        r"^# pyproject-normalized-sha256: ([0-9a-f]{64})$",
        lock_text,
        re.MULTILINE,
    )
    normalized_pyproject = PYPROJECT_PATH.read_text(encoding="utf-8").replace("\r\n", "\n")

    assert match is not None
    assert match.group(1) == hashlib.sha256(normalized_pyproject.encode()).hexdigest()
    assert "# target: Windows CPython 3.13; profile: .[dev]" in lock_text
    assert "--hash=sha256:" in lock_text
    assert "--index-url" not in lock_text
    assert "--trusted-host" not in lock_text
    assert "file://" not in lock_text.lower()
    assert "c:\\users\\" not in lock_text.lower()
    assert "c:/users/" not in lock_text.lower()


def test_bootstrap_preserves_virtual_environment_as_generated_state() -> None:
    ignore_text = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    bootstrap_text = (ROOT / "scripts" / "bootstrap_dev.ps1").read_text(encoding="utf-8")

    assert ".venv/" in ignore_text
    assert ".venv-*/" in ignore_text
    assert "Remove-Item" not in bootstrap_text
