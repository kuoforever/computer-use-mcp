from __future__ import annotations

import pytest

from computer_use_agent.operator_localization import (
    OperatorLocale,
    OperatorLocalizationError,
    decision_button_label,
    localize_fixed_text,
    localized_visual,
    operator_text,
    resolve_operator_locale,
)
from computer_use_agent.operator_visuals import (
    OperatorVisualRole,
    operator_visual,
)


def test_explicit_locale_does_not_probe_windows() -> None:
    def forbidden() -> str:
        raise AssertionError("explicit locale must not probe the system")

    assert (
        resolve_operator_locale("zh-CN", system_locale_loader=forbidden)
        is OperatorLocale.ZH_CN
    )


@pytest.mark.parametrize("observed", ["zh-CN", "zh-Hans-CN", "zh-SG", "ZH_cn"])
def test_auto_locale_maps_simplified_chinese_variants(observed: str) -> None:
    assert resolve_operator_locale(
        "auto", system_locale_loader=lambda: observed
    ) is OperatorLocale.ZH_CN


@pytest.mark.parametrize("observed", ["en-US", "fr-FR", "zh-TW", "zh-Hant-HK"])
def test_auto_locale_uses_english_for_unsupported_or_traditional_locales(
    observed: str,
) -> None:
    assert resolve_operator_locale(
        "auto", system_locale_loader=lambda: observed
    ) is OperatorLocale.EN_US


def test_auto_locale_failure_falls_back_to_english() -> None:
    def unavailable() -> str:
        raise OSError("locale unavailable")

    assert (
        resolve_operator_locale("auto", system_locale_loader=unavailable)
        is OperatorLocale.EN_US
    )


@pytest.mark.parametrize("preference", ["", "en", "zh", "auto ", True, None])
def test_invalid_locale_preference_is_rejected(preference: object) -> None:
    with pytest.raises(OperatorLocalizationError, match="OPERATOR_LOCALE_INVALID"):
        resolve_operator_locale(preference)  # type: ignore[arg-type]


def test_plain_language_decision_buttons_preserve_internal_ids() -> None:
    expected = {
        "option_approve_exact_effect": ("Approve once", "仅批准这一次"),
        "option_reobserve": ("Check screen again", "重新检查屏幕"),
        "option_defer": ("Pause and inspect", "暂停并检查"),
        "option_deny": ("Stop task", "停止任务"),
        "option_human_takeover": ("Take control", "接管桌面"),
    }

    for option_id, (english, chinese) in expected.items():
        assert decision_button_label(OperatorLocale.EN_US, option_id, "fallback") == english
        assert decision_button_label(OperatorLocale.ZH_CN, option_id, "fallback") == chinese
    assert decision_button_label(OperatorLocale.ZH_CN, "custom", "Keep this") == "Keep this"


def test_fixed_host_copy_localizes_known_text_and_preserves_unknown_text() -> None:
    assert (
        localize_fixed_text(
            OperatorLocale.ZH_CN,
            "Public-source research brief update",
        )
        == "公开来源研究简报更新"
    )
    assert (
        localize_fixed_text(OperatorLocale.ZH_CN, "Verify the saved document")
        == "验证已保存的文档"
    )
    assert localize_fixed_text(OperatorLocale.ZH_CN, "Unmapped Host label") == (
        "Unmapped Host label"
    )


def test_operator_copy_formats_both_locales() -> None:
    assert operator_text(OperatorLocale.EN_US, "countdown", seconds=12) == "Closes in 12s"
    assert operator_text(OperatorLocale.ZH_CN, "countdown", seconds=12) == "12 秒后关闭"
    assert operator_text(OperatorLocale.EN_US, "result_unknown") == (
        "Result unknown — do not retry automatically"
    )
    assert operator_text(OperatorLocale.ZH_CN, "result_unknown") == (
        "结果未知——不要自动重试"
    )
    with pytest.raises(OperatorLocalizationError, match="OPERATOR_COPY_KEY_INVALID"):
        operator_text(OperatorLocale.EN_US, "not_a_copy_key")


def test_visual_role_keeps_semantics_and_color_while_localizing_copy() -> None:
    source = operator_visual(OperatorVisualRole.NEEDS_INPUT)

    english = localized_visual(OperatorLocale.EN_US, source)
    chinese = localized_visual(OperatorLocale.ZH_CN, source)

    assert english == source
    assert chinese.role is source.role
    assert chinese.color_rgb == source.color_rgb
    assert chinese.label == "需要确认"
    assert chinese.glyph == "审批"
