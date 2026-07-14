"""Offline, fail-closed release preflight and sanitized evidence."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import venv
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from computer_use_mcp import __version__ as runtime_version


PREFLIGHT_REPORT_VERSION = 2
_PYTEST_SUMMARY = re.compile(
    r"(?P<passed>\d+) passed(?:, (?P<skipped>\d+) skipped)?(?:, (?P<failed>\d+) failed)?"
)
_BLOCKED_ENVIRONMENT = {
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "RUN_ANTHROPIC_INTEGRATION",
    "RUN_OPENAI_INTEGRATION",
}


@dataclass(frozen=True)
class _Command:
    returncode: int
    stdout: str = ""
    stderr: str = ""

    @property
    def passed(self) -> bool:
        return self.returncode == 0


def _offline_environment() -> dict[str, str]:
    environment = {
        key: value for key, value in os.environ.items() if key not in _BLOCKED_ENVIRONMENT
    }
    environment.update(
        {
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUTF8": "1",
            "RUN_ANTHROPIC_INTEGRATION": "0",
            "RUN_OPENAI_INTEGRATION": "0",
        }
    )
    return environment


def _run(arguments: Sequence[str], *, cwd: Path, environment: Mapping[str, str]) -> _Command:
    try:
        completed = subprocess.run(
            list(arguments),
            cwd=cwd,
            env=dict(environment),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError:
        return _Command(127)
    return _Command(completed.returncode, completed.stdout, completed.stderr)


def _gate(command: _Command) -> dict[str, object]:
    return {"passed": command.passed}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_project_version(root: Path) -> str | None:
    try:
        document = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
        version = document["project"]["version"]
    except (OSError, UnicodeError, tomllib.TOMLDecodeError, KeyError, TypeError):
        return None
    return version if isinstance(version, str) and version else None


def _read_eval_report(path: Path) -> dict[str, object] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict):
        return None
    required = {"passed", "case_count", "passed_cases", "failed_cases", "safety_escapes"}
    if not required <= set(value):
        return None
    if not isinstance(value["passed"], bool):
        return None
    for field in required - {"passed"}:
        field_value = value[field]
        if isinstance(field_value, bool) or not isinstance(field_value, int) or field_value < 0:
            return None
    return value


def _pytest_gate(command: _Command) -> dict[str, object]:
    result: dict[str, object] = {"passed": command.passed}
    matches = list(_PYTEST_SUMMARY.finditer(f"{command.stdout}\n{command.stderr}"))
    if matches:
        summary = matches[-1].groupdict(default="0")
        result.update(
            {
                "passed_tests": int(summary["passed"]),
                "skipped_tests": int(summary["skipped"]),
                "failed_tests": int(summary["failed"]),
            }
        )
    return result


def _eval_gate(command: _Command, report_path: Path) -> dict[str, object]:
    report = _read_eval_report(report_path)
    passed = bool(
        command.passed
        and report is not None
        and report["passed"]
        and report["failed_cases"] == 0
        and report["safety_escapes"] == 0
    )
    result: dict[str, object] = {"passed": passed}
    if report is not None:
        result.update(
            {
                "case_count": report["case_count"],
                "passed_cases": report["passed_cases"],
                "failed_cases": report["failed_cases"],
                "safety_escapes": report["safety_escapes"],
                "report_sha256": _sha256(report_path),
            }
        )
    return result


def _python_in_venv(directory: Path) -> Path:
    if os.name == "nt":
        return directory / "Scripts" / "python.exe"
    return directory / "bin" / "python"


def _write_report(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _remove_existing(path: Path) -> bool:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        return False
    return True


def _candidate_state(
    root: Path, environment: Mapping[str, str]
) -> tuple[str | None, bool]:
    commit_command = _run(
        ["git", "rev-parse", "--verify", "HEAD"], cwd=root, environment=environment
    )
    commit = commit_command.stdout.strip()
    if not commit_command.passed or not re.fullmatch(r"[0-9a-fA-F]{40}", commit):
        commit = None
    clean_command = _run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=root,
        environment=environment,
    )
    return commit, clean_command.passed and not clean_command.stdout.strip()


def run_release_preflight(
    root: Path,
    artifacts: Path,
    report_path: Path,
    *,
    python: Path | None = None,
) -> dict[str, object]:
    """Run offline release gates and write a sanitized machine-readable report."""

    root = root.resolve()
    artifacts = artifacts.resolve()
    report_path = report_path.resolve()
    python = (python or Path(sys.executable)).resolve()
    artifacts.mkdir(parents=True, exist_ok=True)
    environment = _offline_environment()

    commit, source_clean = _candidate_state(root, environment)
    project_version = _read_project_version(root)
    version_consistent = project_version is not None and project_version == runtime_version

    ruff = _run(
        [str(python), "-m", "ruff", "check", "src", "tests", "scripts"],
        cwd=root,
        environment=environment,
    )
    pytest = _run(
        [str(python), "-m", "pytest", "-q"], cwd=root, environment=environment
    )
    diff_check = _run(["git", "diff", "--check"], cwd=root, environment=environment)

    eval_report_path = artifacts / "e1-e2-report.json"
    evaluation = (
        _run(
            [
                str(python),
                "-m",
                "computer_use_agent",
                "eval",
                "--cases",
                str(root / "evals" / "cases"),
                "--manifest",
                str(root / "evals" / "e5-case-manifest.json"),
                "--report",
                str(eval_report_path),
            ],
            cwd=root,
            environment=environment,
        )
        if _remove_existing(eval_report_path)
        else _Command(127)
    )

    wheel_gate: dict[str, object] = {"passed": False}
    install_gate: dict[str, object] = {"passed": False}
    with tempfile.TemporaryDirectory(prefix="computer-use-release-") as temporary:
        temporary_root = Path(temporary)
        wheel_output = temporary_root / "wheel"
        build = _run(
            [
                str(python),
                "-m",
                "build",
                "--wheel",
                "--no-isolation",
                "--outdir",
                str(wheel_output),
            ],
            cwd=root,
            environment=environment,
        )
        wheels = sorted(wheel_output.glob("*.whl")) if build.passed else []
        if len(wheels) == 1:
            built_wheel = wheels[0]
            retained_wheel = artifacts / built_wheel.name
            shutil.copyfile(built_wheel, retained_wheel)
            wheel_gate = {
                "passed": True,
                "filename": retained_wheel.name,
                "sha256": _sha256(retained_wheel),
            }
            venv_dir = temporary_root / "venv"
            try:
                venv.EnvBuilder(with_pip=True, clear=True).create(venv_dir)
                wheel_python = _python_in_venv(venv_dir)
                install = _run(
                    [
                        str(wheel_python),
                        "-m",
                        "pip",
                        "install",
                        "--disable-pip-version-check",
                        "--no-deps",
                        str(retained_wheel),
                    ],
                    cwd=root,
                    environment=environment,
                )
                help_smoke = _run(
                    [str(wheel_python), "-m", "computer_use_agent", "--help"],
                    cwd=root,
                    environment=environment,
                )
                installed_version = _run(
                    [
                        str(wheel_python),
                        "-c",
                        "import importlib.metadata; print(importlib.metadata.version('computer-use-mcp'))",
                    ],
                    cwd=root,
                    environment=environment,
                )
                wheel_eval_path = artifacts / "wheel-e1-e2-report.json"
                wheel_eval = (
                    _run(
                        [
                            str(wheel_python),
                            "-m",
                            "computer_use_agent",
                            "eval",
                            "--cases",
                            str(root / "evals" / "cases"),
                            "--manifest",
                            str(root / "evals" / "e5-case-manifest.json"),
                            "--report",
                            str(wheel_eval_path),
                        ],
                        cwd=temporary_root,
                        environment=environment,
                    )
                    if _remove_existing(wheel_eval_path)
                    else _Command(127)
                )
                wheel_eval_gate = _eval_gate(wheel_eval, wheel_eval_path)
                install_gate = {
                    "passed": bool(
                        install.passed
                        and help_smoke.passed
                        and installed_version.passed
                        and installed_version.stdout.strip() == project_version
                        and wheel_eval_gate["passed"]
                    ),
                    "package_version": installed_version.stdout.strip()
                    if installed_version.passed
                    else None,
                    "e1_e2": wheel_eval_gate,
                }
            except OSError:
                install_gate = {"passed": False}

    final_commit, final_source_clean = _candidate_state(root, environment)
    candidate_stability = {
        "passed": bool(
            commit is not None
            and commit == final_commit
            and source_clean
            and final_source_clean
        ),
        "head_unchanged": commit is not None and commit == final_commit,
        "source_clean_at_start": source_clean,
        "source_clean_at_end": final_source_clean,
    }
    gates = {
        "candidate_stability": candidate_stability,
        "diff_check": _gate(diff_check),
        "ruff": _gate(ruff),
        "pytest": _pytest_gate(pytest),
        "e1_e2": _eval_gate(evaluation, eval_report_path),
        "wheel_build": wheel_gate,
        "wheel_install": install_gate,
    }
    passed = bool(
        version_consistent
        and all(bool(gate["passed"]) for gate in gates.values())
    )
    payload: dict[str, object] = {
        "report_version": PREFLIGHT_REPORT_VERSION,
        "passed": passed,
        "candidate": {
            "commit": commit,
            "final_commit": final_commit,
            "source_clean": source_clean,
            "final_source_clean": final_source_clean,
            "package_version": project_version,
            "runtime_version": runtime_version,
            "version_consistent": version_consistent,
        },
        "offline_guarantees": {
            "desktop_calls": False,
            "provider_credentials_forwarded": False,
            "provider_integrations_enabled": False,
        },
        "gates": gates,
    }
    _write_report(report_path, payload)
    return payload


__all__ = ["PREFLIGHT_REPORT_VERSION", "run_release_preflight"]
