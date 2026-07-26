"""Registered campaign workers selected only from durable manifest state.

This module is the generic execution shell around application-specific
campaign workers.  Callers provide only a campaign ID and run ID; the durable
manifest selects a reviewed worker.  A worker still has to validate the exact
claim, policy/schema digests, ownership, evidence, and handoff at its own
boundary.

The registry deliberately contains no fallback, free-form item selector, URL,
tool name, or task text.  Unsupported campaign kinds fail closed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Awaitable, Callable, Mapping

from .application_worker_catalog import ApplicationWorkerSpec
from .campaign import CampaignStore, CampaignStoreError
from .run_lock import RunLock, RunLockError
from .runner import AgentRunner


class CampaignWorkerError(RuntimeError):
    """Fixed failure from registered campaign-worker routing."""


StartWorker = Callable[..., object]
ExecuteWorker = Callable[..., Awaitable[object]]
ResumeWorker = Callable[..., object]
SummarizeWorker = Callable[[object], Mapping[str, object]]


@dataclass(frozen=True)
class CampaignWorker:
    """One reviewed worker implementation for an exact manifest kind."""

    kind: str
    start: StartWorker
    execute: ExecuteWorker
    resume: ResumeWorker
    summarize_start: SummarizeWorker
    summarize_execute: SummarizeWorker
    summarize_resume: SummarizeWorker
    provider_required: bool = False

    def __post_init__(self) -> None:
        if (
            not isinstance(self.kind, str)
            or not self.kind
            or len(self.kind) > 80
            or not all(character.islower() or character.isdigit() or character == "_"
                       for character in self.kind)
        ):
            raise ValueError("campaign worker kind is invalid")
        callbacks = (
            self.start,
            self.execute,
            self.resume,
            self.summarize_start,
            self.summarize_execute,
            self.summarize_resume,
        )
        if not all(callable(callback) for callback in callbacks):
            raise ValueError("campaign worker callbacks are invalid")
        if not isinstance(self.provider_required, bool):
            raise ValueError("campaign worker provider boundary is invalid")


class CampaignWorkerRegistry:
    """Immutable, duplicate-refusing registry of reviewed campaign workers."""

    def __init__(self, workers: tuple[CampaignWorker, ...]) -> None:
        if not isinstance(workers, tuple) or not workers:
            raise ValueError("workers must be a non-empty tuple")
        resolved: dict[str, CampaignWorker] = {}
        for worker in workers:
            if not isinstance(worker, CampaignWorker) or worker.kind in resolved:
                raise ValueError("campaign workers are invalid")
            resolved[worker.kind] = worker
        self._workers: Mapping[str, CampaignWorker] = MappingProxyType(resolved)

    @property
    def kinds(self) -> tuple[str, ...]:
        return tuple(sorted(self._workers))

    def resolve(self, kind: str) -> CampaignWorker:
        try:
            return self._workers[kind]
        except (KeyError, TypeError) as exc:
            raise CampaignWorkerError("CAMPAIGN_WORKER_KIND_UNSUPPORTED") from exc


@dataclass(frozen=True)
class CampaignWorkerResult:
    """Safe operation summary plus the application-specific internal outcome."""

    campaign_kind: str
    operation: str
    summary: Mapping[str, object]
    outcome: object


def _manifest_kind(runner: AgentRunner, campaign_id: str) -> str:
    if (
        not isinstance(runner, AgentRunner)
        or not isinstance(campaign_id, str)
        or not campaign_id
    ):
        raise CampaignWorkerError("CAMPAIGN_WORKER_INPUT_INVALID")
    lock = RunLock(runner.config.application_state_dir)
    try:
        lock.acquire()
        store = CampaignStore(runner.config.state_dir, lock)
        return store.read_manifest(campaign_id).kind
    except (CampaignStoreError, RunLockError, OSError, ValueError) as exc:
        raise CampaignWorkerError("CAMPAIGN_WORKER_STATE_INVALID") from exc
    finally:
        lock.release()


def resolve_campaign_worker(
    runner: AgentRunner,
    *,
    campaign_id: str,
    registry: CampaignWorkerRegistry | None = None,
) -> CampaignWorker:
    """Resolve only the reviewed worker selected by durable manifest state."""

    return (registry or default_campaign_worker_registry()).resolve(
        _manifest_kind(runner, campaign_id)
    )


def _result(
    worker: CampaignWorker,
    *,
    operation: str,
    outcome: object,
    summarize: SummarizeWorker,
) -> CampaignWorkerResult:
    try:
        summary = dict(summarize(outcome))
    except (TypeError, ValueError, AttributeError, KeyError) as exc:
        raise CampaignWorkerError("CAMPAIGN_WORKER_SUMMARY_INVALID") from exc
    if (
        not summary
        or any(not isinstance(key, str) or not key for key in summary)
        or any(isinstance(value, (bytes, bytearray)) for value in summary.values())
    ):
        raise CampaignWorkerError("CAMPAIGN_WORKER_SUMMARY_INVALID")
    return CampaignWorkerResult(
        campaign_kind=worker.kind,
        operation=operation,
        summary=MappingProxyType(summary),
        outcome=outcome,
    )


def start_campaign_batch(
    runner: AgentRunner,
    *,
    campaign_id: str,
    run_id: str,
    now: datetime,
    registry: CampaignWorkerRegistry | None = None,
) -> CampaignWorkerResult:
    """Start the registered worker selected by the durable manifest."""

    selected = resolve_campaign_worker(
        runner,
        campaign_id=campaign_id,
        registry=registry,
    )
    outcome = selected.start(
        runner,
        campaign_id=campaign_id,
        run_id=run_id,
        now=now,
    )
    return _result(
        selected,
        operation="start",
        outcome=outcome,
        summarize=selected.summarize_start,
    )


async def execute_claimed_campaign_item(
    runner: AgentRunner,
    *,
    campaign_id: str,
    run_id: str,
    now: datetime,
    registry: CampaignWorkerRegistry | None = None,
) -> CampaignWorkerResult:
    """Execute only the exact durable claim through its registered worker."""

    selected = resolve_campaign_worker(
        runner,
        campaign_id=campaign_id,
        registry=registry,
    )
    outcome = await selected.execute(
        runner,
        campaign_id=campaign_id,
        run_id=run_id,
        now=now,
    )
    return _result(
        selected,
        operation="execute",
        outcome=outcome,
        summarize=selected.summarize_execute,
    )


def resume_campaign_batch(
    runner: AgentRunner,
    *,
    campaign_id: str,
    replacement_run_id: str,
    now: datetime,
    registry: CampaignWorkerRegistry | None = None,
) -> CampaignWorkerResult:
    """Resume the registered worker without accepting an item selector."""

    selected = resolve_campaign_worker(
        runner,
        campaign_id=campaign_id,
        registry=registry,
    )
    outcome = selected.resume(
        runner,
        campaign_id=campaign_id,
        replacement_run_id=replacement_run_id,
        now=now,
    )
    return _result(
        selected,
        operation="resume",
        outcome=outcome,
        summarize=selected.summarize_resume,
    )


def _boss_worker() -> CampaignWorker:
    from .boss_campaign_batch_runtime import (
        BossCampaignBatchStartOutcome,
        start_boss_read_only_batch,
    )
    from .boss_campaign_discovery import BOSS_CAMPAIGN_KIND
    from .boss_campaign_item_runtime import (
        BossCampaignItemHandoffOutcome,
        execute_claimed_boss_identity_through_handoff,
    )
    from .boss_campaign_restart_runtime import (
        BossCampaignRestartOutcome,
        resume_finished_boss_batch_after_restart,
    )

    def summarize_start(value: object) -> Mapping[str, object]:
        if not isinstance(value, BossCampaignBatchStartOutcome):
            raise TypeError("unexpected BOSS start outcome")
        return {
            "batch_id": value.batch_id,
            "campaign_id": value.campaign_id,
            "claimed_item_ordinal": value.claimed_item_ordinal,
            "discovered_count": value.discovered_count,
            "discovery_pass_count": value.discovery_pass_count,
            "lease_expires_at": value.lease_expires_at,
            "planned_item_count": value.planned_item_count,
            "run_id": value.run_id,
        }

    def summarize_execute(value: object) -> Mapping[str, object]:
        if not isinstance(value, BossCampaignItemHandoffOutcome):
            raise TypeError("unexpected BOSS execution outcome")
        return {
            "campaign_id": value.handoff["campaign_id"],
            "claimed_item_ordinal": value.claimed_item_ordinal,
            "content_digest": value.content_digest,
            "next_item_ordinal": value.handoff["next_item_ordinal"],
            "run_id": value.state.run_id,
            "stop_code": value.stop_code,
            "usage": {
                "elapsed_seconds": value.usage.elapsed_seconds,
                "input_tokens": value.usage.input_tokens,
                "provider_turns": value.usage.provider_turns,
                "tool_calls": value.usage.tool_calls,
            },
        }

    def summarize_resume(value: object) -> Mapping[str, object]:
        if not isinstance(value, BossCampaignRestartOutcome):
            raise TypeError("unexpected BOSS resume outcome")
        return {
            "batch_id": value.batch_id,
            "campaign_id": value.campaign_id,
            "claimed_item_ordinal": value.claimed_item_ordinal,
            "lease_expires_at": value.lease_expires_at,
            "planned_item_count": value.planned_item_count,
            "prior_run_id": value.prior_run_id,
            "run_id": value.replacement_run_id,
        }

    return CampaignWorker(
        kind=BOSS_CAMPAIGN_KIND,
        start=start_boss_read_only_batch,
        execute=execute_claimed_boss_identity_through_handoff,
        resume=resume_finished_boss_batch_after_restart,
        summarize_start=summarize_start,
        summarize_execute=summarize_execute,
        summarize_resume=summarize_resume,
    )


def application_campaign_worker(spec: ApplicationWorkerSpec) -> CampaignWorker:
    """Adapt any validated capability-composed scenario to the shared runtime."""
    from .application_campaign_runtime import (
        ApplicationCampaignBatchStart,
        ApplicationCampaignItemOutcome,
        ApplicationCampaignResumeOutcome,
        execute_claimed_application_item,
        resume_application_campaign_batch,
        start_application_campaign_batch,
    )
    if not isinstance(spec, ApplicationWorkerSpec):
        raise ValueError("application worker specification is invalid")

    def start(runner, *, campaign_id, run_id, now):
        return start_application_campaign_batch(
            runner,
            spec=spec,
            campaign_id=campaign_id,
            run_id=run_id,
            now=now,
        )

    async def execute(runner, *, campaign_id, run_id, now):
        return await execute_claimed_application_item(
            runner,
            spec=spec,
            campaign_id=campaign_id,
            run_id=run_id,
            now=now,
        )

    def resume(runner, *, campaign_id, replacement_run_id, now):
        return resume_application_campaign_batch(
            runner,
            spec=spec,
            campaign_id=campaign_id,
            replacement_run_id=replacement_run_id,
            now=now,
        )

    def summarize_start(value: object) -> Mapping[str, object]:
        if not isinstance(value, ApplicationCampaignBatchStart):
            raise TypeError("unexpected application start outcome")
        return {
            "batch_id": value.batch_id,
            "campaign_id": value.campaign_id,
            "claimed_item_ordinal": value.claimed_item_ordinal,
            "lease_expires_at": value.lease_expires_at,
            "planned_item_count": value.planned_item_count,
            "run_id": value.run_id,
            "scenario_id": value.scenario_id,
        }

    def summarize_execute(value: object) -> Mapping[str, object]:
        if not isinstance(value, ApplicationCampaignItemOutcome):
            raise TypeError("unexpected application execution outcome")
        return {
            "campaign_id": value.campaign_id,
            "claimed_item_ordinal": value.claimed_item_ordinal,
            "content_digest": value.result.content_digest,
            "next_item_ordinal": value.handoff["next_item_ordinal"],
            "run_id": value.run_id,
            "scenario_id": value.scenario_id,
            "stop_code": value.stop_code,
            "usage": {
                "elapsed_seconds": value.usage.elapsed_seconds,
                "input_tokens": value.usage.input_tokens,
                "output_tokens": value.usage.output_tokens,
                "provider_turns": value.usage.provider_turns,
                "tool_calls": value.usage.tool_calls,
            },
        }

    def summarize_resume(value: object) -> Mapping[str, object]:
        if not isinstance(value, ApplicationCampaignResumeOutcome):
            raise TypeError("unexpected application resume outcome")
        return {
            "batch_id": value.batch_id,
            "campaign_id": value.campaign_id,
            "claimed_item_ordinal": value.claimed_item_ordinal,
            "completed": value.completed,
            "lease_expires_at": value.lease_expires_at,
            "planned_item_count": value.planned_item_count,
            "prior_run_id": value.prior_run_id,
            "run_id": value.replacement_run_id,
            "scenario_id": value.scenario_id,
            "terminal_next_action": (
                None
                if value.terminal_handoff is None
                else value.terminal_handoff["next_action"]
            ),
        }

    return CampaignWorker(
        kind=spec.kind,
        start=start,
        execute=execute,
        resume=resume,
        summarize_start=summarize_start,
        summarize_execute=summarize_execute,
        summarize_resume=summarize_resume,
        provider_required=True,
    )


def default_campaign_worker_registry() -> CampaignWorkerRegistry:
    """Return the reviewed built-in registry.

    More application kinds can be added only by registering another complete
    start/execute/resume implementation; there is intentionally no dynamic
    import or config-selected callable.
    """

    from .application_worker_catalog import APPLICATION_WORKER_SPECS

    return CampaignWorkerRegistry(
        (_boss_worker(),)
        + tuple(application_campaign_worker(spec) for spec in APPLICATION_WORKER_SPECS)
    )


__all__ = [
    "CampaignWorker",
    "CampaignWorkerError",
    "CampaignWorkerRegistry",
    "CampaignWorkerResult",
    "application_campaign_worker",
    "default_campaign_worker_registry",
    "execute_claimed_campaign_item",
    "resume_campaign_batch",
    "resolve_campaign_worker",
    "start_campaign_batch",
]
