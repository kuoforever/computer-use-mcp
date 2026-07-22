"""Fail-closed local stdio MCP bridge for the reviewed desktop tool surface.

The bridge is intentionally the only Agent Host module that imports the MCP
client SDK.  It never imports the desktop server, driver, or native automation
code.  One asyncio task owns a live child session so the SDK's async context
managers are entered and exited by the same task.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import os
import warnings
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import timedelta
from io import BytesIO
from json import dumps
from math import isfinite
from typing import Any, Protocol

from mcp import ClientSession, StdioServerParameters
from PIL import Image as PILImage

from .bounded_stdio import bounded_stdio_client
from .config import MCPLaunchConfig
from .tool_registry import (
    ResultContentKind,
    ToolRegistryMismatchError,
    ToolValidationError,
    get_tool_spec,
    validate_tool_arguments,
    validate_tool_result,
    verify_discovered_tools,
)
from .types import (
    MAX_IMAGE_BYTES,
    REVIEWED_RESULT_CODES,
    DispatchCertainty,
    ImageContent,
    MCPToolDescriptor,
    ToolCall,
    ToolCallStatus,
    ToolEffect,
    ToolResult,
    ToolResultStatus,
    to_json_value,
)

DEFAULT_MCP_TIMEOUT_SECONDS = 30.0
DEFAULT_MCP_CLOSE_TIMEOUT_SECONDS = 10.0
MAX_DISCOVERY_PAGES = 16
MAX_DISCOVERED_TOOLS = 32
MAX_SCHEMA_JSON_BYTES = 256 * 1024
MAX_TEXT_RESULT_CHARS = 1_000_000
MAX_IMAGE_DIMENSION = 16_384
MAX_IMAGE_PIXELS = 64_000_000
MAX_BASE64_IMAGE_CHARS = 4 * ((MAX_IMAGE_BYTES + 2) // 3)

_SERVER_RESULT_CODES = frozenset(
    {
        "STALE_ELEMENT",
        "NOT_INVOKABLE",
        "OUT_OF_BOUNDS",
        "PERMISSION_DENIED",
        "DRIVER_ERROR",
    }
)
_SERVER_ERROR_PREFIXES = (
    ("ABORTED:", "ABORTED"),
    ("HUMAN_ACTIVE:", "HUMAN_ACTIVE"),
    ("DENIED by gate:", "DENIED_BY_GATE"),
    ("DENIED by user", "DENIED_BY_USER"),
)


class MCPBridgeError(RuntimeError):
    """A safe startup/discovery error represented by a reviewed result code."""

    def __init__(self, code: str) -> None:
        if code not in REVIEWED_RESULT_CODES:
            raise ValueError("MCP bridge errors require a reviewed result code")
        self.code = code
        super().__init__(code)


class MCPResultConversionError(ValueError):
    """Raised when a post-dispatch MCP payload violates the reviewed contract."""


class MCPCallCancelled(asyncio.CancelledError):
    """Cancellation that carries the dispatched result for ledger recovery."""

    def __init__(self, result: ToolResult) -> None:
        if result.dispatch is DispatchCertainty.NOT_DISPATCHED:
            raise ValueError("cancelled MCP calls require a dispatched or uncertain result")
        self.result = result
        super().__init__("MCP call cancelled after dispatch began")


class _ClientSessionPort(Protocol):
    async def list_tools(self, cursor: str | None = None) -> object: ...

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        read_timeout_seconds: timedelta | None = None,
    ) -> object: ...


SessionFactory = Callable[
    [MCPLaunchConfig, float], AbstractAsyncContextManager[_ClientSessionPort]
]


@asynccontextmanager
async def _open_stdio_session(
    launch: MCPLaunchConfig,
    timeout_seconds: float,
) -> AsyncIterator[_ClientSessionPort]:
    """Open one fixed-command MCP child without a shell or provider credentials."""

    parameters = StdioServerParameters(
        command=str(launch.executable),
        args=list(launch.args),
        cwd=launch.cwd,
        env=launch.child_environment(),
        encoding="utf-8",
        encoding_error_handler="strict",
    )
    timeout = timedelta(seconds=timeout_seconds)
    with open(os.devnull, "w", encoding="utf-8") as errlog:
        async with bounded_stdio_client(parameters, errlog=errlog) as (
            read_stream,
            write_stream,
        ):
            async with ClientSession(
                read_stream,
                write_stream,
                read_timeout_seconds=timeout,
            ) as session:
                await session.initialize()
                yield session


def _validate_timeout(value: float, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be a positive finite number")
    converted = float(value)
    if not isfinite(converted) or converted <= 0:
        raise ValueError(f"{field_name} must be a positive finite number")
    return converted


def _safe_result(
    call: ToolCall,
    status: ToolResultStatus,
    *,
    code: str | None = None,
    sanitized_text: str = "",
    images: tuple[ImageContent, ...] = (),
    dispatch: DispatchCertainty | None = None,
) -> ToolResult:
    resolved_dispatch = dispatch or {
        ToolResultStatus.SUCCESS: DispatchCertainty.DISPATCHED,
        ToolResultStatus.ACTION_ERROR: DispatchCertainty.DISPATCHED,
        ToolResultStatus.TRANSPORT_ERROR: DispatchCertainty.NOT_DISPATCHED,
        ToolResultStatus.REJECTED: DispatchCertainty.NOT_DISPATCHED,
        ToolResultStatus.UNKNOWN_OUTCOME: DispatchCertainty.UNKNOWN,
    }[status]
    return ToolResult(
        identity=call.identity,
        tool_name=call.name,
        status=status,
        dispatch=resolved_dispatch,
        sanitized_text=sanitized_text,
        code=code,
        images=images,
    )


def _protocol_failure(call: ToolCall) -> ToolResult:
    spec = get_tool_spec(call.name)
    status = (
        ToolResultStatus.UNKNOWN_OUTCOME
        if spec.effect is ToolEffect.SIDE_EFFECT
        else ToolResultStatus.ACTION_ERROR
    )
    return _safe_result(
        call,
        status,
        code="MCP_PROTOCOL_ERROR",
        dispatch=DispatchCertainty.DISPATCHED,
    )


def _classify_action_text(text: str) -> tuple[ToolResultStatus, str | None]:
    for prefix, code in _SERVER_ERROR_PREFIXES:
        if text.startswith(prefix):
            return ToolResultStatus.ACTION_ERROR, code
    if text.startswith("ERROR "):
        code = text[6:].partition(":")[0].strip()
        if code in _SERVER_RESULT_CODES:
            return ToolResultStatus.ACTION_ERROR, code
        raise MCPResultConversionError("unreviewed MCP action error code")
    if text == "ok":
        return ToolResultStatus.SUCCESS, None
    raise MCPResultConversionError("unexpected MCP action result")


def _decode_png(data: object, mime_type: object) -> ImageContent:
    if mime_type != "image/png" or not isinstance(data, str) or not data:
        raise MCPResultConversionError("screenshot must be a non-empty base64 PNG")
    if len(data) > MAX_BASE64_IMAGE_CHARS:
        raise MCPResultConversionError("screenshot exceeds the encoded image limit")
    try:
        decoded = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise MCPResultConversionError("screenshot contains invalid base64") from exc
    if not decoded or len(decoded) > MAX_IMAGE_BYTES:
        raise MCPResultConversionError("screenshot exceeds the decoded image limit")

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", PILImage.DecompressionBombWarning)
            with PILImage.open(BytesIO(decoded)) as image:
                if image.format != "PNG":
                    raise MCPResultConversionError("screenshot bytes are not PNG")
                width, height = image.size
                if (
                    width <= 0
                    or height <= 0
                    or width > MAX_IMAGE_DIMENSION
                    or height > MAX_IMAGE_DIMENSION
                    or width * height > MAX_IMAGE_PIXELS
                ):
                    raise MCPResultConversionError("screenshot dimensions exceed the image limit")
                image.verify()
            with PILImage.open(BytesIO(decoded)) as decoded_image:
                if decoded_image.size != (width, height) or decoded_image.format != "PNG":
                    raise MCPResultConversionError("screenshot changed during PNG verification")
                decoded_image.load()
    except MCPResultConversionError:
        raise
    except Exception as exc:
        raise MCPResultConversionError("screenshot PNG failed integrity verification") from exc

    return ImageContent(
        mime_type="image/png",
        data=decoded,
        width=width,
        height=height,
    )


def convert_mcp_result(call: ToolCall, raw_result: object) -> ToolResult:
    """Convert one matching MCP response without retaining unreviewed error text."""

    spec = get_tool_spec(call.name)
    is_error = getattr(raw_result, "isError", None)
    content = getattr(raw_result, "content", None)
    structured_content = getattr(raw_result, "structuredContent", None)
    if not isinstance(is_error, bool) or not isinstance(content, (list, tuple)):
        raise MCPResultConversionError("malformed MCP tool result")
    if is_error:
        if spec.effect is ToolEffect.SIDE_EFFECT:
            return _safe_result(
                call,
                ToolResultStatus.UNKNOWN_OUTCOME,
                code="MCP_PROTOCOL_ERROR",
                dispatch=DispatchCertainty.DISPATCHED,
            )
        return _safe_result(call, ToolResultStatus.ACTION_ERROR, code="DRIVER_ERROR")

    if spec.returns_image and structured_content is not None:
        raise MCPResultConversionError("structured image results are not reviewed")

    if spec.result_content is ResultContentKind.IMAGE:
        if len(content) != 1 or getattr(content[0], "type", None) != "image":
            raise MCPResultConversionError("screenshot must return exactly one image block")
        image = _decode_png(
            getattr(content[0], "data", None),
            getattr(content[0], "mimeType", None),
        )
        result = _safe_result(call, ToolResultStatus.SUCCESS, images=(image,))
        validate_tool_result(call, result)
        return result

    if spec.result_content is ResultContentKind.TEXT_AND_IMAGE:
        # One envelope plus one crop on success; a refused region is text alone.
        if not content or len(content) > 2 or getattr(content[0], "type", None) != "text":
            raise MCPResultConversionError("a region capture must begin with one text block")
        envelope = getattr(content[0], "text", None)
        if not isinstance(envelope, str) or len(envelope) > MAX_TEXT_RESULT_CHARS:
            raise MCPResultConversionError("MCP text result exceeds the reviewed limit")
        images: tuple[ImageContent, ...] = ()
        if len(content) == 2:
            if getattr(content[1], "type", None) != "image":
                raise MCPResultConversionError("a region capture may only append one image block")
            images = (
                _decode_png(
                    getattr(content[1], "data", None),
                    getattr(content[1], "mimeType", None),
                ),
            )
        result = _safe_result(
            call,
            ToolResultStatus.SUCCESS,
            sanitized_text=envelope,
            images=images,
        )
        validate_tool_result(call, result)
        return result

    if len(content) != 1 or getattr(content[0], "type", None) != "text":
        raise MCPResultConversionError("text tools must return exactly one text block")
    text = getattr(content[0], "text", None)
    if not isinstance(text, str) or len(text) > MAX_TEXT_RESULT_CHARS:
        raise MCPResultConversionError("MCP text result exceeds the reviewed limit")
    if structured_content is not None and structured_content != {"result": text}:
        raise MCPResultConversionError("structured MCP text must exactly mirror its text block")

    if spec.effect is ToolEffect.SIDE_EFFECT:
        status, code = _classify_action_text(text)
        result = _safe_result(call, status, code=code)
    else:
        result = _safe_result(call, ToolResultStatus.SUCCESS, sanitized_text=text)
    validate_tool_result(call, result)
    return result


class StdioDesktopMCP:
    """A serialized, generation-aware implementation of ``DesktopMCPPort``.

    A successful ``discover_tools`` call is required before dispatch.  A broken
    generation is never restarted inside ``call_tool``: the caller must perform
    discovery again, which makes the generation change explicit and prevents an
    uncertain call from being replayed.
    """

    def __init__(
        self,
        launch: MCPLaunchConfig,
        *,
        timeout_seconds: float = DEFAULT_MCP_TIMEOUT_SECONDS,
        close_timeout_seconds: float = DEFAULT_MCP_CLOSE_TIMEOUT_SECONDS,
        session_factory: SessionFactory = _open_stdio_session,
    ) -> None:
        if not isinstance(launch, MCPLaunchConfig):
            raise ValueError("launch must be an MCPLaunchConfig")
        if not callable(session_factory):
            raise ValueError("session_factory must be callable")
        self._launch = launch
        self._timeout_seconds = _validate_timeout(timeout_seconds, "timeout_seconds")
        self._close_timeout_seconds = _validate_timeout(
            close_timeout_seconds,
            "close_timeout_seconds",
        )
        self._session_factory = session_factory
        self._operation_lock = asyncio.Lock()
        self._session: _ClientSessionPort | None = None
        self._session_owner_task: asyncio.Task[None] | None = None
        self._session_ready: asyncio.Future[_ClientSessionPort] | None = None
        self._session_stop: asyncio.Event | None = None
        self._verified_generation: int | None = None
        self._generation = 0
        self._ever_connected = False
        self._owner_failed = False
        self._closed = False

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def closed(self) -> bool:
        return self._closed

    async def __aenter__(self) -> "StdioDesktopMCP":
        await self.discover_tools()
        return self

    async def __aexit__(self, _exc_type, _exc, _traceback) -> None:
        await self.close()

    @staticmethod
    async def _run_session_owner(
        context: AbstractAsyncContextManager[_ClientSessionPort],
        ready: asyncio.Future[_ClientSessionPort],
        stop: asyncio.Event,
    ) -> None:
        """Enter and exit the SDK context in one dedicated asyncio task."""

        try:
            async with context as session:
                if not ready.done():
                    ready.set_result(session)
                await stop.wait()
        except asyncio.CancelledError:
            if not ready.done():
                ready.cancel()
            raise
        except BaseException as exc:
            if not ready.done():
                ready.set_exception(exc)
                return
            raise

    def _consume_owner_exception(self, owner_task: asyncio.Task[None]) -> None:
        """Retrieve background failures without retaining or logging raw exceptions."""

        if owner_task.cancelled():
            return
        try:
            self._owner_failed = owner_task.exception() is not None
        except BaseException:
            self._owner_failed = True

    async def _open_locked(self) -> _ClientSessionPort:
        owner_task = self._session_owner_task
        if owner_task is not None and owner_task.done():
            await self._drop_locked(suppress_errors=True)
            raise MCPBridgeError("MCP_TRANSPORT_ERROR")
        if self._session is not None:
            return self._session
        if owner_task is not None:
            raise MCPBridgeError("MCP_TRANSPORT_ERROR")

        context = self._session_factory(self._launch, self._timeout_seconds)
        loop = asyncio.get_running_loop()
        ready: asyncio.Future[_ClientSessionPort] = loop.create_future()
        stop = asyncio.Event()
        owner_task = asyncio.create_task(
            self._run_session_owner(context, ready, stop),
            name="computer-use-agent-mcp-session",
        )
        owner_task.add_done_callback(self._consume_owner_exception)
        self._session_owner_task = owner_task
        self._session_ready = ready
        self._session_stop = stop
        session = await asyncio.shield(ready)
        if owner_task.done():
            await self._drop_locked(suppress_errors=True)
            raise MCPBridgeError("MCP_TRANSPORT_ERROR")
        self._session = session
        self._generation += 1
        self._ever_connected = True
        return session

    async def _drop_locked(self, *, suppress_errors: bool) -> None:
        owner_task = self._session_owner_task
        ready = self._session_ready
        stop = self._session_stop
        self._session = None
        self._verified_generation = None
        if owner_task is None:
            self._session_ready = None
            self._session_stop = None
            return

        if stop is not None:
            stop.set()
        if ready is not None and not ready.done():
            owner_task.cancel()

        cleanup_failed = False
        try:
            async with asyncio.timeout(self._close_timeout_seconds):
                await asyncio.shield(owner_task)
        except TimeoutError:
            owner_task.cancel()
            try:
                async with asyncio.timeout(self._close_timeout_seconds):
                    await asyncio.shield(owner_task)
            except asyncio.CancelledError:
                if not owner_task.done():
                    raise
            except Exception:
                cleanup_failed = True
        except asyncio.CancelledError:
            if not owner_task.done():
                raise
        except Exception:
            cleanup_failed = True

        if owner_task.done():
            if ready is not None and ready.done() and not ready.cancelled():
                ready.exception()
            self._session_owner_task = None
            self._session_ready = None
            self._session_stop = None
        else:
            cleanup_failed = True

        if cleanup_failed and not suppress_errors:
            raise MCPBridgeError("MCP_TRANSPORT_ERROR") from None

    async def _discover_locked(self) -> tuple[MCPToolDescriptor, ...]:
        if self._closed:
            raise MCPBridgeError("MCP_TRANSPORT_ERROR")

        try:
            async with asyncio.timeout(self._timeout_seconds):
                session = await self._open_locked()
                tools: list[object] = []
                cursor: str | None = None
                seen_cursors: set[str] = set()
                for _ in range(MAX_DISCOVERY_PAGES):
                    page = await session.list_tools(cursor=cursor)
                    page_tools = getattr(page, "tools", None)
                    next_cursor = getattr(page, "nextCursor", None)
                    if not isinstance(page_tools, (list, tuple)):
                        raise MCPResultConversionError("malformed MCP tool discovery page")
                    tools.extend(page_tools)
                    if len(tools) > MAX_DISCOVERED_TOOLS:
                        raise MCPResultConversionError("MCP tool discovery exceeds the tool limit")
                    if next_cursor is None:
                        break
                    if (
                        not isinstance(next_cursor, str)
                        or not next_cursor
                        or next_cursor in seen_cursors
                    ):
                        raise MCPResultConversionError("MCP tool discovery cursor is invalid")
                    seen_cursors.add(next_cursor)
                    cursor = next_cursor
                else:
                    raise MCPResultConversionError("MCP tool discovery exceeds the page limit")

                descriptors: list[MCPToolDescriptor] = []
                for tool in tools:
                    name = getattr(tool, "name", None)
                    schema = getattr(tool, "inputSchema", None)
                    output_schema = getattr(tool, "outputSchema", None)
                    if (
                        not isinstance(name, str)
                        or not isinstance(schema, Mapping)
                        or (output_schema is not None and not isinstance(output_schema, Mapping))
                    ):
                        raise MCPResultConversionError("malformed MCP tool descriptor")
                    json_schema = to_json_value(schema)
                    json_output_schema = to_json_value(output_schema)
                    if not isinstance(json_schema, dict):
                        raise MCPResultConversionError("MCP tool schema must be an object")
                    schema_bytes = len(dumps(json_schema, separators=(",", ":")))
                    if json_output_schema is not None:
                        if not isinstance(json_output_schema, dict):
                            raise MCPResultConversionError("MCP output schema must be an object")
                        schema_bytes += len(
                            dumps(json_output_schema, separators=(",", ":"))
                        )
                    if schema_bytes > MAX_SCHEMA_JSON_BYTES:
                        raise MCPResultConversionError("MCP tool schema exceeds the size limit")
                    descriptors.append(
                        MCPToolDescriptor(
                            name=name,
                            input_schema=json_schema,
                            output_schema=json_output_schema,
                        )
                    )
                verify_discovered_tools(descriptors)
                self._verified_generation = self._generation
                return tuple(descriptors)
        except TimeoutError:
            await self._drop_locked(suppress_errors=True)
            raise MCPBridgeError("MCP_TIMEOUT_BEFORE_DISPATCH") from None
        except asyncio.CancelledError:
            await self._drop_locked(suppress_errors=True)
            raise
        except ToolRegistryMismatchError:
            await self._drop_locked(suppress_errors=True)
            raise MCPBridgeError("SCHEMA_MISMATCH") from None
        except MCPBridgeError:
            await self._drop_locked(suppress_errors=True)
            raise
        except (MCPResultConversionError, TypeError, ValueError):
            await self._drop_locked(suppress_errors=True)
            raise MCPBridgeError("MCP_PROTOCOL_ERROR") from None
        except Exception:
            await self._drop_locked(suppress_errors=True)
            raise MCPBridgeError("MCP_TRANSPORT_ERROR") from None

    async def discover_tools(self) -> tuple[MCPToolDescriptor, ...]:
        async with self._operation_lock:
            return await self._discover_locked()

    async def _finish_post_dispatch(
        self,
        result: ToolResult,
        *,
        cancellation_requested: bool = False,
    ) -> ToolResult:
        """Invalidate a generation without letting cancellation discard its result."""

        cleanup_task = asyncio.create_task(
            self._drop_locked(suppress_errors=True),
            name="computer-use-agent-mcp-cleanup",
        )
        cancelled = cancellation_requested
        while not cleanup_task.done():
            try:
                await asyncio.shield(cleanup_task)
            except asyncio.CancelledError:
                if cleanup_task.done() and cleanup_task.cancelled():
                    break
                cancelled = True
            except Exception:
                break
        if cleanup_task.done() and not cleanup_task.cancelled():
            try:
                cleanup_task.exception()
            except BaseException:
                pass
        if cancelled:
            raise MCPCallCancelled(result) from None
        return result

    async def call_tool(self, call: ToolCall) -> ToolResult:
        if not isinstance(call, ToolCall):
            raise ValueError("call must be a ToolCall")
        async with self._operation_lock:
            if call.status is not ToolCallStatus.AUTHORIZED:
                return _safe_result(call, ToolResultStatus.REJECTED, code="POLICY_DENIED")
            try:
                arguments = validate_tool_arguments(call.name, call.arguments)
            except ToolValidationError:
                return _safe_result(call, ToolResultStatus.REJECTED, code="SCHEMA_MISMATCH")

            if self._closed:
                return _safe_result(
                    call,
                    ToolResultStatus.TRANSPORT_ERROR,
                    code="MCP_TRANSPORT_ERROR",
                )
            if self._session_owner_task is not None and self._session_owner_task.done():
                await self._drop_locked(suppress_errors=True)
            if self._session is None or self._verified_generation != self._generation:
                code = (
                    "MCP_CHILD_EXITED_BEFORE_DISPATCH"
                    if self._ever_connected
                    else "MCP_TRANSPORT_ERROR"
                )
                return _safe_result(call, ToolResultStatus.TRANSPORT_ERROR, code=code)

            try:
                async with asyncio.timeout(self._timeout_seconds):
                    raw_result = await self._session.call_tool(
                        call.name,
                        arguments=arguments,
                        read_timeout_seconds=timedelta(seconds=self._timeout_seconds),
                    )
            except TimeoutError:
                result = _safe_result(
                    call,
                    ToolResultStatus.UNKNOWN_OUTCOME,
                    code="MCP_TRANSPORT_ERROR",
                )
                return await self._finish_post_dispatch(result)
            except asyncio.CancelledError:
                result = _safe_result(
                    call,
                    ToolResultStatus.UNKNOWN_OUTCOME,
                    code="MCP_TRANSPORT_ERROR",
                )
                return await self._finish_post_dispatch(
                    result,
                    cancellation_requested=True,
                )
            except Exception:
                result = _safe_result(
                    call,
                    ToolResultStatus.UNKNOWN_OUTCOME,
                    code="MCP_TRANSPORT_ERROR",
                )
                return await self._finish_post_dispatch(result)

            try:
                result = convert_mcp_result(call, raw_result)
            except (MCPResultConversionError, ToolValidationError, ValueError):
                result = _protocol_failure(call)
                return await self._finish_post_dispatch(result)
            if result.status is ToolResultStatus.UNKNOWN_OUTCOME:
                return await self._finish_post_dispatch(result)
            return result

    async def close(self) -> None:
        async with self._operation_lock:
            if self._closed and self._session_owner_task is None:
                return
            self._closed = True
            await self._drop_locked(suppress_errors=False)


__all__ = [
    "DEFAULT_MCP_TIMEOUT_SECONDS",
    "MCPBridgeError",
    "MCPCallCancelled",
    "MCPResultConversionError",
    "StdioDesktopMCP",
    "convert_mcp_result",
]
