"""Opt-in local privacy boundary for provider-facing Agent data.

The package is disabled by default through :class:`PrivacyConfig`. Its public
surface keeps the runner independent from text detectors, OCR, image rendering,
and any future non-text visual backend.
"""

from .core import (
    IMAGE_TOKEN_PATTERN,
    TOKEN_PATTERN,
    TOKEN_PREFIX,
    PrivacyError,
    PrivacySession,
    ProtectedTextSpan,
)
from .image import (
    SUPPORTED_VISUAL_PRIVACY_KINDS,
    LocalPrivacyImageRedactor,
    PrivacyImageRecognizer,
    PrivacyImageRedactionPort,
    PrivacyVisualDetector,
    RecognizedImageText,
    VisualPrivacyRegion,
    WindowsPrivacyImageRecognizer,
)

__all__ = [
    "IMAGE_TOKEN_PATTERN",
    "LocalPrivacyImageRedactor",
    "PrivacyError",
    "PrivacyImageRecognizer",
    "PrivacyImageRedactionPort",
    "PrivacySession",
    "PrivacyVisualDetector",
    "ProtectedTextSpan",
    "RecognizedImageText",
    "SUPPORTED_VISUAL_PRIVACY_KINDS",
    "TOKEN_PATTERN",
    "TOKEN_PREFIX",
    "VisualPrivacyRegion",
    "WindowsPrivacyImageRecognizer",
]
