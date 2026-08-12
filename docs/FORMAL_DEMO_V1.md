# Formal Demo v1

> **Status: the `GDA-DEMO-007A` internal offline contract slice is implemented;
> the Formal Demo product is not executable.** This document owns the selected
> Formal Demo v1 story and its staged delivery boundary. The implemented slice
> adds inert v1 data contracts and fail-closed compilation only. It does not
> add a Console, provider call, launcher, executable application adapter,
> durable run, Formal Demo evidence, or authority to activate later work.
> [Project status](../PROJECT_STATUS.md) remains the only operational tracker.

## Decision

The formal product demonstration will be visibly owned by Guarded Desktop
Agent, not by a Codex coding session. With Codex closed, the operator should be
able to launch an independent Windows Agent Console, enter a natural-language
goal, review a bounded Scope Sheet, explicitly start the task, observe progress
and attention states, and inspect verified outputs and a Completion Receipt.

The selected full story is role based:

~~~text
GitHub Issues fixture -> related PDF -> disposable Excel analysis
  -> disposable Word report -> test-account email draft (never send)
~~~

These products are selected semantic-role targets, not executable or verified
adapters. The earlier BOSS, Google Docs, and WeChat cases remain independent
[application coverage](APPLICATION_EVALUATION_MATRIX.md) and do not define
this Demo.

## Product boundary

The Agent Console is a Host-owned thin front door. It may collect input and
project reviewed state; it never receives desktop authority, API-key values, or
an alternate tool port.

~~~text
operator
  -> planned Agent Console
  -> local intent-disclosure review: provider/model, exact text to disclose,
     purpose, retention warning, and zero desktop/application startup
  -> explicit COMPILE acknowledgement
  -> tool-free provider call for an untrusted TaskIntent candidate
  -> Host validation against reviewed scenario and application-role profiles
  -> Host-compiled Scope Sheet and explicit START
  -> existing H-tree / campaign control
  -> existing Agent Runner
  -> sole stdio MCP server
  -> Windows Driver
~~~

The Console, intent compiler, scenario compiler, campaign, operator UI, and
future adapters cannot bypass the Runner. Policy, approval, grounding, budgets,
WAL, audit, mandatory post-action observation, recovery classification, and
unknown-outcome no-replay remain Host/Runner-owned.

## Implemented offline v1 contracts

`src/computer_use_agent/formal_demo_contract.py` implements the following four
stdlib-only frozen data structures. The module has no Provider, Runner, MCP,
Driver, filesystem, network, CLI, or application port. Its Python API is an
internal contract surface, not a user command or product launcher.

| Contract | Implemented offline responsibility | Explicit non-authority |
| --- | --- | --- |
| `TaskIntent v1` | Strict untrusted representation of the requested outcome, selected role candidates, constraints, and requested outputs | Cannot select tools, grant permission, add an application, widen risk, or start work |
| `DemoScenarioSpec v1` | Host-authored allowlist of roles, outcome classes, budgets, fixtures, risk ceiling, and forbidden effects | Contains no callable, executable, coordinates, transient refs, model prose, or click sequence |
| `ApplicationRoleProfile v1` | Reviewed mapping from one semantic role to one bounded adapter and test-data boundary | Registration is not application evidence and does not create action authority |
| `GenericScopeSheet v1` | Host-compiled review of goal, applications, reads, changes, outputs, budgets, approvals, stops, residue, and forbidden effects | Review and `START` approve no individual action and grant no retry or replay authority |
| Canonical scenario digest | Binds the reviewed intent envelope, profiles, constraints, and resume identity | A new prompt or changed profile cannot mutate an existing run |

The strict in-memory loaders use exact keys and independent version `1` for all
four structures. A `TaskIntent` candidate is capped at 16 KiB, the exact source
task at 8 KiB, and the other canonical artifacts at 64 KiB. Compact sorted
UTF-8 JSON and domain-separated SHA-256 digests bind the source-task digest,
validated intent, reviewed scenario, ordered profiles, effective constraints
and budgets, and resume identity. First compilation creates that binding;
every Scope artifact reload requires the previously retained binding digest,
so a changed intent/profile set cannot silently re-sign an existing run.
Unknown or duplicate keys, unsupported
versions, invalid numeric forms, oversized Unicode after canonicalization,
tamper, stale digest pins, duplicate roles, ambiguous outputs, unavailable
profiles, and scope or budget expansion fail with content-free deterministic
errors.

Structurally valid decoded scenario/profile data is not thereby reviewed. The
public product compiler accepts only exact built-in scenario and profile
`id`/version/digest pins. The internal structural compiler is exercised with
synthetic test-only records and marks the resulting Scope Sheet as not
registry-reviewed. Five target records exist: four contain selected inert
symbolic design bindings, while the email role remains explicitly
`UNSELECTED`. Compiling the complete built-in product scenario therefore stops
with `FORMAL_DEMO_PROFILE_UNAVAILABLE`. This is expected and does not establish
adapter availability or application evidence.

