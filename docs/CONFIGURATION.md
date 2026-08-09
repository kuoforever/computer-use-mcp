# Configuration and safety

> **Status: implemented on Windows.** This page describes the current runtime
> behavior, not a future safety model.

Desktop actions have visible side effects. Keep the allowlist narrow and use
`safe_local` unless an operator has explicitly approved local takeover.

## First-run readiness

The five configuration commands answer different questions:

| Command | Purpose | External activity |
| --- | --- | --- |
| `config setup [--profile PROFILE] [--provider NAME] [--model ID] [--output PATH] [--pause-shortcut CHORD]` | Create one non-overwriting configuration with reviewed defaults and print the exact next check | Creates the same user-local state and MCP working directories as `config init`; reads no credential value and starts no process |
| `config settings [--config PATH] [--json]` | Project the strict TOML as human-first Agent Controls settings | Reads configuration plus provider SDK/credential presence only; creates no state and starts no process |
| `config init --profile PROFILE --provider NAME --model ID --output PATH [--pause-shortcut CHORD]` | Create one non-overwriting, immediately valid installed product profile with a sibling MCP path | Creates the user-local state and MCP working directories; reads no credential and starts no process |
| `config validate --config PATH` | Parse and validate the strict TOML contract | Creates no state directory, reads no credential, and starts no process |
| `config doctor --config PATH` | Prove that the installed provider/MCP runtime is ready | Checks the provider extra and documented key variable, checks MCP paths, then performs one MCP `initialize` / `list_tools` handshake and verifies the exact configured surface: thirteen core schemas plus optional `browser_snapshot` when enabled |

`config setup` defaults to the reviewed `desktop-ask` / `openai` combination
and the current project-validated model ID. Explicit profile, provider, model,
path, Desktop Ask allowlist, and pause-shortcut overrides pass through the same
closed `config init` validation. It never overwrites an existing file, writes a
credential, runs doctor automatically, or starts a provider/MCP/application/
desktop port.

`config settings` uses the default user-local setup path when `--config` is
omitted. Its human and `--json` outputs derive from the same strict
`AgentConfig` and report only bounded configuration, presentation preferences,
provider SDK/credential-variable presence, paths, and the exact doctor command.
Its authority flags are all false, including shortcut registration. See
[Quick Setup and Agent Controls](AGENT_CONTROLS.md).

Shortcut registration belongs only to an explicitly started
`shortcuts run [--config PATH]` foreground host. Settings remain inert and
cannot report another process's liveness. The host atomically owns fixed
`Ctrl+Alt+G` presentation and the configured cooperative-pause request chord
(default `Ctrl+Alt+P`), reports layout/registration conflicts before ACTIVE,
and releases both on exit. `[operator].pause_shortcut` accepts only canonical
`ctrl+alt+<a-z>`; G and Q are reserved. It has no approve/resume action and
does not replace the independent `Ctrl+Alt+Q` emergency stop.

For OpenAI, doctor requires the `agent-openai` extra and a non-empty
`OPENAI_API_KEY`; for Claude it requires `agent-anthropic` and a non-empty
`ANTHROPIC_API_KEY`. Credential values are neither printed nor passed to the MCP
child. The command returns fixed JSON, exits `0` when `ready` is `true`, and
exits `2` with one `{code, action}` failure when setup is incomplete.

Doctor sends no provider request and invokes no MCP tool, so it does not list
windows, capture the screen, read desktop content, or perform an input action.
It does start the configured MCP child to discover its public schemas. Normal
server startup constructs the Windows driver, can create the configured audit
directory, and starts emergency-stop key polling until the child is closed.

