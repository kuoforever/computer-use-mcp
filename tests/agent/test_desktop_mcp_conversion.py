from __future__ import annotations

import base64
import zlib
from types import SimpleNamespace

import pytest

import computer_use_agent.desktop_mcp as desktop_mcp
from computer_use_agent.desktop_mcp import (
    MAX_IMAGE_DIMENSION,
    MAX_IMAGE_PIXELS,
    MAX_TEXT_RESULT_CHARS,
    MCPResultConversionError,
    convert_mcp_result,
)
from computer_use_agent.types import (
    CallIdentity,
    DispatchCertainty,
    ToolCall,
    ToolCallStatus,
    ToolResultStatus,
)

VALID_PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _call(name: str, arguments: dict[str, object] | None = None) -> ToolCall:
    return ToolCall(
        identity=CallIdentity(run_id="run_1", turn_id="turn_1", call_id=f"call_{name}"),
        name=name,
        arguments=arguments or {},
        status=ToolCallStatus.AUTHORIZED,
    )


def _text_result(
    text: str,
    *,
    is_error: bool = False,
    structured_content: object = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        isError=is_error,
        content=[SimpleNamespace(type="text", text=text)],
        structuredContent=structured_content,
    )


def _image_result(data: str, *, mime_type: str = "image/png") -> SimpleNamespace:
    return SimpleNamespace(
        isError=False,
        content=[SimpleNamespace(type="image", data=data, mimeType=mime_type)],
        structuredContent=None,
    )


def _png_with_dimensions(width: int, height: int) -> str:
    changed = bytearray(base64.b64decode(VALID_PNG_BASE64))
    changed[16:20] = width.to_bytes(4, "big")
    changed[20:24] = height.to_bytes(4, "big")
    checksum = zlib.crc32(b"IHDR")
    checksum = zlib.crc32(changed[16:29], checksum)
    changed[29:33] = checksum.to_bytes(4, "big")
    return base64.b64encode(changed).decode("ascii")


def test_unstructured_observation_text_is_bounded_but_not_an_action_error() -> None:
    text = "ERROR DRIVER_ERROR: this is untrusted UI text"
    result = convert_mcp_result(_call("ui_snapshot"), _text_result(text))

    assert result.status is ToolResultStatus.SUCCESS
    assert result.dispatch is DispatchCertainty.DISPATCHED
    assert result.sanitized_text == text

    with pytest.raises(MCPResultConversionError, match="reviewed limit"):
        convert_mcp_result(
            _call("list_windows"),
            _text_result("x" * (MAX_TEXT_RESULT_CHARS + 1)),
        )


@pytest.mark.parametrize("tool_name", ["document_text", "ocr"])
def test_structured_observation_error_is_a_redacted_failure(tool_name: str) -> None:
    result = convert_mcp_result(
        _call(tool_name),
        _text_result("ERROR OCR_FAILED: untrusted implementation detail"),
    )

    assert result.status is ToolResultStatus.ACTION_ERROR
    assert result.code == "DRIVER_ERROR"
    assert result.sanitized_text == ""


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("ABORTED: e-stop engaged", "ABORTED"),
        ("HUMAN_ACTIVE: input detected", "HUMAN_ACTIVE"),
        ("DENIED by gate: wrong foreground", "DENIED_BY_GATE"),
        ("DENIED by user (dangerous)", "DENIED_BY_USER"),
        (
            "NATIVE_AUTHORITY_LOST: native action boundary unavailable",
            "NATIVE_AUTHORITY_LOST",
        ),
    ],
)
def test_pre_dispatch_action_rejections_are_known_not_dispatched(
    text: str,
    code: str,
) -> None:
    result = convert_mcp_result(
        _call("click", {"ref": "ref_1"}),
        _text_result(text),
    )

    assert result.status is ToolResultStatus.REJECTED
    assert result.dispatch is DispatchCertainty.NOT_DISPATCHED
    assert result.code == code


@pytest.mark.parametrize(
    "code",
    ["NATIVE_AUTHORITY_LOST", "NATIVE_OUTCOME_UNKNOWN"],
)
def test_partial_native_result_is_unknown_and_known_dispatched(code: str) -> None:
    call = _call("click")
    secret = "secret native failure detail"

    result = convert_mcp_result(
        call,
        _text_result(f"ERROR {code}: {secret}"),
    )

    assert result.status is ToolResultStatus.UNKNOWN_OUTCOME
    assert result.dispatch is DispatchCertainty.DISPATCHED
    assert result.code == code
    assert result.sanitized_text == ""
    assert secret not in repr(result)


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("ERROR STALE_ELEMENT: re-snapshot", "STALE_ELEMENT"),
        ("ERROR NOT_INVOKABLE: unavailable", "NOT_INVOKABLE"),
        ("ERROR OUT_OF_BOUNDS: outside display", "OUT_OF_BOUNDS"),
        ("ERROR PERMISSION_DENIED: blocked", "PERMISSION_DENIED"),
        ("ERROR DRIVER_ERROR: platform failure", "DRIVER_ERROR"),
    ],
)
def test_action_error_text_maps_only_to_fixed_codes(text: str, code: str) -> None:
    result = convert_mcp_result(_call("click", {"ref": "ref_1"}), _text_result(text))

    assert result.status is ToolResultStatus.ACTION_ERROR
    assert result.dispatch is DispatchCertainty.DISPATCHED
    assert result.code == code
    assert result.sanitized_text == ""