Provider output remains untrusted data. The future Host path must reject
refusal, truncation, malformed structure, unknown roles, unavailable profiles,
scope expansion, ambiguous outputs, and budget overflow before any downstream
provider, durable-workflow, MCP, desktop, or application startup. Free-form
task text never grants authority; typed Host-owned allowlists define the only
admissible outcome, roles, outputs, constraints, risk, and budgets. The generic
Scope Sheet says only that its compilation starts no external work and grants
no execution authority; it does not claim that a separately reviewed intent
provider call never occurred.

The intent call is itself external data disclosure, so it requires a separate
inert review before the call. That review is Host-fixed and local: it names the
provider/model, shows the exact natural-language text to be sent, explains the
TaskIntent-only purpose and provider-retention boundary, and states that no MCP,
desktop, application, durable workflow, or action authority will start. Exact
`COMPILE` acknowledgement permits only that one tool-free request; it grants no
Scope Sheet, task-start, action, retry, replay, or later provider authority. A
local-only intent compiler could replace this call, but it cannot be silently
selected as a provider fallback.

## Selected role profiles and boundaries

| Role | Formal Demo target | Required boundary before implementation can be accepted |
| --- | --- | --- |
| Source | Dedicated GitHub Issues fixture | Read-only stable issue identities, labels, bounded fields, and no write/comment/close authority |
| Evidence | Versioned non-sensitive PDF fixture | Document text first, bounded OCR fallback only when separately allowed, citation/location verification, and no arbitrary file access |
| Analysis | Disposable Excel workbook | Exact workbook/sheet/range identity, bounded values/formulas, save/reopen verification, and no unrelated workbook access |
| Report | Disposable Word document | Bounded generated content, exact output path, save/reopen/readback verification, and no overwrite |
| Handoff | Dedicated test-account email draft | Fixed test recipient boundary, subject/body/attachment verification, reopen and cleanup; `send`, `schedule`, `forward`, and external delivery are forbidden |

An exact email adapter—such as Outlook Desktop or Gmail Web—must be selected and
reviewed in its own slice. “Email draft” is a semantic role, not permission to
connect either product silently.

## Planned user journey

1. Launch Guarded Desktop Agent independently of Codex.
2. Enter a natural-language outcome in the Agent Console.
3. Display the selected provider/model and Formal Demo profile without exposing
   credential values.
4. Show the local, Host-fixed intent-disclosure review, including the exact task
   text and provider/data-use boundary, and require exact `COMPILE` acknowledgement.
5. Make one tool-free provider call for a `TaskIntent` candidate.
6. Validate and compile the candidate against Host-owned profiles.
7. Show the complete Scope Sheet before any further provider call, MCP startup,
   application startup, desktop observation, or durable workflow creation.
8. Require exact `START` acknowledgement to enter the reviewed run. Later
   actions still pass their ordinary policy/approval/grounding gates.
9. Project progress, attention, pause/takeover/resume, E-stop, recovery, and
   outcome state from the same durable run identity.
10. Save, reopen, and verify every output; verify the email remains a draft.
11. Emit a bounded Completion/Failure Receipt with cost, calls, retries,
    uncertain outcomes, cleanup, and retained evidence references.

## Planned product-state projection

The Console must project the existing durable run and control state; it must not
invent a second workflow state machine or become the source of truth. The
product vocabulary below is a UI projection contract, not a new execution
authority:

| Product state | Meaning | Permitted operator transition |
| --- | --- | --- |
| Draft | Natural-language input exists only in the Console | edit, discard, or open the local intent-disclosure review |
| Intent disclosure ready | The exact text, provider/model, purpose, and data-use warning are visible with zero external work | exact `COMPILE` acknowledgement or cancel |
| Review ready | A candidate intent passed Host validation and a bound Scope Sheet is visible | exact `START` acknowledgement or cancel |
| Running | The reviewed durable run owns foreground execution | observe, pause, E-stop, or answer a Decision Card |
| Attention | The run is blocked on approval, challenge, ambiguity, or human judgment | approve/deny only through the existing approval path, or take over |
| Paused / yielded | The Agent has reached a durable boundary and released desktop authority | inspect, take over, resume request, or stop |
| Resuming | The Host is discarding stale grounding and re-observing before dispatch | wait or stop; no action replay |
| Succeeded / failed / uncertain | The Host has reached a terminal classified outcome | inspect the Receipt and perform only separately reviewed cleanup |

Console close, process restart, or display failure cannot change the durable run
outcome. `UNCERTAIN` is visibly distinct from success and ordinary failure.

## Failure and control requirements

- Unsupported goals, roles, profiles, applications, outputs, or risk classes
  stop before startup.
- Human takeover releases desktop authority only at a durable safe boundary.
- Resume discards stale approval and grounding and requires a fresh observation.
- A forced process termination must resume from durable state without repeating
  completed or possibly completed side effects.
