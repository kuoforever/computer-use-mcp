from __future__ import annotations

import asyncio
import io
import json

import pytest
from PIL import Image as PILImage

from computer_use_mcp.contract import Display, Image, ProcRef, Rect, Window
from computer_use_mcp.ocr import (
    MAX_OCR_RUNS,
    OcrError,
    OcrRecognition,
    OcrRun,
    serialize_recognition,
    validate_region,
)
from computer_use_mcp.server import build_server


def _png(width: int, height: int) -> bytes:
    output = io.BytesIO()
    PILImage.new("RGB", (width, height), "white").save(output, format="PNG")
    return output.getvalue()


def _tool_text(result: object) -> str:
    content = result[0] if isinstance(result, tuple) else result
    return "\n".join(getattr(item, "text", "") for item in content)


@pytest.mark.parametrize(
    "values",
    [(-1, 0, 1, 1), (0, -1, 1, 1), (0, 0, 0, 1), (0, 0, 1, 0), (0, 0, 2001, 2000)],
)
def test_ocr_region_rejects_invalid_or_oversized_bounds(values: tuple[int, int, int, int]) -> None:
    with pytest.raises(OcrError):
        validate_region(*values)


def test_ocr_serialization_is_bounded_and_maps_boxes_to_screen_coordinates() -> None:
    recognition = OcrRecognition(
        "en-US",
        tuple(OcrRun(f"word-{index}", Rect(index, 2, 3, 4)) for index in range(MAX_OCR_RUNS + 1)),
    )

    payload = json.loads(serialize_recognition(recognition, Rect(100, 200, 20, 20), b"png"))

    assert len(payload["runs"]) == MAX_OCR_RUNS
    assert payload["runs"][0]["bbox"] == [0, 2, 3, 4]
    assert payload["runs"][0]["screen_bbox"] == [100, 202, 3, 4]
    assert payload["complete"] is False
    assert payload["truncated"] is True
    assert payload["omitted_runs"] == 1


class RecordingReader:
    def __init__(self) -> None:
        self.png: bytes | None = None

    async def recognize(self, png: bytes) -> OcrRecognition:
        self.png = png
        return OcrRecognition("en-US", (OcrRun("visible", Rect(1, 1, 2, 2)),))


class SlowReader:
    async def recognize(self, png: bytes) -> OcrRecognition:
        await asyncio.sleep(1)
        return OcrRecognition("en-US", ())


class RegionDriver:
    def __init__(self) -> None:
        self.region: Rect | None = None

    def capture_screen(self, region: Rect | None = None) -> Image:
        assert region is not None
        self.region = region
        return Image(
            png=_png(region.w, region.h),
            width=region.w,
            height=region.h,
            scale=1.0,
            displays=[Display("1", Rect(0, 0, 1920, 1080), 1.0, True)],
        )

    def list_windows(self) -> list[Window]:
        owner = ProcRef(1, "vault.exe")
        return [Window("1", "Vault", Rect(105, 205, 2, 2), owner, [owner], False)]


def test_server_ocr_captures_only_the_region_and_redacts_before_recognition(tmp_path) -> None:
    driver = RegionDriver()
    reader = RecordingReader()
    server = build_server(
        driver=driver,
        start_estop=False,
        redact_titles=["Vault"],
        ocr_reader=reader,
        audit_path=tmp_path / "audit.jsonl",
    )

    result = asyncio.run(server.call_tool("ocr", {"x": 100, "y": 200, "w": 10, "h": 10}))
    payload = json.loads(_tool_text(result))

    assert driver.region == Rect(100, 200, 10, 10)
    assert payload["scope"]["region"] == [100, 200, 10, 10]
    assert payload["runs"][0]["screen_bbox"] == [101, 201, 2, 2]
    assert reader.png is not None
    redacted = PILImage.open(io.BytesIO(reader.png)).convert("RGB")
    assert redacted.getpixel((5, 5)) == (0, 0, 0)
    assert redacted.getpixel((4, 4)) == (255, 255, 255)


def test_server_ocr_times_out_with_a_stable_error(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("computer_use_mcp.server.OCR_TIMEOUT_SECONDS", 0.01)
    server = build_server(
        driver=RegionDriver(),
        start_estop=False,
        redact_titles=[],
        ocr_reader=SlowReader(),
        audit_path=tmp_path / "audit.jsonl",
    )

    result = asyncio.run(server.call_tool("ocr", {"x": 0, "y": 0, "w": 10, "h": 10}))

    assert _tool_text(result) == "ERROR OCR_TIMEOUT: exceeded 0.01 seconds"
