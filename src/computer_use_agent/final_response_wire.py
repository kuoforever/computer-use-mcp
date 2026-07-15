"""Shared lossless wire projection for tool-free final-response adapters."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from hashlib import sha256

from .executor_final import FinalResponseRequest
from .types import ImageContent


MAX_FINAL_RESPONSE_TEXT_BYTES = 256 * 1024


class FinalResponseWireError(RuntimeError):
    """Fixed failure while projecting a validated final-response request."""


@dataclass(frozen=True, repr=False)
class FinalResponseWire:
    """Canonical text manifest plus ordered native image payloads."""

    manifest_json: str = field(repr=False)
    images: tuple[ImageContent, ...] = field(repr=False)

    def __repr__(self) -> str:
        return (
            "FinalResponseWire("
            f"manifest_bytes={len(self.manifest_json.encode('utf-8'))}, "
            f"image_count={len(self.images)})"
        )


def compile_final_response_wire(request: FinalResponseRequest) -> FinalResponseWire:
    """Project inert request data without adding tools or execution fields."""

    if not isinstance(request, FinalResponseRequest):
        raise FinalResponseWireError("FINAL_RESPONSE_WIRE_INVALID")
    images: list[ImageContent] = []
    observations: list[dict[str, object]] = []
    for observation in request.observations:
        descriptors: list[dict[str, object]] = []
        for image in observation.images:
            image_index = len(images)
            images.append(image)
            descriptors.append(
                {
                    "image_index": image_index,
                    "mime_type": image.mime_type,
                    "sha256": sha256(image.data).hexdigest(),
                    "width": image.width,
                    "height": image.height,
                }
            )
        observations.append(
            {
                "step_id": observation.step_id,
                "tool_name": observation.tool_name,
                "arguments": json.loads(observation.arguments_json),
                "sanitized_text": observation.sanitized_text,
                "images": descriptors,
            }
        )
    payload = {
        "version": 1,
        "request_digest": request.request_digest,
        "run_id": request.run_id,
        "plan_id": request.plan_id,
        "plan_digest": request.plan_digest,
        "snapshot_sequence": request.snapshot_sequence,
        "turn_id": request.turn_id,
        "task": request.task,
        "observations": observations,
    }
    try:
        manifest = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        )
    except (TypeError, ValueError, UnicodeError) as exc:
        raise FinalResponseWireError("FINAL_RESPONSE_WIRE_INVALID") from exc
    return FinalResponseWire(manifest_json=manifest, images=tuple(images))


def validate_final_response_text(value: object) -> str:
    """Accept one bounded non-empty provider text value without normalization."""

    if not isinstance(value, str) or not value.strip():
        raise FinalResponseWireError("FINAL_RESPONSE_TEXT_INVALID")
    try:
        size = len(value.encode("utf-8"))
    except UnicodeError as exc:
        raise FinalResponseWireError("FINAL_RESPONSE_TEXT_INVALID") from exc
    if size > MAX_FINAL_RESPONSE_TEXT_BYTES:
        raise FinalResponseWireError("FINAL_RESPONSE_TEXT_TOO_LARGE")
    return value


__all__ = [
    "FinalResponseWire",
    "FinalResponseWireError",
    "MAX_FINAL_RESPONSE_TEXT_BYTES",
    "compile_final_response_wire",
    "validate_final_response_text",
]
