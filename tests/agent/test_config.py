from __future__ import annotations

from pathlib import Path

import pytest

from computer_use_agent.config import (
    ALL_SIDE_EFFECTS_APPROVAL,
    APPROVED_ACTIONS_MODE,
    HIGH_RISK_ONLY_APPROVAL,
    DEFAULT_PAUSE_SHORTCUT,
    ContinuationConfig,
    READ_ONLY_MODE,
    ConfigError,
    MCPLaunchConfig,
    OperatorConfig,
    PolicyConfig,
    PrivacyConfig,
    ProviderConfig,
    default_state_dir,
    load_agent_config,
    pause_shortcut_virtual_key,
)


def _config_text(
    tmp_path: Path,
    *,
    environment: str = 'CUMCP_ALLOWLIST = "notepad.exe"',
    state_dir: Path | None = None,
    provider_extra: str = "",
    context_window_tokens: int = 128_000,
    output_token_reserve: int = 1_024,
) -> str:
    local_app_data = tmp_path / "LocalAppData"
    configured_state_dir = state_dir or local_app_data / "computer-use-agent" / "test-run"
    executable = (tmp_path / "computer-use-mcp.exe").as_posix()
    cwd = tmp_path.as_posix()
    return f'''\
[agent]
state_dir = "{configured_state_dir.as_posix()}"
policy_version = "phase0"

[provider]
name = "openai"
model = "test-model"
context_window_tokens = {context_window_tokens}
output_token_reserve = {output_token_reserve}
{provider_extra}

[mcp]
executable = "{executable}"
args = []
cwd = "{cwd}"
environment = {{ {environment} }}
'''


def test_config_defaults_to_read_only_and_uses_host_generated_safe_child_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    path = tmp_path / "agent.toml"
    path.write_text(_config_text(tmp_path), encoding="utf-8")

    config = load_agent_config(path)

    assert config.policy.mode == READ_ONLY_MODE
    assert config.policy.require_approval_for_actions is True
    assert config.policy.action_approval_policy == ALL_SIDE_EFFECTS_APPROVAL
    assert config.mcp.child_environment()["CUMCP_MODE"] == "safe_local"
    assert config.mcp.child_environment()["CUMCP_DANGEROUS_CONFIRM"] == "1"
    assert config.mcp.child_environment()["CUMCP_ALLOWLIST"] == "notepad.exe"
    assert config.trace_dir != config.memory_database


def test_provider_request_budget_defaults_and_is_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    path = tmp_path / "agent.toml"
    path.write_text(
        _config_text(tmp_path, provider_extra="max_request_bytes = 4096"),
        encoding="utf-8",
    )

    assert load_agent_config(path).provider.max_request_bytes == 4096

    for value in (1, 49 * 1024 * 1024, True):
        with pytest.raises(ConfigError, match="max_request_bytes"):
            ProviderConfig("openai", "test-model", value)


def test_provider_request_timeout_defaults_and_is_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    default_path = tmp_path / "default-timeout.toml"
    default_path.write_text(_config_text(tmp_path), encoding="utf-8")
    configured_path = tmp_path / "configured-timeout.toml"
    configured_path.write_text(
        _config_text(tmp_path, provider_extra="request_timeout_seconds = 90"),
        encoding="utf-8",
    )

    assert load_agent_config(default_path).provider.request_timeout_seconds == 120
    assert load_agent_config(configured_path).provider.request_timeout_seconds == 90

    for value in (0, 601, True):
        with pytest.raises(ConfigError, match="request_timeout_seconds"):
            ProviderConfig(
                "openai",
                "test-model",
                request_timeout_seconds=value,  # type: ignore[arg-type]
            )


