"""Read-only L0 normalized outcomes and explicit-coverage cost vectors.

This module derives only from the existing redacted Full Cycle run record and,
when requested, one exact durable campaign item. It creates no log, export,
candidate, routing decision, provider call, or execution authority.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, fields
from enum import Enum
from pathlib import Path
from typing import Mapping

from .campaign import (
    CAMPAIGN_VERSION,
    CampaignStatus,
    CampaignStore,
    ItemStatus,
)
from .fullcycle_export import (
    FULLCYCLE_TRAINING_USE,
    build_fullcycle_run_export,
    canonical_json_bytes,
)
from .tool_registry import REVIEWED_TOOLS
from .trace import RunPhase, TERMINAL_PHASES
from .types import JSONValue, ToolEffect


EPISODE_OUTCOME_VERSION = 1
EPISODE_DATA_CLASS = "redacted_normalized_episode_outcome"
EPISODE_USE = "offline_evaluation_only"
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,127}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_SIDE_EFFECT_TOOLS = frozenset(
    tool.name for tool in REVIEWED_TOOLS if tool.effect is ToolEffect.SIDE_EFFECT
)
_REVIEWED_TOOLS = frozenset(tool.name for tool in REVIEWED_TOOLS)
_CAMPAIGN_EPISODE_STATUSES = frozenset(
    {
        ItemStatus.COMMITTED,
        ItemStatus.RETRYABLE,
        ItemStatus.SKIPPED,
        ItemStatus.CHALLENGE,
        ItemStatus.UNCERTAIN,
    }
)


class EpisodeOutcomeError(ValueError):
    """Fixed content-free L0 validation or reconciliation failure."""


class EpisodeOutcomeLabel(str, Enum):
    VERIFIED_SUCCESS = "VERIFIED_SUCCESS"
    VERIFIED_FAILURE = "VERIFIED_FAILURE"
    CHALLENGED = "CHALLENGED"
    CONFLICTED = "CONFLICTED"
    UNCERTAIN = "UNCERTAIN"
    CANCELLED = "CANCELLED"


class MetricCoverage(str, Enum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    MISSING = "missing"


class ExternalEffectEvidence(str, Enum):
    NONE = "none"
    VERIFIED_COMMITTED = "verified_committed"
    UNKNOWN = "unknown"


def _require_nonnegative(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise EpisodeOutcomeError("EPISODE_INVALID")
    return value


def _require_identifier(value: object) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise EpisodeOutcomeError("EPISODE_INVALID")
    return value


def _require_digest(value: object) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise EpisodeOutcomeError("EPISODE_INVALID")
    return value


@dataclass(frozen=True)
class CostMetric:
    """One value whose missing portion can never masquerade as zero."""

    value: int | None
    observed: int
    coverage: MetricCoverage

    def __post_init__(self) -> None:
        _require_nonnegative(self.observed)
        if not isinstance(self.coverage, MetricCoverage):
            raise EpisodeOutcomeError("EPISODE_COST_INVALID")
        if self.coverage is MetricCoverage.COMPLETE:
            if self.value != self.observed:
                raise EpisodeOutcomeError("EPISODE_COST_INVALID")
        elif self.value is not None:
            raise EpisodeOutcomeError("EPISODE_COST_INVALID")
        if self.coverage is MetricCoverage.MISSING and self.observed != 0:
            raise EpisodeOutcomeError("EPISODE_COST_INVALID")

    def to_payload(self) -> dict[str, JSONValue]:
        return {
            "value": self.value,
            "observed": self.observed,
            "coverage": self.coverage.value,
        }


def _complete(value: int) -> CostMetric:
    return CostMetric(value=value, observed=value, coverage=MetricCoverage.COMPLETE)


def _reported_metric(observed: int, *, reported: int, expected: int) -> CostMetric:
    if reported == expected:
        return _complete(observed)
    if reported == 0:
        return CostMetric(value=None, observed=0, coverage=MetricCoverage.MISSING)
    return CostMetric(value=None, observed=observed, coverage=MetricCoverage.PARTIAL)


def _missing() -> CostMetric:
    return CostMetric(value=None, observed=0, coverage=MetricCoverage.MISSING)


@dataclass(frozen=True)
class EpisodeCostVector:
    """Fixed L0 vector; every dimension is present with explicit coverage."""

    model_calls: CostMetric
    tool_calls: CostMetric
    side_effects: CostMetric
    search_calls: CostMetric
    input_tokens: CostMetric
    output_tokens: CostMetric
    observation_events: CostMetric
    tool_result_text_characters: CostMetric
    image_results: CostMetric
    screenshot_results: CostMetric
    ocr_calls: CostMetric
    provider_latency_ms: CostMetric
    tool_latency_ms: CostMetric
    run_duration_ms: CostMetric
    retry_count: CostMetric
    recovery_events: CostMetric
    approval_requests: CostMetric
    policy_denials: CostMetric
    reobserve_requests: CostMetric
    defer_requests: CostMetric
    takeover_requests: CostMetric
    tool_failures: CostMetric
    human_takeover_ms: CostMetric
    human_corrections: CostMetric
    e_stop_activations: CostMetric

    def __post_init__(self) -> None:
        if not all(isinstance(getattr(self, item.name), CostMetric) for item in fields(self)):
            raise EpisodeOutcomeError("EPISODE_COST_INVALID")

    def to_payload(self) -> dict[str, JSONValue]:
        return {
            item.name: getattr(self, item.name).to_payload()
            for item in fields(self)
        }

    @property
    def missing_metrics(self) -> tuple[str, ...]:
        return tuple(
            item.name
            for item in fields(self)
            if getattr(self, item.name).coverage is MetricCoverage.MISSING
        )

    @property
    def partial_metrics(self) -> tuple[str, ...]:
        return tuple(
            item.name
            for item in fields(self)
            if getattr(self, item.name).coverage is MetricCoverage.PARTIAL
        )


@dataclass(frozen=True)
class CampaignEpisodeEvidence:
    """One exact durable campaign item without its key or content digest."""

    campaign_id: str
    campaign_status: CampaignStatus
    policy_digest: str
    schema_digest: str
    item_ordinal: int
    item_sequence: int
    item_status: ItemStatus
    item_attempt: int
    item_code: str | None
    campaign_version: int = CAMPAIGN_VERSION

    def __post_init__(self) -> None:
        _require_identifier(self.campaign_id)
        if self.campaign_version != CAMPAIGN_VERSION:
            raise EpisodeOutcomeError("EPISODE_CAMPAIGN_INVALID")
        if not isinstance(self.campaign_status, CampaignStatus):
            raise EpisodeOutcomeError("EPISODE_CAMPAIGN_INVALID")
        _require_digest(self.policy_digest)
        _require_digest(self.schema_digest)
        if self.item_ordinal <= 0 or self.item_sequence <= 0 or self.item_attempt < 0:
            raise EpisodeOutcomeError("EPISODE_CAMPAIGN_INVALID")
        if self.item_status not in _CAMPAIGN_EPISODE_STATUSES:
            raise EpisodeOutcomeError("EPISODE_CAMPAIGN_INCOMPLETE")
        if self.item_code is not None and _CODE.fullmatch(self.item_code) is None:
            raise EpisodeOutcomeError("EPISODE_CAMPAIGN_INVALID")

    def to_payload(self) -> dict[str, JSONValue]:
        return {
            "campaign_version": self.campaign_version,
            "campaign_id": self.campaign_id,
            "campaign_status": self.campaign_status.value,
            "policy_digest": self.policy_digest,
            "schema_digest": self.schema_digest,
            "item_ordinal": self.item_ordinal,
            "item_sequence": self.item_sequence,
            "item_status": self.item_status.value,
            "item_attempt": self.item_attempt,
            "item_code": self.item_code,
        }


@dataclass(frozen=True)
class EpisodeOutcome:
    """One normalized L0 record with no raw episode content or authority."""

    episode_id: str
    run_id: str
    source_record_digest: str
    manifest_digest: str
    checkpoint_sequence: int
    outcome: EpisodeOutcomeLabel
    run_phase: RunPhase
    failure_code: str | None
    verified_observation_epoch: int | None
    external_effect: ExternalEffectEvidence
    costs: EpisodeCostVector
    campaign: CampaignEpisodeEvidence | None = None
    episode_version: int = EPISODE_OUTCOME_VERSION

    def __post_init__(self) -> None:
        if self.episode_version != EPISODE_OUTCOME_VERSION:
            raise EpisodeOutcomeError("EPISODE_INVALID")
        _require_digest(self.episode_id)
        _require_identifier(self.run_id)
        _require_digest(self.source_record_digest)
        if (
            not isinstance(self.manifest_digest, str)
            or not self.manifest_digest.startswith("sha256:")
            or _DIGEST.fullmatch(self.manifest_digest[7:]) is None
        ):
            raise EpisodeOutcomeError("EPISODE_INVALID")
        if self.checkpoint_sequence <= 0:
            raise EpisodeOutcomeError("EPISODE_INVALID")
        if not isinstance(self.outcome, EpisodeOutcomeLabel):
            raise EpisodeOutcomeError("EPISODE_INVALID")
        if not isinstance(self.run_phase, RunPhase) or self.run_phase not in TERMINAL_PHASES:
            raise EpisodeOutcomeError("EPISODE_INVALID")
        if self.failure_code is not None and _CODE.fullmatch(self.failure_code) is None:
            raise EpisodeOutcomeError("EPISODE_INVALID")
        if self.verified_observation_epoch is not None:
            _require_nonnegative(self.verified_observation_epoch)
        if not isinstance(self.external_effect, ExternalEffectEvidence):
            raise EpisodeOutcomeError("EPISODE_INVALID")
        if not isinstance(self.costs, EpisodeCostVector):
            raise EpisodeOutcomeError("EPISODE_INVALID")
        if self.campaign is not None and not isinstance(
            self.campaign, CampaignEpisodeEvidence
        ):
            raise EpisodeOutcomeError("EPISODE_INVALID")

    def to_payload(self) -> dict[str, JSONValue]:
        return {
            "episode_outcome_version": self.episode_version,
            "episode_id": self.episode_id,
            "run_id": self.run_id,
            "source_record_digest": self.source_record_digest,
            "manifest_digest": self.manifest_digest,
            "checkpoint_sequence": self.checkpoint_sequence,
            "outcome": self.outcome.value,
            "run_phase": self.run_phase.value,
            "failure_code": self.failure_code,
            "verified_observation_epoch": self.verified_observation_epoch,
            "external_effect": self.external_effect.value,
            "outcome_scope": "run" if self.campaign is None else "campaign_item",
            "cost_scope": "run",
            "costs": self.costs.to_payload(),
            "missing_metrics": list(self.costs.missing_metrics),
            "partial_metrics": list(self.costs.partial_metrics),
            "campaign": None if self.campaign is None else self.campaign.to_payload(),
            "data_class": EPISODE_DATA_CLASS,
            "use": EPISODE_USE,
            "source_training_use": FULLCYCLE_TRAINING_USE,
            "privacy": {
                "contains_raw_task": False,
                "contains_model_text": False,
                "contains_tool_result_text": False,
                "contains_images": False,
                "contains_memory": False,
                "contains_continuation": False,
                "contains_campaign_item_key": False,
                "contains_campaign_content_digest": False,
            },
            "authority": {
                "can_dispatch": False,
                "can_approve": False,
                "can_retry": False,
                "can_replay": False,
                "can_route": False,
                "can_promote": False,
            },
        }


def _event_objects(export: Mapping[str, JSONValue]) -> tuple[dict[str, JSONValue], ...]:
    raw = export.get("events")
    if not isinstance(raw, list) or not all(isinstance(event, dict) for event in raw):
        raise EpisodeOutcomeError("EPISODE_SOURCE_INVALID")
    return tuple(event for event in raw if isinstance(event, dict))


def _build_costs(
    checkpoint: Mapping[str, JSONValue], events: tuple[dict[str, JSONValue], ...]
) -> EpisodeCostVector:
    budgets = checkpoint.get("budgets")
    metrics = checkpoint.get("metrics")
    if not isinstance(budgets, dict) or not isinstance(metrics, dict):
        raise EpisodeOutcomeError("EPISODE_SOURCE_INVALID")

    model_events = tuple(event for event in events if event.get("kind") == "model_turn")
    tool_calls = tuple(event for event in events if event.get("kind") == "tool_call")
    tool_results = tuple(event for event in events if event.get("kind") == "tool_result")
    observations = tuple(event for event in events if event.get("kind") == "observation")
    recoveries = tuple(event for event in events if event.get("kind") == "recovery")
    decisions = tuple(event for event in events if event.get("kind") == "policy_decision")

    model_count = len(model_events)
    tool_count = len(tool_calls)
    model_budget = _require_nonnegative(budgets.get("model_turns_used"))
    tool_budget = _require_nonnegative(budgets.get("tool_calls_used"))
    side_effects = _require_nonnegative(budgets.get("side_effects_used"))
    input_budget = _require_nonnegative(budgets.get("input_tokens_used"))
    maximum_pairs = (
        (model_budget, _require_nonnegative(budgets.get("max_model_turns"))),
        (tool_budget, _require_nonnegative(budgets.get("max_tool_calls"))),
        (side_effects, _require_nonnegative(budgets.get("max_side_effects"))),
    )
    if (
        any(used > maximum for used, maximum in maximum_pairs)
        or side_effects > tool_budget
        or _require_nonnegative(metrics.get("model_calls")) != model_budget
        or model_count != model_budget
        or _require_nonnegative(metrics.get("tool_calls")) != tool_budget
        or tool_count != tool_budget
    ):
        raise EpisodeOutcomeError("EPISODE_COST_RECONCILIATION_FAILED")

    for event in (*tool_calls, *tool_results):
        tool_name = event.get("tool")
        if not isinstance(tool_name, str) or tool_name not in _REVIEWED_TOOLS:
            raise EpisodeOutcomeError("EPISODE_SOURCE_INVALID")
    for event in observations:
        tool_name = event.get("tool")
        if not isinstance(tool_name, str) or tool_name not in _REVIEWED_TOOLS:
            raise EpisodeOutcomeError("EPISODE_SOURCE_INVALID")
        _require_nonnegative(event.get("observation_epoch"))
    allowed_decisions = {
        "allow",
        "deny",
        "approval_required",
        "reobserve",
        "defer",
        "takeover",
    }
    if any(event.get("decision") not in allowed_decisions for event in decisions):
        raise EpisodeOutcomeError("EPISODE_SOURCE_INVALID")

    input_observed = 0
    output_observed = 0
    usage_reports = 0
    provider_latency_observed = 0
    provider_latency_reports = 0
    for event in model_events:
        input_value = event.get("input_tokens")
        output_value = event.get("output_tokens")
        if (
            not isinstance(input_value, bool)
            and isinstance(input_value, int)
            and input_value >= 0
            and not isinstance(output_value, bool)
            and isinstance(output_value, int)
            and output_value >= 0
        ):
            usage_reports += 1
            input_observed += input_value
            output_observed += output_value
        latency = _require_nonnegative(event.get("latency_ms"))
        provider_latency_observed += latency
        provider_latency_reports += int(latency > 0)

    text_characters = sum(
        _require_nonnegative(event.get("text_length")) for event in tool_results
    )
    image_results = sum(
        _require_nonnegative(event.get("image_count")) for event in tool_results
    )
    screenshot_results = sum(
        event.get("tool") == "screenshot" and event.get("status") == "success"
        for event in tool_results
    )
    tool_failures = sum(event.get("status") != "success" for event in tool_results)
    tool_latency_observed = 0
    tool_latency_reports = 0
    for event in tool_results:
        if "latency_ms" in event:
            tool_latency_observed += _require_nonnegative(event.get("latency_ms"))
            tool_latency_reports += 1

    allowed_results = {
        ("success", "dispatched"),
        ("action_error", "dispatched"),
        ("transport_error", "not_dispatched"),
        ("rejected", "not_dispatched"),
        ("unknown_outcome", "dispatched"),
        ("unknown_outcome", "unknown"),
    }
    if any(
        (event.get("status"), event.get("dispatch")) not in allowed_results
        for event in tool_results
    ):
        raise EpisodeOutcomeError("EPISODE_SOURCE_INVALID")

    expected_metrics = {
        "input_tokens": input_observed,
        "output_tokens": output_observed,
        "provider_latency_ms": provider_latency_observed,
        "tool_latency_ms": tool_latency_observed,
        "tool_failures": tool_failures,
        "image_results": image_results,
        "screenshot_results": screenshot_results,
        "provider_usage_report_count": usage_reports,
    }
    if any(
        _require_nonnegative(metrics.get(name)) != value
        for name, value in expected_metrics.items()
    ) or input_budget != input_observed:
        raise EpisodeOutcomeError("EPISODE_COST_RECONCILIATION_FAILED")

    retry_count = _require_nonnegative(metrics.get("retry_count"))
    duration = metrics.get("run_duration_ms")
    duration_metric = (
        _missing() if duration is None else _complete(_require_nonnegative(duration))
    )
    policy_counts = {
        decision: sum(event.get("decision") == decision for event in decisions)
        for decision in (
            "approval_required",
            "deny",
            "reobserve",
            "defer",
            "takeover",
        )
    }
    return EpisodeCostVector(
        model_calls=_complete(model_count),
        tool_calls=_complete(tool_count),
        side_effects=_complete(side_effects),
        search_calls=_complete(sum(event.get("tool") == "find" for event in tool_calls)),
        input_tokens=_reported_metric(
            input_observed, reported=usage_reports, expected=model_count
        ),
        output_tokens=_reported_metric(
            output_observed, reported=usage_reports, expected=model_count
        ),
        observation_events=_complete(len(observations)),
        tool_result_text_characters=_complete(text_characters),
        image_results=_complete(image_results),
        screenshot_results=_complete(screenshot_results),
        ocr_calls=_complete(sum(event.get("tool") == "ocr" for event in tool_calls)),
        provider_latency_ms=_reported_metric(
            provider_latency_observed,
            reported=provider_latency_reports,
            expected=model_count,
        ),
        tool_latency_ms=_reported_metric(
            tool_latency_observed,
            reported=tool_latency_reports,
            expected=tool_count,
        ),
        run_duration_ms=duration_metric,
        retry_count=_complete(retry_count),
        recovery_events=_complete(len(recoveries)),
        approval_requests=_complete(policy_counts["approval_required"]),
        policy_denials=_complete(policy_counts["deny"]),
        reobserve_requests=_complete(policy_counts["reobserve"]),
        defer_requests=_complete(policy_counts["defer"]),
        takeover_requests=_complete(policy_counts["takeover"]),
        tool_failures=_complete(tool_failures),
        human_takeover_ms=_missing(),
        human_corrections=_missing(),
        e_stop_activations=_missing(),
    )


def _external_effect(
    checkpoint: Mapping[str, JSONValue], events: tuple[dict[str, JSONValue], ...]
) -> ExternalEffectEvidence:
    budgets = checkpoint.get("budgets")
    if not isinstance(budgets, dict):
        raise EpisodeOutcomeError("EPISODE_SOURCE_INVALID")
    used = _require_nonnegative(budgets.get("side_effects_used"))
    if used == 0:
        return ExternalEffectEvidence.NONE
    relevant = tuple(
        event
        for event in events
        if event.get("kind") == "tool_result"
        and event.get("tool") in _SIDE_EFFECT_TOOLS
    )
    if any(
        event.get("status") == "unknown_outcome"
        or (
            event.get("dispatch") in {"dispatched", "unknown"}
            and event.get("status") != "success"
        )
        for event in relevant
    ):
        return ExternalEffectEvidence.UNKNOWN
    successes = sum(event.get("status") == "success" for event in relevant)
    if successes == used:
        return ExternalEffectEvidence.VERIFIED_COMMITTED
    return ExternalEffectEvidence.UNKNOWN


def _base_outcome(phase: RunPhase) -> EpisodeOutcomeLabel:
    return {
        RunPhase.SUCCESS: EpisodeOutcomeLabel.VERIFIED_SUCCESS,
        RunPhase.FAILED: EpisodeOutcomeLabel.VERIFIED_FAILURE,
        RunPhase.UNKNOWN_OUTCOME: EpisodeOutcomeLabel.UNCERTAIN,
        RunPhase.CANCELLED: EpisodeOutcomeLabel.CANCELLED,
    }[phase]


def _reconcile_campaign_outcome(
    base: EpisodeOutcomeLabel, evidence: CampaignEpisodeEvidence
) -> EpisodeOutcomeLabel:
    desired = {
        ItemStatus.COMMITTED: EpisodeOutcomeLabel.VERIFIED_SUCCESS,
        ItemStatus.RETRYABLE: EpisodeOutcomeLabel.VERIFIED_FAILURE,
        ItemStatus.SKIPPED: EpisodeOutcomeLabel.VERIFIED_FAILURE,
        ItemStatus.CHALLENGE: EpisodeOutcomeLabel.CHALLENGED,
        ItemStatus.UNCERTAIN: EpisodeOutcomeLabel.UNCERTAIN,
    }[evidence.item_status]
    if base is desired:
        return desired
    if desired is EpisodeOutcomeLabel.CHALLENGED and base in {
        EpisodeOutcomeLabel.VERIFIED_SUCCESS,
        EpisodeOutcomeLabel.VERIFIED_FAILURE,
    }:
        return desired
    if desired is EpisodeOutcomeLabel.VERIFIED_FAILURE and base in {
        EpisodeOutcomeLabel.VERIFIED_SUCCESS,
        EpisodeOutcomeLabel.VERIFIED_FAILURE,
    }:
        return desired
    return EpisodeOutcomeLabel.CONFLICTED


def _campaign_evidence(
    store: CampaignStore,
    *,
    campaign_id: str,
    item_ordinal: int,
    run_id: str,
) -> CampaignEpisodeEvidence:
    manifest = store.read_manifest(campaign_id)
    projection = store.read_ledger(campaign_id)
    matches = tuple(
        item for item in projection.items.values() if item.ordinal == item_ordinal
    )
    if len(matches) != 1:
        raise EpisodeOutcomeError("EPISODE_CAMPAIGN_ITEM_MISSING")
    item = matches[0]
    if item.status not in _CAMPAIGN_EPISODE_STATUSES:
        raise EpisodeOutcomeError("EPISODE_CAMPAIGN_INCOMPLETE")
    if item.run_id != run_id:
        raise EpisodeOutcomeError("EPISODE_CAMPAIGN_RUN_MISMATCH")
    return CampaignEpisodeEvidence(
        campaign_id=manifest.campaign_id,
        campaign_status=manifest.status,
        policy_digest=manifest.policy_digest,
        schema_digest=manifest.schema_digest,
        item_ordinal=item.ordinal,
        item_sequence=item.sequence,
        item_status=item.status,
        item_attempt=item.attempt,
        item_code=item.code,
    )


def build_episode_outcome(
    state_dir: Path,
    run_id: str,
    *,
    campaign_store: CampaignStore | None = None,
    campaign_id: str | None = None,
    item_ordinal: int | None = None,
) -> EpisodeOutcome:
    """Read and normalize one terminal redacted run, optionally one item."""

    supplied = (
        campaign_store is not None,
        campaign_id is not None,
        item_ordinal is not None,
    )
    if any(supplied) and not all(supplied):
        raise EpisodeOutcomeError("EPISODE_CAMPAIGN_INPUT_INVALID")
    if item_ordinal is not None and (
        isinstance(item_ordinal, bool)
        or not isinstance(item_ordinal, int)
        or item_ordinal <= 0
    ):
        raise EpisodeOutcomeError("EPISODE_CAMPAIGN_INPUT_INVALID")
    if not isinstance(state_dir, Path) or not state_dir.is_absolute():
        raise EpisodeOutcomeError("EPISODE_SOURCE_INVALID")
    _require_identifier(run_id)

    export = build_fullcycle_run_export(state_dir, run_id)
    checkpoint = export.get("checkpoint")
    if not isinstance(checkpoint, dict):
        raise EpisodeOutcomeError("EPISODE_SOURCE_INVALID")
    try:
        phase = RunPhase(checkpoint.get("phase"))
    except ValueError as exc:
        raise EpisodeOutcomeError("EPISODE_SOURCE_INVALID") from exc
    if phase not in TERMINAL_PHASES:
        raise EpisodeOutcomeError("EPISODE_RUN_INCOMPLETE")
    checkpoint_sequence = _require_nonnegative(checkpoint.get("checkpoint_sequence"))
    if checkpoint_sequence == 0:
        raise EpisodeOutcomeError("EPISODE_SOURCE_INVALID")
    failure_code = checkpoint.get("failure_code")
    if failure_code is not None and (
        not isinstance(failure_code, str) or _CODE.fullmatch(failure_code) is None
    ):
        raise EpisodeOutcomeError("EPISODE_SOURCE_INVALID")
    verified_epoch = checkpoint.get("verified_observation_epoch")
    if verified_epoch is not None:
        verified_epoch = _require_nonnegative(verified_epoch)

    events = _event_objects(export)
    costs = _build_costs(checkpoint, events)
    campaign: CampaignEpisodeEvidence | None = None
    if campaign_store is not None and campaign_id is not None and item_ordinal is not None:
        if campaign_store.state_dir != state_dir:
            raise EpisodeOutcomeError("EPISODE_CAMPAIGN_SOURCE_MISMATCH")
        campaign = _campaign_evidence(
            campaign_store,
            campaign_id=campaign_id,
            item_ordinal=item_ordinal,
            run_id=run_id,
        )

    outcome = _base_outcome(phase)
    if campaign is not None:
        outcome = _reconcile_campaign_outcome(outcome, campaign)
    record_digest = hashlib.sha256(canonical_json_bytes(export)).hexdigest()
    source_identity: dict[str, JSONValue] = {
        "episode_outcome_version": EPISODE_OUTCOME_VERSION,
        "run_id": run_id,
        "source_record_digest": record_digest,
        "checkpoint_sequence": checkpoint_sequence,
        "campaign": None if campaign is None else campaign.to_payload(),
    }
    episode_id = hashlib.sha256(canonical_json_bytes(source_identity)).hexdigest()
    manifest_digest = export.get("manifest_digest")
    if not isinstance(manifest_digest, str):
        raise EpisodeOutcomeError("EPISODE_SOURCE_INVALID")
    return EpisodeOutcome(
        episode_id=episode_id,
        run_id=run_id,
        source_record_digest=record_digest,
        manifest_digest=manifest_digest,
        checkpoint_sequence=checkpoint_sequence,
        outcome=outcome,
        run_phase=phase,
        failure_code=failure_code,
        verified_observation_epoch=verified_epoch,
        external_effect=_external_effect(checkpoint, events),
        costs=costs,
        campaign=campaign,
    )


__all__ = [
    "EPISODE_DATA_CLASS",
    "EPISODE_OUTCOME_VERSION",
    "EPISODE_USE",
    "CampaignEpisodeEvidence",
    "CostMetric",
    "EpisodeCostVector",
    "EpisodeOutcome",
    "EpisodeOutcomeError",
    "EpisodeOutcomeLabel",
    "ExternalEffectEvidence",
    "MetricCoverage",
    "build_episode_outcome",
]
