"""Opt-in disposable Word diagnostic. Fixed text; one local image proposal."""
from __future__ import annotations

import argparse
import asyncio
import base64
from dataclasses import replace
import hashlib
import importlib
import json
from pathlib import Path
import re
import runpy
import sys
import time
from uuid import uuid4

from computer_use_agent.config import PolicyConfig
from computer_use_agent.desktop_mcp import StdioDesktopMCP
from computer_use_agent.fakes import FakeModelProvider
from computer_use_agent.grounding import GroundingState
from computer_use_agent.public_web_word import (
    _document_text_content, _latest_word_editor, _unique_window_id,
    _WORD_EDIT_LINE, _WORD_EDITOR_NAME, _WORD_DOCUMENT_LINE,
)
from computer_use_agent.public_web_word_runtime import (
    _document_text, _packaged_template_bytes, _wait_for_durable_document,
)
from computer_use_agent.runner import AgentRunner, RunnerPorts, RunFailure
from computer_use_agent.tool_registry import verify_discovered_tools
from computer_use_agent.trace import RunPhase, RunRecorder, read_run_record
from computer_use_agent.types import CallIdentity, ToolCall, PolicyDecision, PolicyDecisionKind
from computer_use_agent.word_content_adapter import WordContentAdapter

ROOT = Path(__file__).resolve().parents[1]
INERT = runpy.run_path(str(ROOT / "scripts/probe_gui_inert_model.py"))
READ = INERT["READ"]
NOTE = ("\n\nLOCAL GUI WORD READINESS\n"
        "This is fixed synthetic test content, not a generated source summary.\n"
        "Local GUI-Owl proposes an editor location from a screenshot.\n"
        "Runtime validates the target, writes this text once and saves the document.\n"
        "Success requires complete read-back and a separately reopened saved file.")


def sha(value):
    return hashlib.sha256(value).hexdigest()


def normalized(value):
    return " ".join(value.split())


def verify_text(value, original):
    # Exact normalized full body, including original text and one appended note.
    if normalized(value) != normalized(original + NOTE):
        raise ValueError("DOCUMENT_MISMATCH")


def editor_bounds(snapshot):
    candidates = []
    for match in _WORD_EDIT_LINE.finditer(snapshot):
        flags = {flag.strip() for flag in match[7].split(",")}
        if (_WORD_EDITOR_NAME.fullmatch(match[2]) and "enabled" in flags
                and "offscreen" not in flags):
            candidates.append((match[1], match[2], *(int(match[i]) for i in range(3, 7))))
    if len(candidates) != 1:
        raise ValueError("EDITOR_AMBIGUOUS")
    return candidates[0]


def pixel_point(raw, size, editor, parse):
    point = parse(raw)
    if point is None:
        raise ValueError("MODEL_STOPPED")
    width, height = size
    x, y = int(point[0] * width / 1000), int(point[1] * height / 1000)
    _, _, left, top, w, h = editor
    if not (0 <= x < width and 0 <= y < height
            and left + 8 <= x < left + w - 8 and top + 8 <= y < top + h - 8):
        raise ValueError("POINT_OUTSIDE_EDITOR")
    return {"x": x, "y": y}