@pytest.mark.parametrize(
    ("section", "setting", "expected_error"),
    [
        pytest.param(
            "agent",
            "state_dir = 7",
            "agent state_dir must be a non-empty absolute path",
            id="state-dir-non-string",
        ),
        pytest.param(
            "provider",
            "base_url = 7",
            "provider base_url must be a string or omitted",
            id="provider-base-url-non-string",
        ),
        pytest.param(
            "provider",
            "region = false",
            "provider region must be a string or omitted",
            id="provider-region-non-string",
        ),
        pytest.param(
            "provider",
            'workspace_id = ["workspace"]',
            "provider workspace_id must be a string or omitted",
            id="provider-workspace-non-string",
        ),
        pytest.param(
            "provider",
            "request_timeout_seconds = true",
            "provider request_timeout_seconds must be between 1 and 600",
            id="provider-timeout-boolean",
        ),
        pytest.param(
            "provider",
            "request_timeout_seconds = 1.5",
            "provider request_timeout_seconds must be between 1 and 600",
            id="provider-timeout-non-integer",
        ),
        pytest.param(
            "policy",
            "mode = 7",
            "policy mode must be 'read_only' or 'approved_actions'",
            id="policy-mode-non-string",
        ),
        pytest.param(
            "policy",
            "action_approval_policy = false",
            "action_approval_policy must be 'all_side_effects' or 'high_risk_only'",
            id="action-approval-policy-non-string",
        ),
    ],
)
def test_load_agent_config_rejects_malformed_scalar_types_with_exact_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    section: str,
    setting: str,
    expected_error: str,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    if section == "provider":
        config_text = _config_text(tmp_path, provider_extra=setting)
    else:
        config_text = _config_text(tmp_path)
        if section == "agent":
            state_dir_line = next(
                line for line in config_text.splitlines() if line.startswith("state_dir = ")
            )
            config_text = config_text.replace(state_dir_line, setting, 1)
        else:
            config_text += f"\n[policy]\n{setting}\n"
    path = tmp_path / "malformed-scalar.toml"
    path.write_text(config_text, encoding="utf-8")

    with pytest.raises(ConfigError) as raised:
        load_agent_config(path)
    assert str(raised.value) == expected_error


@pytest.mark.parametrize(
    (
        "provider_name",
        "provider_extra",
        "policy_text",
        "expected_error",
    ),
    [
        pytest.param(
            "unsupported",
            "base_url = 7",
            "",
            "provider name must be one of: anthropic, deepseek, doubao, glm, "
            "kimi, local_openai, minimax, openai, qwen",
            id="provider-name-before-base-url-type",
        ),
        pytest.param(
            "unsupported",
            "request_timeout_seconds = true",
            "",
            "provider name must be one of: anthropic, deepseek, doubao, glm, "
            "kimi, local_openai, minimax, openai, qwen",
            id="provider-name-before-timeout-type",
        ),
        pytest.param(
            "openai",
            'base_url = "https://example.invalid/v1"\n'
            "request_timeout_seconds = true",
            "",
            "provider base_url must be omitted for a reviewed-region provider",
            id="provider-route-before-timeout-type",
        ),
        pytest.param(
            "openai",
            "",
            '[policy]\nmode = "invalid"\naction_approval_policy = false',
            "policy mode must be 'read_only' or 'approved_actions'",
            id="policy-mode-before-action-policy-type",
        ),
        pytest.param(
            "openai",
            "",
            '[policy]\nmode = "approved_actions"\n'
            "require_approval_for_actions = false\n"
            "action_approval_policy = false",
            "approved_actions mode still requires a host approval boundary",
            id="policy-boundary-before-action-policy-type",
        ),
        pytest.param(
            "openai",
            "base_url = 7\nmax_request_bytes = true",
            "",
            "[provider].max_request_bytes must be a non-negative integer",
            id="provider-numeric-reader-preempts-base-url-type",
        ),
        pytest.param(
            "openai",
            "",
            "[policy]\naction_approval_policy = false\nmax_model_turns = true",
            "[policy].max_model_turns must be a non-negative integer",
            id="policy-numeric-reader-preempts-action-policy-type",
        ),
    ],
)
def test_load_agent_config_preserves_mixed_malformation_error_precedence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider_name: str,
    provider_extra: str,
    policy_text: str,
    expected_error: str,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    config_text = _config_text(tmp_path, provider_extra=provider_extra)
    config_text = config_text.replace(
        'name = "openai"', f'name = "{provider_name}"', 1
    )
    if policy_text:
        config_text += f"\n{policy_text}\n"
    path = tmp_path / "mixed-malformation.toml"
    path.write_text(config_text, encoding="utf-8")

    with pytest.raises(ConfigError) as raised:
        load_agent_config(path)
    assert type(raised.value) is ConfigError
    assert str(raised.value) == expected_error


def test_provider_token_window_defaults_and_is_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    path = tmp_path / "agent.toml"
    path.write_text(
        _config_text(
            tmp_path,
            context_window_tokens=200_000,
            output_token_reserve=4_096,
        ),
        encoding="utf-8",
    )

    provider = load_agent_config(path).provider
    assert provider.context_window_tokens == 200_000
    assert provider.output_token_reserve == 4_096

    with pytest.raises(ConfigError, match="context_window_tokens"):
        ProviderConfig("openai", "test-model", context_window_tokens=100)
    with pytest.raises(ConfigError, match="output_token_reserve"):
        ProviderConfig(
            "openai",
            "test-model",
            context_window_tokens=2_000,
            output_token_reserve=2_000,
        )

    missing = tmp_path / "missing-window.toml"
    missing.write_text(
        _config_text(tmp_path).replace("context_window_tokens = 128000\n", ""),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="context_window_tokens"):
        load_agent_config(missing)


