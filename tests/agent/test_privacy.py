from __future__ import annotations

import asyncio
import io

from PIL import Image as PILImage

from computer_use_agent.config import PrivacyConfig
from computer_use_agent.privacy import (
    LocalPrivacyImageRedactor,
    PrivacyError,
    PrivacySession,
    RecognizedImageText,
    TOKEN_PATTERN,
    VisualPrivacyRegion,
)
from computer_use_agent.types import (
    CallIdentity,
    DispatchCertainty,
    ImageContent,
    ToolCall,
    ToolResult,
    ToolResultStatus,
)


def _session(
    *, terms: tuple[str, ...] = (), image_redaction: bool = True
) -> PrivacySession:
    return PrivacySession(
        PrivacyConfig(
            enabled=True,
            terms=terms,
            image_redaction=image_redaction,
        ),
        "run_privacy",
    )


def _image(width: int = 220, height: int = 60) -> ImageContent:
    output = io.BytesIO()
    PILImage.new("RGB", (width, height), "white").save(output, format="PNG")
    return ImageContent("image/png", output.getvalue(), width, height)


class _ImageRecognizer:
    def __init__(self, runs: tuple[RecognizedImageText, ...]) -> None:
        self.runs = runs
        self.calls = 0

    async def recognize(self, image: ImageContent) -> tuple[RecognizedImageText, ...]:
        self.calls += 1
        return self.runs


def test_reversible_entities_are_stable_within_one_run_and_restore_locally() -> None:
    privacy = _session(terms=("Project Phoenix",))
    raw = (
        "Project Phoenix: alice@example.com, 13800138000, "
        "server 192.168.1.8; repeat alice@example.com"
    )

    protected = privacy.protect_text(raw)

    assert raw != protected
    assert "alice@example.com" not in protected
    assert "13800138000" not in protected
    assert "192.168.1.8" not in protected
    assert "Project Phoenix" not in protected
    email_tokens = [
        match.group(0) for match in TOKEN_PATTERN.finditer(protected)
        if match.group(1) == "EMAIL"
    ]
    assert len(email_tokens) == 2
    assert email_tokens[0] == email_tokens[1]
    assert privacy.restore_text(protected) == raw


def test_checksum_validated_identity_and_bank_card_numbers_are_protected() -> None:
    privacy = _session()
    cn_id = "11010519491231002X"
    bank_card = "4111 1111 1111 1111"

    protected = privacy.protect_text(f"ID {cn_id}; card {bank_card}")

    assert cn_id not in protected
    assert bank_card not in protected
    assert "[[PRIVATE:CN_ID:" in protected
    assert "[[PRIVATE:BANK_CARD:" in protected
    assert privacy.restore_text(protected) == f"ID {cn_id}; card {bank_card}"
    invalid = "110105194902310021 and 4111111111111112"
    assert privacy.protect_text(invalid) == invalid


def test_assigned_secrets_are_never_restored_into_final_text() -> None:
    privacy = _session()

    protected = privacy.protect_text("api_key=sk-local-secret")
    restored = privacy.restore_text(f"Use {protected}")

    assert "sk-local-secret" not in protected
    assert "sk-local-secret" not in restored
    assert "[[PRIVATE:SECRET:" in restored


def test_reserved_and_forged_tokens_fail_closed() -> None:
    privacy = _session()

    try:
        privacy.protect_text("untrusted [[PRIVATE:EMAIL:00000000000000000000000000000000]]")
    except PrivacyError as exc:
        assert str(exc) == "PRIVACY_RESERVED_TOKEN_INPUT"
    else:
        raise AssertionError("reserved input token was accepted")

    try:
        privacy.restore_text("[[PRIVATE:EMAIL:00000000000000000000000000000000]]")
    except PrivacyError as exc:
        assert str(exc) == "PRIVACY_TOKEN_INVALID"
    else:
        raise AssertionError("forged model token was accepted")


