"""Bounded, non-logging MCP stdio transport for an untrusted local child.

The upstream MCP client transport buffers complete stdout lines before parsing
and logs parser exceptions that may contain raw child output. This variant keeps
the SDK's process-tree handling and session streams while bounding each JSON-RPC
frame and replacing parser failures with a fixed, non-sensitive exception.
"""
from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from typing import TextIO

import anyio
import anyio.lowlevel
import mcp.types as mcp_types
from anyio.streams.memory import MemoryObjectSendStream
from mcp.client.stdio import (
    PROCESS_TERMINATION_TIMEOUT,
    StdioServerParameters,
    _create_platform_compatible_process,
    _get_executable_command,
    _terminate_process_tree,
    get_default_environment,
)
from mcp.shared.message import SessionMessage

MAX_MCP_FRAME_BYTES = 48 * 1024 * 1024
MCP_READ_CHUNK_BYTES = 64 * 1024


class BoundedStdioError(RuntimeError):
    """A fixed transport error that never embeds raw child or request content."""

    def __init__(self) -> None:
        super().__init__("MCP_PROTOCOL_ERROR")


async def _send_safe_error(
    stream: MemoryObjectSendStream[SessionMessage | Exception],
) -> None:
    await stream.send(BoundedStdioError())


@asynccontextmanager
async def bounded_stdio_client(
    server: StdioServerParameters,
    *,
    errlog: TextIO = sys.stderr,
    max_frame_bytes: int = MAX_MCP_FRAME_BYTES,
):
    """Spawn an MCP child and exchange bounded newline-delimited JSON-RPC frames."""

    if isinstance(max_frame_bytes, bool) or not isinstance(max_frame_bytes, int):
        raise ValueError("max_frame_bytes must be a positive integer")
    if max_frame_bytes <= 0:
        raise ValueError("max_frame_bytes must be a positive integer")

    read_stream_writer, read_stream = anyio.create_memory_object_stream[
        SessionMessage | Exception
    ](0)
    write_stream, write_stream_reader = anyio.create_memory_object_stream[SessionMessage](0)

    try:
        command = _get_executable_command(server.command)
        environment = get_default_environment()
        if server.env is not None:
            environment.update(server.env)
        process = await _create_platform_compatible_process(
            command=command,
            args=server.args,
            env=environment,
            errlog=errlog,
            cwd=server.cwd,
        )
    except OSError:
        await read_stream.aclose()
        await write_stream.aclose()
        await read_stream_writer.aclose()
        await write_stream_reader.aclose()
        raise

    async def stdout_reader() -> None:
        assert process.stdout, "opened process is missing stdout"
        buffer = bytearray()
        try:
            async with read_stream_writer:
                while True:
                    try:
                        chunk = await process.stdout.receive(MCP_READ_CHUNK_BYTES)
                    except anyio.EndOfStream:
                        break
                    if not chunk:
                        break
                    start = 0
                    while start < len(chunk):
                        newline = chunk.find(b"\n", start)
                        end = len(chunk) if newline < 0 else newline
                        segment = chunk[start:end]
                        if len(buffer) + len(segment) > max_frame_bytes:
                            buffer.clear()
                            await _send_safe_error(read_stream_writer)
                            return
                        buffer.extend(segment)
                        if newline < 0:
                            break
                        frame = bytes(buffer)
                        buffer.clear()
                        try:
                            message = mcp_types.JSONRPCMessage.model_validate_json(frame)
                        except Exception:
                            await _send_safe_error(read_stream_writer)
                            return
                        if not isinstance(
                            message.root,
                            (mcp_types.JSONRPCResponse, mcp_types.JSONRPCError),
                        ):
                            await _send_safe_error(read_stream_writer)
                            return
                        await read_stream_writer.send(SessionMessage(message))
                        start = newline + 1
                if buffer:
                    buffer.clear()
                    await _send_safe_error(read_stream_writer)
        except anyio.ClosedResourceError:
            await anyio.lowlevel.checkpoint()

    async def stdin_writer() -> None:
        assert process.stdin, "opened process is missing stdin"
        try:
            async with write_stream_reader:
                async for session_message in write_stream_reader:
                    serialized = session_message.message.model_dump_json(
                        by_alias=True,
                        exclude_none=True,
                    )
                    encoded = serialized.encode(
                        encoding=server.encoding,
                        errors=server.encoding_error_handler,
                    )
                    if len(encoded) > max_frame_bytes:
                        raise BoundedStdioError()
                    await process.stdin.send(encoded + b"\n")
        except anyio.ClosedResourceError:
            await anyio.lowlevel.checkpoint()

    async with anyio.create_task_group() as task_group, process:
        task_group.start_soon(stdout_reader)
        task_group.start_soon(stdin_writer)
        try:
            yield read_stream, write_stream
        finally:
            if process.stdin:
                try:
                    await process.stdin.aclose()
                except Exception:
                    pass
            try:
                with anyio.fail_after(PROCESS_TERMINATION_TIMEOUT):
                    await process.wait()
            except TimeoutError:
                await _terminate_process_tree(process)
            except ProcessLookupError:
                pass
            await read_stream.aclose()
            await write_stream.aclose()
            await read_stream_writer.aclose()
            await write_stream_reader.aclose()


__all__ = ["BoundedStdioError", "MAX_MCP_FRAME_BYTES", "bounded_stdio_client"]
