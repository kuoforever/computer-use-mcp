from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import computer_use_agent.approval_inbox as approval_inbox_module
from computer_use_agent.approval_inbox import (
    ApprovalAttentionLifecycle,
    ApprovalInboxError,
    ApprovalInboxStatus,
    LocalApprovalInbox,
    build_approval_inbox,
    render_approval_inbox,
)
from computer_use_agent.operator_localization import OperatorLocale
from computer_use_agent.tool_registry import REVIEWED_TOOLS
from computer_use_agent.decision_cards import (
    ApplicationClass,
    DecisionCard,
    DecisionCardRequest,
    DecisionClass,
    DecisionOptionKind,
    EvidenceKind,
    EvidenceReference,
    IntendedEffect,
    RecipientScope,
    UnknownFact,
    compile_decision_card,
)
from computer_use_agent.types import (
    ApprovalBinding,
    ApprovalRequest,
    CallIdentity,
    SafeArgumentSummary,
    ToolEffect,
)


NOW = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)
DIGESTS = tuple(f"{index:064x}" for index in range(1, 10))


def test_inbox_action_classification_covers_the_exact_reviewed_registry() -> None:
    reviewed_actions = {
        tool.name for tool in REVIEWED_TOOLS if tool.effect is ToolEffect.SIDE_EFFECT
    }

    assert set(approval_inbox_module._ACTION_LABELS) == reviewed_actions


def _request(*, tool_name: str = "click") -> ApprovalRequest:
    binding = ApprovalBinding(
        run_id="run_approval_inbox",
        state_digest=DIGESTS[0],
        policy_digest=DIGESTS[1],
        task_digest=DIGESTS[2],
        registry_digest=DIGESTS[3],
        object_digest=DIGESTS[4],
        evidence_digest=DIGESTS[5],
    )
    return ApprovalRequest(
        request_id="request_approval_inbox",
        identity=CallIdentity("run_approval_inbox", "turn_2", "call_3"),
        tool_name=tool_name,
        call_digest=DIGESTS[6],
        reason="side_effect_requires_local_approval",
        safe_argument_summary=SafeArgumentSummary(
            tool_name,
            {"ref": "private-control-ref", "x": 420, "y": 240},
        ),
        binding=binding,
    )


def _card(request: ApprovalRequest, *, expires_at: datetime | None = None) -> DecisionCard:
    assert request.binding is not None
    return compile_decision_card(
        DecisionCardRequest(
            decision_id=request.request_id,
            binding=request.binding,
            expires_at=expires_at or NOW + timedelta(minutes=3),
            decision_class=DecisionClass.EXTERNAL_EFFECT,
            application=ApplicationClass.DESKTOP,
            intended_effect=IntendedEffect.APPROVE_ONE_EXACT_EFFECT,
            recipient_scope=RecipientScope.NONE,
            evidence=(EvidenceReference(EvidenceKind.OBSERVATION, DIGESTS[5]),),
            unknown_facts=(UnknownFact.COMPLETION_OUTCOME,),
            option_kinds=(
                DecisionOptionKind.APPROVE_EXACT_EFFECT,
                DecisionOptionKind.REOBSERVE,
                DecisionOptionKind.HUMAN_TAKEOVER,
                DecisionOptionKind.DENY,
            ),
        ),
        now=NOW,
    )


class _Notifications:
    def __init__(self) -> None:
        self.shown: list[object] = []
        self.withdrawn: list[str] = []

    def show(self, notice: object) -> None:
        self.shown.append(notice)

    def withdraw(self, notice_id: str) -> None:
        self.withdrawn.append(notice_id)


