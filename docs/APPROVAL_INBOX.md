# Approval Inbox and local notifications

> **Status: implemented, offline verified, and bounded native notification
> lifecycle verified.** This surface supplements the
> existing Decision Card. It does not approve, deny, defer, take over, resume,
> retry, or dispatch work.

## Product purpose

Mature supervised-agent products separate an attention signal from the place
where authority is granted. Guarded Desktop Agent follows that separation:

1. the Runner records `WAITING_APPROVAL` and creates its digest-bound
   `ApprovalRequest`;
2. the existing `DecisionCardApprovalPort` compiles the exact card and expiry;
3. a private pending record and optional fixed-content Windows notification
   make the waiting decision discoverable;
4. the operator returns to the bound Decision Card to decide; and
5. card choice, close, timeout, cancellation, or ordinary cleanup withdraws the
   notification and removes the record.

The Inbox is an inspection surface only. Its command is:

~~~powershell
guarded-desktop-agent approval inbox --config C:\absolute\path\agent.toml
guarded-desktop-agent approval inbox --config C:\absolute\path\agent.toml --json
~~~

`pending_at_last_record` means only that an unexpired validated record existed
at read time. It is not a process-liveness claim. An abnormal process exit may
leave a record until its exact Decision Card expiry; that record can become
`expired`, but it can never revive approval authority. Corrupt, oversized,
unsupported, or identity-invalid records are excluded and counted as
unavailable rather than trusted.

## Data and authority boundary

One record contains only:

- request, run, turn, and call identity;
- one fixed reviewed action classification;
- the existing call and Decision Card SHA-256 digests; and
- opened and expiry timestamps.

Records never contain raw arguments, safe argument summaries, task text, model
prose, screenshots, UI content, typed values, credentials, account names,
arbitrary errors, or tool results. They are local to the configured private
`state_dir`, bounded in count and size, strictly versioned, and fail closed on
unsafe paths or malformed data.

The English Windows notification contains only the fixed title `Guarded Desktop Agent`
and fixed body `Approval needed. Return to the open decision window.` It
contains no request ID, run ID, tool name, digest, target, task, model content,
or action button. It is withdrawn by Host routing identity, but that identity
is not rendered or serialized into notification content. Notification
construction, display, or withdrawal failure cannot change a policy decision.

The only allow path remains:

~~~text
Decision Card choice
  -> existing ApprovalPort validation
    -> Runner grounding and budget checks
      -> sole local stdio MCP dispatch
~~~

Inbox reads and notification delivery have no provider, desktop, MCP, or task
mutation port.

## Configuration

The Decision Card remains the prerequisite. Notifications are separately
configurable:

~~~toml
[operator]
decision_cards_enabled = true
approval_notifications_enabled = true
~~~

Newly generated installed profiles enable both settings. A missing key remains
`false` for compatibility. The Inbox record lifecycle is active whenever the
Decision Card is enabled, even if notifications are disabled or unavailable.
Console approval does not synthesize an Inbox record because it has no compiled
Decision Card expiry to bind.

## Accessibility and UX status

Implemented accessibility properties:

- the human CLI view uses explicit status words, absolute expiry, remaining
  time, and next action rather than colour or animation;
- the versioned JSON view exposes the same facts for assistive wrappers;
- the Windows notification uses the operating-system notification surface and
  respects Windows quiet-time behavior;
- the notification is noninteractive, so it cannot create an inaccessible
  alternate approval control; and
- the Decision Card remains the single keyboard/focus-taking decision surface.

Not yet claimed:

- retained Narrator, NVDA, or JAWS announcement evidence for the native
  notification and Decision Card together;
- human judgment of the automated keyboard/UIA order, 200%/400% reflow, and
  Windows High Contrast presentation;
- notification-center persistence behavior across Windows versions, a native
  Inbox window, multi-monitor placement, or mobile push; and
- localization of Approval Inbox CLI wording; the fixed notification itself is
  localized in English and Simplified Chinese under the
  [operator localization contract](OPERATOR_LOCALIZATION.md).

The current two-locale Shell show/withdraw lifecycle is retained in
[PRODUCT-017 automated native evidence](PRODUCT017_AUTOMATED_NATIVE_EVIDENCE.md).
Windows
quiet time means Shell acceptance is not a visibility claim. The remaining
gaps do not weaken the current exact approval, expiry, privacy, or dispatch
boundaries.

## Verification boundary

Offline tests cover strict persistence and parsing, expiry, corrupt-record
isolation, bounded projection, empty-read inertness, registry action coverage,
raw-content exclusion, fixed notification payload, notifier withdrawal, CLI
human/JSON parity, strict configuration, and fail-silent attachment to the
existing Decision Card. This evidence proves the local contract; it does not
prove provider, live desktop, application, or release behavior.
