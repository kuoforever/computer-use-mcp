# Project status

> **Mode: closure and Full Cycle integration.**
> Updated: 2026-07-28.
> This file is the single operational entry point for the next coding session.
> It does not replace capability evidence in `docs/CAPABILITY_STATUS.md`.

## Objective

Freeze `guarded-desktop-agent` as the reliable Windows execution environment
for the Multimodal LLM Full Cycle project. Finish only the smallest stable
integration surface needed for:

1. runtime capability discovery;
2. safe reliability/evaluation data export;
3. an external, explicitly consented rich-training capture adapter; and
4. a reproducible frozen baseline.

The model factory, multimodal dataset pipeline, post-training, serving,
Agentic RL, and Multi-Agent work live outside this repository.

## Current baseline

| Fact | Current state |
| --- | --- |
| Product | Experimental Windows-only foreground desktop MCP runtime and Agent Host |
| Public tools | 13 reviewed tools |
| Driver contract | `1.0.0` |
| Agent contract | `0.1.0` |
| Trace/checkpoint | Redacted `trace_version=1`, `checkpoint_version=1` |
| Providers | OpenAI and Claude bounded paths |
| Safety | Sole Runner/MCP dispatch, grounding, policy, approval, budgets, audit, mandatory re-observation |
| Recovery | Conservative recovery; uncertain side effects are never replayed |
| Offline baseline | `1428 passed, 8 skipped` on 2026-07-28 after `GDA-FC-001` |
| Worktree at start | Clean |
| Branch at start | `docs/hierarchical-task-and-behavior-trees` |

The test count is a dated working snapshot, not a permanent capability claim.
Run the current suite before relying on it.

## Scope freeze

Until the Full Cycle bridge is closed, do not implement:

- hierarchical task or behavior-tree runtime support;
- more BOSS/application automation;
- universal GUI showcase work;
- additional desktop tools or platform drivers;
- Multi-Agent coordination;
- automatic continual learning;
- richer operator UI;
- broad refactors unrelated to the bridge.

Existing planned documents remain valid design records, but they are not active
delivery work.

## Closure backlog

| ID | Status | Deliverable | Completion evidence |
| --- | --- | --- | --- |
| `GDA-FC-000` | Complete | Closure scope, integration contract, project status, Codex/Claude entrypoints | This documentation change |
| `GDA-FC-001` | Complete | Safe Full Cycle manifest and redacted run-export CLI | Exact schema/version tests, CLI tests, fail-closed record/output tests |
| `GDA-FC-002` | Next | Consumer fixture in `LLM-FullCycle-Learning` | Export bundle parsed and validated without desktop/provider access |
| `GDA-FC-003` | Pending review | Explicit-consent rich episode capture contract owned by Full Cycle | Separate security/privacy review; disabled by default |
| `GDA-FC-004` | Complete locally | Freeze validation and handoff | Clean release preflight passed for producer candidate `45bee82`; PR CI validates the final documentation commit |

Only one item may be `Next` or `In progress`.

## Exact next task: GDA-FC-002

Work in `C:\Users\Alienware\Desktop\LLM-FullCycle-Learning`, not in this
repository's Runtime:

1. Add an offline consumer for manifest v1 and redacted run-export v1.
2. Validate exact supported versions, the manifest digest, data class, training
   use, and every `automatic_export` false claim.
3. Reject unknown versions, digest mismatch, malformed JSON, unexpected rich
   content, and oversized inputs.
4. Add one fixture generated from the current canonical producer without
   provider, MCP, desktop, network, approval, memory, or continuation access.
5. Pin Runtime package/commit and schema versions in the consumer project.
6. Do not add rich multimodal capture under this item.

After the consumer passes, return here only for `GDA-FC-004`: commit the
reviewed bridge, rerun release preflight from a clean candidate, record the
exact commit, and freeze Runtime feature work.

## Definition of closed

This repository is considered closed for the Full Cycle handoff when:

- `GDA-FC-001` and `GDA-FC-002` are complete;
- the rich-capture boundary is either accepted with a separate reviewed design
  or explicitly deferred;
- the complete offline validation gate passes;
- the root README, documentation index, this file, and `HANDOFF.md` agree;
- no planned feature is described as implemented;
- the Full Cycle repository records the pinned runtime version and consumer
  contract;
- a fresh Codex or Claude Code session can complete the next task using only
  repository files.

## Session protocol

At the beginning of every session:

1. Read `AGENTS.md` or `CLAUDE.md`.
2. Read this file.
3. Read only the owner documents linked by the active task.
4. Run `git status --short --branch`.
5. Confirm the active backlog item and avoid unrelated work.

At the end of every session:

1. Run the task's validation commands.
2. Update exactly one backlog row and the `Exact next task` section.
3. Record new durable implementation facts in `HANDOFF.md` only when needed.
4. Do not promote capability evidence without the required retained run.
5. Leave a concise list of modified files, tests, limitations, and next task.

## Validation gate

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check src tests scripts
.\.venv\Scripts\python.exe -m mypy
.\.venv\Scripts\python.exe scripts\check_docs_consistency.py
git diff --check
```

On-device smoke scripts are not part of the routine closure gate and must not
be run on an active or sensitive desktop without an explicit evidence plan.

## Decisions

| Date | Decision |
| --- | --- |
| 2026-07-28 | The Runtime is a Full Cycle dependency, not the model-training repository. |
| 2026-07-28 | Existing redacted traces may feed reliability/evaluation work but are insufficient for multimodal model training. |
| 2026-07-28 | Rich episodes require an explicit-consent external capture adapter and a separate privacy/security review. |
| 2026-07-28 | New product features are frozen until the bridge and baseline handoff close. |
| 2026-07-28 | Lane A manifest/export v1 is implemented; the next code task is the external offline consumer, not more Runtime capability. |
| 2026-07-28 | Clean release preflight passed for producer candidate `45bee82`; Runtime remains feature-frozen while the external consumer is completed. |
