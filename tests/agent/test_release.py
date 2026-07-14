from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

import computer_use_agent.release as release


ROOT = Path(__file__).parents[2]


class _FakeVenvBuilder:
    def __init__(self, **_: object) -> None:
        pass

    def create(self, directory: Path) -> None:
        directory.mkdir(parents=True)


def _install_fake_commands(
    monkeypatch: pytest.MonkeyPatch,
    *,
    dirty: bool = False,
    final_dirty: bool = False,
    final_commit: str | None = None,
    safety_escapes: int = 0,
) -> list[dict[str, str]]:
    environments: list[dict[str, str]] = []
    rev_parse_calls = 0
    status_calls = 0

    def fake_run(
        arguments: list[str] | tuple[str, ...],
        *,
        cwd: Path,
        environment: dict[str, str],
    ) -> release._Command:
        nonlocal rev_parse_calls, status_calls
        del cwd
        environments.append(dict(environment))
        command = list(arguments)
        if command[:3] == ["git", "rev-parse", "--verify"]:
            rev_parse_calls += 1
            commit = final_commit if rev_parse_calls > 1 and final_commit else "a" * 40
            return release._Command(0, commit + "\n")
        if command[:3] == ["git", "status", "--porcelain=v1"]:
            status_calls += 1
            is_dirty = dirty if status_calls == 1 else final_dirty
            return release._Command(0, "?? local.txt\n" if is_dirty else "")
        if command[:2] == ["git", "diff"]:
            return release._Command(0)
        if "pytest" in command:
            return release._Command(0, "321 passed, 3 skipped in 1.00s\n")
        if "build" in command:
            output = Path(command[command.index("--outdir") + 1])
            output.mkdir(parents=True)
            (output / "computer_use_mcp-0.1.0-py3-none-any.whl").write_bytes(b"wheel")
            return release._Command(0)
        if "eval" in command:
            report_path = Path(command[command.index("--report") + 1])
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(
                json.dumps(
                    {
                        "passed": safety_escapes == 0,
                        "case_count": 13,
                        "passed_cases": 13 if safety_escapes == 0 else 12,
                        "failed_cases": 0 if safety_escapes == 0 else 1,
                        "safety_escapes": safety_escapes,
                    }
                ),
                encoding="utf-8",
            )
            return release._Command(0, stderr="SENSITIVE_SUBPROCESS_OUTPUT")
        if any("importlib.metadata" in item for item in command):
            return release._Command(0, "0.1.0\n")
        return release._Command(0)

    monkeypatch.setattr(release, "_run", fake_run)
    monkeypatch.setattr(release.venv, "EnvBuilder", _FakeVenvBuilder)
    return environments


def test_release_preflight_records_sanitized_offline_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "secret-openai")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "secret-anthropic")
    monkeypatch.setenv("RUN_OPENAI_INTEGRATION", "1")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secret-aws")
    monkeypatch.setenv("GITHUB_TOKEN", "secret-github")
    monkeypatch.setenv("UNRELATED_SECRET", "secret-unrelated")
    environments = _install_fake_commands(monkeypatch)
    monkeypatch.setattr(release, "_utc_timestamp", lambda: "2026-07-14T01:02:03Z")
    monkeypatch.setattr(
        release,
        "_runtime_metadata",
        lambda: {
            "python_version": "3.13.5",
            "python_implementation": "CPython",
            "os_name": "nt",
            "sys_platform": "win32",
        },
    )
    artifacts = tmp_path / "artifacts"
    report_path = tmp_path / "preflight.json"

    payload = release.run_release_preflight(ROOT, artifacts, report_path)

    assert payload["passed"] is True
    assert payload["report_version"] == 3
    assert payload["generated_at_utc"] == "2026-07-14T01:02:03Z"
    assert payload["execution"] == {
        "python_version": "3.13.5",
        "python_implementation": "CPython",
        "os_name": "nt",
        "sys_platform": "win32",
    }
    assert payload["candidate"] == {
        "commit": "a" * 40,
        "final_commit": "a" * 40,
        "source_clean": True,
        "final_source_clean": True,
        "package_version": "0.1.0",
        "runtime_version": "0.1.0",
        "version_consistent": True,
    }
    assert payload["gates"]["pytest"] == {
        "passed": True,
        "passed_tests": 321,
        "skipped_tests": 3,
        "failed_tests": 0,
    }
    assert payload["gates"]["e1_e2"]["safety_escapes"] == 0
    assert payload["gates"]["candidate_stability"] == {
        "passed": True,
        "head_unchanged": True,
        "source_clean_at_start": True,
        "source_clean_at_end": True,
    }
    assert payload["gates"]["wheel_install"]["e1_e2"]["case_count"] == 13
    assert len(payload["gates"]["wheel_build"]["sha256"]) == 64
    raw = report_path.read_text(encoding="utf-8")
    assert json.loads(raw) == payload
    assert "SENSITIVE_SUBPROCESS_OUTPUT" not in raw
    assert all("OPENAI_API_KEY" not in environment for environment in environments)
    assert all("ANTHROPIC_API_KEY" not in environment for environment in environments)
    assert all("AWS_SECRET_ACCESS_KEY" not in environment for environment in environments)
    assert all("GITHUB_TOKEN" not in environment for environment in environments)
    assert all("UNRELATED_SECRET" not in environment for environment in environments)
    assert all(environment["RUN_OPENAI_INTEGRATION"] == "0" for environment in environments)
    assert all(
        environment["RUN_ANTHROPIC_INTEGRATION"] == "0" for environment in environments
    )
    assert all(environment["PIP_NO_INDEX"] == "1" for environment in environments)
    assert all(environment["PIP_NO_INPUT"] == "1" for environment in environments)
    assert all(environment["PYTHONNOUSERSITE"] == "1" for environment in environments)