def test_continuation_persistence_is_explicit_opt_in_and_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    path = tmp_path / "agent.toml"
    path.write_text(
        _config_text(tmp_path)
        + "\n[continuation]\nenabled = true\nttl_seconds = 600\n",
        encoding="utf-8",
    )

    config = load_agent_config(path)

    assert config.continuation == ContinuationConfig(enabled=True, ttl_seconds=600)
    with pytest.raises(ConfigError, match="ttl_seconds"):
        ContinuationConfig(enabled=True, ttl_seconds=59)


def test_privacy_is_explicit_opt_in_and_rejects_ephemeral_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert PrivacyConfig().enabled is False

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    path = tmp_path / "agent.toml"
    path.write_text(
        _config_text(tmp_path)
        + '\n[privacy]\nenabled = true\ndetectors = ["email", "phone"]\n'
        + 'terms = ["Project Phoenix"]\nimage_redaction = false\n',
        encoding="utf-8",
    )

    config = load_agent_config(path)

    assert config.privacy == PrivacyConfig(
        enabled=True,
        detectors=("email", "phone"),
        terms=("Project Phoenix",),
        image_redaction=False,
    )
    with pytest.raises(ConfigError, match="cannot be combined"):
        type(config)(
            state_dir=config.state_dir,
            policy_version=config.policy_version,
            provider=config.provider,
            mcp=config.mcp,
            policy=config.policy,
            continuation=ContinuationConfig(enabled=True),
            privacy=config.privacy,
        )


def test_privacy_config_rejects_unknown_detectors_and_reserved_terms() -> None:
    with pytest.raises(ConfigError, match="unknown privacy detector"):
        PrivacyConfig(enabled=True, detectors=("ner",))
    with pytest.raises(ConfigError, match="token syntax"):
        PrivacyConfig(enabled=True, terms=("[[PRIVATE:EMAIL:value]]",))


def test_operator_presence_is_disabled_by_default_and_strictly_opt_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    path = tmp_path / "agent.toml"
    path.write_text(_config_text(tmp_path), encoding="utf-8")
    assert load_agent_config(path).operator == OperatorConfig()

    path.write_text(
        _config_text(tmp_path)
        + "\n[operator]\npresence_enabled = true\n"
        + "reduced_motion = true\nhigh_contrast = true\n",
        encoding="utf-8",
    )
    assert load_agent_config(path).operator == OperatorConfig(
        presence_enabled=True, reduced_motion=True, high_contrast=True
    )