`--profile desktop-ask` is the default and generates the existing read-only,
continuation-enabled Notepad profile. `--profile public-web-word` generates the
fixed workflow's `approved_actions` profile, allows only `chrome.exe` and
`winword.exe`, disables continuation, and sets bounded budgets of 28 model
turns, 24 tool calls, and 7 side effects. It also writes
`action_approval_policy = "high_risk_only"`: only a side effect that the fixed
Host workflow validates as an exact in-scope reversible step is classified
low risk and allowed without a Decision Card. High-risk effects still require
an exact approval; a missing classifier, invalid proposal, ambiguity, or scope
drift is denied before dispatch. Risk is never provider- or model-authored.
Every legacy or hand-written `approved_actions` profile that omits this setting
defaults to `action_approval_policy = "all_side_effects"` and retains one
approval per side effect. Both generated installed product
profiles explicitly enable all current UI/UX booleans: action feedback,
presence, progress, reduced motion, high contrast, and Decision Cards. These
profiles also write the strict presentation-only `theme = "auto"` preference.
These surfaces remain passive or locally interactive under their existing contracts;
the settings grant no provider, desktop, approval, replay, or side-effect
authority. See the
[workflow contract](PUBLIC_WEB_WORD_WORKFLOW.md). Its allowlist is closed:
`config init --profile public-web-word` rejects `--allowlist`, and the runtime
rejects a hand-edited value instead of failing later during Chrome or Word use.

`[provider].request_timeout_seconds` defaults to `120` and accepts integers from
`1` through `600`. The public-web-word generated profile uses `90`. Expiry
terminalizes that provider turn as fixed `PROVIDER_TIMEOUT` before any proposed
desktop call from the timed-out turn can be dispatched.

## Control modes

### `safe_local` (default)

Before an action is executed, the server:

1. Rejects it if the emergency stop is latched.
2. Yields when recent human input is detected.
3. For `click`, `scroll`, `drag`, `type`, and `key`, checks that the foreground
   window's process ownership chain contains an allowlisted executable.
4. For a dangerous `click(ref=...)`, asks for a native confirmation dialog.
5. Immediately before `Session`, rechecks e-stop, the foreground where required,
   and human input without waiting or retrying.
6. Repeats that non-waiting check through one call-scoped boundary immediately
   before every later driver-controlled native mutation.
7. Writes one action result to the JSONL audit log.

`activate_window(window_id)` intentionally skips the foreground allowlist
check, because it is used to bring a listed target forward. It still requires
that this MCP instance successfully returned the id from `list_windows`, bound
to the exact direct-owner PID and executable name. The server captures that
binding when the activation call begins, rechecks the live owner before every
native mutation and after the Driver returns, and requires a fresh successful
`list_windows` after the target disappears or its owner changes. At a mutation
checkpoint the owner enumeration runs before the final non-waiting e-stop and
human checks, so that slower read cannot age the more volatile human authority.
In safe mode activation remains human-activity guarded, e-stop guarded, and
audited.

The initial stable-idle gate captures the current platform input tick for this
MCP call. The final human check samples the tick around one fresh idle-age
observation and returns `HUMAN_ACTIVE` with zero driver calls when evidence is
unavailable or changed. A successful dangerous confirmation may pass its exact
post-dialog tick only into that click's final check so the approving input does
not reject itself. That capture is never stored, never treated as agent input,
and cannot be reused by the next MCP call; any newer tick rejects. Windows
events reported under the same `GetLastInputInfo` millisecond tick cannot be
distinguished by this boundary.

When a reviewed side effect returns the exact
`REJECTED / NOT_DISPATCHED / HUMAN_ACTIVE` or
`REJECTED / NOT_DISPATCHED / DENIED_BY_GATE` tuple, the Agent Host invalidates
its prior verified observation and all Host-owned grounding before completing
the continuation record. The former means current human-idle authority is
unavailable or indicates that local input may have changed the desktop since
Host grounding was established; the latter proves the live foreground gate no
longer grants the authority checked for the attempted action. A later side
effect therefore requires a fresh successful observation; refs, window ids, and
screenshot bounds from before the yield cannot regain authority through an
unrelated observation or later allowlisted foreground. This rule does not
generalize to observation-shaped results, other certainty tuples, or unrelated
rejected actions.

After each known-returning native input inside a multi-event action, an exact
tick capture is allowed only for the next checkpoint in that same call. It keeps
pointer/key/drag pacing from yielding to its own preceding event. Physical input
that lands after native return but before this capture can still be
misattributed; the Runtime installs no global source-tagging hook and makes no
stronger claim.

