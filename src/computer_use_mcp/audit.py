"""Append-only action audit log (JSONL).

Every gated action records what was attempted, the gate/confirm/e-stop decision,
and the outcome — so there is a durable trail of what the agent did on the user's
machine. Long argument strings are truncated so the log can't be used to exfiltrate
large pasted secrets verbatim.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path


class AuditLog:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def record(self, tool: str, args: dict | None = None, decision: str = "ok",
               result: str | None = None) -> dict:
        rec = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "tool": tool,
            "args": self._sanitize(args or {}),
            "decision": decision,
            "result": result,
        }
        line = json.dumps(rec, ensure_ascii=False)
        with self._lock, self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
        return rec

    @staticmethod
    def _sanitize(args: dict) -> dict:
        out = {}
        for k, v in args.items():
            if isinstance(v, str) and len(v) > 120:
                v = v[:120] + "…"
            out[k] = v
        return out
