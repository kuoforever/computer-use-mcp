from __future__ import annotations

import pytest

from computer_use_agent.operator_visuals import (
    OperatorVisualError,
    OperatorVisualRole,
    operator_visual,
)
from computer_use_agent.decision_card_window import decision_attention_visual
from computer_use_agent.presence import (
    DesktopAuthority,
    PresencePhase,
    PresenceSnapshot,
    project_presence,
)
from computer_use_agent.progress_window import workflow_visual
from computer_use_agent.workflow_checklist import WorkflowStatus


@pytest.mark.parametrize("role", tuple(OperatorVisualRole))
def test_every_shared_operator_role_has_a_fixed_visual_token(
    role: OperatorVisualRole,
) -> None:
    token = operator_visual(role)

    assert token.role is role
    assert token.label
    assert token.glyph
    assert 0 <= token.color_rgb <= 0xFFFFFF


def test_attention_verification_and_inspection_roles_are_visually_distinct() -> None:
    attention = operator_visual(OperatorVisualRole.NEEDS_INPUT)
    verifying = operator_visual(OperatorVisualRole.VERIFYING)
    inspection = operator_visual(OperatorVisualRole.NEEDS_INSPECTION)

    assert attention.label == "Needs input"
    assert attention.color_rgb == 0xF2C94C
    assert verifying.label == "Verifying"
    assert verifying.color_rgb == 0x00A7B5
    assert inspection.label == "Needs inspection"
    assert inspection.color_rgb == 0xEB5757
    assert len(
        {attention.color_rgb, verifying.color_rgb, inspection.color_rgb}
    ) == 3


def test_unknown_visual_role_fails_closed() -> None:
    with pytest.raises(OperatorVisualError, match="OPERATOR_VISUAL_ROLE_INVALID"):
        operator_visual("needs_input")  # type: ignore[arg-type]


def test_needs_input_is_identical_across_presence_progress_and_decision() -> None:
    presence = project_presence(
        PresenceSnapshot(
            PresencePhase.WAITING_APPROVAL,
            DesktopAuthority.WAITING,
        )
    )
    progress = workflow_visual(WorkflowStatus.NEEDS_INPUT)
    decision = decision_attention_visual()

    assert presence is not None
    assert presence.visual_role == progress.role.value == decision.role.value
    assert presence.label == progress.label == decision.label == "Needs input"
    assert presence.color_rgb == progress.color_rgb == decision.color_rgb == 0xF2C94C