After a known-successful native mouse or keyboard action, the server records
the platform input tick so its next action does not yield to its own injected
input. This attribution is limited to successful OS-input ref/coordinate
clicks, valid scrolls and drags, focused-control typing without a ref, and key
chords. User-enabled semantic UIA ref clicks and ref typing, window activation, validation failures,
no-op motions, and failed driver results never claim an input tick. Concurrent
human input therefore remains authoritative and makes the next `safe_local`
action yield without dispatch. A failed native call is left unattributed. If it
follows one or more recorded native attempts, the current run instead
terminalizes immediately with the fixed redacted `NATIVE_OUTCOME_UNKNOWN`
unknown-outcome/dispatched result and cannot issue a next action or replay.

If repeated authority fails before any native mutation, the action retains its
fixed rejected/not-dispatched result. If a native attempt already occurred, the
driver stops target progress, performs only required key/button release or input-
queue detach cleanup, and the server returns fixed `NATIVE_AUTHORITY_LOST` as
unknown-outcome/dispatched. This remains distinct from
`NATIVE_OUTCOME_UNKNOWN`, which the server emits when the native action itself
returns failure or raises after an attempt. The Agent terminalizes either result
and never replays the call. Cleanup is not rollback and does not restore pointer
or application state. A zero-attempt failure retains its existing result and
certainty semantics.

For activation, `NATIVE_AUTHORITY_LOST` also covers a missing observation
binding, a disappeared target, owner drift, ambiguous duplicate ids, or invalid
direct-owner evidence. The fixed result never includes the observed or live
owner. Internal window enumeration for screenshot, OCR, or redaction cannot
create or refresh activation authority.

### `full_control_local`

This mode explicitly bypasses the foreground allowlist and human-activity
yielding checks. It **does not** disable the emergency stop or auditing; the
e-stop is still rechecked before every driver-controlled native mutation.
Activation's observed-owner binding and live target checks also remain active.
Dangerous ref-click confirmation defaults to off in this mode, but can be
enabled with `CUMCP_DANGEROUS_CONFIRM=1`.

Use it only for an operator-approved local session. It does not make
same-desktop background control safe or parallel.