def test_lifecycle_publishes_read_only_pending_item_and_removes_it(tmp_path: Path) -> None:
    state_dir = tmp_path.resolve()
    store = LocalApprovalInbox(state_dir)
    notifications = _Notifications()
    lifecycle = ApprovalAttentionLifecycle(store, notifications=notifications)
    request = _request()
    card = _card(request)

    record = lifecycle.open(request, card, opened_at=NOW)
    projection = build_approval_inbox(state_dir, now=NOW + timedelta(seconds=5))

    assert record.request_id == request.request_id
    assert len(projection.items) == 1
    assert projection.items[0].status is ApprovalInboxStatus.PENDING
    assert projection.items[0].record.action_label == "Click"
    assert projection.as_json()["capabilities"] == {
        "approve": False,
        "deny": False,
        "defer": False,
        "takeover": False,
        "dispatch": False,
    }
    assert len(notifications.shown) == 1

    lifecycle.close(request.request_id)

    assert build_approval_inbox(state_dir, now=NOW).items == ()
    assert notifications.withdrawn == [request.request_id]


def test_lifecycle_localizes_notice_without_changing_its_authority(tmp_path: Path) -> None:
    notifications = _Notifications()
    lifecycle = ApprovalAttentionLifecycle(
        LocalApprovalInbox(tmp_path.resolve()),
        notifications=notifications,
        locale=OperatorLocale.ZH_CN,
    )
    request = _request()

    lifecycle.open(request, _card(request), opened_at=NOW)

    notice = notifications.shown[0]
    assert notice.as_json() == {  # type: ignore[union-attr]
        "approval_notice_version": 1,
        "category": "approval_required",
        "title": "受保护的桌面智能体",
        "body": "需要审批。请返回已打开的决策窗口。",
        "interactive": False,
        "capabilities": {"approve": False, "deny": False, "dispatch": False},
    }


def test_record_and_notice_never_retain_argument_or_task_content(tmp_path: Path) -> None:
    state_dir = tmp_path.resolve()
    notifications = _Notifications()
    lifecycle = ApprovalAttentionLifecycle(
        LocalApprovalInbox(state_dir), notifications=notifications
    )
    request = _request()

    lifecycle.open(request, _card(request), opened_at=NOW)

    encoded = next((state_dir / "approval-inbox").glob("*.json")).read_text(
        encoding="utf-8"
    )
    assert "private-control-ref" not in encoded
    assert '"x"' not in encoded
    assert '"y"' not in encoded
    assert "safe_argument_summary" not in encoded
    notice_text = json.dumps(notifications.shown[0].as_json(), sort_keys=True)  # type: ignore[union-attr]
    for private_value in (
        request.request_id,
        request.identity.run_id,
        request.identity.turn_id,
        request.identity.call_id,
        request.tool_name,
        request.call_digest,
        "private-control-ref",
    ):
        assert private_value not in notice_text


def test_expired_and_corrupt_records_are_bounded_and_fail_closed(tmp_path: Path) -> None:
    state_dir = tmp_path.resolve()
    store = LocalApprovalInbox(state_dir)
    request = _request()
    store.open(request, _card(request), opened_at=NOW)
    inbox_dir = state_dir / "approval-inbox"
    (inbox_dir / "corrupt.json").write_text('{"unexpected":true}\n', encoding="utf-8")

    projection = build_approval_inbox(
        state_dir,
        now=NOW + timedelta(minutes=4),
    )

    assert len(projection.items) == 1
    assert projection.items[0].status is ApprovalInboxStatus.EXPIRED
    assert projection.unavailable_records == 1
    assert "cannot approve" in render_approval_inbox(projection).lower()
    assert "Expired" in render_approval_inbox(projection)


def test_empty_projection_does_not_create_state(tmp_path: Path) -> None:
    state_dir = tmp_path.resolve()

    projection = build_approval_inbox(state_dir, now=NOW)

    assert projection.items == ()
    assert projection.unavailable_records == 0
    assert not (state_dir / "approval-inbox").exists()


def test_store_rejects_mismatched_card_and_unknown_action(tmp_path: Path) -> None:
    store = LocalApprovalInbox(tmp_path.resolve())
    request = _request()
    mismatched = replace(request, request_id="other_request")
    other = _request(tool_name="unreviewed_action")

    with pytest.raises(ApprovalInboxError, match="APPROVAL_INBOX_BINDING_MISMATCH"):
        store.open(request, _card(mismatched), opened_at=NOW)

    with pytest.raises(ApprovalInboxError, match="APPROVAL_INBOX_ACTION_UNSUPPORTED"):
        store.open(other, _card(other), opened_at=NOW)
