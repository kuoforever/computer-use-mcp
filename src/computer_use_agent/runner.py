"""Side-effect-free AgentRunner foundation for later workflow phases."""
from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

from .config import AgentConfig
from .policy import HostPolicy
from .run_lock import RunLock
from .types import (
    ApprovalPort,
    DesktopMCPPort,
    LedgerEvent,
    LedgerEventKind,
    ModelProviderPort,
    RunState,
)


@dataclass(frozen=True)
class RunnerPorts:
    """Injected external boundaries; Phase 2 never calls them."""

    provider: ModelProviderPort
    desktop: DesktopMCPPort
    approvals: ApprovalPort


@dataclass
class PreparedRun:
    """An initial in-memory run state that owns one local run lock."""

    state: RunState
    _lock: RunLock = field(repr=False)
    _closed: bool = field(default=False, init=False, repr=False)

    @property
    def closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        if self._closed:
            return
        self._lock.release()
        self._closed = True

    def __enter__(self) -> "PreparedRun":
        if self._closed:
            raise RuntimeError("prepared run is already closed")
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.close()


class AgentRunner:
    """Build bounded initial state without invoking a provider or desktop."""

    def __init__(self, config: AgentConfig, ports: RunnerPorts | None = None) -> None:
        if not isinstance(config, AgentConfig):
            raise ValueError("config must be an AgentConfig")
        if ports is not None and not isinstance(ports, RunnerPorts):
            raise ValueError("ports must be RunnerPorts or None")
        self.config = config
        self.ports = ports
        self.policy = HostPolicy.from_config(config.policy_version, config.policy)

    def prepare(self, task: str, *, run_id: str | None = None) -> PreparedRun:
        if not isinstance(task, str) or not task.strip():
            raise ValueError("task must be a non-empty string")
        resolved_run_id = run_id or uuid4().hex
        if not isinstance(resolved_run_id, str) or not resolved_run_id.strip():
            raise ValueError("run_id must be a non-empty string")

        state = RunState(
            run_id=resolved_run_id,
            task=task,
            policy_version=self.policy.version,
            observation_epoch=0,
            budgets=self.policy.initial_budget(),
            event_log=(
                LedgerEvent(
                    event_id=f"{resolved_run_id}:event:1",
                    kind=LedgerEventKind.USER_TASK,
                    payload={"task_length": len(task)},
                ),
            ),
        )
        lock = RunLock(self.config.application_state_dir)
        lock.acquire()
        return PreparedRun(state=state, _lock=lock)