## Environment variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `CUMCP_ALLOWLIST` | `notepad.exe` | Comma-separated executable names allowed for safe-mode foreground actions. Surrounding whitespace on each non-empty item is ignored. Matching is case-insensitive and exact per executable name; a match anywhere in the foreground process ancestry is accepted. |
| `CUMCP_MODE` | `safe_local` | Either `safe_local` or `full_control_local`. No `isolated_worker` mode is currently accepted. |
| `CUMCP_HUMAN_IDLE_SECONDS` | `2.5` | Seconds after local mouse/keyboard input during which safe-mode actions yield. |
| `CUMCP_HUMAN_STABLE_SAMPLES` | `1` | Consecutive healthy idle samples required inside one MCP action call. The bounded Demo and installed Public Web to Word workflow use `3`, so a Decision Card click can settle before the approved action continues; a timeout rejects before dispatch and is never replayed. |
| `CUMCP_HUMAN_POLL_INTERVAL_SECONDS` | `0.25` | Interval between consecutive readiness samples. The Host accepts only `0.05` through `5.0` seconds. |
| `CUMCP_HUMAN_MAX_WAIT_SECONDS` | `60` | Maximum time one action call may wait for a stable idle streak. The Host accepts only `1` through `300` seconds. The installed Public Web to Word profile fixes this at `15`, below its 30-second MCP bridge timeout, so extended operator activity remains a known pre-dispatch result rather than a transport timeout. |
| `CUMCP_INTERACTION_SPEED` | unset | Optional Host-owned presentation profile: `fast`, `normal`, or `deliberate`. It changes only bounded pointer motion, pre/post-action dwell, and the default typing delay. Unset preserves native timing. Delay is never authority: every later native mutation still revalidates. The profile never changes observation, approval, readiness, policy, budgets, or verification. |
| `CUMCP_ACTION_FEEDBACK` | Raw MCP default `0`; generated product profiles write `1` | Shows a passive, click-through, non-activating, capture-excluded mouse halo and content-free `AGENT TYPING` / `AGENT KEY` badge. During visible typing, a pulsing caret, cycling dots, and progress bar follow the foreground editor's native caret using bounded geometry plus length/timing metadata. If no native caret exists, the badge stays at its last safe fallback. It never receives typed text or key values. |
| `CUMCP_TYPE_WAIT_SECONDS` | profile value or `0` | Optional explicit delay between literal Unicode scalars for focused-control OS typing. Accepted range is `0` to `0.1`; it overrides the selected presentation profile. Braces are literal; chords use `key`. User-enabled ref-based ValuePattern writes remain one opaque UIA mutation rather than per-character. |
| `CUMCP_BROWSER_OBSERVATION` | `off` | `off` exposes the thirteen core tools. `cdp` adds the reviewed read-only `browser_snapshot` tool and makes the Agent Host advertise it to the model. |
| `CUMCP_BROWSER_CDP_ENDPOINT` | `http://127.0.0.1:9222` | Existing Chromium debugging endpoint used only when browser observation is `cdp`. It must be loopback `http`/`ws`, include a port, and contain no credentials, query, or fragment. The Runtime neither launches nor closes the browser. |
| `CUMCP_UIA_ACTIONS` | `0` | OS pointer/keyboard input is the default action route. Set to `1` only when the user wants ref clicks to use UIA Invoke/SelectionItem and ref typing to use ValuePattern. A failed UIA call never falls back to OS input. |
| `CUMCP_DANGEROUS_CONFIRM` | on in safe mode; off in full-control mode | Enables confirmation for dangerous `click(ref=...)` targets. |
| `CUMCP_ESTOP` | `ctrl+alt+q` | Global hotkey that latches all actions off until the server restarts. |
| `CUMCP_AUDIT` | `audit/actions.jsonl` | JSONL audit-log path. |
| `CUMCP_REDACT_TITLES` | `1Password,Bitwarden,KeePass,Authenticator` | Comma-separated title substrings for screenshot, OCR, and cropped-capture blackouts. Surrounding whitespace on each non-empty item is ignored, and matching is case-insensitive. |
| `CUMCP_VMRUN` | unset | Optional path to VMware `vmrun.exe` for the host-side helper. |
| `CUMCP_WORKER_VMX` | unset | Existing VMware `.vmx` path for the host-side helper. |

For both comma-list variables, compact and spaced forms are equivalent. An
unset, empty, or whitespace-only value retains the documented default.

Examples:

~~~powershell
# Default guardrails; only foreground Notepad actions are permitted.
$env:CUMCP_MODE = "safe_local"
$env:CUMCP_ALLOWLIST = "notepad.exe"
.\.venv\Scripts\guarded-desktop-mcp.exe

# Operator-visible presentation without weakening any safety boundary.
$env:CUMCP_INTERACTION_SPEED = "normal"
$env:CUMCP_ACTION_FEEDBACK = "1"
$env:CUMCP_ALLOWLIST = "notepad.exe"
.\.venv\Scripts\guarded-desktop-mcp.exe

# Explicit local takeover. E-stop and audit remain enabled.
$env:CUMCP_MODE = "full_control_local"
$env:CUMCP_DANGEROUS_CONFIRM = "1"
.\.venv\Scripts\guarded-desktop-mcp.exe
~~~

For an Agent Host configuration, the optional rendered-browser route is user
owned and may point at any explicitly started local Chromium debugging port:

~~~toml
[mcp]
environment = { CUMCP_ALLOWLIST = "chrome.exe", CUMCP_BROWSER_OBSERVATION = "cdp", CUMCP_BROWSER_CDP_ENDPOINT = "http://127.0.0.1:9222" }
~~~

