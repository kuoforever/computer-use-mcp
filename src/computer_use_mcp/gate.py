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

    def foreground_allowed(self) -> tuple[bool, str]:
        """Return (allowed, reason). Allowed if any process in the foreground
        window's owner chain is on the allowlist."""
        chain_names: list[str] = []
        for attempt in range(self.retries + 1):
            chain_names = [p.name for p in self.driver.foreground_owner_chain()]
            for name in chain_names:
                if name.lower() in self.allow:
                    return True, name
            if attempt < self.retries:
                time.sleep(self.retry_wait)  # ride out a transient foreground flicker
        fg = chain_names[0] if chain_names else "?"
        return False, f"foreground {fg!r} (chain={chain_names}) not in allowlist {sorted(self.allow)}"

    def describe(self) -> str:
        return f"allowlist={sorted(self.allow)} (foreground process-tree gate)"
