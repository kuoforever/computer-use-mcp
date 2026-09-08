"""Inert, source-bound append-text tasks. No execution, persistence or model ports.

HostContext is trusted caller input, never parsed from a model response. A review
digest binds the exact candidate; it does not authenticate the caller or grant
Runtime authority. Real adapters still own freshness, policy and dispatch.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import re
from typing import Mapping

MAX_HANDOFF_BYTES = 65_536
MAX_TEXT_BYTES = 32_768
CHECKS = ("readback", "saved", "reopened")


class ContentHandoffError(ValueError):
    """Fixed code only; never includes source, document or model text."""


def text_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _identifier(value: object) -> str:
    if type(value) is not str or re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,95}", value) is None:
        raise ContentHandoffError("IDENTIFIER")
    return value


def _digest(value: object) -> str:
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ContentHandoffError("DIGEST")
    return value


def _object(value: object, fields: set[str]) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != fields or any(type(k) is not str for k in value):
        raise ContentHandoffError("FIELDS")
    return value


def _text(value: object, *, allow_empty: bool = False) -> str:
    if type(value) is not str or (not value and not allow_empty):
        raise ContentHandoffError("TEXT")
    try:
        size = len(value.encode("utf-8"))
    except UnicodeError:
        raise ContentHandoffError("TEXT") from None
    if size > MAX_TEXT_BYTES or any(ord(c) < 32 and c not in "\n\t" for c in value):
        raise ContentHandoffError("TEXT")
    return value


@dataclass(frozen=True)
class ContentProfile:
    """Host-selected limits. The first operation is append_text only."""

    profile_id: str
    max_content_characters: int
    max_final_characters: int


@dataclass(frozen=True)
class HostContentContext:
    """Externally established source/target identity and exact candidate review."""

    task_id: str
    target_id: str
    sources: Mapping[str, str] = field(repr=False)
    initial_text: str = field(repr=False)
    reviewed_task_sha256: str = field(repr=False)


@dataclass(frozen=True)
class BoundContentTask:
    """Validated data only. Do not log or automatically export this object."""

    task_sha256: str
    content_sha256: str
    expected_text_sha256: str
    initial_text_sha256: str
    target_id: str
    source_pins: tuple[tuple[str, str], ...]
    content: str = field(repr=False)


def _decode(raw: bytes) -> dict[str, object]:
    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ContentHandoffError("DUPLICATE_FIELD")
            result[key] = value
        return result

    def nonfinite(value: str) -> object:
        raise ContentHandoffError("NONFINITE")

    if type(raw) is not bytes or not 0 < len(raw) <= MAX_HANDOFF_BYTES:
        raise ContentHandoffError("SIZE")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique, parse_constant=nonfinite)
    except ContentHandoffError:
        raise
    except (ValueError, RecursionError):
        raise ContentHandoffError("JSON") from None
    return _object(value, {"version", "task_id", "profile_id", "operation", "sources",
                           "target", "content", "acceptance"})


def candidate_digest(raw: bytes) -> str:
    """Canonical envelope identity for external review; not approval or validation."""
    value = _decode(raw)
    canonical = json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return text_digest(canonical)


def bind_content_task(raw: bytes, *, profile: ContentProfile,
                      host: HostContentContext) -> BoundContentTask:
    value = _decode(raw)
    task_sha = candidate_digest(raw)
    if type(value["version"]) is not int or value["version"] != 1 or value["operation"] != "append_text":
        raise ContentHandoffError("VERSION_OR_OPERATION")
    if (_identifier(value["task_id"]) != _identifier(host.task_id)
            or _identifier(value["profile_id"]) != _identifier(profile.profile_id)):
        raise ContentHandoffError("TASK_BINDING")
    for cap in (profile.max_content_characters, profile.max_final_characters):
        if type(cap) is not int or not 1 <= cap <= MAX_TEXT_BYTES:
            raise ContentHandoffError("PROFILE")
    if task_sha != _digest(host.reviewed_task_sha256):
        raise ContentHandoffError("REVIEW_BINDING")
    sources = value["sources"]
    if type(sources) is not list or not 1 <= len(sources) <= 8:
        raise ContentHandoffError("SOURCES")
    pins: dict[str, str] = {}
    for source in sources:
        item = _object(source, {"source_id", "content_sha256"})
        key = _identifier(item["source_id"])
        if key in pins:
            raise ContentHandoffError("DUPLICATE_SOURCE")
        pins[key] = _digest(item["content_sha256"])
    trusted_pins = {_identifier(k): _digest(v) for k, v in host.sources.items()}
    if pins != trusted_pins:
        raise ContentHandoffError("SOURCE_BINDING")
    target = _object(value["target"], {"target_id", "initial_text_sha256"})
    target_id = _identifier(target["target_id"])
    initial = _text(host.initial_text, allow_empty=True)
    initial_sha = text_digest(initial)
    if target_id != _identifier(host.target_id) or _digest(target["initial_text_sha256"]) != initial_sha:
        raise ContentHandoffError("TARGET_BINDING")
    content = _object(value["content"], {"text", "sha256"})
    text = _text(content["text"])
    content_sha = text_digest(text)
    if len(text) > profile.max_content_characters or _digest(content["sha256"]) != content_sha:
        raise ContentHandoffError("CONTENT_BINDING")
    final = _text(initial + text)
    if len(final) > profile.max_final_characters:
        raise ContentHandoffError("FINAL_SIZE")
    acceptance = _object(value["acceptance"], {"expected_text_sha256", "checks"})
    expected_sha = text_digest(final)
    if (acceptance["checks"] != list(CHECKS)
            or _digest(acceptance["expected_text_sha256"]) != expected_sha):
        raise ContentHandoffError("ACCEPTANCE_BINDING")
    return BoundContentTask(task_sha, content_sha, expected_sha, initial_sha,
                            target_id, tuple(sorted(pins.items())), text)


def verify_content_results(task: BoundContentTask, *, target_id: str,
                           observations: Mapping[str, str]) -> None:
    """Check three complete bodies supplied by a trusted adapter, never by a model.

    Equality alone does not prove that a save or reopen took place. The adapter
    must establish each phase's occurrence, completeness and target identity.
    """
    if target_id != task.target_id or set(observations) != set(CHECKS):
        raise ContentHandoffError("RESULT_BINDING")
    for text in observations.values():
        if text_digest(_text(text)) != task.expected_text_sha256:
            raise ContentHandoffError("RESULT_MISMATCH")


def safe_content_receipt(task: BoundContentTask) -> dict[str, object]:
    """Content-free local diagnostic metadata; no automatic Lane A export hook."""
    return dict(version=1, task_sha256=task.task_sha256,
                content_sha256=task.content_sha256, expected_text_sha256=task.expected_text_sha256,
                content_characters=len(task.content), source_count=len(task.source_pins),
                execution_authorized=False)
