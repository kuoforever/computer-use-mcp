from __future__ import annotations

import asyncio
import json
import pytest

from computer_use_mcp.browser_observation import (
    BrowserObservationError,
    PlaywrightCDPBrowserObserver,
    configured_browser_observer,
)
from computer_use_mcp.server import build_server


class _Locator:
    async def aria_snapshot(self, **kwargs: object) -> str:
        assert kwargs == {"depth": 12, "mode": "default", "timeout": 5000.0}
        return '- button "Continue"'

    async def inner_text(self, **kwargs: object) -> str:
        assert kwargs == {"timeout": 5000.0}
        return "Rendered by JavaScript"


class _Frame:
    def __init__(self, url: str) -> None:
        self.url = url

    def locator(self, selector: str) -> _Locator:
        assert selector == "body"
        return _Locator()


class _Page:
    def __init__(self, url: str) -> None:
        self.url = url
        self.frames = [_Frame(url), _Frame("https://frame.example/path?token=hidden")]

    async def title(self) -> str:
        return "Rendered page"


class _Observer(PlaywrightCDPBrowserObserver):
    async def _pages(self) -> list[_Page]:
        return [
            _Page("https://example.com/app?token=hidden#fragment"),
            _Page("https://example.com/other"),
        ]


def test_playwright_snapshot_reads_rendered_semantics_without_action_refs() -> None:
    observer = _Observer("http://127.0.0.1:9222", timeout_seconds=5.0, max_chars=20_000)

    payload = json.loads(asyncio.run(observer.snapshot(page_index=0, detail="both")))

    assert payload["version"] == 1
    assert payload["source"] == "playwright_cdp_read_only"
    assert payload["action_backend"] == "os_input_only"
    assert payload["selected_page"]["url"] == "https://example.com/app"
    assert payload["pages"][1]["url"] == "https://example.com/other"
    assert payload["frames"][0]["visible_text"] == "Rendered by JavaScript"
    assert payload["frames"][0]["aria"] == '- button "Continue"'
    assert payload["frames"][1]["url"] == "https://frame.example/path"
    assert "token=hidden" not in json.dumps(payload)
    assert "[ref=" not in json.dumps(payload)


def test_browser_observer_is_disabled_by_default_and_fails_once_with_fixed_code() -> None:
    observer = configured_browser_observer({})

    with pytest.raises(BrowserObservationError) as raised:
        asyncio.run(observer.snapshot(page_index=0, detail="semantic"))

    assert raised.value.code == "BROWSER_OBSERVATION_UNAVAILABLE"


def test_direct_server_configuration_rejects_non_loopback_cdp_without_connecting() -> None:
    observer = configured_browser_observer(
        {
            "CUMCP_BROWSER_OBSERVATION": "cdp",
            "CUMCP_BROWSER_CDP_ENDPOINT": "http://example.com:9222",
        }
    )

    with pytest.raises(BrowserObservationError) as raised:
        asyncio.run(observer.snapshot(page_index=0, detail="text"))

    assert raised.value.code == "BROWSER_ENDPOINT_INVALID"


def test_playwright_snapshot_rejects_out_of_range_page_without_fallback() -> None:
    observer = _Observer("http://127.0.0.1:9222", timeout_seconds=5.0, max_chars=20_000)

    with pytest.raises(BrowserObservationError) as raised:
        asyncio.run(observer.snapshot(page_index=7, detail="text"))

    assert raised.value.code == "BROWSER_PAGE_NOT_FOUND"


def test_mcp_browser_tool_delegates_only_the_reviewed_read_request() -> None:
    calls: list[tuple[int, str]] = []

    class Observer:
        async def snapshot(self, *, page_index: int, detail: str) -> str:
            calls.append((page_index, detail))
            return '{"source":"playwright_cdp_read_only"}'

    server = build_server(
        driver=object(),
        start_estop=False,
        browser_observer=Observer(),
        browser_observation_enabled=True,
    )

    result = asyncio.run(
        server.call_tool("browser_snapshot", {"page_index": 2, "detail": "text"})
    )
    content = result[0] if isinstance(result, tuple) else result.content
    text = "\n".join(getattr(item, "text", "") for item in content)

    assert calls == [(2, "text")]
    assert text == '{"source":"playwright_cdp_read_only"}'