Install the `browser` extra (for example `.[agent-openai,browser]`) in that
environment. The model may choose `browser_snapshot`, UIA, document text, OCR,
or pixels per scene, but cannot change the endpoint, enable UIA actions, or add
authority: those remain trusted user configuration. Browser observation reads
the already rendered page, which addresses JavaScript pages whose raw HTTP
body is empty; it does not navigate or bypass login, CAPTCHA, anti-automation,
or other site challenges. Those conditions require cooperative user takeover
or a different authorized source.

## What the safeguards do not cover

- Dangerous-action confirmation currently applies to keyword-matched
  `click(ref=...)` targets. It does not classify coordinate clicks, text
  entry, key chords, or window activation as dangerous.
- Password values are omitted from UI snapshots, but the server does not
  perform general sensitive-data detection.
- Screenshot redaction blackens visible windows only when their titles match a
  configured substring. It does not inspect the pixels or redact every secret.
- Browser observation strips URL credentials/query/fragment but does not
  classify or redact rendered page text. Enable it only for a CDP session whose
  visible content may be sent to the configured provider.
- The safe-mode allowlist is a local guardrail, not an operating-system
  security boundary.
- A single desktop still has shared focus, pointer, keyboard, and screenshot
  resources.
- Input-tick attribution suppresses only known successful agent input; the
  platform's latest-input tick cannot prove the source of input interleaved
  during one successful native action.

The presentation profile is not a model/reasoning-speed control. Provider
latency depends on the selected provider/model and service; the profile only
makes already-authorized desktop actions easier for an operator to follow.

## Audit and recovery

Each action records its tool name, a bounded argument summary, decision, result,
and control mode in the JSONL audit file. For `type`, the audit record contains
only `text_present`, `text_length`, and `ref_supplied`; it never contains typed
text, a typed-text prefix, arbitrary type arguments, or a driver result message.
Inspect it with a text editor or a JSON-aware log viewer.

Hold the configured e-stop hotkey to abort future actions. The e-stop is
latched; restart the MCP server to clear it.

Experimental write-ahead continuation persistence is disabled by default. To
collect private crash boundaries, configure `[continuation] enabled = true` and
`ttl_seconds` between 60 and 86400. The resulting `continuation.json` can contain
the exact task, assistant text, UI results, and PNG screenshots. It is written
with user-only permissions, removed on normal terminal completion, excluded from
`agent trace` and `agent report`, and never authorizes automatic replay. An
operator may execute one strictly classified read-only continuation boundary by
default, or 1-4 with `--max-steps`, using
`agent recover ... --execute-read-only`. The command holds one run lock and fails
closed on task, policy, provider, registry, budget, digest, or sequence drift.
Strict v6 persistence rejects raw `type.text`, so an enabled continuation also
removes `type` from the live provider's final tool schemas and persisted
`advertised_tool_names`, even when the MCP reports its typed-text audit baseline.
With continuation disabled, the ordinary baseline, policy, approval, grounding,
and verification gates continue to govern `type`.
The bounded `agent ask` / `plan run` path also requires continuation persistence
before it makes its one Planner request, because every observation and final-response
dispatch must retain the existing crash boundary. It remains disabled when
`enabled = false`.

## Passive operator presence

The ordinary Agent `run` and `resume` paths, bounded observation-only
`ask` / `plan run`, explicit `recover --execute-read-only`, and the three fixed
MCP-backed campaign execution commands can show the selected-display
computer-use halo when enabled:

~~~toml
[operator]
presence_enabled = true
reduced_motion = true
high_contrast = true
locale = "auto"
theme = "auto"
~~~

