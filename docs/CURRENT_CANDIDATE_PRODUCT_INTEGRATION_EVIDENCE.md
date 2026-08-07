# Current-candidate product integration evidence

> **Status: PASS for `GDA-PRODUCT-015`.** One clean installed wheel completed
> the bounded Notepad Desktop Ask and fixed public-web-to-disposable-Word
> product paths on the same Windows machine. This record retains only bounded
> hashes, counts, states, and correctness predicates. Raw observed content,
> model prose, typed text, screenshots, and credentials remain outside the
> repository.

## Acceptance boundary

- Runtime source candidate:
  `d254cd980836b2416ca3f0738eaa5b65ef315222`.
- Wheel: `guarded_desktop_agent-0.1.0-py3-none-any.whl`.
- Wheel SHA-256:
  `9589a611186fe1a0537c0c30a4ac2d17af9fd92f1fdfbd6fd6d5b48b55e1423a`.
- Platform: Windows 11, Python `3.13.7`, one supervised foreground desktop.
- Provider/model: OpenAI / `gpt-5.6-terra`.
- Installed contract: both fresh profiles returned `ready=true` and the exact
  thirteen-tool sibling-MCP contract before application startup.
- Applications: the reviewed synthetic Notepad fixture, one fresh-profile
  Chrome fixture on the fixed public Microsoft Support source, and disposable
  Microsoft Word edit/reopen fixtures only.
- Authority: Desktop Ask remained read-only. The Word workflow retained the
  Host-fixed Pre-run Review, ordinary Decision Card path, policy, grounding,
  mandatory post-action re-observation, budgets, sole Runner/MCP dispatch, and
  exact-process cleanup.

The clean wheel was built before either passing application run. The later
evidence-only documentation changes do not alter runtime or package inputs.

## Observed functional hardening

The first current-candidate diagnostics exposed two real fixed-workflow gaps.
They remain failure records and were not promoted as acceptance evidence.

1. A fast first `list_windows` could observe Chrome while its title was still
   the loading URL rather than the fixed reviewed source title. Exact-title
   matching correctly failed closed, but the bounded proposal feedback said
   only to replan. The Host now gives a content-free instruction to request a
   fresh `list_windows`; it does not accept the incomplete title, extend the
   correction bound, or dispatch the rejected proposal.
2. After a successful side effect, cooperative control correctly narrowed the
   Host-advertised tools to observations until fresh grounding. The OpenAI
   continuation adapter also correctly rejected changing its pinned request
   contract, so the two safety invariants could not compose. The fixed workflow
   wrapper now pins the initial reviewed inner-provider tool tuple while still
   enforcing the Runner's current observation-only subset before returning a
   call. An action proposed during re-observation is converted into a bounded
   `NOT_DISPATCHED` correction; an unknown or changed schema fails closed.

Targeted tests prove the inner provider sees one stable contract through
`full -> observation-only -> full`, an action cannot reach the Runner during
the observation-only phase, and scope drift is rejected. The combined public
workflow, core Runner, and OpenAI adapter regression set passed `81` tests.

The final repository closeout gate passed `2028 passed, 8 skipped`, Ruff,
mypy over 138 source files, documentation consistency with thirteen reviewed
tools, and `git diff --check`. These deterministic gates do not replace the
separate live application evidence below.

Two environmental diagnostics were kept separate from code defects. An
external Computer Use activation helper returned `node_repl exec context not
found`, so the operator manually foregrounded only the reviewed Notepad
fixture. One overly long ignored evidence path caused a Chrome private-profile
startup error; the retained candidate used a short user-local state root.
Neither condition changed product code or widened application authority.

## Desktop Ask result

| Field | Observed |
| --- | --- |
| Fixture | `docs/fixtures/desktop_ask_product003.txt`; Windows checkout SHA-256 `a075bd69ec3fe5f7f3d5a9b17fbafd0042eca66652084d3cf3ac94ea2af344b6` |
| Run / plan | `8e87cfe9c16343319ae890d9756018f0` / `plan_7991750a9cc749f6898aa65b0333cfb4` |
| Plan | One completed `document_text({"scope":"foreground"})`, then one completed `final_response` |
| Usage | 1 Planner call; 1 final model turn; 1 tool call; 1,086 final-input tokens |
| Answer projection | 110 characters; SHA-256 `860e601b9c093825b53e51bd154a59ea5e90cb4bd829b74e940c9e27ab1f846a`; codename, `37 + 58 = 95`, and `GO` predicates all `true` |
| Trace/state | `SUCCESS`; `user_task -> tool_call -> tool_result -> observation -> model_turn`; 0 retries; 0 tool failures |
| Authority | 0 side effects |
| Redacted export | SHA-256 `3b9ad42aea026fb7cad02b46c3db83818feda9ad9931e103d5699254a4887b2f` |
| Cleanup | The one exact Notepad fixture window and owning process were closed; no Notepad window remained |