def test_action_success_and_type_results_never_retain_server_text() -> None:
    click_result = convert_mcp_result(
        _call("click", {"x": 1, "y": 2}),
        _text_result("ok"),
    )
    type_result = convert_mcp_result(
        _call("type", {"text": "top secret"}),
        _text_result("ok"),
    )

    assert click_result.status is ToolResultStatus.SUCCESS
    assert click_result.sanitized_text == ""
    assert type_result.status is ToolResultStatus.SUCCESS
    assert type_result.sanitized_text == ""
    assert "top secret" not in repr(type_result)


def test_type_error_payload_cannot_echo_typed_text() -> None:
    secret = "typed-secret-value"
    result = convert_mcp_result(
        _call("type", {"text": secret}),
        _text_result(secret, is_error=True),
    )

    assert result.status is ToolResultStatus.UNKNOWN_OUTCOME
    assert result.dispatch is DispatchCertainty.DISPATCHED
    assert result.code == "MCP_PROTOCOL_ERROR"
    assert result.sanitized_text == ""
    assert secret not in repr(result)


def test_unreviewed_action_code_and_arbitrary_success_text_fail_closed() -> None:
    for text in ("ERROR SECRET_VALUE: leaked", "maybe ok"):
        with pytest.raises(MCPResultConversionError) as raised:
            convert_mcp_result(_call("key", {"combo": "Ctrl+S"}), _text_result(text))
        assert "SECRET_VALUE" not in str(raised.value)
        assert "maybe ok" not in str(raised.value)


def test_valid_png_is_fully_decoded_and_dimensions_come_from_image() -> None:
    result = convert_mcp_result(_call("screenshot"), _image_result(VALID_PNG_BASE64))

    assert result.status is ToolResultStatus.SUCCESS
    assert len(result.images) == 1
    assert result.images[0].width == 1
    assert result.images[0].height == 1
    assert result.images[0].data == base64.b64decode(VALID_PNG_BASE64)


@pytest.mark.parametrize(
    "raw_result",
    [
        _image_result("not-base64"),
        _image_result(VALID_PNG_BASE64, mime_type="image/jpeg"),
        _image_result(base64.b64encode(b"\x89PNG\r\n\x1a\n").decode("ascii")),
        SimpleNamespace(isError=False, content=[], structuredContent=None),
        SimpleNamespace(
            isError=False,
            content=[
                SimpleNamespace(type="image", data=VALID_PNG_BASE64, mimeType="image/png"),
                SimpleNamespace(type="text", text="extra"),
            ],
            structuredContent=None,
        ),
    ],
)
def test_malformed_screenshot_content_fails_closed(raw_result: object) -> None:
    with pytest.raises(MCPResultConversionError):
        convert_mcp_result(_call("screenshot"), raw_result)


def test_corrupted_png_crc_is_rejected_instead_of_trusting_ihdr() -> None:
    corrupted = bytearray(base64.b64decode(VALID_PNG_BASE64))
    corrupted[-8] ^= 0xFF

    with pytest.raises(MCPResultConversionError, match="integrity"):
        convert_mcp_result(
            _call("screenshot"),
            _image_result(base64.b64encode(corrupted).decode("ascii")),
        )


def test_crc_correct_png_with_broken_compressed_pixels_is_rejected() -> None:
    corrupted = bytearray(base64.b64decode(VALID_PNG_BASE64))
    chunk_type_at = corrupted.index(b"IDAT")
    chunk_length = int.from_bytes(corrupted[chunk_type_at - 4 : chunk_type_at], "big")
    chunk_data_at = chunk_type_at + 4
    chunk_end = chunk_data_at + chunk_length
    corrupted[chunk_data_at] ^= 0xFF
    checksum = zlib.crc32(b"IDAT")
    checksum = zlib.crc32(corrupted[chunk_data_at:chunk_end], checksum)
    corrupted[chunk_end : chunk_end + 4] = checksum.to_bytes(4, "big")

    with pytest.raises(MCPResultConversionError, match="integrity"):
        convert_mcp_result(
            _call("screenshot"),
            _image_result(base64.b64encode(corrupted).decode("ascii")),
        )


