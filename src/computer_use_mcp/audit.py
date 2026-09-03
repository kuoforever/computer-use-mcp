"""Append-only action audit log (JSONL).

Every gated action records what was attempted, the gate/confirm/e-stop decision,
and the outcome — so there is a durable trail of what the agent did on the user's
machine. Long non-sensitive argument strings are bounded. Typed input is stored
only as non-reversible metadata and is never truncated or written verbatim.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

TYPE_AUDIT_DECISIONS = frozenset(
    {
        "ok",
        "estop",
        "human_active",
        "gate_denied",
        "user_denied",
        "unknown_outcome",
    }
)


class AuditLog:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def record(
        self,
        tool: str,
        args: dict | None = None,
        decision: str = "ok",
        result: object | None = None,
    ) -> dict:
        rec = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "tool": tool,
            "args": self._sanitize_args(tool, args or {}),
            "decision": self._sanitize_decision(tool, decision),
            "result": self._sanitize_result(tool, result),
        }
        line = json.dumps(rec, ensure_ascii=False)
        with self._lock, self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
        return rec

    @staticmethod
    def _sanitize_args(tool: str, args: dict) -> dict:
        if tool == "type":
            return AuditLog._sanitize_type_args(args)
        out = {}
        for k, v in args.items():
            if isinstance(v, str) and len(v) > 120:
                v = v[:120] + "…"
            out[k] = v
        return out

    @staticmethod
    def _sanitize_type_args(args: dict) -> dict:
        """Build an allowlisted, non-reversible typed-input audit summary."""

        text = args.get("text")
        out: dict[str, object] = {
            "text_present": "text" in args,
            "text_length": len(text) if isinstance(text, str) else None,
            "ref_supplied": args.get("ref") is not None,
        }
        control_mode = args.get("control_mode")
        if isinstance(control_mode, str) and control_mode in {"safe_local", "full_control_local"}:
            out["control_mode"] = control_mode
        return out

    @staticmethod
    def _sanitize_result(tool: str, result: object | None) -> object | None:
        if tool != "type" or result is None:
            return result
        return {
            "present": True,
            "length": len(result) if isinstance(result, str) else None,
        }

    @staticmethod
    def _sanitize_decision(tool: str, decision: str) -> str:
        if tool != "type":
            return decision
        if isinstance(decision, str) and decision in TYPE_AUDIT_DECISIONS:
            return decision
        return "redacted"