def document_box(snapshot, editor, title):
    _, _, x, y, w, h = editor
    boxes = []
    for match in _WORD_DOCUMENT_LINE.finditer(snapshot):
        left, top, width, height = (int(match[i]) for i in range(3, 7))
        flags = {flag.strip() for flag in match[7].split(",")}
        if (title in match[2] and "enabled" in flags and "offscreen" not in flags
                and left <= x + w // 2 < left + width and top <= y + h // 2 < top + height):
            boxes.append([left, top, width, height])
    if len(boxes) != 1:
        raise ValueError("DOCUMENT_AMBIGUOUS")
    return boxes[0]


def body_text(raw, scope, box):
    # Window TextPattern traversal also returns ribbon font/size fields. Select
    # exactly one complete block at the freshly observed Document bounds.
    if _document_text_content(raw, require_complete=True) is None:
        raise ValueError("DOCUMENT_INCOMPLETE")
    value = INERT["strict_json"](raw)
    if (value.get("scope") != scope or value.get("semantic_source") != "uia_text_pattern"
            or value.get("coordinate_space") != "primary_display_physical_pixels"):
        raise ValueError("DOCUMENT_SCOPE_MISMATCH")
    selected = [b for b in value["blocks"] if b.get("bbox") == box]
    if len(selected) != 1:
        raise ValueError("DOCUMENT_BLOCK_AMBIGUOUS")
    for block in value["blocks"]:
        if block is selected[0]:
            continue
        bounds = block.get("bbox")
        if (type(bounds) is not list or len(bounds) != 4
                or any(type(v) is not int for v in bounds) or bounds[2] <= 0 or bounds[3] <= 0):
            raise ValueError("DOCUMENT_BLOCK_UNGROUNDED")
        x, y, w, h = bounds
        if len(block["text"]) > 64 or h > 100:
            raise ValueError("EXTRA_DOCUMENT_BLOCK")
        left, top, width, height = box
        if x < left + width and x + w > left and y < top + height and y + h > top:
            raise ValueError("DOCUMENT_BLOCK_OVERLAP")
    return selected[0]["text"]


def config_for():
    base = READ["config_for"]()
    return replace(base, state_dir=base.state_dir.parent / "gui-word",
                   policy_version="gui-word-v1",
                   policy=PolicyConfig(mode="approved_actions", max_model_turns=1,
                                       max_tool_calls=32, max_side_effects=4),
                   mcp=replace(base.mcp, environment={
                       "CUMCP_ALLOWLIST": "winword.exe", "CUMCP_MODE": "safe_local",
                       "CUMCP_UIA_ACTIONS": "1", "CUMCP_DANGEROUS_CONFIRM": "1",
                       "CUMCP_HUMAN_STABLE_SAMPLES": "3", "CUMCP_HUMAN_MAX_WAIT_SECONDS": "15",
                   }))


class WordPermit:
    """One consumed exact-call authorization per validated fixed workflow stage."""
    def __init__(self):
        self.armed = None
        self.requests = 0

    async def request_approval(self, request):
        self.requests += 1
        armed, self.armed = self.armed, None
        allowed = False
        if armed is not None:
            call, tick, before, deadline = armed
            allowed = (request.tool_name == call.name and request.identity == call.identity
                       and request.call_digest == call.digest and request.binding is not None
                       and tick() == before and time.monotonic() <= deadline)
        return PolicyDecision(request.request_id, request.identity, request.call_digest,
                              PolicyDecisionKind.ALLOW if allowed else PolicyDecisionKind.DENY,
                              "explicit_word_diagnostic" if allowed else "word_permit_rejected")


class WordRun:
    def __init__(self, runner, scope, title, tick, *, strict_content=False):
        self.runner, self.scope, self.title, self.tick = runner, scope, title, tick
        self.strict_content = strict_content
        label = "Reviewed Word content diagnostic" if strict_content else "Disposable Word fixed-text diagnostic"
        self.prepared = runner.prepare(label, run_id="gui-word-" + uuid4().hex)
        self.state = self.prepared.state
        self.recorder = RunRecorder(runner.config.state_dir, self.state.run_id)
        self.grounding = GroundingState()
        self.last_tick = tick()
        self.generation = None
        self.document_box = None

    def unchanged(self):
        if self.tick() != self.last_tick:
            raise ValueError("INPUT_CHANGED")

    async def call(self, name, arguments, *, action=False):
        self.unchanged()
        call = ToolCall(CallIdentity(self.state.run_id, "word_diagnostic", uuid4().hex), name, arguments)
        if action:
            self.runner.ports.approvals.armed = (call, self.tick, self.last_tick, time.monotonic() + 2)
        result = await self.runner._execute_requested_call_boundary(
            self.state, call, grounding=self.grounding, recorder=self.recorder, continuation=None)
        self.state, self.grounding = result.state, result.grounding
        if not result.result.ok or result.abandon_remaining_calls:
            raise ValueError("TOOL_REJECTED")
        current = self.runner.ports.desktop.generation
        if self.generation is not None and current != self.generation:
            raise ValueError("SESSION_CHANGED")
        self.generation = current
        if action:
            # Input injection legitimately changes the OS tick. MCP's human-activity
            # gate owns in-dispatch attribution; never claim this is a global input lock.
            self.last_tick = self.tick()
        else:
            self.unchanged()
        return result.result

    async def windows(self):
        windows = await self.call("list_windows", {})
        _unique_window_id(windows.sanitized_text, owner="winword.exe", title_fragment=self.title,
                          expected_window_id=self.scope)
        if not any(line.startswith("* " + self.scope + " | ")
                   for line in windows.sanitized_text.splitlines()):
            raise ValueError("FOREGROUND_CHANGED")

    async def observe(self, *, focus=False):
        await self.windows()
        snapshot = await self.call("ui_snapshot", {"scope": self.scope})
        editor = editor_bounds(snapshot.sanitized_text)
        self.document_box = document_box(snapshot.sanitized_text, editor, self.title)
        if focus:
            focused = _latest_word_editor(self.state.event_log, word_window_id=self.scope,
                                          word_title_fragment=self.title)
            if focused is None or not focused[2]:
                raise ValueError("EDITOR_NOT_FOCUSED")
        return editor

    async def text(self):
        result = await self.call("document_text", {"scope": self.scope})
        if self.document_box is None:
            raise ValueError("DOCUMENT_NOT_OBSERVED")
        return body_text(result.sanitized_text, self.scope, self.document_box)

    async def expect_document(self, expected):
        # Save is a window command, not text entry: fresh exact-window scope and
        # a complete expected body are its grounding. No editor ref is reused.
        await self.windows()
        result = await self.call("document_text", {"scope": self.scope})
        raw = result.sanitized_text
        if _document_text_content(raw, require_complete=True) is None:
            raise ValueError("DOCUMENT_INCOMPLETE")
        blocks = INERT["strict_json"](raw)["blocks"]
        equal = (lambda a, b: a == b) if self.strict_content else (lambda a, b: normalized(a) == normalized(b))
        candidates = [b for b in blocks if equal(b["text"], expected)]
        if len(candidates) != 1:
            raise ValueError("DOCUMENT_MISMATCH")
        box = candidates[0].get("bbox")
        if (type(box) is not list or len(box) != 4 or any(type(v) is not int for v in box)
                or box[2] <= 0 or box[3] <= 0):
            raise ValueError("DOCUMENT_BLOCK_UNGROUNDED")
        body = body_text(raw, self.scope, box)
        if not equal(body, expected):
            raise ValueError("DOCUMENT_MISMATCH")
        return body


async def probe(scope, document, api=None, *, reopen=False, save_only=False, tick=READ["input_tick"], runner=None,
                worker=INERT["local_worker"], content_adapter: WordContentAdapter | None = None):
    config = config_for()
    if runner is None:
        runner = AgentRunner(config, RunnerPorts(FakeModelProvider(), StdioDesktopMCP(config.mcp), WordPermit()))
    if (not isinstance(runner.ports.desktop, StdioDesktopMCP)
            or not isinstance(runner.ports.approvals, WordPermit)
            or runner.config.continuation.enabled or runner.config.privacy.enabled
            or any(p is not None for p in (runner.ports.control, runner.ports.presence, runner.ports.progress))):
        raise ValueError("CONFIGURATION_REJECTED")
    original = (content_adapter.begin(document, reopen=reopen, save_only=save_only)
                if content_adapter is not None else _document_text(document))
    note = content_adapter.task.content if content_adapter is not None else NOTE
    equal = (lambda a, b: a == b) if content_adapter is not None else (lambda a, b: normalized(a) == normalized(b))
    if content_adapter is None and not reopen and "LOCAL GUI WORD READINESS" in original:
        raise ValueError("ATTEMPT_ALREADY_CONSUMED")
    if content_adapter is None and not reopen and document.read_bytes() != _packaged_template_bytes():
        raise ValueError("FIXTURE_TEMPLATE_MISMATCH")
    run = WordRun(runner, scope, document.name, tick, strict_content=content_adapter is not None)
    outcome, code, requests, metrics, verified = "FAIL", "OBSERVATION_REJECTED", 0, {}, False
    artifact_sha = None
    try:
        run.recorder.start(run.state)
        run.recorder.record(run.state, RunPhase.OBSERVING)
        verify_discovered_tools(await runner.ports.desktop.discover_tools())
        run.recorder.record(run.state, RunPhase.PLANNING)
        if save_only:
            await run.expect_document(original + note)
        elif reopen:
            reopened_body = await run.expect_document(original)
            if content_adapter is not None:
                artifact_sha = content_adapter.record_reopened(reopened_body)
        else:
            editor = await run.observe()
            observed = await run.text()
            if not equal(observed, original):
                raise ValueError("INITIAL_DOCUMENT_MISMATCH")
        if reopen:
            if content_adapter is None and normalized(note) not in normalized(original):
                raise ValueError("SAVED_NOTE_MISSING")
        elif not save_only:
            shot = await run.call("screenshot", {})
            if len(shot.images) != 1 or len(shot.images[0].data) > 8 * 1024 * 1024:
                raise ValueError("IMAGE_REJECTED")
            frame = shot.images[0]
            context = dict(scope=scope, generation=run.generation, epoch=run.state.observation_epoch,
                           editor=editor, document_sha256=sha(original.encode()), image_sha256=sha(frame.data))
            if content_adapter is not None:
                context["content_task_sha256"] = content_adapter.task.task_sha256
            request = dict(version=1, request_id=run.state.run_id,
                           context_digest=sha(json.dumps(context, sort_keys=True).encode()),
                           image_base64=base64.b64encode(frame.data).decode())
            code, requests = "WORKER_REJECTED", None
            response = await asyncio.to_thread(worker, api, request)
            INERT["validate_response"](response, request, sha(frame.data))
            requests = 1
            metrics = {k: response[k] for k in ("model_id", "revision", "adapter_sha256", "image_sha256",
                       "input_tokens", "output_tokens", "generation_seconds", "peak_allocated_bytes")}
            metrics["raw_output_sha256"] = sha(response["raw_output"].encode())
            code = "PROPOSAL_REJECTED"
            point = pixel_point(response["raw_output"], (frame.width, frame.height), editor, api.parse)
            code = "REVALIDATION_REJECTED"
            if await run.observe() != editor or not equal(await run.text(), original):
                raise ValueError("CONTEXT_CHANGED")
            # A fresh scoped snapshot precedes every action. The click uses the
            # model's explicit pixel point; it never degrades a ref into a coordinate.
            if await run.observe() != editor:
                raise ValueError("CONTEXT_CHANGED")
            if content_adapter is not None:
                content_adapter.revalidate_initial()
            code = "CLICK_REJECTED"
            await run.call("click", point, action=True)
            await run.observe(focus=True)
            if content_adapter is not None:
                content_adapter.revalidate_initial()
            code = "CARET_REJECTED"
            await run.call("key", {"combo": "Ctrl+End"}, action=True)
            await run.observe(focus=True)
            if content_adapter is not None:
                content_adapter.revalidate_initial()
                if not equal(await run.text(), original):
                    raise ValueError("CONTEXT_CHANGED")
            code = "WRITE_REJECTED"
            await run.call("type", {"text": note}, action=True)
            code = "PRE_SAVE_MISMATCH"
            readback = await run.expect_document(original + note)
            if content_adapter is not None:
                content_adapter.record_readback(readback)
        if not reopen:
            code = "SAVE_REJECTED"
            if content_adapter is not None:
                content_adapter.revalidate_initial()
            await run.call("key", {"combo": "Ctrl+S"}, action=True)
            code = "POST_SAVE_MISMATCH"
            saved_body = await run.expect_document(original + note)
            if content_adapter is not None:
                artifact_sha = content_adapter.wait_saved(saved_body)
            else:
                _wait_for_durable_document(document, note)
                verify_text(_document_text(document), original)
        if content_adapter is None:
            artifact_sha = sha(document.read_bytes())
        run.unchanged()
        verified = True
        outcome, code = "PASS", ("REOPEN_READ_VERIFIED" if reopen else
                                 "RECOVERED_SAVE_VERIFIED" if save_only else "WORD_SAVE_VERIFIED")
    except RunFailure as exc:
        run.state = exc.state
        code = "HOST_" + exc.code
        if exc.code == "UNKNOWN_OUTCOME":
            outcome, code = "UNKNOWN_OUTCOME", "UNKNOWN_OUTCOME"
    except ValueError as exc:
        if str(exc) == "INPUT_CHANGED":
            outcome, code = "INVALID", "INPUT_CHANGED"
    except Exception:
        pass  # No raw UI, model prose or exception text in the safe receipt.
    finally:
        try:
            await runner.ports.desktop.close()
        except Exception:
            outcome, code = "FAIL", "SESSION_CLEANUP_FAILED"
        finally:
            try:
                if content_adapter is not None and outcome != "PASS":
                    content_adapter.phase = "failed"
                if run.recorder.phase is not RunPhase.UNKNOWN_OUTCOME:
                    phase = (RunPhase.SUCCESS if outcome == "PASS" else RunPhase.UNKNOWN_OUTCOME
                             if outcome == "UNKNOWN_OUTCOME" else RunPhase.FAILED)
                    run.recorder.record(run.state, phase)
            finally:
                run.prepared.close()
    record = read_run_record(runner.config.state_dir, run.state.run_id)["state"]
    return dict(version=1, run_id=run.state.run_id, outcome=outcome, code=code,
                phase=record["phase"], model_requests=requests, metrics=metrics,
                tool_calls=record["budgets"]["tool_calls_used"],
                host_model_turns=record["budgets"]["model_turns_used"],
                side_effects=record["budgets"]["side_effects_used"],
                approval_requests=runner.ports.approvals.requests,
                content_verified=verified, artifact_sha256=artifact_sha,
                fixed_note_sha256=sha(NOTE.encode()) if content_adapter is None else None,
                content_handoff=content_adapter.receipt() if content_adapter is not None else None,
                reopened=reopen, save_only=save_only,
                raw_observations_exported=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-disposable-word", required=True, action="store_true")
    parser.add_argument("--scope", required=True)
    parser.add_argument("--document", required=True, type=Path)
    parser.add_argument("--consumer-root", type=Path)
    parser.add_argument("--reopen-read-only", action="store_true")
    parser.add_argument("--save-verified-only", action="store_true")
    parser.add_argument("--expected-artifact-sha256")
    args = parser.parse_args(argv)
    try:
        if sys.platform != "win32" or not re.fullmatch(r"[1-9][0-9]{0,19}", args.scope):
            raise ValueError("WINDOWS_SCOPE_REQUIRED")
        if args.reopen_read_only and args.save_verified_only:
            raise ValueError("EXCLUSIVE_MODE_REQUIRED")
        document = args.document.resolve(strict=True)
        if (document.suffix.lower() != ".docx" or document.parent != ROOT / "out"
                or not document.name.startswith("gui-word-")):
            raise ValueError("DISPOSABLE_OUTPUT_REQUIRED")
        if args.reopen_read_only and (not args.expected_artifact_sha256
                or sha(document.read_bytes()) != args.expected_artifact_sha256):
            raise ValueError("REOPEN_ARTIFACT_MISMATCH")
        api = None
        if not args.reopen_read_only and not args.save_verified_only:
            api = INERT["load_consumer"](args.consumer_root)
            api.worker = args.consumer_root.resolve() / "scripts/probe_gui_owl_word.py"
            if sha(api.worker.read_text(encoding="utf-8").encode()) != "b9307dfcd06409393201eeb715757ea020a8d34bce08a3a1090fefc4a1bf9a6c":
                raise ValueError("WORD_WORKER_SOURCE_MISMATCH")
            api.parse = importlib.import_module("fullcycle_bridge.native_gui_proposal").parse_native
        receipt = asyncio.run(probe(args.scope, document, api, reopen=args.reopen_read_only,
                                    save_only=args.save_verified_only))
    except Exception:
        receipt = dict(version=1, outcome="ERROR", code="WORD_PROBE_UNAVAILABLE")
    print(json.dumps(receipt, sort_keys=True))
    return 0 if receipt["outcome"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