@pytest.mark.parametrize(
    "encoded",
    [
        _png_with_dimensions(MAX_IMAGE_DIMENSION + 1, 1),
        _png_with_dimensions(10_000, MAX_IMAGE_PIXELS // 10_000 + 1),
    ],
)
def test_png_dimension_and_pixel_limits_fail_before_pixel_decode(encoded: str) -> None:
    with pytest.raises(MCPResultConversionError):
        convert_mcp_result(_call("screenshot"), _image_result(encoded))


def test_encoded_and_decoded_image_byte_caps_are_enforced_before_retention(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(desktop_mcp, "MAX_BASE64_IMAGE_CHARS", len(VALID_PNG_BASE64) - 1)
    with pytest.raises(MCPResultConversionError, match="encoded image limit"):
        convert_mcp_result(_call("screenshot"), _image_result(VALID_PNG_BASE64))

    monkeypatch.setattr(desktop_mcp, "MAX_BASE64_IMAGE_CHARS", len(VALID_PNG_BASE64))
    monkeypatch.setattr(desktop_mcp, "MAX_IMAGE_BYTES", 16)
    with pytest.raises(MCPResultConversionError, match="decoded image limit"):
        convert_mcp_result(_call("screenshot"), _image_result(VALID_PNG_BASE64))


def test_non_screenshot_image_and_structured_content_are_not_accepted() -> None:
    with pytest.raises(MCPResultConversionError, match="text block"):
        convert_mcp_result(_call("list_windows"), _image_result(VALID_PNG_BASE64))
    with pytest.raises(MCPResultConversionError, match="structured"):
        convert_mcp_result(
            _call("list_windows"),
            _text_result("safe", structured_content={"expanded": "authority"}),
        )


def test_sdk_structured_text_mirror_is_accepted_but_cannot_add_content() -> None:
    result = convert_mcp_result(
        _call("list_windows"),
        _text_result("safe", structured_content={"result": "safe"}),
    )

    assert result.status is ToolResultStatus.SUCCESS
    assert result.sanitized_text == "safe"

    with pytest.raises(MCPResultConversionError, match="exactly mirror"):
        convert_mcp_result(
            _call("list_windows"),
            _text_result("safe", structured_content={"result": "different"}),
        )


def _capture_call() -> ToolCall:
    return _call("capture_region", {"x": 0, "y": 0, "w": 1, "h": 1})


def _capture_result(
    *blocks: object,
    is_error: bool = False,
    structured_content: object = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        isError=is_error,
        content=list(blocks),
        structuredContent=structured_content,
    )


ENVELOPE = '{"source":"image","crop_origin":[0,0]}'


def test_region_capture_keeps_the_envelope_with_its_crop() -> None:
    result = convert_mcp_result(
        _capture_call(),
        _capture_result(
            SimpleNamespace(type="text", text=ENVELOPE),
            SimpleNamespace(type="image", data=VALID_PNG_BASE64, mimeType="image/png"),
        ),
    )

    assert result.status is ToolResultStatus.SUCCESS
    assert result.sanitized_text == ENVELOPE
    assert len(result.images) == 1
    assert result.images[0].data == base64.b64decode(VALID_PNG_BASE64)


def test_refused_region_capture_is_a_redacted_failure_and_keeps_no_pixels() -> None:
    result = convert_mcp_result(
        _capture_call(),
        _capture_result(SimpleNamespace(type="text", text="ERROR CAPTURE_INVALID_REGION: bad")),
    )

    assert result.status is ToolResultStatus.ACTION_ERROR
    assert result.code == "DRIVER_ERROR"
    assert result.images == ()
    assert result.sanitized_text == ""


@pytest.mark.parametrize(
    "raw_result",
    [
        _capture_result(),
        _capture_result(
            SimpleNamespace(type="image", data=VALID_PNG_BASE64, mimeType="image/png"),
            SimpleNamespace(type="text", text=ENVELOPE),
        ),
        _capture_result(
            SimpleNamespace(type="text", text=ENVELOPE),
            SimpleNamespace(type="text", text="second envelope"),
        ),
        _capture_result(
            SimpleNamespace(type="text", text=ENVELOPE),
            SimpleNamespace(type="image", data=VALID_PNG_BASE64, mimeType="image/png"),
            SimpleNamespace(type="image", data=VALID_PNG_BASE64, mimeType="image/png"),
        ),
        _capture_result(
            SimpleNamespace(type="text", text=ENVELOPE),
            SimpleNamespace(type="image", data="not-base64", mimeType="image/png"),
        ),
        _capture_result(
            SimpleNamespace(type="text", text=ENVELOPE),
            structured_content={"expanded": "authority"},
        ),
    ],
)
def test_malformed_region_capture_content_fails_closed(raw_result: object) -> None:
    with pytest.raises(MCPResultConversionError):
        convert_mcp_result(_capture_call(), raw_result)