def test_only_find_can_resolve_reversible_tokens_for_local_dispatch() -> None:
    privacy = _session()
    protected = privacy.protect_text("alice@example.com")
    identity = CallIdentity("run_privacy", "turn_1", "call_1")
    find_call = ToolCall(identity, "find", {"query": protected, "scope": "foreground"})

    resolved = privacy.resolve_local_call(find_call)

    assert resolved.arguments["query"] == "alice@example.com"
    click_call = ToolCall(identity, "click", {"ref": protected})
    try:
        privacy.resolve_local_call(click_call)
    except PrivacyError as exc:
        assert str(exc) == "PRIVACY_TOOL_RESTORE_DENIED"
    else:
        raise AssertionError("token was restored for an unreviewed tool sink")


def test_text_only_privacy_mode_rejects_screenshot_requests() -> None:
    privacy = _session(image_redaction=False)
    call = ToolCall(
        CallIdentity("run_privacy", "turn_1", "call_image"),
        "screenshot",
        {},
    )

    try:
        privacy.validate_tool_call(call)
    except PrivacyError as exc:
        assert str(exc) == "PRIVACY_IMAGE_OBSERVATION_DENIED"
    else:
        raise AssertionError("screenshot was allowed in text-only privacy mode")


def test_tool_result_is_protected_before_it_reaches_the_ledger() -> None:
    privacy = _session()
    result = ToolResult(
        identity=CallIdentity("run_privacy", "turn_1", "call_1"),
        tool_name="list_windows",
        status=ToolResultStatus.SUCCESS,
        dispatch=DispatchCertainty.DISPATCHED,
        sanitized_text="Owner alice@example.com",
    )

    protected = privacy.protect_result(result)

    assert "alice@example.com" not in protected.sanitized_text
    assert privacy.restore_text(protected.sanitized_text) == result.sanitized_text


def test_screenshot_ocr_boxes_are_blacked_out_without_changing_coordinates() -> None:
    privacy = _session()
    image = _image()
    recognizer = _ImageRecognizer(
        (RecognizedImageText("alice@example.com", 20, 15, 140, 22),)
    )
    result = ToolResult(
        identity=CallIdentity("run_privacy", "turn_1", "call_image"),
        tool_name="screenshot",
        status=ToolResultStatus.SUCCESS,
        dispatch=DispatchCertainty.DISPATCHED,
        images=(image,),
    )

    protected = asyncio.run(LocalPrivacyImageRedactor(recognizer).redact(result, privacy))

    assert recognizer.calls == 1
    assert protected.images[0].data != image.data
    assert (protected.images[0].width, protected.images[0].height) == (220, 60)
    rendered = PILImage.open(io.BytesIO(protected.images[0].data)).convert("RGB")
    assert rendered.getpixel((18, 35)) == (0, 0, 0)
    assert rendered.getpixel((5, 5)) == (255, 255, 255)
    assert privacy.restore_text("Found [EMAIL#1]") == "Found alice@example.com"


def test_screenshot_secret_label_remains_opaque_and_invalid_boxes_fail_closed() -> None:
    privacy = _session()
    image = _image()
    secret_result = ToolResult(
        identity=CallIdentity("run_privacy", "turn_1", "call_secret"),
        tool_name="screenshot",
        status=ToolResultStatus.SUCCESS,
        dispatch=DispatchCertainty.DISPATCHED,
        images=(image,),
    )
    secret_reader = _ImageRecognizer(
        (RecognizedImageText("api_key=local-secret", 10, 10, 120, 20),)
    )

    asyncio.run(LocalPrivacyImageRedactor(secret_reader).redact(secret_result, privacy))

    assert privacy.restore_text("Visible [SECRET#1]") == "Visible [SECRET#1]"
    invalid_reader = _ImageRecognizer(
        (RecognizedImageText("alice@example.com", 200, 10, 30, 20),)
    )
    try:
        asyncio.run(LocalPrivacyImageRedactor(invalid_reader).redact(secret_result, privacy))
    except PrivacyError as exc:
        assert str(exc) == "PRIVACY_IMAGE_ANALYSIS_INVALID"
    else:
        raise AssertionError("out-of-bounds OCR box was accepted")


