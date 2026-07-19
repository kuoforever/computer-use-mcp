# Observation contract

> **Status: partially implemented multi-source contract.** UIA snapshots,
> primary-display screenshots, and bounded region OCR are implemented.
> Document text, deltas, and standalone scoped image capture remain design
> targets.

## Purpose

A universal GUI agent needs one observation model that can degrade from rich
structure to pixels without pretending every application exposes a usable
accessibility tree.

~~~text
structured app / browser accessibility
  -> UIA
  -> document text when explicitly available
  -> OCR
  -> vision screenshot
~~~

The caller chooses the cheapest sufficient source and may escalate after an
explicit incomplete result.

## Envelope

All observation backends should project into:

~~~text
Observation {
  id,
  epoch,
  source: "uia" | "document_text" | "ocr" | "image" | "delta",
  scope,
  window_identity,
  coordinate_space,
  complete,
  truncated,
  content_digest,
  payload
}
~~~

`epoch` changes whenever an action invalidates grounding or a new observation
detects material application state change. Refs and coordinates declare which
epoch grounded them.

## Scope

Supported target forms should be explicit:

~~~text
foreground
window:<stable runtime id>
region:<window id>:<x,y,w,h>
display:<display id>
all
~~~

The current runtime implements only part of this model. A backend must reject
unsupported scopes instead of silently widening to the entire display.

## Source-specific payloads

### UIA

Bounded nodes with role, name, safe value, state, patterns, bounding box, and
session ref. Preserve truncation and incomplete-browser hints.

### Document text

Text exposed through an application- or browser-supported semantic channel.
Return bounded blocks with stable local ordering and optional bounding boxes.
Do not label DOM body dumps or hidden application state as document text.

### OCR

Bounded text runs with box, confidence, reading order, language hint, and image
digest. OCR results are evidence, not invokable refs. Acting on OCR requires a
fresh target-location check.

The current Windows backend accepts one explicit primary-display rectangle,
uses the installed user-profile OCR languages, and reports confidence as
`null` because `Windows.Media.Ocr` does not expose word confidence. It returns
both crop-local `bbox` and primary-display `screen_bbox` values.

### Image

PNG bytes plus dimensions, scale, crop origin, display metadata, and digest.
Image bytes travel through native image content, never text serialization.

### Delta

Added, removed, or changed observations relative to a declared base digest.
Reject a delta when the base is unavailable, the window identity changed, or
the changed region exceeds the configured bound.

## Bounding

Each call must enforce source-appropriate limits:

- maximum nodes or text runs;
- maximum characters;
- maximum image pixels and encoded bytes;
- maximum regions;
- maximum wall time.

The result reports omitted counts or an explicit incomplete reason. Silent
truncation is not allowed.

## Grounding and actions

- UIA refs remain session- and epoch-scoped.
- OCR boxes and image coordinates declare their coordinate space and epoch.
- Document-text offsets do not imply clickable screen coordinates.
- An action invalidates prior grounding unless the backend proves otherwise.
- Post-action verification uses a new observation epoch.

## Static browser content

The BOSS live probe showed that interactive UIA controls can be present while
job-description text is absent. This is an observation gap, not proof of site
blocking. The planned fallback is:

1. `find` for known controls;
2. bounded UIA snapshot;
3. bounded document-text channel when available;
4. OCR over the job card or detail region;
5. cropped image observation;
6. full screenshot only for orientation or layout recovery.

## Challenge classification

Observation adapters may report fixed non-content states:

~~~text
AUTH_REQUIRED
CHALLENGE_REQUIRED
RATE_LIMITED
SITE_BLOCKED
CONTENT_UNAVAILABLE
~~~

These are diagnostic states, not instructions to bypass a site control. They
stop equivalent automatic retries and allow a long-running campaign to persist
a resumable handoff.

## Evaluation

The first evaluation corpus should contain:

- native Windows controls with complete UIA;
- Chrome with interactive controls but missing static text;
- Google Docs or an equivalent canvas document editor, including zoom and
  scroll-position changes;
- WeChat or an equivalent native messaging client whose launcher/main windows
  have different handles and whose editor requires verified focus;
- an image-only or remote-desktop surface;
- a dynamic page where a UIA ref becomes stale;
- a visible login or challenge state;
- a multi-monitor case once the coordinate model exists.

Later evaluation waves add Excel grid virtualization, PDF text/OCR ordering,
Figma/Canva infinite canvases, Electron virtual lists, Remote Desktop nested
pixels, Office mode transitions, legacy custom widgets, and GPU modal tools.

For each case, measure completeness, characters, nodes, image pixels, provider
tokens, tool calls, retries, and whether the chosen source was sufficient for
the next decision.

See [Application evaluation matrix](APPLICATION_EVALUATION_MATRIX.md) for the
first BOSS, Google Docs, WeChat, and cross-application scenarios.