def test_operator_pause_shortcut_is_canonical_bounded_and_reserved_safe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    path = tmp_path / "agent.toml"
    path.write_text(_config_text(tmp_path), encoding="utf-8")
    assert load_agent_config(path).operator.pause_shortcut == DEFAULT_PAUSE_SHORTCUT

    path.write_text(
        _config_text(tmp_path) + '\n[operator]\npause_shortcut = "ctrl+alt+k"\n',
        encoding="utf-8",
    )
    assert load_agent_config(path).operator.pause_shortcut == "ctrl+alt+k"
    assert pause_shortcut_virtual_key("ctrl+alt+k") == ord("K")

    for value in (
        "Ctrl+Alt+K",
        "ctrl+alt+k ",
        "ctrl+shift+k",
        "ctrl+alt+g",
        "ctrl+alt+q",
        "ctrl+alt+f12",
        "win+k",
    ):
        with pytest.raises(ConfigError, match="operator pause_shortcut"):
            OperatorConfig(pause_shortcut=value)

    path.write_text(
        _config_text(tmp_path) + "\n[operator]\npause_shortcut = true\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match=r"\[operator\]\.pause_shortcut.*string"):
        load_agent_config(path)


def test_operator_presence_rejects_non_boolean_and_unknown_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    path = tmp_path / "agent.toml"
    path.write_text(
        _config_text(tmp_path) + '\n[operator]\npresence_enabled = "yes"\n',
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="presence_enabled.*boolean"):
        load_agent_config(path)

    path.write_text(
        _config_text(tmp_path) + "\n[operator]\nlabel = true\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match=r"unknown \[operator\] key"):
        load_agent_config(path)


def test_operator_progress_is_disabled_by_default_and_strictly_opt_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    path = tmp_path / "agent.toml"
    path.write_text(
        _config_text(tmp_path) + "\n[operator]\nprogress_enabled = true\n",
        encoding="utf-8",
    )

    assert load_agent_config(path).operator == OperatorConfig(progress_enabled=True)

    path.write_text(
        _config_text(tmp_path) + '\n[operator]\nprogress_enabled = "yes"\n',
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="progress_enabled.*boolean"):
        load_agent_config(path)


def test_decision_cards_are_default_off_and_timeout_is_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    path = tmp_path / "agent.toml"
    path.write_text(
        _config_text(tmp_path)
        + "\n[operator]\ndecision_cards_enabled = true\n"
        + "approval_notifications_enabled = true\n"
        + "decision_timeout_seconds = 45\n"
        + 'decision_card_corner = "top_left"\n',
        encoding="utf-8",
    )
    assert load_agent_config(path).operator == OperatorConfig(
        decision_cards_enabled=True,
        approval_notifications_enabled=True,
        decision_timeout_seconds=45,
        decision_card_corner="top_left",
    )

    for value in (4, 3_601, True):
        with pytest.raises(ConfigError, match="decision_timeout_seconds"):
            OperatorConfig(decision_timeout_seconds=value)  # type: ignore[arg-type]

    with pytest.raises(ConfigError, match="decision_card_corner"):
        OperatorConfig(decision_card_corner="center")

    path.write_text(
        _config_text(tmp_path)
        + '\n[operator]\napproval_notifications_enabled = "yes"\n',
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="approval_notifications_enabled.*boolean"):
        load_agent_config(path)


def test_operator_locale_is_strict_and_absent_key_preserves_english(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    path = tmp_path / "agent.toml"
    path.write_text(_config_text(tmp_path), encoding="utf-8")
    assert load_agent_config(path).operator.locale == "en-US"

    path.write_text(
        _config_text(tmp_path) + '\n[operator]\nlocale = "zh-CN"\n',
        encoding="utf-8",
    )
    assert load_agent_config(path).operator.locale == "zh-CN"


def test_operator_theme_is_strict_and_absent_key_preserves_dark(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    path = tmp_path / "agent.toml"
    path.write_text(_config_text(tmp_path), encoding="utf-8")
    assert load_agent_config(path).operator.theme == "dark"

    path.write_text(
        _config_text(tmp_path) + '\n[operator]\ntheme = "light"\n',
        encoding="utf-8",
    )
    assert load_agent_config(path).operator.theme == "light"


@pytest.mark.parametrize("theme", ["system", "auto ", "LIGHT", "blue"])
def test_operator_theme_rejects_unsupported_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    theme: str,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    path = tmp_path / "agent.toml"
    path.write_text(
        _config_text(tmp_path) + f'\n[operator]\ntheme = "{theme}"\n',
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="operator theme"):
        load_agent_config(path)


@pytest.mark.parametrize("locale", ["en", "zh", "auto ", "fr-FR"])
def test_operator_locale_rejects_unsupported_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    locale: str,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    path = tmp_path / "agent.toml"
    path.write_text(
        _config_text(tmp_path) + f'\n[operator]\nlocale = "{locale}"\n',
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="operator locale"):
        load_agent_config(path)


def test_operator_locale_rejects_non_string(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    path = tmp_path / "agent.toml"
    path.write_text(
        _config_text(tmp_path) + "\n[operator]\nlocale = true\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match=r"\[operator\]\.locale must be a string"):
        load_agent_config(path)


@pytest.mark.parametrize(
    "environment",
    [
        'OPENAI_API_KEY = "not-allowed"',
        'OPENAI_KEY = "not-allowed"',
        'AWS_ACCESS_KEY_ID = "not-allowed"',
        'SERVICE_TOKEN = "not-allowed"',
        'PYTHONPATH = "not-allowed"',
        'CUMCP_AUDIT = "NUL"',
        'CUMCP_ESTOP = ""',
    ],
)
def test_config_rejects_unreviewed_child_environment_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, environment: str
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    path = tmp_path / "agent.toml"
    path.write_text(_config_text(tmp_path, environment=environment), encoding="utf-8")

    with pytest.raises(ConfigError, match="not reviewed"):
        load_agent_config(path)


@pytest.mark.parametrize(
    "environment",
    [
        'CUMCP_MODE = "full_control_local"',
        'CUMCP_DANGEROUS_CONFIRM = "0"',
        'CUMCP_HUMAN_IDLE_SECONDS = "0"',
        'CUMCP_HUMAN_STABLE_SAMPLES = "0"',
        'CUMCP_HUMAN_POLL_INTERVAL_SECONDS = "0"',
        'CUMCP_HUMAN_MAX_WAIT_SECONDS = "0"',
        'CUMCP_TYPE_WAIT_SECONDS = "0.2"',
        'CUMCP_INTERACTION_SPEED = "turbo"',
        'CUMCP_ACTION_FEEDBACK = "sometimes"',
    ],
)
def test_config_rejects_child_environment_values_that_weaken_server_safety(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, environment: str
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    path = tmp_path / "agent.toml"
    path.write_text(_config_text(tmp_path, environment=environment), encoding="utf-8")

    with pytest.raises(ConfigError):
        load_agent_config(path)


def test_config_rejects_state_outside_the_user_local_application_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    path = tmp_path / "agent.toml"
    path.write_text(_config_text(tmp_path, state_dir=tmp_path / "outside"), encoding="utf-8")

    with pytest.raises(ConfigError, match="user-local"):
        load_agent_config(path)


def test_approved_actions_cannot_disable_host_approval() -> None:
    with pytest.raises(ConfigError, match="still requires"):
        PolicyConfig(mode=APPROVED_ACTIONS_MODE, require_approval_for_actions=False)


def test_high_risk_only_approval_is_explicit_and_action_mode_only() -> None:
    policy = PolicyConfig(
        mode=APPROVED_ACTIONS_MODE,
        action_approval_policy=HIGH_RISK_ONLY_APPROVAL,
    )

    assert policy.action_approval_policy == HIGH_RISK_ONLY_APPROVAL
    with pytest.raises(ConfigError, match="requires approved_actions"):
        PolicyConfig(action_approval_policy=HIGH_RISK_ONLY_APPROVAL)
    with pytest.raises(ConfigError, match="action_approval_policy"):
        PolicyConfig(mode=APPROVED_ACTIONS_MODE, action_approval_policy="model_chosen")


def test_context_event_budget_must_be_positive() -> None:
    with pytest.raises(ConfigError, match="max_context_events"):
        PolicyConfig(max_context_events=0)


def test_input_token_budget_must_be_nonnegative() -> None:
    with pytest.raises(ConfigError, match="max_input_tokens"):
        PolicyConfig(max_input_tokens=-1)


def test_launch_config_rejects_relative_executable_and_unreviewed_environment() -> None:
    with pytest.raises(ConfigError, match="absolute"):
        MCPLaunchConfig(
            executable=Path("computer-use-mcp.exe"),
            args=(),
            cwd=Path.cwd(),
            environment={},
        )
    with pytest.raises(ConfigError, match="not reviewed"):
        MCPLaunchConfig(
            executable=Path.cwd() / "computer-use-mcp.exe",
            args=(),
            cwd=Path.cwd(),
            environment={"OPENAI_API_KEY": "not-allowed"},
        )


def test_browser_and_uia_controls_are_reviewed_user_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    path = tmp_path / "agent.toml"
    path.write_text(
        _config_text(
            tmp_path,
            environment=(
                'CUMCP_ALLOWLIST = "chrome.exe", '
                'CUMCP_BROWSER_OBSERVATION = "cdp", '
                'CUMCP_BROWSER_CDP_ENDPOINT = "http://127.0.0.1:9222", '
                'CUMCP_UIA_ACTIONS = "1"'
            ),
        ),
        encoding="utf-8",
    )

    child = load_agent_config(path).mcp.child_environment()

    assert child["CUMCP_BROWSER_OBSERVATION"] == "cdp"
    assert child["CUMCP_BROWSER_CDP_ENDPOINT"] == "http://127.0.0.1:9222"
    assert child["CUMCP_UIA_ACTIONS"] == "1"


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("CUMCP_BROWSER_OBSERVATION", "auto", "must be off or cdp"),
        ("CUMCP_BROWSER_CDP_ENDPOINT", "https://example.com:9222", "loopback"),
        ("CUMCP_BROWSER_CDP_ENDPOINT", "http://user:pass@127.0.0.1:9222", "credentials"),
        ("CUMCP_UIA_ACTIONS", "maybe", "boolean"),
    ],
)
def test_browser_and_uia_controls_fail_closed(
    key: str,
    value: str,
    message: str,
) -> None:
    with pytest.raises(ConfigError, match=message):
        MCPLaunchConfig(
            executable=Path.cwd() / "computer-use-mcp.exe",
            args=(),
            cwd=Path.cwd(),
            environment={key: value},
        )


def test_default_state_directory_is_user_local() -> None:
    path = default_state_dir({"LOCALAPPDATA": "C:/Users/example/AppData/Local"})

    assert path.name == "computer-use-agent"
    assert "AppData" in str(path)
