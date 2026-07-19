"""Bounded Windows OCR over caller-supplied PNG bytes."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Protocol

from .contract import Rect

MAX_OCR_PIXELS = 4_000_000
MAX_OCR_RUNS = 100
MAX_OCR_CHARS = 8_000
OCR_TIMEOUT_SECONDS = 5.0


class OcrError(RuntimeError):
    """A stable OCR failure safe to return through the text tool boundary."""


@dataclass(frozen=True)
class OcrRun:
    text: str
    bbox: Rect


@dataclass(frozen=True)
class OcrRecognition:
    language: str
    runs: tuple[OcrRun, ...]


class OcrReader(Protocol):
    async def recognize(self, png: bytes) -> OcrRecognition: ...


def validate_region(x: int, y: int, w: int, h: int) -> Rect:
    values = {"x": x, "y": y, "w": w, "h": h}
    if any(isinstance(value, bool) or not isinstance(value, int) for value in values.values()):
        raise OcrError("OCR_INVALID_REGION: x, y, w, and h must be integers")
    if x < 0 or y < 0 or w <= 0 or h <= 0:
        raise OcrError("OCR_INVALID_REGION: region must be positive and within the primary display")
    if w * h > MAX_OCR_PIXELS:
        raise OcrError(f"OCR_REGION_TOO_LARGE: maximum is {MAX_OCR_PIXELS} pixels")
    return Rect(x, y, w, h)


def serialize_recognition(recognition: OcrRecognition, region: Rect, png: bytes) -> str:
    runs: list[dict[str, object]] = []
    chars = 0
    omitted = 0
    for index, run in enumerate(recognition.runs):
        if len(runs) >= MAX_OCR_RUNS or chars + len(run.text) > MAX_OCR_CHARS:
            omitted = len(recognition.runs) - index
            break
        chars += len(run.text)
        runs.append(
            {
                "reading_order": index,
                "text": run.text,
                "bbox": [run.bbox.x, run.bbox.y, run.bbox.w, run.bbox.h],
                "screen_bbox": [
                    region.x + run.bbox.x,
                    region.y + run.bbox.y,
                    run.bbox.w,
                    run.bbox.h,
                ],
                "confidence": None,
            }
        )
    payload = {
        "source": "ocr",
        "scope": {"display": "primary", "region": list(region.as_tuple())},
        "coordinate_space": "primary_display_physical_pixels",
        "language_hint": recognition.language,
        "image_digest": hashlib.sha256(png).hexdigest(),
        "complete": omitted == 0,
        "truncated": omitted > 0,
        "omitted_runs": omitted,
        "runs": runs,
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


class WindowsOcrReader:
    """Windows.Media.Ocr adapter; imports stay local so discovery remains portable."""

    async def recognize(self, png: bytes) -> OcrRecognition:
        try:
            from winrt.windows.graphics.imaging import BitmapDecoder
            from winrt.windows.media.ocr import OcrEngine
            from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream
        except (ImportError, ModuleNotFoundError) as exc:
            raise OcrError("OCR_UNAVAILABLE: Windows OCR dependencies are not installed") from exc

        stream = InMemoryRandomAccessStream()
        writer = DataWriter(stream)
        try:
            writer.write_bytes(png)
            await writer.store_async()
            writer.detach_stream()
            stream.seek(0)
            decoder = await BitmapDecoder.create_async(stream)
            bitmap = await decoder.get_software_bitmap_async()
            engine = OcrEngine.try_create_from_user_profile_languages()
            if engine is None:
                raise OcrError("OCR_UNAVAILABLE: no engine for the user profile languages")
            result = await engine.recognize_async(bitmap)
            runs = tuple(
                OcrRun(
                    text=word.text,
                    bbox=Rect(
                        round(word.bounding_rect.x),
                        round(word.bounding_rect.y),
                        round(word.bounding_rect.width),
                        round(word.bounding_rect.height),
                    ),
                )
                for line in result.lines
                for word in line.words
                if word.text
            )
            return OcrRecognition(engine.recognizer_language.language_tag, runs)
        except OcrError:
            raise
        except Exception as exc:
            raise OcrError(f"OCR_FAILED: {type(exc).__name__}") from exc
        finally:
            stream.close()
