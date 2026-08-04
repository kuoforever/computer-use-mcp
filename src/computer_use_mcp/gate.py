"""Security gate — foreground process-tree allowlist (DESIGN §E).

A state-changing action is permitted only when the foreground window's owning
process, OR any of its ancestors, is on the allowlist. The ancestor rule is
deliberate: authorize ``weixin.exe`` and its renderer child ``Wechatappex``
passes automatically (a real pain point this project hit before). A transient
foreground flicker is retried a couple of times before denying.

This is the load-bearing safety control: there is no vendor consent UX and no
vendor safety training behind an arbitrary model, so the gate is what keeps an
agent inside the apps the user explicitly allowed.
"""
from __future__ import annotations

import time

from .contract import Driver


class Gate:
    def __init__(self, allowlist, driver: Driver, retries: int = 2, retry_wait: float = 0.15):
        self.allow = {a.strip().lower() for a in allowlist if a and a.strip()}
        self.driver = driver
        self.retries = retries
        self.retry_wait = retry_wait

    def _decision(self, chain_names: list[str]) -> tuple[bool, str]:
        for name in chain_names:
            if name.lower() in self.allow:
                return True, name
        fg = chain_names[0] if chain_names else "?"
        return False, f"foreground {fg!r} (chain={chain_names}) not in allowlist {sorted(self.allow)}"

    def foreground_allowed_once(self) -> tuple[bool, str]:
        """Check one current foreground owner chain without retrying or waiting."""

        chain_names = [p.name for p in self.driver.foreground_owner_chain()]
        return self._decision(chain_names)

    def foreground_allowed(self) -> tuple[bool, str]:
        """Return (allowed, reason) after bounded transient-flicker retries."""

        decision: tuple[bool, str] = (False, "foreground state unavailable")
        for attempt in range(self.retries + 1):
            chain_names = [p.name for p in self.driver.foreground_owner_chain()]
            decision = self._decision(chain_names)
            if decision[0]:
                return decision
            if attempt < self.retries:
                time.sleep(self.retry_wait)  # ride out a transient foreground flicker
        return decision

    def describe(self) -> str:
        return f"allowlist={sorted(self.allow)} (foreground process-tree gate)"
