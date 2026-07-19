"""Run-scoped text pseudonymization and in-memory token vault.

The vault is deliberately memory-only. Provider requests, ledgers, traces, and
checkpoints may retain opaque tokens, but never the corresponding plaintext.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Iterable, Mapping

from ..config import PrivacyConfig
from ..types import JSONValue, MemoryContextItem, ToolCall, ToolResult


TOKEN_PREFIX = "[[PRIVATE:"
_CATEGORY = r"EMAIL|PHONE|IPV4|CN_ID|BANK_CARD|TERM|SECRET"
TOKEN_PATTERN = re.compile(
    rf"\[\[PRIVATE:({_CATEGORY}):([0-9A-F]{{32}})\]\]"
)
IMAGE_TOKEN_PATTERN = re.compile(rf"\[({_CATEGORY})#([1-9][0-9]*)\]")
IMAGE_TOKEN_CANDIDATE = re.compile(rf"\[(?:{_CATEGORY})#")

PRIVACY_MODEL_RULE = (
    "Local privacy boundary: strings shaped like [[PRIVATE:TYPE:ID]] and "
    "[TYPE#N] are opaque run-scoped labels. Preserve them exactly when needed; "
    "never alter or invent a label. SECRET labels must never be requested or revealed."
)

_EMAIL = re.compile(r"(?<![\w.+-])[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+(?![\w.-])")
_PHONE = re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)")
_IPV4 = re.compile(r"(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)")
_CN_ID = re.compile(r"(?<!\d)\d{17}[0-9Xx](?!\d)")
_BANK_CARD = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(?:api[_-]?key|access[_-]?token|auth[_-]?token|password|passwd|secret)"
    r"\s*[:=]\s*(['\"]?)([^\s,;\"']+)\1"
)


class PrivacyError(RuntimeError):
    """A fixed fail-closed privacy-boundary error."""


@dataclass(frozen=True)
class _VaultEntry:
    category: str
    plaintext: str
    restorable: bool


@dataclass(frozen=True)
class _Candidate:
    start: int
    end: int
    category: str
    plaintext: str
    restorable: bool
    priority: int


@dataclass(frozen=True)
class ProtectedTextSpan:
    """One tokenized text span for a local presentation-layer redactor."""

    start: int
    end: int
    category: str
    token: str


def _valid_ipv4(value: str) -> bool:
    return all(int(part) <= 255 for part in value.split("."))


def _valid_cn_id(value: str) -> bool:
    if len(value) != 18:
        return False
    try:
        datetime.strptime(value[6:14], "%Y%m%d")
    except ValueError:
        return False
    weights = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
    checks = "10X98765432"
    total = sum(int(digit) * weight for digit, weight in zip(value[:17], weights))
    return value[-1].upper() == checks[total % 11]


def _valid_bank_card(value: str) -> bool:
    digits = "".join(character for character in value if character.isdigit())
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    parity = len(digits) % 2
    for index, character in enumerate(digits):
        digit = int(character)
        if index % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


class PrivacySession:
    """One ephemeral token vault bound to exactly one run."""

    def __init__(self, config: PrivacyConfig, run_id: str) -> None:
        if not isinstance(config, PrivacyConfig):
            raise ValueError("config must be a PrivacyConfig")
        if not isinstance(run_id, str) or not run_id:
            raise ValueError("run_id must be a non-empty string")
        self.config = config
        self.run_id = run_id
        self._key = secrets.token_bytes(32)
        self._entries: dict[str, _VaultEntry] = {}
        self._tokens_by_value: dict[tuple[str, str], str] = {}
        self._image_aliases: dict[str, str] = {}
        self._term_expression = (
            re.compile(
                "|".join(
                    re.escape(term)
                    for term in sorted(self.config.terms, key=len, reverse=True)
                )
            )
            if self.config.terms
            else None
        )

    def _token(self, category: str, plaintext: str, *, restorable: bool) -> str:
        identity = (category, plaintext)
        existing = self._tokens_by_value.get(identity)
        if existing is not None:
            return existing
        digest = hmac.new(
            self._key,
            f"{self.run_id}\0{category}\0{plaintext}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()[:32].upper()
        token = f"[[PRIVATE:{category}:{digest}]]"
        if token in self._entries and self._entries[token].plaintext != plaintext:
            raise PrivacyError("PRIVACY_TOKEN_COLLISION")
        self._entries[token] = _VaultEntry(category, plaintext, restorable)
        self._tokens_by_value[identity] = token
        return token

    def image_alias(self, token: str) -> str:
        """Return a compact run-local label for an existing canonical token."""

        existing = self._image_aliases.get(token)
        if existing is not None:
            return existing
        entry = self._entries.get(token)
        if entry is None:
            raise PrivacyError("PRIVACY_TOKEN_INVALID")
        alias = f"[{entry.category}#{len(self._image_aliases) + 1}]"
        self._entries[alias] = entry
        self._image_aliases[token] = alias
        return alias

    def _candidates(self, text: str) -> list[_Candidate]:
        candidates: list[_Candidate] = []
        detectors = frozenset(self.config.detectors)
        if "secret" in detectors:
            for match in _SECRET_ASSIGNMENT.finditer(text):
                start, end = match.span(2)
                candidates.append(
                    _Candidate(start, end, "SECRET", match.group(2), False, 0)
                )
        if "cn_id" in detectors:
            for match in _CN_ID.finditer(text):
                if _valid_cn_id(match.group(0)):
                    candidates.append(
                        _Candidate(
                            match.start(),
                            match.end(),
                            "CN_ID",
                            match.group(0),
                            True,
                            1,
                        )
                    )
        if self._term_expression is not None:
            for match in self._term_expression.finditer(text):
                candidates.append(
                    _Candidate(match.start(), match.end(), "TERM", match.group(0), True, 2)
                )
        if "email" in detectors:
            for match in _EMAIL.finditer(text):
                candidates.append(
                    _Candidate(match.start(), match.end(), "EMAIL", match.group(0), True, 3)
                )
        if "phone" in detectors:
            for match in _PHONE.finditer(text):
                candidates.append(
                    _Candidate(match.start(), match.end(), "PHONE", match.group(0), True, 3)
                )
        if "ipv4" in detectors:
            for match in _IPV4.finditer(text):
                if _valid_ipv4(match.group(0)):
                    candidates.append(
                        _Candidate(match.start(), match.end(), "IPV4", match.group(0), True, 3)
                    )
        if "bank_card" in detectors:
            for match in _BANK_CARD.finditer(text):
                if _valid_bank_card(match.group(0)):
                    candidates.append(
                        _Candidate(
                            match.start(),
                            match.end(),
                            "BANK_CARD",
                            match.group(0),
                            True,
                            4,
                        )
                    )
        return candidates

    def _selected_candidates(self, text: str) -> list[_Candidate]:
        if TOKEN_PREFIX in text or IMAGE_TOKEN_CANDIDATE.search(text):
            raise PrivacyError("PRIVACY_RESERVED_TOKEN_INPUT")
        return self._select_nonoverlapping(self._candidates(text))

    def _candidate_token(self, candidate: _Candidate) -> str:
        return self._token(
            candidate.category,
            candidate.plaintext,
            restorable=candidate.restorable,
        )

    def _protections(self, text: str) -> list[tuple[_Candidate, str]]:
        return [
            (candidate, self._candidate_token(candidate))
            for candidate in self._selected_candidates(text)
        ]

    def protected_spans(self, text: str) -> tuple[ProtectedTextSpan, ...]:
        """Expose bounded span/token data to a local presentation redactor."""

        if not self.config.enabled:
            return ()
        return tuple(
            ProtectedTextSpan(
                candidate.start,
                candidate.end,
                candidate.category,
                token,
            )
            for candidate, token in self._protections(text)
        )

    @staticmethod
    def _select_nonoverlapping(candidates: Iterable[_Candidate]) -> list[_Candidate]:
        selected: list[_Candidate] = []
        for candidate in sorted(
            candidates,
            key=lambda item: (item.priority, -(item.end - item.start), item.start),
        ):
            if any(candidate.start < item.end and item.start < candidate.end for item in selected):
                continue
            selected.append(candidate)
        return sorted(selected, key=lambda item: item.start)

    def protect_text(self, text: str) -> str:
        """Replace reviewed sensitive spans and reject reserved-token injection."""

        if not isinstance(text, str):
            raise ValueError("privacy input must be a string")
        if not self.config.enabled:
            return text
        protections = self._protections(text)
        if not protections:
            return text
        pieces: list[str] = []
        offset = 0
        for item, token in protections:
            pieces.append(text[offset:item.start])
            pieces.append(token)
            offset = item.end
        pieces.append(text[offset:])
        return "".join(pieces)

    def protect_task(self, task: str) -> str:
        protected = self.protect_text(task)
        if not self.config.enabled:
            return protected
        return f"{protected}\n\n{PRIVACY_MODEL_RULE}"

    def validate_model_text(self, text: str) -> None:
        """Reject malformed, unknown, or cross-run tokens in model output."""

        if not self.config.enabled:
            return
        if not isinstance(text, str):
            raise ValueError("model text must be a string")
        canonical_matches = list(TOKEN_PATTERN.finditer(text))
        image_matches = list(IMAGE_TOKEN_PATTERN.finditer(text))
        remainder = TOKEN_PATTERN.sub("", text)
        remainder = IMAGE_TOKEN_PATTERN.sub("", remainder)
        if TOKEN_PREFIX in remainder or IMAGE_TOKEN_CANDIDATE.search(remainder):
            raise PrivacyError("PRIVACY_TOKEN_INVALID")
        if any(
            match.group(0) not in self._entries
            for match in (*canonical_matches, *image_matches)
        ):
            raise PrivacyError("PRIVACY_TOKEN_INVALID")

    def restore_text(self, text: str) -> str:
        """Restore ordinary PII for local display while keeping secrets opaque."""

        self.validate_model_text(text)
        if not self.config.enabled:
            return text

        def restore(match: re.Match[str]) -> str:
            token = match.group(0)
            entry = self._entries[token]
            return entry.plaintext if entry.restorable else token

        restored = TOKEN_PATTERN.sub(restore, text)
        return IMAGE_TOKEN_PATTERN.sub(restore, restored)

    def protect_memories(
        self, memories: tuple[MemoryContextItem, ...]
    ) -> tuple[MemoryContextItem, ...]:
        if not self.config.enabled:
            return memories
        return tuple(
            replace(
                item,
                content=self.protect_text(item.content),
                scope=self.protect_text(item.scope),
            )
            for item in memories
        )

    def protect_result(self, result: ToolResult) -> ToolResult:
        if not self.config.enabled or not result.sanitized_text:
            return result
        return replace(result, sanitized_text=self.protect_text(result.sanitized_text))

    def validate_tool_call(self, call: ToolCall) -> None:
        if not self.config.enabled:
            return
        if call.name == "screenshot" and not self.config.image_redaction:
            raise PrivacyError("PRIVACY_IMAGE_OBSERVATION_DENIED")

        def walk(value: JSONValue) -> None:
            if isinstance(value, str):
                self.validate_model_text(value)
            elif isinstance(value, list):
                for item in value:
                    walk(item)
            elif isinstance(value, Mapping):
                for item in value.values():
                    walk(item)  # type: ignore[arg-type]

        walk(call.arguments)  # type: ignore[arg-type]

    def resolve_local_call(self, call: ToolCall) -> ToolCall:
        """Resolve tokens only for the reviewed, local read-only query sink."""

        if not self.config.enabled:
            return call
        self.validate_tool_call(call)

        def contains_token(value: object) -> bool:
            if isinstance(value, str):
                return TOKEN_PATTERN.search(value) is not None
            if isinstance(value, (list, tuple)):
                return any(contains_token(item) for item in value)
            if isinstance(value, Mapping):
                return any(contains_token(item) for item in value.values())
            return False

        contains_token = contains_token(call.arguments)
        if not contains_token:
            return call
        if call.name != "find" or set(call.arguments) - {"query", "scope"}:
            raise PrivacyError("PRIVACY_TOOL_RESTORE_DENIED")
        arguments = dict(call.arguments)
        query = arguments.get("query")
        if not isinstance(query, str):
            raise PrivacyError("PRIVACY_TOOL_RESTORE_DENIED")
        scope = arguments.get("scope")
        if isinstance(scope, str) and TOKEN_PATTERN.search(scope):
            raise PrivacyError("PRIVACY_TOOL_RESTORE_DENIED")
        restored = self.restore_text(query)
        if TOKEN_PREFIX in restored:
            raise PrivacyError("PRIVACY_SECRET_RESTORE_DENIED")
        arguments["query"] = restored
        return replace(call, arguments=arguments)


__all__ = [
    "IMAGE_TOKEN_PATTERN",
    "PrivacyError",
    "PrivacySession",
    "ProtectedTextSpan",
    "TOKEN_PATTERN",
    "TOKEN_PREFIX",
]
