"""Reviewed application-worker specifications for the evaluation matrix.

The catalog is data, not execution authority.  It gives a generic campaign
worker the stable identity dimensions, observation ladder, optional effects,
and stop states that must be enforced for each application family.  Provider
output cannot add tools, effects, or bypass states to these specifications.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from hashlib import sha256
from types import MappingProxyType
from typing import Mapping


_OBSERVATION_TOOLS = frozenset(
    {
        "list_windows",
        "ui_snapshot",
        "document_text",
        "ocr",
        "capture_region",
        "screenshot",
    }
)
_ACTION_TOOLS = frozenset({"activate_window", "click", "type", "key"})
_RISK_TIERS = frozenset({"read_only", "draft", "reversible", "external", "critical"})
_SCENARIO_ID = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}\Z")
_KIND = re.compile(r"[a-z][a-z0-9_]{0,79}\Z")

COMMON_STOP_STATES = (
    "CHALLENGE",
    "IDENTITY_DRIFT",
    "OWNERSHIP_STALE",
    "POLICY_DENIED",
    "UNKNOWN_OUTCOME",
    "HUMAN_HANDOFF_REQUIRED",
)


@dataclass(frozen=True)
class ApplicationWorkerSpec:
    """One immutable reviewed scenario contract."""

    scenario_id: str
    kind: str
    name: str
    identity_dimensions: tuple[str, ...]
    result_fields: tuple[str, ...]
    observation_ladder: tuple[str, ...]
    navigation_tools: tuple[str, ...]
    optional_effects: tuple[str, ...]
    maximum_risk: str
    capability_names: tuple[str, ...] = ()
    stop_states: tuple[str, ...] = COMMON_STOP_STATES

    def __post_init__(self) -> None:
        if (
            not isinstance(self.scenario_id, str)
            or _SCENARIO_ID.fullmatch(self.scenario_id) is None
            or not isinstance(self.kind, str)
            or _KIND.fullmatch(self.kind) is None
            or not isinstance(self.name, str)
            or not self.name
            or self.maximum_risk not in _RISK_TIERS
        ):
            raise ValueError("application worker specification is invalid")
        sequences = (
            self.identity_dimensions,
            self.result_fields,
            self.observation_ladder,
            self.stop_states,
        )
        if any(
            not isinstance(values, tuple)
            or not values
            or len(set(values)) != len(values)
            or any(not isinstance(value, str) or not value for value in values)
            for values in sequences
        ):
            raise ValueError("application worker specification is invalid")
        if (
            not isinstance(self.capability_names, tuple)
            or len(set(self.capability_names)) != len(self.capability_names)
            or any(
                not isinstance(value, str) or not value
                for value in self.capability_names
            )
        ):
            raise ValueError("application worker capability composition is invalid")
        if (
            not set(self.observation_ladder) <= _OBSERVATION_TOOLS
            or not set(self.navigation_tools) <= _ACTION_TOOLS
            or not set(self.optional_effects) <= _ACTION_TOOLS
        ):
            raise ValueError("application worker tool boundary is invalid")
        if self.optional_effects and self.maximum_risk == "read_only":
            raise ValueError("read-only worker cannot declare optional effects")


def _spec(
    scenario_id: str,
    kind: str,
    name: str,
    identities: tuple[str, ...],
    fields: tuple[str, ...],
    observations: tuple[str, ...],
    navigation: tuple[str, ...] = ("activate_window", "click", "key"),
    effects: tuple[str, ...] = (),
    risk: str = "read_only",
    stops: tuple[str, ...] = COMMON_STOP_STATES,
) -> ApplicationWorkerSpec:
    return ApplicationWorkerSpec(
        scenario_id=scenario_id,
        kind=kind,
        name=name,
        identity_dimensions=identities,
        result_fields=fields,
        observation_ladder=observations,
        navigation_tools=navigation,
        optional_effects=effects,
        maximum_risk=risk,
        stop_states=stops,
    )


APPLICATION_WORKER_SPECS = (
    _spec(
        "A1",
        "boss_saved_job_review",
        "BOSS saved-job review",
        ("account", "public_job_id"),
        ("company", "role", "location", "compensation", "experience", "classification"),
        ("ui_snapshot", "document_text", "ocr", "capture_region"),
    ),
    _spec(
        "A2",
        "google_docs_section_review",
        "Google Docs long-document review",
        ("document_id", "section_ordinal", "heading_digest"),
        ("heading", "summary", "links", "tables", "image_notes"),
        ("ui_snapshot", "document_text", "ocr", "capture_region"),
        effects=("type",),
        risk="reversible",
    ),
    _spec(
        "A3",
        "wechat_conversation_draft",
        "WeChat conversation draft",
        ("account", "conversation_alias"),
        ("conversation_title", "draft_digest", "draft_verified"),
        ("list_windows", "ui_snapshot", "ocr", "capture_region"),
        navigation=("activate_window", "click", "type", "key"),
        effects=("key",),
        risk="external",
        stops=COMMON_STOP_STATES + ("LOGIN_REQUIRED", "RECIPIENT_AMBIGUOUS"),
    ),
    _spec(
        "A4",
        "excel_virtual_grid",
        "Excel large virtualized grid",
        ("workbook_id", "sheet_name", "a1_range"),
        ("displayed_value", "formula", "format", "filter_state"),
        ("list_windows", "ui_snapshot", "document_text", "ocr", "capture_region"),
        navigation=("activate_window", "click", "type", "key"),
        effects=("type",),
        risk="reversible",
    ),
    _spec(
        "A5",
        "pdf_layout_review",
        "PDF text, scan, and layout review",
        ("document_digest", "page_number", "section_digest"),
        ("text", "reading_order", "layout_conflicts", "form_fields", "comments"),
        ("ui_snapshot", "document_text", "ocr", "capture_region", "screenshot"),
    ),
    _spec(
        "A6",
        "design_infinite_canvas",
        "Figma or Canva infinite canvas",
        ("document_id", "frame_name", "object_path"),
        ("object_type", "bounds", "text", "selection_state", "viewport"),
        ("ui_snapshot", "ocr", "capture_region", "screenshot"),
        effects=("click", "type", "key"),
        risk="reversible",
    ),
    _spec(
        "A7",
        "electron_collaboration",
        "Electron collaboration client",
        ("tenant", "channel_id", "thread_id", "message_id"),
        ("author", "timestamp", "text_digest", "draft_state"),
        ("list_windows", "ui_snapshot", "document_text", "ocr", "capture_region"),
        effects=("type", "key"),
        risk="external",
        stops=COMMON_STOP_STATES + ("EXTERNAL_RECIPIENT",),
    ),
    _spec(
        "A8",
        "realtime_media_feed",
        "Douyin real-time media and infinite feed",
        ("account", "video_id", "media_timestamp"),
        ("caption", "transcript", "playback_state", "account_identity", "content_digest"),
        ("list_windows", "ui_snapshot", "ocr", "capture_region", "screenshot"),
        effects=("click", "type", "key"),
        risk="external",
        stops=COMMON_STOP_STATES
        + ("ADVERTISEMENT", "LIVE_STREAM", "AUTOPLAY_DRIFT", "CONTENT_UNAVAILABLE"),
    ),
    _spec(
        "A9",
        "nested_remote_desktop",
        "Remote Desktop, Citrix, or VM console",
        ("host_window", "guest_identity", "guest_viewport"),
        ("frame_digest", "resolution", "latency_state", "guest_state"),
        ("list_windows", "ocr", "capture_region", "screenshot"),
        effects=("click", "type", "key"),
        risk="reversible",
        stops=COMMON_STOP_STATES + ("RECONNECTED", "RESOLUTION_DRIFT"),
    ),
    _spec(
        "A10",
        "office_mode_transition",
        "Word and PowerPoint mode transitions",
        ("document_id", "page_or_slide", "object_identity", "editor_mode"),
        ("text", "comments", "shape_state", "selection_state", "visual_digest"),
        ("list_windows", "ui_snapshot", "document_text", "ocr", "capture_region"),
        effects=("click", "type", "key"),
        risk="reversible",
    ),
    _spec(
        "A11",
        "legacy_custom_ui",
        "Legacy ERP, Java Swing, Qt, or industrial UI",
        ("application", "record_id", "view_id"),
        ("fields", "accessibility_failures", "modal_state", "visual_digest"),
        ("list_windows", "ui_snapshot", "ocr", "capture_region", "screenshot"),
        effects=("click", "type", "key"),
        risk="reversible",
    ),
    _spec(
        "A12",
        "creative_modal_editor",
        "Blender, CAD, or video editor",
        ("project_id", "workspace", "editor", "object_id", "mode"),
        ("selection", "active_tool", "change_digest", "visual_digest"),
        ("list_windows", "ui_snapshot", "ocr", "capture_region", "screenshot"),
        effects=("click", "type", "key"),
        risk="reversible",
    ),
    _spec(
        "A13",
        "system_dialog_boundary",
        "System dialog and secure-desktop boundary",
        ("parent_window", "dialog_kind", "owner_process"),
        ("dialog_state", "parent_restored", "boundary_code"),
        ("list_windows", "ui_snapshot", "ocr", "capture_region", "screenshot"),
        effects=("click", "type", "key"),
        risk="critical",
        stops=COMMON_STOP_STATES
        + ("SECURE_DESKTOP", "ELEVATION_REQUIRED", "CAPTURE_UNAVAILABLE"),
    ),
    _spec(
        "A14",
        "enterprise_incident",
        "IT incident and ticket workflow",
        ("tenant", "project", "ticket_id", "object_version"),
        ("status", "owner", "priority", "sla", "evidence", "allowed_transitions"),
        ("ui_snapshot", "document_text", "ocr", "capture_region"),
        effects=("click", "type", "key"),
        risk="external",
        stops=COMMON_STOP_STATES
        + ("MFA_REQUIRED", "PERMISSION_DENIED", "VERSION_CONFLICT", "SLA_AUTHORITY_EXPIRED"),
    ),
    _spec(
        "A15",
        "enterprise_crm",
        "CRM and customer-operations workflow",
        ("tenant", "account_id", "contact_id", "opportunity_id", "owner_id"),
        ("classification", "provenance", "duplicate_candidates", "field_changes"),
        ("ui_snapshot", "document_text", "ocr", "capture_region"),
        effects=("click", "type", "key"),
        risk="external",
        stops=COMMON_STOP_STATES + ("DUPLICATE_AMBIGUOUS", "FIELD_AUTHORITY_DENIED"),
    ),
    _spec(
        "A16",
        "enterprise_finance",
        "ERP, procurement, and finance workflow",
        ("tenant", "document_number", "supplier_id", "object_version"),
        ("currency", "amount", "tax", "cost_center", "line_items", "reconciliation"),
        ("ui_snapshot", "document_text", "ocr", "capture_region"),
        effects=("click", "type", "key"),
        risk="critical",
        stops=COMMON_STOP_STATES
        + (
            "MAKER_CHECKER_REQUIRED",
            "AMOUNT_MISMATCH",
            "DUPLICATE_INVOICE",
            "ACCOUNTING_PERIOD_CLOSED",
        ),
    ),
    _spec(
        "A17",
        "enterprise_communication",
        "Enterprise communication and scheduling",
        ("tenant", "mailbox", "thread_or_channel", "recipient_set", "revision"),
        ("recipients", "external_scope", "attachments", "timezone", "draft_digest"),
        ("list_windows", "ui_snapshot", "document_text", "ocr", "capture_region"),
        effects=("click", "type", "key"),
        risk="external",
        stops=COMMON_STOP_STATES
        + ("EXTERNAL_RECIPIENT", "LARGE_GROUP", "SENSITIVE_ATTACHMENT", "TIMEZONE_AMBIGUOUS"),
    ),
    _spec(
        "A18",
        "enterprise_bi_report",
        "BI, reporting, and internal operations portal",
        ("tenant", "report_id", "page_id", "filter_digest", "time_range"),
        ("metrics", "refresh_time", "provenance", "export_digest", "anomalies"),
        ("ui_snapshot", "document_text", "ocr", "capture_region", "screenshot"),
        effects=("click", "key"),
        risk="reversible",
        stops=COMMON_STOP_STATES + ("STALE_REPORT", "FILTER_DRIFT", "EXPORT_SCOPE_DENIED"),
    ),
    _spec(
        "A19",
        "identity_privilege_boundary",
        "SSO, tenant, and privilege boundary",
        ("identity", "tenant", "role", "session_id"),
        ("authentication_state", "tenant_state", "permissions", "boundary_code"),
        ("list_windows", "ui_snapshot", "ocr", "capture_region", "screenshot"),
        effects=("click", "type", "key"),
        risk="critical",
        stops=COMMON_STOP_STATES
        + ("SSO_REQUIRED", "MFA_REQUIRED", "TENANT_MISMATCH", "PRIVILEGE_ESCALATION_REQUIRED"),
    ),
)

APPLICATION_WORKERS_BY_KIND: Mapping[str, ApplicationWorkerSpec] = MappingProxyType(
    {spec.kind: spec for spec in APPLICATION_WORKER_SPECS}
)
APPLICATION_WORKERS_BY_SCENARIO: Mapping[str, ApplicationWorkerSpec] = MappingProxyType(
    {spec.scenario_id: spec for spec in APPLICATION_WORKER_SPECS}
)


def get_application_worker(kind: str) -> ApplicationWorkerSpec:
    try:
        return APPLICATION_WORKERS_BY_KIND[kind]
    except (KeyError, TypeError) as exc:
        raise KeyError("APPLICATION_WORKER_UNSUPPORTED") from exc


def application_worker_policy_digest(spec: ApplicationWorkerSpec) -> str:
    if not isinstance(spec, ApplicationWorkerSpec):
        raise ValueError("application worker specification is invalid")
    encoded = json.dumps(
        {
            "contract": "application-worker-policy-v1",
            "scenario_id": spec.scenario_id,
            "kind": spec.kind,
            "observation_ladder": spec.observation_ladder,
            "navigation_tools": spec.navigation_tools,
            "optional_effects": spec.optional_effects,
            "maximum_risk": spec.maximum_risk,
            "stop_states": spec.stop_states,
            "capability_names": spec.capability_names,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    return sha256(encoded).hexdigest()


def application_worker_schema_digest(spec: ApplicationWorkerSpec) -> str:
    if not isinstance(spec, ApplicationWorkerSpec):
        raise ValueError("application worker specification is invalid")
    encoded = json.dumps(
        {
            "contract": "application-worker-result-v1",
            "scenario_id": spec.scenario_id,
            "kind": spec.kind,
            "identity_dimensions": spec.identity_dimensions,
            "result_fields": spec.result_fields,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    return sha256(encoded).hexdigest()


__all__ = [
    "APPLICATION_WORKERS_BY_KIND",
    "APPLICATION_WORKERS_BY_SCENARIO",
    "APPLICATION_WORKER_SPECS",
    "ApplicationWorkerSpec",
    "COMMON_STOP_STATES",
    "application_worker_policy_digest",
    "application_worker_schema_digest",
    "get_application_worker",
]