The three enablement/accessibility values are strict booleans. `locale` accepts
only `"en-US"`, `"zh-CN"`, or `"auto"`; `theme` accepts only `"dark"`,
`"light"`, or `"auto"`. Newly generated installed product profiles write all
three booleans as `true` and select `auto` for locale and theme; legacy or
hand-written configuration that omits them retains disabled booleans, the
English locale, and the dark theme. When disabled, the CLI does not
construct the native Win32 surface. When enabled, the surface
receives only fixed phases after their run checkpoints are durably published.
It receives no task, target, model output, arguments, approval, or execution
capability. E-stop, detected human activity, terminal completion, and final
cleanup remove it and prevent later reopening. A presence failure is
fail-silent and cannot fail, approve, or advance the run. Bounded-plan phases
use the same durable Executor checkpoint observer and immediate E-stop/human-
yield teardown. Recovery starts only after its persisted checkpoint and private
continuation validate; later notifications follow the existing recovery CAS,
and `ABORTED`/`HUMAN_ACTIVE` close the halo before another bounded step. This
same immediate teardown applies to fixed campaign MCP calls. Campaign
prepare/start/resume control commands remain window-free. The Host selects the
foreground window's monitor, with Windows primary-monitor fallback when no
foreground HWND exists, and repositions only native operator presentation.
Desktop actions, screenshots, OCR, and region capture remain
primary-display-only. See
[Native operator multi-display composition](OPERATOR_MULTI_DISPLAY.md).

`high_contrast` and `reduced_motion` are force-on presentation preferences for
all three composed operator surfaces, not replacements for Windows settings.
The Host also reads system High Contrast, animation, and text-scale preferences;
either configured or system High Contrast/reduced motion wins. Text scale is
always system-owned and combines with display DPI through 400%, with container
growth through 200% followed by reflow. If those public Windows preference APIs
are unavailable or invalid, presentation falls back to the compatible 100%
defaults without affecting run authority. See
[Operator accessibility](OPERATOR_ACCESSIBILITY.md).

Theme is resolved before each native surface is constructed. Explicit dark or
light selects the fixed product palette; `auto` reads the Windows application
theme and fails silently to legacy dark. Configured or detected High Contrast
always overrides theme with Windows system colors. Generated profiles force
High Contrast on, so their `theme = "auto"` becomes visible only when the
operator explicitly disables that force-on flag and Windows High Contrast is
also off. Theme changes presentation only and cannot change surface enablement,
monitor selection, action/capture coordinates, approval, or dispatch. See
[Operator presentation personalization](OPERATOR_PERSONALIZATION.md).

## Passive progress lifecycle

The Agent `run`, `resume`, bounded observation-only `ask` / `plan run`, and explicit
`recover --execute-read-only` paths can also own the read-only progress window
for the duration of one CLI process:

~~~toml
[operator]
progress_enabled = true
locale = "auto"
theme = "auto"
~~~

`progress_enabled` is a strict boolean. Newly generated installed product
profiles write `true`; legacy or hand-written configuration that omits it
retains the parser default `false`. When enabled, a
dedicated background UI thread reads only validated local state and pumps the
native Win32 window; durable phase notifications wake that reader after each
checkpoint. The window receives no provider, MCP, desktop, approval, or replay
authority. Human activity and a focus-taking Decision Card do not close it,
because progress remains useful while the Agent has yielded. E-stop and final
run cleanup close it and join the UI thread. Construction, polling, rendering,
and native-window failures are fail-silent and cannot fail or advance the run.
Recovery notifications occur only after the existing checkpoint/continuation
CAS has completed and cannot authorize or replay work. This lifecycle currently
covers ordinary `run`/`resume`, `ask` / `plan run`, explicit read-only recovery, and
the fixed MCP-backed `run-claimed-synthetic`, `observe-boss-page`, and
`run-claimed-boss` campaign commands. Campaign progress is read from validated
campaign state by the existing poller; the zero-port prepare/start/resume
commands deliberately do not flash a window.

The approved-actions path can replace its one-action console prompt with the
focus-taking local Decision Card:

~~~toml
[operator]
decision_cards_enabled = true
approval_notifications_enabled = true
pause_shortcut = "ctrl+alt+p"
decision_timeout_seconds = 300
decision_card_corner = "bottom_right"
locale = "auto"
theme = "auto"
~~~