## Public Web to Word result

| Field | Observed |
| --- | --- |
| Pre-run Review | Version `1`; output absent; zero workflow-state files; maximum approvals `7`; `grants_action_approval=false` |
| Source | Fixed Microsoft Support page, `Collaborate on Word documents with real-time co-authoring` |
| Run | `public-web-word-a1b3f312904128839b246b93f888b811` |
| Main Runner | `SUCCESS`; 16 model turns; 15 tool calls; 5 side effects; 0 retries; 0 tool failures; 0 proposal corrections |
| Authored brief projection | 498 characters; 3 bullets; SHA-256 `7bffb263164aeabfaca857fcb460a1e82ea3115524d5e2ecb7016b6c1dbee6b4` |
| Template | SHA-256 `3311022016ab64287b169e44cb072b0f5e11612fa821b8dc6e754d3cdd973a63` |
| Artifact | New disposable DOCX; SHA-256 `b1ef021559d5a51c1415b8766878de9688df1901cb7a0b3d77a9a5876f71e6fc` |
| Verification | Pre-save semantic check, save, post-save semantic check, OOXML/digest verification, and independent reopen/readback all passed |
| Total result | 17 tool calls including the bounded reopen verifier; `reopen_verified=true` |
| Cleanup | Original Chrome and Word fixture windows plus the independent verifier window all reported `window_cleanup_verified=true`; a fresh Computer Use listing found zero fixture or Decision Card windows |
| Receipt | Version `1`, `COMPLETED`; receipt SHA-256 `271f386dd16d55bc44be56b6adc424662099eb9bb92e4e3affffe88d7e997a94` |
| Task Center | Read-only completion: `Document saved and verified`; artifact `VERIFIED_AT_COMPLETION`; cleanup `VERIFIED`; `needs_attention=false` |

The operator's pre-existing Chrome window was never selected or closed. The
workflow used its own fresh profile and exact launched-process identities.
Word can retain a shared background process after an exact fixture window is
closed; acceptance therefore binds the owned window cleanup record rather than
terminating an unrelated Office process.

The successful workflow also confirmed one product UX limitation: the current
`approved_actions` policy requests one exact human approval for every side
effect, so all five effects interrupted the operator even though they remained
inside the fixed disposable workflow. No implemented risk tier currently
distinguishes a bounded reversible effect from a high-risk effect. This run
keeps those approvals as valid historical authority evidence; it does not
promote per-effect prompting as the intended final UX or silently replace it
with automatic approval.

## Explicitly open gates

| Gate | State | Reason |
| --- | --- | --- |
| Human Narrator/NVDA/JAWS acceptance | `NOT RUN` | automated UIA evidence does not substitute assistive-technology use |
| Human 200%/400% text and visual review | `NOT RUN` | automated geometry/reflow remains separate from human usability |
| Physical two-monitor acceptance | `BLOCKED BY AVAILABLE HARDWARE` | the machine exposes one monitor |
| Native cooperative takeover timing | `NOT RUN` | offline control tests do not establish the live operator timing result |
| Host-owned risk-tier approval policy | `NOT IMPLEMENTED` | the current policy still prompts for every side effect; low-risk bypass must be a fixed Host decision, never model self-approval |
| E4 four-cell matrix | `NOT RUN` | explicitly deferred; no waiver is requested or implied |
| Tag, release artifact, and release decision | `NOT RUN` | this is product integration evidence, not release approval |

## Supported claim

This record supports one exact-candidate, model-scoped, provider-scoped
installed Desktop Ask result and one fixed Chrome-to-disposable-Word workflow
result from the same wheel, including ordinary review/approval boundaries,
durable verification, a completion receipt, and exact fixture-window cleanup.
It does not establish arbitrary webpages, broad Notepad support, other
applications/providers/models, unattended operation, universal GUI coverage,
human accessibility acceptance, physical multi-monitor usability, E4, or
release readiness.
