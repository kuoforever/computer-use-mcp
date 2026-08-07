"""Host-compiled Pre-run Review models for fixed installed workflows.

The review is local product information, never authority. It is compiled from
reviewed Host constants and the exact resolved local request, not model prose.
This module has no provider, MCP, desktop, approval, execution, or persistence
port.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import AgentConfig
from .public_web_word import (
    PUBLIC_WEB_WORD_MAX_HIGH_RISK_APPROVALS,
    PUBLIC_WEB_WORD_MAX_SIDE_EFFECTS,
    PUBLIC_WEB_WORD_SOURCE_TITLE,
    PUBLIC_WEB_WORD_SOURCE_URL,
    public_web_word_contract_error,
)


PRE_RUN_REVIEW_VERSION = 2
MAX_PRE_RUN_PATH_CHARS = 2048


class PreRunReviewError(RuntimeError):
    """Fixed failure while compiling a non-authoritative Scope Sheet."""


@dataclass(frozen=True)
class ReviewApplication:
    """One fixed application identity and its reviewed role."""

    name: str
    role: str
    executable_override: str | None

    def as_json(self) -> dict[str, object]:
        return {
            "name": self.name,
            "role": self.role,
            "executable_override": self.executable_override,
        }


@dataclass(frozen=True)
class ReviewDataUse:
    """One fixed read or modification statement."""

    kind: str
    description: str
    location: str | None = None

    def as_json(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "description": self.description,
            "location": self.location,
        }


@dataclass(frozen=True)
class ReviewStopCondition:
    """One Host-owned reason execution will stop rather than infer success."""

    code: str
    description: str

    def as_json(self) -> dict[str, str]:
        return {"code": self.code, "description": self.description}


@dataclass(frozen=True)
class PreRunReview:
    """Versioned Scope Sheet with no execution or approval authority."""

    workflow: str
    objective: str
    applications: tuple[ReviewApplication, ...]
    reads: tuple[ReviewDataUse, ...]
    modifies: tuple[ReviewDataUse, ...]
    output_path: Path
    output_policy: str
    max_side_effects: int
    max_high_risk_approvals: int
    stop_conditions: tuple[ReviewStopCondition, ...]
    possible_residue: tuple[str, ...]

    def as_json(self) -> dict[str, object]:
        return {
            "pre_run_review_version": PRE_RUN_REVIEW_VERSION,
            "source": "host_fixed_contract",
            "contains_model_prose": False,
            "external_work_started": False,
            "workflow": self.workflow,
            "objective": self.objective,
            "applications": [item.as_json() for item in self.applications],
            "reads": [item.as_json() for item in self.reads],
            "modifies": [item.as_json() for item in self.modifies],
            "output": {
                "path": str(self.output_path),
                "policy": self.output_policy,
            },
            "action_authorization": {
                "policy": "host_risk_tier_v1",
                "low_risk_requires_action_approval": False,
                "high_risk_requires_action_approval": True,
                "ambiguous_or_out_of_scope": "deny",
            },
            "maximum_side_effects": self.max_side_effects,
            "maximum_high_risk_approvals": self.max_high_risk_approvals,
            "stop_conditions": [item.as_json() for item in self.stop_conditions],
            "possible_residue": list(self.possible_residue),
            "acknowledgement": {
                "interactive_token": "START",
                "noninteractive_flag": "--acknowledge-scope",
                "starts_ordinary_workflow_only": True,
                "grants_action_approval": False,
                "grants_retry_or_replay": False,
            },
        }


def _resolved_review_path(value: Path, *, suffix: str | None = None) -> Path:
    if not isinstance(value, Path):
        raise PreRunReviewError("PRE_RUN_REVIEW_PATH_INVALID")
    resolved = value.expanduser().resolve(strict=False)
    if (
        not resolved.is_absolute()
        or len(str(resolved)) > MAX_PRE_RUN_PATH_CHARS
        or "\x00" in str(resolved)
        or (suffix is not None and resolved.suffix.lower() != suffix)
    ):
        raise PreRunReviewError("PRE_RUN_REVIEW_PATH_INVALID")
    return resolved


def compile_public_web_word_review(
    config: AgentConfig,
    output: Path,
    *,
    chrome_executable: Path | None = None,
    word_executable: Path | None = None,
) -> PreRunReview:
    """Compile the fixed public-web-word Scope Sheet with zero external work."""

    error = public_web_word_contract_error(config)
    if error is not None:
        raise PreRunReviewError(error)
    output_path = _resolved_review_path(output, suffix=".docx")
    if output_path.exists():
        raise PreRunReviewError("PUBLIC_WEB_WORD_OUTPUT_EXISTS")
    if not output_path.parent.is_dir():
        raise PreRunReviewError("PUBLIC_WEB_WORD_OUTPUT_PARENT_NOT_FOUND")
    chrome_path = (
        None
        if chrome_executable is None
        else _resolved_review_path(chrome_executable)
    )
    word_path = (
        None if word_executable is None else _resolved_review_path(word_executable)
    )

    return PreRunReview(
        workflow="public-web-word",
        objective=(
            "Read the fixed public Microsoft Support source, author a two-to-four-"
            "bullet source-grounded brief, save one new Word document, then reopen "
            "and verify it."
        ),
        applications=(
            ReviewApplication(
                "Google Chrome",
                "Open the fixed public source in a fresh private profile.",
                None if chrome_path is None else str(chrome_path),
            ),
            ReviewApplication(
                "Microsoft Word",
                "Edit, save, close, reopen, and read back the disposable document.",
                None if word_path is None else str(word_path),
            ),
        ),
        reads=(
            ReviewDataUse(
                "public_web_page",
                PUBLIC_WEB_WORD_SOURCE_TITLE,
                PUBLIC_WEB_WORD_SOURCE_URL,
            ),
            ReviewDataUse(
                "packaged_template",
                "The packaged disposable DOCX template; no existing user document.",
            ),
            ReviewDataUse(
                "verification_readback",
                "The newly written output is reopened and read back for verification.",
                str(output_path),
            ),
        ),
        modifies=(
            ReviewDataUse(
                "new_document",
                "Create one new DOCX exclusively; an existing path is never overwritten.",
                str(output_path),
            ),
            ReviewDataUse(
                "private_workflow_state",
                "Create a disposable Chrome profile and bounded workflow evidence.",
                str(config.state_dir),
            ),
            ReviewDataUse(
                "fixture_lifecycle",
                "Open and close only the exact disposable Chrome and Word fixtures.",
            ),
        ),
        output_path=output_path,
        output_policy="CREATE_NEW_ONLY_NEVER_OVERWRITE",
        max_side_effects=PUBLIC_WEB_WORD_MAX_SIDE_EFFECTS,
        max_high_risk_approvals=PUBLIC_WEB_WORD_MAX_HIGH_RISK_APPROVALS,
        stop_conditions=(
            ReviewStopCondition(
                "PRECONDITION_FAILED",
                "Configuration, application, source, or output preconditions fail.",
            ),
            ReviewStopCondition(
                "OPERATOR_NOT_APPROVED",
                "The operator denies, defers, closes, or times out one exact action.",
            ),
            ReviewStopCondition(
                "DESKTOP_AUTHORITY_LOST",
                "Human input, E-stop, foreground drift, grounding, or policy blocks work.",
            ),
            ReviewStopCondition(
                "BOUND_EXHAUSTED",
                "A model, tool, token, side-effect, correction, or timeout bound is reached.",
            ),
            ReviewStopCondition(
                "VERIFICATION_FAILED",
                "Brief, save, reopen/read-back, artifact, or fixture cleanup is not proven.",
            ),
            ReviewStopCondition(
                "UNKNOWN_OUTCOME",
                "A side effect may have happened; stop and do not retry automatically.",
            ),
        ),
        possible_residue=(
            "A failed or unknown run may leave a partial DOCX at the output path for inspection.",
            "Private workflow/profile files or fixture processes may remain when cleanup cannot be verified.",
        ),
    )


def render_pre_run_review(review: PreRunReview) -> str:
    """Render one human-first Scope Sheet without adding inferred facts."""

    if not isinstance(review, PreRunReview):
        raise PreRunReviewError("PRE_RUN_REVIEW_INVALID")
    lines = [
        "Pre-run Review - nothing has started",
        f"Workflow: {review.workflow}",
        f"Goal: {review.objective}",
        "",
        "Applications",
    ]
    for application in review.applications:
        override = (
            "automatic installed-app discovery"
            if application.executable_override is None
            else application.executable_override
        )
        lines.append(f"- {application.name}: {application.role} [{override}]")
    lines.extend(["", "Reads"])
    for item in review.reads:
        location = "" if item.location is None else f" ({item.location})"
        lines.append(f"- {item.description}{location}")
    lines.extend(["", "Changes"])
    for item in review.modifies:
        location = "" if item.location is None else f" ({item.location})"
        lines.append(f"- {item.description}{location}")
    lines.extend(
        [
            "",
            f"Output: {review.output_path}",
            "Output policy: create new only; never overwrite.",
            f"Maximum side effects: {review.max_side_effects}",
            "Host risk policy: reviewed low-risk reversible effects do not prompt; "
            "high-risk effects require one exact approval; ambiguous or out-of-scope "
            "effects are denied.",
            "Maximum high-risk action approvals: "
            f"{review.max_high_risk_approvals}",
            "",
            "Stops when",
        ]
    )
    lines.extend(
        f"- {item.description} [{item.code}]" for item in review.stop_conditions
    )
    lines.extend(["", "Possible unfinished state"])
    lines.extend(f"- {item}" for item in review.possible_residue)
    lines.extend(
        [
            "",
            "Starting this workflow does not approve a high-risk desktop action and does not grant retry or replay authority. Reviewed low-risk effects proceed only under the fixed Host policy above.",
        ]
    )
    return "\n".join(lines) + "\n"


__all__ = [
    "PRE_RUN_REVIEW_VERSION",
    "PUBLIC_WEB_WORD_MAX_HIGH_RISK_APPROVALS",
    "PUBLIC_WEB_WORD_MAX_SIDE_EFFECTS",
    "PreRunReview",
    "PreRunReviewError",
    "ReviewApplication",
    "ReviewDataUse",
    "ReviewStopCondition",
    "compile_public_web_word_review",
    "render_pre_run_review",
]
