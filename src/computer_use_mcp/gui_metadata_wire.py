"""Bounded local-only Session metadata resource; no execution capability."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import re

from .gui_metadata import GuiMetadataError, VerifiedControl, VerifiedGuiState

RESOURCE_PREFIX = "gui-observation://session/"


def metadata_uri(scope: str) -> str:
    if type(scope) is not str or not re.fullmatch(r"[1-9][0-9]{0,19}", scope):
        raise GuiMetadataError("GUI_SCOPE_INVALID")
    return RESOURCE_PREFIX + scope


@dataclass(frozen=True)
class SessionGuiMetadata:
    state: VerifiedGuiState
    refs: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if not isinstance(self.state, VerifiedGuiState) or type(self.refs) is not tuple:
            raise GuiMetadataError("GUI_METADATA_INVALID")
        if len(self.refs) > 64:
            raise GuiMetadataError("GUI_METADATA_INVALID")
        native = {c.native_id for c in self.state.controls}
        refs, identities = set(), set()
        for pair in self.refs:
            if type(pair) is not tuple or len(pair) != 2:
                raise GuiMetadataError("GUI_METADATA_INVALID")
            ref, identity = pair
            if (
                type(ref) is not str
                or not re.fullmatch(r"ref_[1-9][0-9]{0,9}", ref)
                or type(identity) is not str
                or identity not in native
                or ref in refs
                or identity in identities
            ):
                raise GuiMetadataError("GUI_METADATA_INVALID")
            refs.add(ref)
            identities.add(identity)

    def encode(self) -> str:
        text = json.dumps(
            dict(version=1, state=asdict(self.state), refs=dict(self.refs)),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        if len(text.encode()) > 65536:
            raise GuiMetadataError("GUI_METADATA_TOO_LARGE")
        return text


def decode_metadata(text: str, scope: str) -> SessionGuiMetadata:
    metadata_uri(scope)
    try:
        if type(text) is not str or len(text.encode()) > 65536:
            raise GuiMetadataError("GUI_METADATA_INVALID")
        value = json.loads(text, object_pairs_hook=_unique_object)
        if type(value) is not dict or set(value) != {"version", "state", "refs"}:
            raise GuiMetadataError("GUI_METADATA_INVALID")
        if type(value["version"]) is not int or value["version"] != 1:
            raise GuiMetadataError("GUI_METADATA_INVALID")
        state = value["state"]
        if type(state) is not dict or set(state) != {
            "scope",
            "foreground_scope",
            "window_bounds",
            "frame_bounds",
            "controls",
        }:
            raise GuiMetadataError("GUI_METADATA_INVALID")
        if state["scope"] != scope or type(state["controls"]) is not list:
            raise GuiMetadataError("GUI_METADATA_INVALID")
        if len(state["controls"]) > 64 or any(
            type(state[key]) is not list for key in ("window_bounds", "frame_bounds")
        ):
            raise GuiMetadataError("GUI_METADATA_INVALID")
        controls = []
        for control in state["controls"]:
            if (
                type(control) is not dict
                or set(control)
                != {"native_id", "role", "name", "bounds", "enabled", "visible", "focused"}
                or type(control["bounds"]) is not list
            ):
                raise GuiMetadataError("GUI_METADATA_INVALID")
            controls.append(VerifiedControl(**{**control, "bounds": tuple(control["bounds"])}))
        verified = VerifiedGuiState(
            scope,
            state["foreground_scope"],
            tuple(state["window_bounds"]),
            tuple(state["frame_bounds"]),
            tuple(controls),
        )
        if type(value["refs"]) is not dict:
            raise GuiMetadataError("GUI_METADATA_INVALID")
        return SessionGuiMetadata(verified, tuple(value["refs"].items()))
    except GuiMetadataError:
        raise
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise GuiMetadataError("GUI_METADATA_INVALID") from None


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise GuiMetadataError("GUI_METADATA_INVALID")
        result[key] = value
    return result