def test_offline_environment_uses_a_platform_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PATH", "reviewed-path")
    monkeypatch.setenv("TEMP", "reviewed-temp")
    monkeypatch.setenv("HOME", "reviewed-home")
    monkeypatch.setenv("AZURE_CLIENT_SECRET", "secret-azure")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "secret-google")
    monkeypatch.setenv("PYTHONPATH", "unreviewed-import-path")
    monkeypatch.setenv("PIP_INDEX_URL", "https://unreviewed.example")

    environment = release._offline_environment()

    assert environment["PATH"] == "reviewed-path"
    assert environment["TEMP"] == "reviewed-temp"
    assert environment["HOME"] == "reviewed-home"
    assert "AZURE_CLIENT_SECRET" not in environment
    assert "GOOGLE_APPLICATION_CREDENTIALS" not in environment
    assert "PYTHONPATH" not in environment
    assert "PIP_INDEX_URL" not in environment
    assert environment["PIP_CONFIG_FILE"] == os.devnull
    assert environment["PIP_DISABLE_PIP_VERSION_CHECK"] == "1"
    assert environment["PIP_NO_INDEX"] == "1"
    assert environment["PIP_NO_INPUT"] == "1"
    assert environment["PYTHONNOUSERSITE"] == "1"


def test_runtime_evidence_is_utc_and_omits_local_identity_paths() -> None:
    timestamp = release._utc_timestamp()
    metadata = release._runtime_metadata()

    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", timestamp)
    assert set(metadata) == {
        "python_version",
        "python_implementation",
        "os_name",
        "sys_platform",
    }
    assert all(isinstance(value, str) and value for value in metadata.values())
    assert not ({"user", "hostname", "executable", "path"} & set(metadata))


def test_release_preflight_fails_closed_for_dirty_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_commands(monkeypatch, dirty=True)

    payload = release.run_release_preflight(
        ROOT, tmp_path / "artifacts", tmp_path / "report.json"
    )

    assert payload["passed"] is False
    assert payload["candidate"]["source_clean"] is False
    assert payload["gates"]["candidate_stability"]["passed"] is False
    assert all(
        gate["passed"]
        for name, gate in payload["gates"].items()
        if name != "candidate_stability"
    )


def test_release_preflight_fails_closed_for_a_safety_escape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_commands(monkeypatch, safety_escapes=1)

    payload = release.run_release_preflight(
        ROOT, tmp_path / "artifacts", tmp_path / "report.json"
    )

    assert payload["passed"] is False
    assert payload["gates"]["e1_e2"]["passed"] is False
    assert payload["gates"]["e1_e2"]["safety_escapes"] == 1
    assert payload["gates"]["wheel_install"]["passed"] is False


def test_release_preflight_fails_closed_for_public_version_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_commands(monkeypatch)
    monkeypatch.setattr(release, "runtime_version", "0.0.0")

    payload = release.run_release_preflight(
        ROOT, tmp_path / "artifacts", tmp_path / "report.json"
    )

    assert payload["passed"] is False
    assert payload["candidate"]["version_consistent"] is False
    assert payload["candidate"]["package_version"] == "0.1.0"
    assert payload["candidate"]["runtime_version"] == "0.0.0"


def test_release_preflight_fails_closed_when_head_changes_during_gates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_commands(monkeypatch, final_commit="b" * 40)

    payload = release.run_release_preflight(
        ROOT, tmp_path / "artifacts", tmp_path / "report.json"
    )

    assert payload["passed"] is False
    assert payload["candidate"]["commit"] == "a" * 40
    assert payload["candidate"]["final_commit"] == "b" * 40
    assert payload["gates"]["candidate_stability"]["head_unchanged"] is False


def test_release_preflight_fails_closed_when_source_becomes_dirty_during_gates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_commands(monkeypatch, final_dirty=True)

    payload = release.run_release_preflight(
        ROOT, tmp_path / "artifacts", tmp_path / "report.json"
    )

    assert payload["passed"] is False
    assert payload["candidate"]["source_clean"] is True
    assert payload["candidate"]["final_source_clean"] is False
    stability = payload["gates"]["candidate_stability"]
    assert stability["head_unchanged"] is True
    assert stability["source_clean_at_end"] is False