- `UNKNOWN_OUTCOME` remains terminal for automatic replay.
- Login, challenge, anti-automation, unexpected tenant, recipient drift, or
  fixture drift requires human handoff or fail-closed termination.
- Temporary refs never silently degrade to coordinates.
- Cleanup failure is reported, not hidden behind an otherwise successful task.

## Delivery sequence

Each item requires explicit activation in [Project status](../PROJECT_STATUS.md).
Writing this plan activates none of them.

1. **`GDA-DEMO-007A` — offline scenario contract, implemented:** four versioned
   inert structures, strict loading/compilation, deterministic digests, bounds,
   exact reviewed pins, and fail-closed tests. It adds no UI, provider request,
   MCP, desktop, application work, or live evidence.
2. **Intent disclosure and tool-free provider compilation:** first implement a
   local Host surface that shows the exact text, provider/model, purpose, and
   data-use warning and requires exact `COMPILE`. Only then may it make one
   tool-free provider call for an untrusted `TaskIntent` and validate it locally.
   The gate and call require deterministic fake/offline tests before a separately
   authorized live provider check; neither exposes tools or desktop authority.
3. **Review-only Agent Console:** project natural-language input, the required
   intent-disclosure gate, provider/model and profile display, validation errors,
   and Scope Sheet review in the independent Console. `Start` remains disabled
   until this surface is stable and accessible.
4. **First real vertical:** GitHub Issues fixture -> disposable Word -> dedicated
   email draft, with exact output verification and send permanently forbidden.
5. **Evidence and analysis expansion:** add the reviewed PDF and disposable Excel
   roles one at a time, each with its own evidence gate.
6. **Control and recovery composition:** add Pause/Takeover/Resume, one Decision
   Card, E-stop, forced restart, fresh-context resume, and exact cleanup.
7. **Formal evidence freeze:** retain fixtures, manifests, digests, recordings,
   sanitized traces, receipts, provider scope, cost, failures, and waivers.

## Presentation modes

These cuts belong to Formal Demo v1 and are independent of the future
[Universal GUI final showcase](UNIVERSAL_GUI_DEMO.md).

- **3-minute product cut:** natural-language input, review, bounded source
  result, verified Word output, verified unsent email draft, and final Receipt.
- **15-minute technical cut:** add PDF, Excel, one Decision Card, cooperative
  control, and one forced restart/fresh-context recovery.
- **Full technical run:** add exact provider comparison or documented waiver,
  fault injection, E-stop, trace/cost inspection, and complete cleanup evidence.

Editing may shorten presentation time but must not manufacture continuity or
hide skipped, failed, challenged, uncertain, or human-completed work.

## Acceptance and evidence

A formal claim requires retained evidence for the exact candidate and scope:

- Codex is closed and absent from the runtime path;
- the GDA Host, not the Console or model, owns provider calls and authority;
- two meaningfully different natural-language inputs yield separately validated
  intent envelopes and non-hard-coded content;
- unsupported or widened requests fail before startup;
- every application role passes its own save/reopen or state-verification gate;
- the email remains an unsent test-account draft and is cleaned up exactly;
- pause/resume and forced restart require fresh evidence and produce no repeated
  side effect;
- UI, CLI, durable state, Scope Sheet, and Receipt agree on run ID and digests;
- the complete repository gate and the named provider/desktop/application gates
  pass without inheriting evidence across models, adapters, or fixtures.

Offline tests, fake MCP runs, UI mockups, recordings, or a polished edit cannot
promote provider, desktop, application, E4, or release evidence.

## Relationship to other programs

| Program | Relationship |
| --- | --- |
| Fixed `public-web-word` workflow | Existing implemented vertical and reusable safety/verification reference; not the generic Formal Demo launcher |
| Retained `GDA-DEMO-003` | Historical bounded Chrome-to-Word HUD result; not this Demo |
| Retired `GDA-DEMO-006` | Recoverable archive only; never restore it as the candidate |
| Application Coverage Set A | BOSS, Google Docs, WeChat, and their legacy cross-app scenario remain separate representative application evidence |
| Universal GUI final showcase | Future integration/presentation gate across many independently verified mechanisms; its edited cuts do not replace this Demo |
| Continual learning L5 | Inactive and separately consented; not a prerequisite or hidden feature of Formal Demo v1 |
| Full Cycle Lane B | Separately deferred consent/security/privacy program; Formal Demo recordings or artifacts do not enter it automatically |

## Explicit non-goals

Formal Demo v1 does not introduce a second Runner, direct Driver access, an
arbitrary plugin/callable system, chat-channel gateway, scheduler/daemon,
Multi-Agent execution, background desktop control, automatic memory injection,
model training, L5, universal GUI coverage, E4 completion, or release approval.
“OpenClaw-like” may describe the desired clarity of the front-door experience;
it is not permission to import OpenClaw's architecture or any of those excluded
capabilities.
