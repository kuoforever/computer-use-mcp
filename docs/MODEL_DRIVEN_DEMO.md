# Model-driven bounded Chrome-to-Word Demo

> **Status: implemented and offline verified; no retained live-provider or
> application evidence yet.** `GDA-DEMO-006` changes the live presentation path
> without promoting a universal desktop-agent claim.

## Purpose

The original `CrossAppDemoProvider` is a deterministic result-driven state
machine. It is useful E1 regression evidence, but it does not demonstrate a
model observing a changing desktop and deciding what to do next.

The live Demo now defaults to a real OpenAI or Claude provider. The model chooses
zero or one next tool call from fresh results on every turn. The deterministic
provider remains available as `--mode controlled` for repeatable offline and
fixture validation.

The presentation scenario is a real bounded knowledge-work task, not a fake
website or a prewritten model answer. Chrome opens the current public Microsoft
Support article about Word co-authoring. The model reads that page, writes its
own two-to-four-bullet source brief into a disposable copy of a Word research
document, saves it, and verifies the saved content. The Host fixes the source,
destination, layout, length, and safety envelope; it does not replace the
model's brief with scripted prose. The disposable copy prevents the Demo from
editing an operator document.

~~~powershell
# Model-driven presentation. The selected provider SDK and credential must be
# available in the Host environment; credentials are never passed to MCP.
.\.venv\Scripts\python.exe .\scripts\demo_cross_app.py `
  --mode model --provider openai --model <explicit-model-id>

# Deterministic regression baseline; no provider credential is required.
.\.venv\Scripts\python.exe .\scripts\demo_cross_app.py --mode controlled
~~~

`--interaction-speed fast|normal|deliberate` and `--no-action-feedback` apply to
both modes. Model selection does not change the Host-owned desktop presentation
speed.

The Demo defaults to project-wide `--permission-mode agentic_actions`: reviewed,
grounded, in-budget actions do not open one Decision Card per step. Use
`--permission-mode approved_actions` only when a presentation specifically
needs exact-effect approval cards. Both keep the MCP child in `safe_local`, so
foreground allowlisting, local-input yielding, E-stop, audit, and confirmation
remain enforced.

The capture-excluded Presence Halo enters its fixed planning presentation before
Chrome or Word starts, so the operator sees that Demo preparation has begun.
This early visual projection grants no dispatch authority and is explicitly
closed if fixture or provider setup fails before Runner starts.

## Authority boundary

The model-driven path adds no desktop dispatch route. Every accepted request
still passes through the existing `AgentRunner`, project permission policy,
grounding, budget, audit, mandatory re-observation, MCP guard, and validated
result boundary. `approved_actions` adds exact local approval; the default
`agentic_actions` mode removes only that per-action prompt.

Before Runner sees a model turn, `ModelDrivenCrossAppDemoProvider` applies a
second Demo-specific fail-closed envelope:

- exactly zero or one tool call per provider turn;
- only the exact launched Chrome and Word fixture windows;
- explicit observed window IDs for UIA/document reads; ambient `foreground`
  and `all` scopes are forbidden;
- bounded `document_text` may read either exact disposable fixture, while
  completion accepts the required marker only from the exact Word fixture;
- only semantic-ref clicks, never coordinate clicks;
- only `PageDown`, `Ctrl+End`, and `Ctrl+S` in their grounded application phase;
- generated typed text must use the fixed source title and URL, contain the
  fixed verification marker, stay within 220-900 characters and two-to-four
  bullets, and retain lexical support from the freshly observed public source;
- source UIA plus either exact semantic document text or valid OCR evidence
  must exist before entering the Word phase;
- the note must be observed before save;
- a post-save `document_text` result containing the fixed marker is required
  before a no-call provider turn can become Demo success.

Provider prose is discarded for intermediate turns and cannot become the
trusted completion marker. Unknown or possibly dispatched outcomes retain the
ordinary Runtime rule: never replay automatically.

A model proposal rejected by this Demo envelope is known not to have reached
desktop dispatch. The Host may return that fixed rejection to the same provider
continuation for at most two correction attempts. The HUD temporarily shows the
replanning state, the provider token usage is accumulated, and the rejection
code/tool names are retained without model prose or typed content. Exhaustion,
premature tool-free completion, or any unknown outcome still stops the run.

The Demo provider profile can advertise tools with required safety baselines
only because Runner first removes every tool whose baseline the discovered MCP
server did not report. This is a closed Host profile, not a user-supplied system
prompt and not a general approved-action expansion.

## Evidence boundary

Offline tests cover provider prompt compilation, a complete shorter
model-selected fake-provider path through the real Runner boundary, multiple
different grounded source briefs, bounded correction after a known
not-dispatched rejection, and adversarial turns including another window,
coordinate click, changed source, ungrounded text, unreviewed key, unreviewed
tool, multiple calls, and premature success.

Owned application dialogs remain operator decisions. The Demo waits only for
the exact handed-off fixture windows to become stably absent, then classifies
the disposable document as `saved` or `discarded` from its marker. Cancel or
timeout stays `unresolved`. `final-state.json` schema v3 records both proposal
rejections and this post-handoff resolution; the Demo never clicks the dialog.

These tests prove contract behavior only. Provider, desktop, and application
evidence remain unchanged until one explicit opt-in run with a reviewed model
is retained and documented.

## 2026-08-03 live diagnostic attempts

These are failed engineering diagnostics, not promoted Demo evidence:

- `cross-app-demo-20260803-053832-777053` stopped on an operator `Defer` and
  cleaned both exact fixture windows.
- `cross-app-demo-20260803-070335-529976` showed that the model correctly
  activated the exact Demo Chrome but then selected ambient `foreground` scope;
  the pre-Runner guard rejected it and the prompt now requires exact IDs.
- `cross-app-demo-20260803-070730-385414` and
  `cross-app-demo-20260803-071109-571128` exposed two deterministic-script
  assumptions: exact Chrome `document_text` is a safe semantic observation, and
  semantic text should precede OCR when available. The Host contract now allows
  exact Chrome semantic text and accepts UIA plus semantic text or valid OCR as
  source evidence.
- `cross-app-demo-20260803-071544-014435` followed the revised model-driven
  path through exact Chrome UIA and semantic document text, then requested the
  exact disposable Word window. The local card denied that activation after its
  timeout; audit records `not_dispatched`, exact cleanup completed, and no action
  was replayed. The startup Halo began before application launch: its first
  retained projection was `PLANNING/HELD`, with 38 painted samples and zero
  unpainted or window-absent samples.
- Nine later engineering attempts exposed prompt/guard drift, invalid key and
  typed-payload proposals, time-based fixture readiness, a missing provider
  timeout, and finally a premature save request after successful Chrome reading
  and Word typing. Those runs are not acceptance evidence. They motivated the
  bounded correction loop, state-based fixture readiness, provider timeout,
  generated-brief contract, and post-handoff resolution implemented offline.

After the complete offline gate passes, the exact next gate is one fresh real
Microsoft Support-to-disposable-Word run in default `agentic_actions` mode with
the operator available only as fallback. Acceptance requires a model-authored
brief, zero out-of-scope dispatch, durable save verification, and resolved exact
fixture cleanup. None of the failed runs may supply reusable approval,
observation, or generated brief state.
