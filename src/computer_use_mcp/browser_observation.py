"""Bounded, read-only observation of an explicitly configured Chromium CDP session.

This module deliberately exposes no navigation, evaluation, cookies, storage,
download, or browser-action method. Browser content is untrusted observation;
desktop side effects continue through the existing Driver/Runner path.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit, urlunsplit

DEFAULT_CDP_ENDPOINT = "http://127.0.0.1:9222"
DEFAULT_TIMEOUT_SECONDS = 5.0
DEFAULT_MAX_CHARS = 50_000
MAX_PAGES = 32
MAX_FRAMES = 32
ARIA_DEPTH = 12
DETAILS = frozenset({"semantic", "text", "both"})


class BrowserObservationError(RuntimeError):
    """One fixed, non-sensitive browser observation failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _safe_url(value: object) -> str:
    """Remove credentials, query, and fragment before browser metadata leaves the tool."""

    if not isinstance(value, str) or not value:
        return ""
    try:
        parsed = urlsplit(value)
    except ValueError:
        return ""
    if parsed.scheme not in {"http", "https", "about", "chrome", "edge"}:
        return ""
    hostname = parsed.hostname or ""
    if parsed.scheme in {"http", "https"} and not hostname:
        return ""
    try:
        parsed_port = parsed.port
    except ValueError:
        return ""
    port = f":{parsed_port}" if parsed_port is not None else ""
    netloc = f"{hostname}{port}" if hostname else ""
    return urlunsplit((parsed.scheme, netloc, parsed.path[:2048], "", ""))


def _bounded_text(value: object, limit: int) -> tuple[str, bool]:
    text = value if isinstance(value, str) else ""
    if len(text) <= limit:
        return text, False
    return text[:limit], True


class DisabledBrowserObserver:
    async def snapshot(self, *, page_index: int, detail: str) -> str:
        del page_index, detail
        raise BrowserObservationError("BROWSER_OBSERVATION_UNAVAILABLE")


class FailingBrowserObserver:
    def __init__(self, code: str) -> None:
        self.code = code

    async def snapshot(self, *, page_index: int, detail: str) -> str:
        del page_index, detail
        raise BrowserObservationError(self.code)


def _loopback_cdp_endpoint(value: str) -> bool:
    try:
        endpoint = urlsplit(value)
        port = endpoint.port
    except ValueError:
        return False
    return (
        endpoint.scheme in {"http", "ws"}
        and endpoint.hostname in {"127.0.0.1", "localhost", "::1"}
        and port is not None
        and endpoint.username is None
        and endpoint.password is None
        and not endpoint.query
        and not endpoint.fragment
    )


class PlaywrightCDPBrowserObserver:
    """Lazy CDP reader. The attached browser is never closed or mutated here."""

    def __init__(
        self,
        endpoint: str,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_chars: int = DEFAULT_MAX_CHARS,
    ) -> None:
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds
        self.max_chars = max_chars
        self._playwright: Any | None = None
        self._browser: Any | None = None

    async def _reset_connection(self) -> None:
        playwright = self._playwright
        self._playwright = None
        self._browser = None
        if playwright is not None:
            try:
                await playwright.stop()
            except Exception:
                pass

    async def _pages(self) -> list[Any]:
        try:
            if self._browser is None or not self._browser.is_connected():
                await self._reset_connection()
                from playwright.async_api import async_playwright

                self._playwright = await async_playwright().start()
                self._browser = await self._playwright.chromium.connect_over_cdp(
                    self.endpoint,
                    timeout=self.timeout_seconds * 1000,
                    is_local=True,
                    no_defaults=True,
                )
            pages = [page for context in self._browser.contexts for page in context.pages]
        except ImportError as exc:
            raise BrowserObservationError("BROWSER_PLAYWRIGHT_NOT_INSTALLED") from exc
        except Exception as exc:
            await self._reset_connection()
            raise BrowserObservationError("BROWSER_CONNECTION_FAILED") from exc
        if len(pages) > MAX_PAGES:
            pages = pages[:MAX_PAGES]
        return pages

    async def snapshot(self, *, page_index: int, detail: str) -> str:
        if detail not in DETAILS:
            raise BrowserObservationError("BROWSER_REQUEST_INVALID")
        pages = await self._pages()
        if not 0 <= page_index < len(pages):
            raise BrowserObservationError("BROWSER_PAGE_NOT_FOUND")

        selected = pages[page_index]
        try:
            title = await selected.title()
        except Exception:
            title = ""
        page_metadata = [
            {"index": index, "url": _safe_url(page.url)}
            for index, page in enumerate(pages)
        ]
        frames: list[dict[str, object]] = []
        truncated = False
        selected_frames = list(selected.frames)[:MAX_FRAMES]
        if len(selected.frames) > MAX_FRAMES:
            truncated = True
        per_field_limit = max(256, self.max_chars // max(4, len(selected_frames) * 2))
        timeout_ms = self.timeout_seconds * 1000
        for index, frame in enumerate(selected_frames):
            item: dict[str, object] = {"index": index, "url": _safe_url(frame.url)}
            body = frame.locator("body")
            if detail in {"semantic", "both"}:
                try:
                    aria = await body.aria_snapshot(
                        depth=ARIA_DEPTH,
                        mode="default",
                        timeout=timeout_ms,
                    )
                except Exception:
                    aria = ""
                item["aria"], clipped = _bounded_text(aria, per_field_limit)
                truncated = truncated or clipped
            if detail in {"text", "both"}:
                try:
                    visible_text = await body.inner_text(timeout=timeout_ms)
                except Exception:
                    visible_text = ""
                item["visible_text"], clipped = _bounded_text(
                    visible_text, per_field_limit
                )
                truncated = truncated or clipped
            frames.append(item)

        payload: dict[str, object] = {
            "version": 1,
            "source": "playwright_cdp_read_only",
            "action_backend": "os_input_only",
            "content_trust": "untrusted_web_content",
            "pages": page_metadata,
            "selected_page": {
                "index": page_index,
                "url": _safe_url(selected.url),
                "title": _bounded_text(title, 512)[0],
            },
            "frames": frames,
            "truncated": truncated,
        }
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        while len(encoded) > self.max_chars and frames:
            frames.pop()
            payload["truncated"] = True
            encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if len(encoded) > self.max_chars:
            raise BrowserObservationError("BROWSER_RESULT_TOO_LARGE")
        return encoded


def configured_browser_observer(
    environment: Mapping[str, str],
) -> DisabledBrowserObserver | FailingBrowserObserver | PlaywrightCDPBrowserObserver:
    mode = environment.get("CUMCP_BROWSER_OBSERVATION", "off").strip().lower()
    if mode != "cdp":
        return DisabledBrowserObserver()
    endpoint = environment.get("CUMCP_BROWSER_CDP_ENDPOINT", DEFAULT_CDP_ENDPOINT)
    if not _loopback_cdp_endpoint(endpoint):
        return FailingBrowserObserver("BROWSER_ENDPOINT_INVALID")
    return PlaywrightCDPBrowserObserver(endpoint)


__all__ = [
    "BrowserObservationError",
    "DisabledBrowserObserver",
    "FailingBrowserObserver",
    "PlaywrightCDPBrowserObserver",
    "configured_browser_observer",
]
