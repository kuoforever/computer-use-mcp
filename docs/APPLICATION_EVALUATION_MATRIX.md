# Application evaluation matrix

> **Status: planned real-application evaluation.** These cases complement the
> isolated Notepad E4 smoke. They are not default CI tests and must use dedicated
> test data or accounts appropriate to the application.

## Purpose

The universal-GUI goal requires representative applications with different
rendering, state, and recovery behavior.

| Family | Representative | Primary difficulty |
| --- | --- | --- |
| Dynamic browser workflow | BOSS saved jobs | Large item collection, virtualized/static content, login/challenge state, long duration |
| Canvas document editor | Google Docs | Canvas rendering, accessibility/document-text gaps, cursor and selection state, long documents |
| Native messaging client | WeChat | Window recreation, foreground/focus, search, conversation identity, externally visible send action |

These three applications are Wave 1. Later waves add failure mechanisms that
the first set does not cover.

## Shared measurements

Every case records:

- application/runtime version and Windows build;
- observation sources used and escalation count;
- UIA nodes/characters, OCR regions/characters, and image pixels;
- provider input/output tokens;
- model/tool calls and retries;
- committed items and tokens per committed item;
- activation, stale-ref, challenge, and unknown-outcome counts;
- batch boundaries, fresh provider contexts, and forced restarts;
- whether continuation required prior chat text (must be no).

## A1: BOSS saved-job review

### Goal

Review at least 100 saved-job identities without changing the saved collection.

### Work item

One stable job identifier or URL. Extract a bounded schema such as company,
role, location, compensation, experience, and a semantic classification.

### Required coverage

- at least five batches and two fresh provider contexts;
- one restart between items;
- one restart after observation but before item commit;
- one stale UI reference and one activation failure;
- bounded document-text/OCR or crop fallback when UIA lacks static content;
- login/challenge detection produces a durable handoff instead of repeated
  navigation.

### Pass condition

One committed result per stable item key, no duplicate committed outputs, and a
fresh session resumes from the campaign handoff without conversational history.

## A2: Google Docs long-document review

### Goal

Review a dedicated test document containing at least 50 sections or pages with
headings, paragraphs, lists, tables, links, and images. The initial campaign is
read-only.

### Work item

One heading-delimited section or other stable document range. Prefer a document
structure identifier when exposed; otherwise use a bounded ordinal plus nearby
heading digest and revalidate it on resume.

### Required coverage

- detect that the visible editor body is canvas-based or otherwise not fully
  represented by ordinary DOM/UIA nodes;
- compare UIA/accessibility, bounded document text, OCR, and cropped screenshot
  observations;
- navigate by heading/search/keyboard as well as visual clicking;
- rotate provider context at least twice;
- force a restart while scrolled away from the current section and prove the
  item identity is re-established;
- change browser zoom or viewport once and invalidate stale coordinates;
- verify that final structured output covers every committed section exactly
  once.

### Optional edit tier

Use a disposable copy of the document. Apply one deterministic marker or style
change to a named test section, verify it visually and structurally when
possible, and treat a crash after dispatch but before verification as
`UNCERTAIN`. Never replay the edit solely because the run restarted.

## A3: WeChat native-client workflow

### Goal

Exercise native window lifecycle, contact search, conversation selection, and
draft verification using a dedicated test contact, test group, or File Transfer
Assistant. The baseline does not send a message.

### Work item

One test conversation identity and one bounded draft instruction. Do not use
display position alone as identity; revalidate the conversation title or other
available identity after every restart.

### Required coverage

- launcher/login window changes into a new main-window handle;
- stale window ID recovery through a fresh `list_windows` observation;
- activation after Codex or another benign app owns foreground;
- contact search and exact conversation disambiguation;
- editor focus verification before typing;
- draft text verification without sending;
- one forced restart before typing and one after draft verification;
- multiple conversations in the campaign remain distinct by stable test alias.

### Optional send tier

Use only a dedicated test destination. Sending is a separate side-effect item
with an idempotency key and a pre-send approval boundary. After dispatch, verify
the outgoing bubble or delivery state before commit. If the result is unknown,
record `UNCERTAIN` and require human re-observation; do not send the same payload
again automatically.

## Cross-application scenario

After individual cases pass, run one campaign that:

1. reads a bounded set of BOSS job results;
2. writes a structured summary into a disposable Google Doc copy;
3. prepares, but does not send, a WeChat draft pointing the test recipient to
   that summary;
4. rotates provider context between applications;
5. resumes from a fresh Codex session before the WeChat step.

The handoff contains only fixed campaign state and artifact identifiers, not
prior model prose or raw page/chat content.

## Promotion gates

1. Read-only single-application case.
2. Forced restart and fresh-provider-context case.
3. 100-item or 50-section long-run case.
4. Optional disposable-data side-effect tier.
5. Cross-application campaign.

Failures in a later tier do not invalidate the narrower capability, but the
released documentation must state the highest tier with retained evidence.

## Wave 2: high-value coverage gaps

### A4: Excel large virtualized grid

Use a dedicated workbook with at least 10,000 rows, multiple sheets, formulas,
filters, frozen panes, merged cells, and one table.

Required coverage:

- identify workbook, sheet, and A1-style cell identity separately from screen
  position;
- move across a virtualized grid and frozen panes;
- distinguish displayed value, formula, and edit mode;
- resume after the active cell and scroll position changed;
- verify one disposable-cell edit without using a stale coordinate;
- measure when keyboard/name-box navigation outperforms UIA or vision.

Primary mechanism: semantic coordinates over a virtualized two-dimensional
surface.

### A5: PDF text, scan, and layout conflict

Use four dedicated fixtures: native-text PDF, scanned PDF, two-column paper,
and a PDF containing a table, comments, or form fields.