def test_screenshot_joins_adjacent_words_on_one_line_and_maps_exact_boxes() -> None:
    privacy = _session(terms=("Project Phoenix",))
    image = _image(420, 150)
    result = ToolResult(
        identity=CallIdentity("run_privacy", "turn_1", "call_joined"),
        tool_name="screenshot",
        status=ToolResultStatus.SUCCESS,
        dispatch=DispatchCertainty.DISPATCHED,
        images=(image,),
    )
    reader = _ImageRecognizer(
        (
            RecognizedImageText("alice", 10, 10, 60, 20),
            RecognizedImageText("@", 74, 10, 12, 20),
            RecognizedImageText("example.com", 90, 10, 110, 20),
            RecognizedImageText("Project", 10, 50, 70, 20),
            RecognizedImageText("Phoenix", 85, 50, 70, 20),
            RecognizedImageText("api_key", 10, 90, 65, 20),
            RecognizedImageText("=", 80, 90, 10, 20),
            RecognizedImageText("local-secret", 95, 90, 100, 20),
        )
    )

    protected = asyncio.run(LocalPrivacyImageRedactor(reader).redact(result, privacy))

    assert protected.images[0].data != image.data
    assert privacy.restore_text("[EMAIL#1]") == "alice@example.com"
    assert privacy.restore_text("[TERM#2]") == "Project Phoenix"
    assert privacy.restore_text("[SECRET#3]") == "[SECRET#3]"
    rendered = PILImage.open(io.BytesIO(protected.images[0].data)).convert("RGB")
    assert rendered.getpixel((198, 28)) == (0, 0, 0)
    assert rendered.getpixel((153, 68)) == (0, 0, 0)
    assert rendered.getpixel((193, 108)) == (0, 0, 0)
    assert rendered.getpixel((300, 120)) == (255, 255, 255)


def test_screenshot_does_not_join_words_from_different_visual_lines() -> None:
    privacy = _session()
    image = _image()
    result = ToolResult(
        identity=CallIdentity("run_privacy", "turn_1", "call_lines"),
        tool_name="screenshot",
        status=ToolResultStatus.SUCCESS,
        dispatch=DispatchCertainty.DISPATCHED,
        images=(image,),
    )
    reader = _ImageRecognizer(
        (
            RecognizedImageText("alice", 10, 5, 50, 16),
            RecognizedImageText("@example.com", 10, 35, 110, 16),
        )
    )

    protected = asyncio.run(LocalPrivacyImageRedactor(reader).redact(result, privacy))

    assert protected.images[0].data == image.data


def test_optional_visual_detector_redacts_reviewed_regions_without_restoration() -> None:
    privacy = _session()
    image = _image()
    result = ToolResult(
        identity=CallIdentity("run_privacy", "turn_1", "call_visual"),
        tool_name="screenshot",
        status=ToolResultStatus.SUCCESS,
        dispatch=DispatchCertainty.DISPATCHED,
        images=(image,),
    )
    recognizer = _ImageRecognizer(())

    class Detector:
        async def detect(
            self, source: ImageContent
        ) -> tuple[VisualPrivacyRegion, ...]:
            assert source == image
            return (VisualPrivacyRegion("qr", 40, 10, 50, 30),)

    protected = asyncio.run(
        LocalPrivacyImageRedactor(
            recognizer,
            visual_detector=Detector(),
        ).redact(result, privacy)
    )

    rendered = PILImage.open(io.BytesIO(protected.images[0].data)).convert("RGB")
    assert rendered.getpixel((88, 38)) == (0, 0, 0)
    assert privacy.restore_text("[VISUAL:QR]") == "[VISUAL:QR]"
