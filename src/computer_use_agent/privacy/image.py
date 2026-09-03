"""Independent local screenshot-privacy pipeline and future visual detector port.

The active backend uses Windows OCR for deterministic text regions. Non-text
visual detection is an injected, default-absent port so a future DeepSeek-OCR,
QR, face, document, or signature backend does not expand the core text vault or
provider boundary merely by being installed.
"""
from __future__ import annotations

import asyncio
import io
from dataclasses import dataclass, replace
from typing import Protocol

from ..types import ImageContent, ToolResult
from .core import PrivacyError, PrivacySession


MAX_IMAGE_OCR_RUNS = 500
MAX_IMAGE_OCR_CHARS = 32_000
MAX_IMAGE_OCR_JOIN_WORDS = 8
MAX_VISUAL_PRIVACY_REGIONS = 100
IMAGE_ANALYSIS_TIMEOUT_SECONDS = 8.0
SUPPORTED_VISUAL_PRIVACY_KINDS = frozenset(
    {"face", "qr", "identity_document", "signature"}
)


@dataclass(frozen=True)
class RecognizedImageText:
    """One local OCR word and its image-relative pixel box."""

    text: str
    x: int
    y: int
    width: int
    height: int

    def __post_init__(self) -> None:
        if not isinstance(self.text, str) or not self.text:
            raise ValueError("recognized image text must be non-empty")
        _validate_box(self.x, self.y, self.width, self.height, "recognized image")


@dataclass(frozen=True)
class VisualPrivacyRegion:
    """One non-reversible region proposed by an optional local visual backend."""

    kind: str
    x: int
    y: int
    width: int
    height: int

    def __post_init__(self) -> None:
        if self.kind not in SUPPORTED_VISUAL_PRIVACY_KINDS:
            raise ValueError("visual privacy region kind is not reviewed")
        _validate_box(self.x, self.y, self.width, self.height, "visual privacy")


def _validate_box(x: int, y: int, width: int, height: int, prefix: str) -> None:
    for name, value in (("x", x), ("y", y), ("width", width), ("height", height)):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{prefix} {name} must be an integer")
    if x < 0 or y < 0 or width <= 0 or height <= 0:
        raise ValueError(f"{prefix} box must be positive")


class PrivacyImageRecognizer(Protocol):
    """Local-only OCR boundary over an already validated screenshot."""

    async def recognize(self, image: ImageContent) -> tuple[RecognizedImageText, ...]: ...


class PrivacyVisualDetector(Protocol):
    """Optional local-only non-text detector; no backend is enabled by default."""

    async def detect(self, image: ImageContent) -> tuple[VisualPrivacyRegion, ...]: ...


class PrivacyImageRedactionPort(Protocol):
    """Complete screenshot sanitization boundary consumed by the Runner."""

    async def redact(self, result: ToolResult, privacy: PrivacySession) -> ToolResult: ...


