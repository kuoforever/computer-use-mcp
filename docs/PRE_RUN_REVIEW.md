# Pre-run Review Scope Sheet

> **Status: implemented for the fixed `public-web-word` product workflow and
> offline verified.** This is a CLI-first Host-compiled review, not a general
> model-plan viewer, native window, approval, or workflow designer. Live
> provider, desktop, application, and release evidence remain separate gates.

## Product purpose

Before the installed side-effect workflow opens a provider connection, MCP
child, Chrome, Word, or a disposable fixture, the operator can answer:

1. What fixed outcome will this workflow attempt?
2. Which applications will it open?
3. What will it read and modify?
4. Where will the output be written?
5. Which actions can proceed under fixed Host policy, and which require exact
   approval?
6. Which conditions stop it?
7. What partial local state might remain after failure or uncertainty?

Preview the Scope Sheet with zero external work:

~~~powershell
guarded-desktop-agent review public-web-word `
  --config C:\absolute\path\public-web-word.toml `
  --output C:\absolute\path\collaboration-brief.docx
~~~

Add `--json` to receive the same `pre_run_review_version=2` projection. The
review command validates the product profile and output preconditions, but it
does not create workflow state, start an application, discover an executable,
read the source page, contact a provider, start MCP, or approve an action.

## Default start interaction

The ordinary command displays the same human Scope Sheet on stderr and waits
for the exact, case-sensitive token `START`:

~~~powershell
guarded-desktop-agent workflow public-web-word `
  --config C:\absolute\path\public-web-word.toml `
  --output C:\absolute\path\collaboration-brief.docx
~~~

EOF, interruption, or any other text cancels before startup and returns a
non-zero status. An intentional non-interactive caller must use the explicit
`--acknowledge-scope` flag. The sheet is still displayed, and the flag does not
approve any later desktop action.

## Host-fixed source

~~~text
reviewed product profile + exact resolved local paths
  -> fixed public-web-word contract validation
  -> Host-compiled Scope Sheet
      -> review-only text or versioned JSON       # zero external work
      -> exact START / --acknowledge-scope        # start gate only
          -> ordinary workflow
              -> policy + grounding + one-effect approval + Runner/MCP
~~~

The objective, application roles, data-use statements, authorization policy,
stop conditions, residue warning, and acknowledgement consequences are fixed
Host strings. They are not copied from provider output or a model-authored
plan. The only local values inserted are the configured state directory,
resolved output path, and any executable override paths explicitly supplied by
the caller.

The compiler and workflow share one fixed product-profile validator. On the
start path, the exact in-memory `AgentConfig` and resolved request used for the
review are passed into the ordinary workflow; the CLI does not reload config
after acknowledgement. Output exclusivity and every normal runtime gate are
still checked when execution begins, so acknowledgement cannot turn a stale or
conflicting output path into authority.

## Version 2 facts

The Scope Sheet reports:

- fixed goal: read the reviewed public Microsoft Support source, author a
  two-to-four-bullet brief, create one DOCX, then reopen and verify it;
- applications: Google Chrome with a fresh private profile and Microsoft Word
  for edit/save/reopen/read-back;
- reads: the fixed public page, packaged disposable template, and newly written
  output during verification;
- changes: one exclusive new DOCX, bounded private workflow/profile state, and
  the exact disposable fixture lifecycle;
- output policy: `CREATE_NEW_ONLY_NEVER_OVERWRITE`;
- maximum side effects: seven;
- authorization: exact fixed-workflow low-risk actions proceed under
  `host_risk_tier_v1` without an action prompt; high-risk actions require one
  exact approval, with a maximum of zero expected in this reviewed workflow;
  ambiguous, invalid, or out-of-scope actions are denied;
- fixed stop families: precondition, operator decision, desktop authority,
  resource bounds, verification, and unknown outcome;
- possible residue: a partial DOCX, private workflow/profile files, or fixture
  processes when cleanup cannot be proved.

`UNKNOWN_OUTCOME` explicitly says to stop and not retry automatically. The
JSON acknowledgement object fixes `grants_action_approval=false` and
`grants_retry_or_replay=false`.

## Trust and privacy boundary

The Scope Sheet has no provider, MCP, desktop, approval, execution,
persistence, notification, campaign, or Full Cycle export port. It contains no
raw user task, observed UI content, model prose, tool result, screenshot, typed
text, credential, approval payload, continuation, or memory.

The explicit local paths are shown only to the local operator who requested the
review. They are not added to automatic Full Cycle Lane A. Starting grants only
permission to enter the existing workflow; each side effect must still pass
current Host risk policy, grounding, live authority, budget, and authorization
checks. A high-risk effect cannot inherit authority from the start gate.

## Limits and verification

Version 2 covers only `public-web-word`, the repository's installed fixed
side-effect product path. It does not add Pre-run Review to read-only `ask`,
arbitrary `run`, campaigns, recovery, or future workflows. It does not estimate
duration, predict the model's chosen observations, resolve installed
applications during review, or pin an executable binary hash.

Offline tests cover complete fixed fields, human/JSON parity, contract drift,
existing/missing output preconditions, explicit executable paths, exact start
confirmation, EOF/cancel zero-execution behavior, one config load, bound
config/request handoff, and the non-interactive acknowledgement flag. These
tests do not establish a native UI, provider behavior, real desktop behavior,
application acceptance, E4, or a release artifact.
