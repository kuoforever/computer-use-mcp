from __future__ import annotations

import builtins
import json

import pytest

import computer_use_agent.formal_demo_console_launcher as launcher


def test_help_does_not_import_native_backend(capsys, monkeypatch) -> None:
    original_import = builtins.__import__

    def checked_import(name, *args, **kwargs):  # noqa: ANN001, ANN202
        if name.endswith("formal_demo_console_win32"):
            raise AssertionError("help imported the native backend")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", checked_import)
    with pytest.raises(SystemExit, match="^0$"):
        launcher.main(["--help"])
    assert "Review-only Formal Demo Console" in capsys.readouterr().out


def test_describe_is_no_key_and_does_not_import_native_backend(
    capsys,
    monkeypatch,
) -> None:
    secret = "secret-env-value-must-not-appear"
    for name in (
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "DASHSCOPE_API_KEY",
    ):
        monkeypatch.setenv(name, secret)
    original_import = builtins.__import__

    def checked_import(name, *args, **kwargs):  # noqa: ANN001, ANN202
        if name.endswith("formal_demo_console_win32"):
            raise AssertionError("describe imported the native backend")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", checked_import)
    result = launcher.main(
        ["--provider", "openai", "--model", "gpt-reviewed", "--describe"]
    )

    assert result == 0
    output = capsys.readouterr()
    payload = json.loads(output.out)
    assert payload["mode"] == "review_only"
    assert payload["provider"] == "openai"
    assert payload["credential_readiness_checked"] is False
    assert payload["provider_request_started"] is False
    assert payload["scope_available"] is False
    assert payload["start_enabled"] is False
    assert payload["desktop_automation_started"] is False
    assert secret not in output.out
    assert output.err == ""


def test_invalid_route_error_is_fixed_and_does_not_echo_input(capsys) -> None:
    attacker = "https://attacker.example/secret-route"
    result = launcher.main(
        [
            "--provider",
            "openai",
            "--model",
            "gpt-reviewed",
            "--base-url",
            attacker,
            "--describe",
        ]
    )

    output = capsys.readouterr()
    assert result == 2
    assert attacker not in output.err
    assert output.err.startswith("error: FORMAL_DEMO_")


def test_window_launch_is_explicitly_windows_only(capsys, monkeypatch) -> None:
    monkeypatch.setattr(launcher.sys, "platform", "linux")

    result = launcher.main(["--provider", "openai", "--model", "gpt-reviewed"])

    assert result == 2
    assert capsys.readouterr().err == "error: FORMAL_DEMO_CONSOLE_WINDOWS_REQUIRED\n"


def test_launcher_source_has_no_config_environment_provider_or_runtime_wiring() -> None:
    source = open(launcher.__file__ or "", encoding="utf-8").read()
    for value in (
        "load_agent_config",
        "os.environ",
        "getenv",
        "provider_factory",
        "computer_use_agent.providers",
        "AgentRunner",
        "StdioDesktopMCP",
        "WindowsDriver",
        "compile_task_intent_once",
        ".consume(",
        "subprocess",
        "socket",
    ):
        assert value not in source