Required coverage:

- compare PDF text layer, accessibility order, OCR, and visual reading order;
- detect when extracted order conflicts with visible layout;
- resume from a stable page/section identity after zoom or scroll changes;
- classify missing or conflicting text as uncertain instead of silently
  merging incompatible sources;
- measure tokens and accuracy for text, OCR regions, and page crops.

Primary mechanism: conflicting semantic and visual representations.

### A6: Figma or Canva infinite canvas

Use a disposable design containing named frames, nested groups, text, images,
and partially overlapping objects.

Required coverage:

- distinguish world, viewport, and screen coordinate spaces;
- pan and zoom before relocating the same named frame;
- identify occluded and selected objects;
- perform one disposable property or text edit and visually verify it;
- invalidate coordinates after zoom, layout, or viewport changes;
- recover from selection mode versus text-edit mode confusion.

Primary mechanism: infinite canvas, object modes, drag paths, and multiple
coordinate systems.

### A7: Electron collaboration client

Use Slack, Teams, Discord, or an equivalent Electron application with a
dedicated workspace/channel.

Required coverage:

- enumerate the correct top-level window and renderer ownership chain;
- navigate a virtualized message list and search results;
- handle Shadow DOM, webview/iframe, native menu, and popup boundaries when
  exposed by the chosen observation backend;
- distinguish draft/editor state from sent-message state;
- resume after a renderer refresh without reusing stale element identities.

Primary mechanism: browser technology embedded in a multi-process desktop app.

## Wave 3: pure-vision, mode, and system boundaries

### A8: Remote Desktop, Citrix, or VM console

Use a disposable guest containing a benign editor or form.

Required coverage:

- treat the guest as a pixel surface when host UIA cannot expose guest controls;
- model host-window, guest-viewport, and guest-screen coordinates;
- recover after reconnect, latency, or resolution/DPI change;
- detect whether key chords were consumed by host or guest;
- verify each action from a later frame rather than assuming immediate effect.

Primary mechanism: a computer interface nested inside another application.

### A9: Word and PowerPoint mode transitions

Use disposable documents and presentations containing body text, comments,
headers, tables, text boxes, and shapes.

Required coverage:

- distinguish object selection, insertion point, text editing, and modal
  ribbon/dialog states;
- use keyboard and menu-search paths when ribbon UIA is unstable;
- re-establish document/slide/object identity after restart;
- verify one disposable edit at both semantic and visual levels when possible.

Primary mechanism: rich-document mode state and mixed native/canvas surfaces.

### A10: Legacy ERP, Java Swing, Qt, or industrial UI

Use a non-production fixture or demo with custom tables, trees, modal dialogs,
and form controls.

Required coverage:

- record which accessibility patterns are exposed but nonfunctional;
- exercise the fallback chain from native pattern to keyboard, OCR, and
  coordinates;
- detect owned or blocking modal dialogs;
- continue after one stale-control and one incomplete-accessibility failure.

Primary mechanism: inconsistent accessibility and blocking custom widgets.

### A11: Blender, CAD, or video editor

Use a disposable project and a narrowly bounded action.

Required coverage:

- track workspace, editor, active tool, mode, selection, and pending modal
  operation;
- confirm which viewport has focus before issuing shortcuts;
- escape or cancel a pending modal tool before recovery;
- verify one bounded change without relying on UIA content.

Primary mechanism: GPU viewport, shortcut-heavy modal state, and drag semantics.

### A12: System dialog and secure-desktop boundary

Exercise file pickers, save/overwrite prompts, print dialogs, crash recovery,
and a synthetic elevation-required boundary.

Required coverage:

- distinguish application window, owned modal, system dialog, and secure
  desktop;
- restore the parent application after a modal closes;
- return fixed `SECURE_DESKTOP`, `ELEVATION_REQUIRED`, or
  `HUMAN_HANDOFF_REQUIRED` states when the surface cannot be controlled;
- never report a black or unavailable capture as successful observation.

Primary mechanism: process/window topology and intentionally non-automatable
system boundaries.

## Cross-cutting input suite

Run the following input cases against WeChat, an Electron editor, Office, and a
plain native editor:

- ASCII text;
- Chinese IME composition;
- mixed Chinese/English text;
- emoji and supplementary Unicode characters;
- newline versus send-key behavior;
- clipboard paste versus direct Unicode input;
- unfinished IME candidate state before an externally visible submission.

Record the actual transport used, focused control identity, visible result, and
whether input composition remained pending.

## Coverage scoring

Score each application on the same axes so progress is measured by failure
mechanisms rather than application count:

| Axis | 0 | 1 | 2 | 3 |
| --- | --- | --- | --- | --- |
| Perception opacity | complete structured tree | partial structure | OCR/visual mix | pixel-only/nested display |
| State volatility | static | navigation changes | virtualized/dynamic | real-time/recreated surface |
| Input complexity | click/type | shortcuts | drag/IME | modal tool/multi-step gesture |
| Window topology | one window | owned modal | multi-process/multi-window | nested or secure desktop |
| Coordinate complexity | fixed window | scroll | zoom/multi-space | remote/multi-monitor transform |
| Task scale | one step | one document | tens of items | hundreds/day-scale campaign |

An application adds meaningful coverage only when it exercises a cell not
already proven by a simpler case.

## Recommended order

1. Wave 1: BOSS, Google Docs, WeChat.
2. Wave 2: Excel, PDF, Figma/Canva, one Electron client.
3. Remote Desktop and system-dialog detection.
4. Word/PowerPoint and one legacy custom-widget application.
5. Blender/CAD only after observation epochs, mode tracking, and drag recovery
   are stable.
