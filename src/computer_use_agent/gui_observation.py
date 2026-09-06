"""Internal offline-tested observation coordinator; no default Host/desktop route."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
import time
from typing import Callable, Mapping, Protocol, TypedDict

from computer_use_mcp.gui_metadata import GuiMetadataError, VerifiedGuiState
from .types import ToolCall, ToolResult


@dataclass(frozen=True)
class StampedObservation:
    call: ToolCall
    result: ToolResult
    generation: int
    epoch: int


class ObservationSource(Protocol):
    """Future Host adapter must use the sole Runner/MCP path and actual ledger stamps."""

    def state(self) -> tuple[int, int]: ...
    def inspect(self, scope: str) -> VerifiedGuiState: ...
    def read(self, tool: str, arguments: Mapping[str, str]) -> StampedObservation: ...
    def resolve_ref(self, ref: str) -> str: ...


class _ResultRow(TypedDict):
    call_id: str
    tool: str
    status: str
    dispatch: str
    generation: int
    epoch: int
    arguments: dict[str, str]
    text: str


def _state(source: ObservationSource) -> tuple[int, int]:
    state = source.state()
    if (
        type(state) is not tuple
        or len(state) != 2
        or any(type(v) is not int or not 0 <= v < 2**31 for v in state)
    ):
        raise GuiMetadataError("GUI_STAMP_INVALID")
    return state


@dataclass(frozen=True)
class ObservationBundle:
    payload: bytes
    image: bytes

    def to_dict(self) -> dict:
        return json.loads(self.payload)


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode()


def collect_gui_observation(
    task: dict,
    source: ObservationSource,
    *,
    clock: Callable[[], float] = time.monotonic,
    max_seconds: float = 2.0,
) -> ObservationBundle:
    """Derive four Host fact groups from successful reads plus endpoint comparison."""
    # Copy before any callbacks. The new interface never accepts Host-fact booleans.
    if type(task) is not dict:
        raise GuiMetadataError("GUI_TASK_INVALID")
    try:
        request = json.loads(_canonical(task))
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise GuiMetadataError("GUI_TASK_INVALID") from None
    if (
        set(request) != {"version", "request_id", "target_scope", "target"}
        or type(request["version"]) is not int
        or request["version"] != 1
    ):
        raise GuiMetadataError("GUI_TASK_INVALID")
    scope = request["target_scope"]
    if type(scope) is not str or not re.fullmatch(r"[1-9][0-9]{0,19}", scope):
        raise GuiMetadataError("GUI_SCOPE_INVALID")
    if type(request["request_id"]) is not str or not re.fullmatch(
        r"[a-z0-9][a-z0-9_-]{0,63}", request["request_id"]
    ):
        raise GuiMetadataError("GUI_TASK_INVALID")
    target = request["target"]
    if (
        type(target) is not dict
        or set(target) != {"name", "role"}
        or type(target["name"]) is not str
        or not target["name"].strip()
        or len(target["name"]) > 160
        or any(ord(c) < 32 for c in target["name"])
        or type(target["role"]) is not str
        or target["role"] not in {"button", "edit", "document"}
    ):
        raise GuiMetadataError("GUI_TARGET_INVALID")
    if type(max_seconds) not in {int, float} or not 0 < max_seconds <= 5:
        raise GuiMetadataError("GUI_BUDGET_INVALID")
    started = clock()
    generation, initial_epoch = _state(source)
    before = source.inspect(scope)
    rows: dict[str, _ResultRow] = {}
    previous_epoch = initial_epoch
    identities = set()
    image = b""
    image_size = (0, 0)
    owner = None
    for key, tool, arguments in [
        ("windows", "list_windows", {}),
        ("snapshot", "ui_snapshot", {"scope": scope}),
        ("screenshot", "screenshot", {}),
    ]:
        stamp = source.read(tool, arguments)
        call, result = stamp.call, stamp.result
        if (
            call.name != tool
            or dict(call.arguments) != arguments
            or result.tool_name != tool
            or call.identity != result.identity
            or not result.ok
        ):
            raise GuiMetadataError("GUI_RESULT_MISMATCH")
        identity = call.identity
        if identity.call_id in identities:
            raise GuiMetadataError("GUI_CALL_DUPLICATE")
        identities.add(identity.call_id)
        current_owner = (identity.run_id, identity.turn_id)
        if owner is not None and owner != current_owner:
            raise GuiMetadataError("GUI_CALL_OWNER_CHANGED")
        owner = current_owner
        if (
            type(stamp.epoch) is not int
            or not previous_epoch < stamp.epoch < 2**31
            or type(stamp.generation) is not int
            or stamp.generation != generation
        ):
            raise GuiMetadataError("GUI_STAMP_CHANGED")
        if _state(source) != (generation, stamp.epoch):
            raise GuiMetadataError("GUI_LEDGER_CHANGED")
        previous_epoch = stamp.epoch
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", identity.call_id):
            raise GuiMetadataError("GUI_CALL_ID_UNSUPPORTED")
        if len(result.sanitized_text) > 32768:
            raise GuiMetadataError("GUI_RESULT_TOO_LARGE")
        rows[key] = _ResultRow(
            call_id=identity.call_id,
            tool=tool,
            status=result.status.value,
            dispatch=result.dispatch.value,
            generation=generation,
            epoch=stamp.epoch,
            arguments=arguments,
            text=result.sanitized_text,
        )
        if tool == "screenshot":
            if len(result.images) != 1:
                raise GuiMetadataError("GUI_IMAGE_INVALID")
            image = result.images[0].data
            image_size = (result.images[0].width, result.images[0].height)
        elif result.images:
            raise GuiMetadataError("GUI_IMAGE_INVALID")
        if not 0 <= clock() - started <= max_seconds:
            raise GuiMetadataError("GUI_OBSERVATION_TIMEOUT")
    after = source.inspect(scope)
    if before != after or _state(source) != (generation, previous_epoch):
        raise GuiMetadataError("GUI_OBSERVATION_CHANGED")
    elapsed = clock() - started
    if not 0 <= elapsed <= max_seconds:
        raise GuiMetadataError("GUI_OBSERVATION_TIMEOUT")
    if (
        before.scope != scope
        or before.foreground_scope != scope
        or before.frame_bounds != (0, 0, *image_size)
    ):
        raise GuiMetadataError("GUI_FRAME_MISMATCH")
    window_lines = rows["windows"]["text"].splitlines()
    if not window_lines or len(window_lines) > 128:
        raise GuiMetadataError("GUI_WINDOW_LIST_INVALID")
    window_ids = set()
    active = []
    for line in window_lines:
        window_match = re.fullmatch(r'([ *]) ([1-9][0-9]{0,19}) \| [^|"\r\n]+ \| "[^"\r\n]*"', line)
        if window_match is None or window_match[2] in window_ids:
            raise GuiMetadataError("GUI_WINDOW_LIST_INVALID")
        window_ids.add(window_match[2])
        if window_match[1] == "*":
            active.append(window_match[2])
    if active != [scope]:
        raise GuiMetadataError("GUI_FOREGROUND_MISMATCH")
    visible = {c.native_id: c for c in before.controls if c.visible}
    states = {}
    matched = set()
    snapshot = rows["snapshot"]["text"]
    lines = [] if snapshot == "# (no interactive elements in scope)" else snapshot.splitlines()
    if snapshot != "# (no interactive elements in scope)" and not lines:
        raise GuiMetadataError("GUI_SNAPSHOT_INCOMPLETE")
    pattern = r'ref_([1-9][0-9]{0,9}) \| ([a-z]+) "([^"\r\n]*)" \| \((-?[0-9]{1,6}),(-?[0-9]{1,6}),([0-9]{1,6}),([0-9]{1,6})\) \| ([a-z,]+)(?: \| value="[^"\r\n]*")?'
    for line in lines:
        match = re.fullmatch(pattern, line)
        if match is None:
            raise GuiMetadataError("GUI_SNAPSHOT_INCOMPLETE")
        number, role, name, x, y, w, h, state_text = match.groups()
        ref = "ref_" + number
        native_id = source.resolve_ref(ref)
        control = visible.get(native_id)
        if control is None or native_id in matched or ref in states:
            raise GuiMetadataError("GUI_REF_MISMATCH")
        matched.add(native_id)
        bounds = (int(x), int(y), int(x) + int(w), int(y) + int(h))
        observed_states = state_text.split(",")
        expected_enabled = "enabled" if control.enabled else "disabled"
        if (
            role != control.role
            or name != control.name
            or bounds != control.bounds
            or expected_enabled not in observed_states
            or ("offscreen" in observed_states)
            or ("focused" in observed_states) != control.focused
            or len(set(observed_states)) != len(observed_states)
            or not set(observed_states) <= {expected_enabled, "focused", "selected"}
        ):
            raise GuiMetadataError("GUI_CONTROL_MISMATCH")
        states[ref] = dict(enabled=control.enabled, visible=control.visible)
    if matched != set(visible):
        raise GuiMetadataError("GUI_SNAPSHOT_INCOMPLETE")
    if _state(source) != (generation, previous_epoch):
        raise GuiMetadataError("GUI_LEDGER_CHANGED")
    if not 0 <= clock() - started <= max_seconds:
        raise GuiMetadataError("GUI_OBSERVATION_TIMEOUT")
    request.update(current_epoch=previous_epoch, runtime_generation=generation)
    binding = hashlib.sha256(
        b"gui-observation-projection-v1\0"
        + _canonical(
            dict(task=request, results=rows, image_sha256=hashlib.sha256(image).hexdigest())
        )
    ).hexdigest()
    facts = dict(
        binding_digest=binding,
        window_bounds=list(before.window_bounds),
        frame_origin=[0, 0],
        coherent_complete_projection=True,
        control_states=states,
    )
    payload = _canonical(
        dict(task=request, results=rows, host_facts=facts, execution_authorized=False)
    )
    if len(payload) > 65536:
        raise GuiMetadataError("GUI_OBSERVATION_TOO_LARGE")
    return ObservationBundle(payload, image)