Newly generated installed product profiles write `decision_cards_enabled =
true` and `approval_notifications_enabled = true`; legacy or hand-written
configuration that omits either key retains the parser default `false`.
Notification enablement is a strict boolean. The timeout is a strict integer
from 5 to 3600 seconds.
The card defaults to the bottom-right work-area corner; the other
accepted positions are `top_left`, `top_right`, and `bottom_left`. It opens as
a normal movable, resizable, minimizable, non-topmost Windows window. Its
initial size stays compact, while the decision and digest-only evidence panes
scroll independently and expand with the window. Before the card opens, the ordinary Runner records
`WAITING_APPROVAL`, releases passive presence/Agent desktop authority, and makes
no desktop call while the card is open. The native adapter presents four fixed
choices around one effect: request approval for the exact effect, re-observe,
defer, or deny. Its expandable evidence section contains only fixed
classifications, unknown-fact enums, expiry, and SHA-256 digests. Re-observe
invalidates grounding and forces a fresh observation in the same run. Defer
persists `PAUSED`/`stopped`, closes desktop ownership, and requires inspection
plus a fresh run rather than resuming provider state. Deny, cancel, window close,
timeout, malformed choice, missing binding, expiry, native failure, and Host
digest drift all stop before side-effect dispatch. An
allow remains bound to the original
`ApprovalRequest` and continues through the existing grounding, budget, MCP,
audit, and post-action verification path. The adapter is Windows-only and does
not apply to read-only, planned, campaign, or recovery runtimes.

The native card starts keyboard focus on the unique `option_deny` choice,
displayed as `Stop task` in English and `停止任务` in Simplified Chinese; native
dialog traversal handles
`Tab`, `Shift+Tab`, arrows, `Space`, and bounded focused-control `Enter`, while
`Esc` denies. Its standard Text/Edit/Button UIA semantics, labelled details
pane, announcement milestones, High Contrast, reduced motion, and large-text
rules are owned by [Operator accessibility](OPERATOR_ACCESSIBILITY.md).

When Decision Cards are enabled, the Host also publishes one strict private,
expiring Approval Inbox record after card compilation. `approval inbox` reads
that record without claiming process liveness and cannot decide or dispatch
work. When notifications are enabled, Windows receives only fixed product
wording with no request identity, tool, target, task, model text, argument, or
digest. Native notification failure is fail-silent and cannot affect approval.
See the complete [Approval Inbox contract](APPROVAL_INBOX.md).
The bounded locale resolution, fallback, translated surfaces, and stable
machine-contract rules are owned by
[Operator localization](OPERATOR_LOCALIZATION.md).

## Agent text privacy

The Agent Host can pseudonymize reviewed text before provider dispatch:

~~~toml
[privacy]
enabled = true
detectors = ["email", "phone", "ipv4", "cn_id", "bank_card", "secret"]
terms = ["Project Phoenix", "Example Customer"]
image_redaction = true
~~~

The run-scoped plaintext mapping remains in Host memory. Non-secret tokens are
restored only for local final display or the local read-only `find.query` sink;
secret tokens are never restored into final text. When image redaction is
enabled, the privacy package's image-redaction path uses local Windows OCR to detect
sensitive text within a word or across up to eight adjacent words on the same
visual line, then replaces the corresponding pixels with solid,
coordinate-preserving token labels before the screenshot enters the ledger.
Missing or failed image redaction stops the screenshot; disabling it removes
`screenshot` and `capture_region` from the provider surface. A non-text
visual-detector extension port exists, but no face, QR, document, signature, or DeepSeek backend is
installed or enabled. Because this MVP does not persist the vault, privacy and
continuation cannot both be enabled. See
[Local text privacy](LOCAL_PRIVACY.md) for the exact boundary and limitations.

## VMware helper

`scripts/vmware_worker.py` is an **experimental host-side helper**. It can
check `vmrun.exe`, start an existing VMware Workstation VM, and optionally wait
for VMware Tools:

~~~powershell
$env:CUMCP_WORKER_VMX = "D:\VMs\cumcp-worker\cumcp-worker.vmx"
.\.venv\Scripts\python.exe scripts\vmware_worker.py doctor
.\.venv\Scripts\python.exe scripts\vmware_worker.py start --wait-tools
~~~

It does not create or license the guest OS, install this project in the guest,
start a guest MCP server, or connect the host agent to it. Those are future
orchestration concerns.
