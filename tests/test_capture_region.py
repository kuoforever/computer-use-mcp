from __future__ import annotations

import asyncio
import base64
import io
import json

import pytest
from PIL import Image as PILImage

from computer_use_mcp.capture import (
    MAX_CAPTURE_PIXELS,
    MAX_CAPTURE_PNG_BYTES,
    CaptureError,
    serialize_capture,
    validate_region,
)
from computer_use_mcp.contract import Display, DriverError, Image, ProcRef, Rect, Window
from computer_use_mcp.server import build_server


def _png(width: int, height: int, color: str = "white") -> bytes:
    output = io.BytesIO()
    PILImage.new("RGB", (width, height), color).save(output, format="PNG")
    return output.getvalue()


def _image(region: Rect) -> Image:
    return Image(
        png=_png(region.w, region.h),
        width=region.w,
        height=region.h,
        scale=1.0,
        displays=[Display("1", Rect(0, 0, 1920, 1080), 1.0, True)],
    )


class RegionDriver:
    def __init__(self, *, windows: list[Window] | None = None) -> None:
        self.region: Rect | None = None
        self._windows = windows if windows is not None else []

    def capture_screen(self, region: Rect | None = None) -> Image:
        assert region is not None
        self.region = region
        return _image(region)

    def list_windows(self) -> list[Window]:
        return list(self._windows)


class FailingDriver(RegionDriver):
    def capture_screen(self, region: Rect | None = None) -> Image:
        raise DriverError("DRIVER_ERROR", "capture failed")


class WideDriver(RegionDriver):
    """Returns a different rectangle than the one requested."""

    def capture_screen(self, region: Rect | None = None) -> Image:
        assert region is not None
        return _image(Rect(region.x, region.y, region.w + 1, region.h))


def _vault_window() -> Window:
    owner = ProcRef(1, "vault.exe")
    return Window("1", "Vault", Rect(105, 205, 2, 2), owner, [owner], False)


def _content(result: object) -> list[object]:
    return list(result[0] if isinstance(result, tuple) else result)


@pytest.mark.parametrize(
    "values",
    [(-1, 0, 1, 1), (0, -1, 1, 1), (0, 0, 0, 1), (0, 0, 1, 0), (0, 0, 2001, 2000)],
)
def test_capture_region_rejects_invalid_or_oversized_bounds(
    values: tuple[int, int, int, int],
) -> None:
    with pytest.raises(CaptureError):
        validate_region(*values)


def test_capture_region_accepts_the_largest_reviewed_rectangle() -> None:
    assert validate_region(0, 0, MAX_CAPTURE_PIXELS, 1) == Rect(0, 0, MAX_CAPTURE_PIXELS, 1)


def test_capture_envelope_describes_the_crop_and_the_bytes_the_caller_receives() -> None:
    region = Rect(100, 200, 10, 20)
    png = _png(10, 20)

    payload = json.loads(serialize_capture(_image(region), region, png))

    assert payload["source"] == "image"
    assert payload["scope"] == {"display": "primary", "region": [100, 200, 10, 20]}
    assert payload["coordinate_space"] == "primary_display_physical_pixels"
    assert payload["crop_origin"] == [100, 200]
    assert (payload["width"], payload["height"]) == (10, 20)
    assert payload["encoded_bytes"] == len(png)
    assert payload["complete"] is True and payload["truncated"] is False


def test_capture_envelope_digest_follows_the_redacted_bytes() -> None:
    region = Rect(0, 0, 4, 4)
    image = _image(region)

    original = json.loads(serialize_capture(image, region, image.png))
    redacted = json.loads(serialize_capture(image, region, _png(4, 4, "black")))

    assert original["image_digest"] != redacted["image_digest"]


def test_capture_envelope_rejects_a_driver_rectangle_that_is_not_the_request() -> None:
    region = Rect(0, 0, 4, 4)

    with pytest.raises(CaptureError, match="CAPTURE_MISMATCH"):
        serialize_capture(_image(Rect(0, 0, 5, 4)), region, _png(5, 4))


def test_capture_envelope_rejects_an_oversized_encoding() -> None:
    region = Rect(0, 0, 4, 4)

    with pytest.raises(CaptureError, match="CAPTURE_IMAGE_TOO_LARGE"):
        serialize_capture(_image(region), region, b"x" * (MAX_CAPTURE_PNG_BYTES + 1))


def test_server_capture_region_returns_an_envelope_and_the_redacted_crop(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("CUMCP_REDACT_TITLES", "KeePass, Vault")
    driver = RegionDriver(windows=[_vault_window()])
    server = build_server(
        driver=driver,
        start_estop=False,
        audit_path=tmp_path / "audit.jsonl",
    )

    content = _content(
        asyncio.run(server.call_tool("capture_region", {"x": 100, "y": 200, "w": 10, "h": 10}))
    )
    payload = json.loads(getattr(content[0], "text", ""))

    assert driver.region == Rect(100, 200, 10, 10)
    assert payload["crop_origin"] == [100, 200]
    assert getattr(content[1], "type", None) == "image"
    blacked = PILImage.open(io.BytesIO(base64.b64decode(content[1].data))).convert("RGB")
    assert blacked.getpixel((5, 5)) == (0, 0, 0)
    assert blacked.getpixel((4, 4)) == (255, 255, 255)


def test_server_capture_region_reports_an_invalid_region_as_text_only(tmp_path) -> None:
    server = build_server(
        driver=RegionDriver(),
        start_estop=False,
        redact_titles=[],
        audit_path=tmp_path / "audit.jsonl",
    )

    content = _content(
        asyncio.run(server.call_tool("capture_region", {"x": 0, "y": 0, "w": 0, "h": 10}))
    )

    assert len(content) == 1
    assert getattr(content[0], "text", "").startswith("ERROR CAPTURE_INVALID_REGION")


def test_server_capture_region_reports_a_driver_failure_as_text_only(tmp_path) -> None:
    server = build_server(
        driver=FailingDriver(),
        start_estop=False,
        redact_titles=[],
        audit_path=tmp_path / "audit.jsonl",
    )

    content = _content(
        asyncio.run(server.call_tool("capture_region", {"x": 0, "y": 0, "w": 4, "h": 4}))
    )

    assert len(content) == 1
    assert getattr(content[0], "text", "").startswith("ERROR DRIVER_ERROR")


def test_server_capture_region_refuses_a_crop_the_driver_widened(tmp_path) -> None:
    server = build_server(
        driver=WideDriver(),
        start_estop=False,
        redact_titles=[],
        audit_path=tmp_path / "audit.jsonl",
    )

    content = _content(
        asyncio.run(server.call_tool("capture_region", {"x": 0, "y": 0, "w": 4, "h": 4}))
    )

    assert len(content) == 1
    assert getattr(content[0], "text", "").startswith("ERROR CAPTURE_MISMATCH")