class WindowsPrivacyImageRecognizer:
    """Adapt the existing Windows.Media.Ocr reader to the image privacy port."""

    def __init__(self, reader: object | None = None) -> None:
        self._reader = reader

    async def recognize(self, image: ImageContent) -> tuple[RecognizedImageText, ...]:
        reader = self._reader
        if reader is None:
            from computer_use_mcp.ocr import WindowsOcrReader

            reader = WindowsOcrReader()
            self._reader = reader
        try:
            recognition = await reader.recognize(image.data)  # type: ignore[attr-defined]
            return tuple(
                RecognizedImageText(
                    run.text,
                    run.bbox.x,
                    run.bbox.y,
                    run.bbox.w,
                    run.bbox.h,
                )
                for run in recognition.runs
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise PrivacyError("PRIVACY_IMAGE_OCR_FAILED") from exc


class LocalPrivacyImageRedactor:
    """Coordinate-preserving OCR redaction with a dormant visual-detector slot."""

    def __init__(
        self,
        recognizer: PrivacyImageRecognizer,
        *,
        visual_detector: PrivacyVisualDetector | None = None,
    ) -> None:
        self.recognizer = recognizer
        self.visual_detector = visual_detector

    @staticmethod
    def _same_ocr_line(previous: RecognizedImageText, current: RecognizedImageText) -> bool:
        overlap = max(
            0,
            min(previous.y + previous.height, current.y + current.height)
            - max(previous.y, current.y),
        )
        return current.x >= previous.x and overlap * 2 >= min(
            previous.height, current.height
        )

    @classmethod
    def _ocr_lines(cls, runs: tuple[RecognizedImageText, ...]) -> list[list[int]]:
        lines: list[list[int]] = []
        for index, run in enumerate(runs):
            if lines and cls._same_ocr_line(runs[lines[-1][-1]], run):
                lines[-1].append(index)
            else:
                lines.append([index])
        return lines

    @staticmethod
    def _join_ocr_runs(
        runs: tuple[RecognizedImageText, ...],
        indices: list[int],
        separator: str,
    ) -> tuple[str, list[tuple[int, int, int]]]:
        pieces: list[str] = []
        spans: list[tuple[int, int, int]] = []
        cursor = 0
        for offset, index in enumerate(indices):
            if offset:
                pieces.append(separator)
                cursor += len(separator)
            start = cursor
            pieces.append(runs[index].text)
            cursor += len(runs[index].text)
            spans.append((index, start, cursor))
        return "".join(pieces), spans

    @classmethod
    def _text_groups(
        cls,
        runs: tuple[RecognizedImageText, ...],
        privacy: PrivacySession,
    ) -> dict[tuple[int, ...], list[str]]:
        groups: dict[tuple[int, ...], list[str]] = {}

        def add(indices: tuple[int, ...], token: str) -> None:
            tokens = groups.setdefault(indices, [])
            if token not in tokens:
                tokens.append(token)

        for index, run in enumerate(runs):
            for span in privacy.protected_spans(run.text):
                add((index,), span.token)

        for line in cls._ocr_lines(runs):
            for start in range(len(line)):
                stop_limit = min(len(line), start + MAX_IMAGE_OCR_JOIN_WORDS)
                for stop in range(start + 2, stop_limit + 1):
                    window = line[start:stop]
                    for separator in (" ", ""):
                        text, spans = cls._join_ocr_runs(runs, window, separator)
                        for protected in privacy.protected_spans(text):
                            touched = tuple(
                                index
                                for index, span_start, span_end in spans
                                if protected.start < span_end and span_start < protected.end
                            )
                            if len(touched) >= 2 or protected.category == "SECRET":
                                add(touched, protected.token)
        return groups

    @staticmethod
    def _validate_bounds(
        image: ImageContent,
        runs: tuple[RecognizedImageText, ...],
        visual_regions: tuple[VisualPrivacyRegion, ...],
    ) -> None:
        if (
            len(runs) > MAX_IMAGE_OCR_RUNS
            or sum(len(run.text) for run in runs) > MAX_IMAGE_OCR_CHARS
            or len(visual_regions) > MAX_VISUAL_PRIVACY_REGIONS
        ):
            raise PrivacyError("PRIVACY_IMAGE_ANALYSIS_INVALID")
        regions: tuple[RecognizedImageText | VisualPrivacyRegion, ...] = (
            *runs,
            *visual_regions,
        )
        for region in regions:
            if region.x + region.width > image.width or region.y + region.height > image.height:
                raise PrivacyError("PRIVACY_IMAGE_ANALYSIS_INVALID")

    async def _analyze(
        self, image: ImageContent
    ) -> tuple[tuple[RecognizedImageText, ...], tuple[VisualPrivacyRegion, ...]]:
        try:
            runs = await asyncio.wait_for(
                self.recognizer.recognize(image),
                timeout=IMAGE_ANALYSIS_TIMEOUT_SECONDS,
            )
            visual_regions = (
                ()
                if self.visual_detector is None
                else await asyncio.wait_for(
                    self.visual_detector.detect(image),
                    timeout=IMAGE_ANALYSIS_TIMEOUT_SECONDS,
                )
            )
        except asyncio.CancelledError:
            raise
        except PrivacyError:
            raise
        except Exception as exc:
            raise PrivacyError("PRIVACY_IMAGE_ANALYSIS_FAILED") from exc
        if (
            not isinstance(runs, tuple)
            or not all(isinstance(run, RecognizedImageText) for run in runs)
            or not isinstance(visual_regions, tuple)
            or not all(isinstance(region, VisualPrivacyRegion) for region in visual_regions)
        ):
            raise PrivacyError("PRIVACY_IMAGE_ANALYSIS_INVALID")
        self._validate_bounds(image, runs, visual_regions)
        return runs, visual_regions

    async def redact(self, result: ToolResult, privacy: PrivacySession) -> ToolResult:
        """Analyze and paint sensitive regions before an image enters the ledger."""

        if not privacy.config.enabled or not result.images:
            return result
        if result.tool_name != "screenshot" or len(result.images) != 1:
            raise PrivacyError("PRIVACY_IMAGE_RESULT_INVALID")
        image = result.images[0]
        runs, visual_regions = await self._analyze(image)
        text_groups = self._text_groups(runs, privacy)
        if not text_groups and not visual_regions:
            return result

        paint: list[tuple[int, int, int, int, str]] = []
        for indices, tokens in text_groups.items():
            selected = tuple(runs[index] for index in indices)
            paint.append(
                (
                    min(run.x for run in selected),
                    min(run.y for run in selected),
                    max(run.x + run.width for run in selected),
                    max(run.y + run.height for run in selected),
                    " ".join(privacy.image_alias(token) for token in tokens),
                )
            )
        paint.extend(
            (
                region.x,
                region.y,
                region.x + region.width,
                region.y + region.height,
                f"[VISUAL:{region.kind.upper()}]",
            )
            for region in visual_regions
        )

        # Imported here, not at module scope: image redaction is disabled by
        # default, but this module is on the CLI import chain through
        # `runner`. An eager import would make Pillow a hard requirement for
        # every offline command, including `--help` and the fake-MCP eval.
        from PIL import Image as PILImage
        from PIL import ImageDraw

        try:
            with PILImage.open(io.BytesIO(image.data)) as source:
                canvas = source.convert("RGB")
            for raw_left, raw_top, raw_right, raw_bottom, label in paint:
                padding = 2
                left = max(0, raw_left - padding)
                top = max(0, raw_top - padding)
                right = min(image.width, raw_right + padding)
                bottom = min(image.height, raw_bottom + padding)
                patch = PILImage.new("RGB", (right - left, bottom - top), "black")
                draw = ImageDraw.Draw(patch)
                draw.text((1, 0), label, fill="white")
                canvas.paste(patch, (left, top))
            output = io.BytesIO()
            canvas.save(output, format="PNG")
            protected_image = ImageContent(
                mime_type="image/png",
                data=output.getvalue(),
                width=image.width,
                height=image.height,
            )
        except Exception as exc:
            raise PrivacyError("PRIVACY_IMAGE_REDACTION_FAILED") from exc
        return replace(result, images=(protected_image,))


__all__ = [
    "LocalPrivacyImageRedactor",
    "PrivacyImageRecognizer",
    "PrivacyImageRedactionPort",
    "PrivacyVisualDetector",
    "RecognizedImageText",
    "SUPPORTED_VISUAL_PRIVACY_KINDS",
    "VisualPrivacyRegion",
    "WindowsPrivacyImageRecognizer",
]
