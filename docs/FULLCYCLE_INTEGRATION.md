# Full Cycle integration contract

> **Status: Lane A manifest/export v1 is implemented and offline verified, and
> the Full Cycle consumer is complete. Freeze validation is next. Rich
> multimodal capture is not implemented.**

## Purpose

`guarded-desktop-agent` supplies a reliable, safety-governed Windows execution
environment to the external Multimodal LLM Full Cycle project. It does not own
model training, post-training, serving, dataset registries, Agentic RL, or
Multi-Agent coordination.

The bridge has two deliberately separate data lanes.

## Lane A: automatic safe runtime evidence

Lane A exports only facts already present in the redacted trace, checkpoint,
reviewed tool registry, and public contract versions.

Intended uses:

- reliability and safety evaluation;
- failure classification;
- tool-sequence and budget analysis;
- Verifier negatives such as denial, timeout, unknown outcome, or duplicate
  dispatch protection;
- runtime-version and policy compatibility gates.

Lane A is not sufficient for:

- instruction following;
- GUI grounding;
- multimodal SFT;
- action imitation from screenshots;
- final-answer quality;
- semantic tool-result learning.

The current trace intentionally stores lengths, reviewed safe argument
summaries, status, dispatch certainty, image count, observation epoch, policy
decision, and recovery state. It does not persist raw task text, model prose,
tool-result text, or image bytes.

### Runtime manifest v1

Implemented canonical top-level fields:

```json
{
  "fullcycle_manifest_version": 1,
  "agent_contract_version": "0.1.0",
  "driver_contract_version": "1.0.0",
  "trace_version": 1,
  "checkpoint_version": 1,
  "plan_contract_version": 1,
  "tools": [],
  "automatic_export": {
    "contains_raw_task": false,
    "contains_model_text": false,
    "contains_tool_result_text": false,
    "contains_images": false,
    "contains_memory": false,
    "contains_continuation": false
  }
}
```

Each tool entry is derived from `REVIEWED_TOOLS`, not copied into a second
hand-maintained registry. It includes the reviewed name, description, host
input schema, effect, result-content/sensitivity policy, grounding rule,
approval/observation behavior, sensitive argument names, and required safety
baselines.

### Redacted run bundle v1

Implemented canonical fields:

```json
{
  "fullcycle_run_export_version": 1,
  "manifest_digest": "sha256:...",
  "run_id": "...",
  "checkpoint": {},
  "events": [],
  "data_class": "redacted_runtime_evidence",
  "training_use": "reliability_and_verifier_only"
}
```

The exporter validates the existing run record with the same fail-closed reader
used by the trace inspection command. The reader rejects malformed, incomplete,
mismatched, redirected, or over-16-MiB trace input. It retains the existing
1-MiB per-event and 64-KiB checkpoint bounds.

## Lane B: explicit-consent rich training episodes

Lane B belongs to the external Full Cycle project and requires a separate
review before implementation.

Potential episode content:

- sanitized instruction;
- UIA/document/OCR observation;
- explicit screenshot or crop references;
- model candidate action;
- Runtime policy/approval decision;
- tool result and post-action observation;
- state-based success/failure label;
- environment, model, policy, and schema versions.

Requirements:

- disabled by default;
- explicit run-scoped operator consent;
- visible capture indicator;
- separate output directory and retention policy;
- local sanitization and image redaction before write;
- no secrets, assigned-secret plaintext, memory database, or continuation data;
- no cooperative control record, request, authority handoff, or resume state;
- content-addressed artifacts with deletion support;
- train/validation/test split and licensing decisions owned by Full Cycle;
- a state-based verifier, not model self-report, supplies outcome labels.

Lane B must not modify the existing safe trace into a secret rich log. It is a
separate adapter with separate consent, schema, storage, and tests.

## Authority boundary

```text
Full Cycle model / trainer / evaluator
  -> candidate plan or action
  -> guarded-desktop-agent Runner
  -> grounding / policy / budget / approval / WAL
  -> sole MCP desktop boundary
  -> mandatory post-action observation
  -> state-based evidence
```

The external project may replace or route models. It may not replace the
Runtime's execution authority or infer permission from a model score.

## Implemented command surface

```powershell
guarded-desktop-agent fullcycle manifest `
  --output C:\absolute\path\runtime-manifest.json

guarded-desktop-agent fullcycle export-run `
  --config C:\absolute\path\agent.toml `
  --run-id <run-id> `
  --output C:\absolute\path\run-export.json
```

Both commands are offline and read-only. They open no provider, MCP, desktop,
network, approval, memory, or continuation port. Output paths must be absolute,
their parent directories must already exist and not be symbolic links, and an
existing output is never overwritten. Output is canonical compact JSON and is
bounded to 24 MiB.

## Ownership

| Concern | Owner |
| --- | --- |
| Desktop tool contract and execution safety | `guarded-desktop-agent` |
| Redacted run/checkpoint validation | `guarded-desktop-agent` |
| Lane A manifest and export schema | This document |
| Rich episode consent and capture | Full Cycle project, separate review |
| Dataset processing and versioning | Full Cycle project |
| Training, post-training, Serving, Agentic RL | Full Cycle project |
| Cross-project compatibility fixture | Full Cycle project |

## Closure gates

1. ~~Implement and test the Lane A manifest/export commands.~~ Complete.
2. ~~Add an offline consumer fixture in the Full Cycle project.~~ Complete as
   `FC-BRIDGE-001` in `reliable-agent-model-lifecycle`.
3. ~~Pin the Runtime and export schema versions in the consumer project.~~
   Complete: producer commit `8ace897`, consumer schema `1.0.0`, and every
   contract version are pinned in `fixtures/bridge_v1/fixture-metadata.json`.
4. ~~Decide whether Lane B is accepted or deferred.~~ Deferred to the Full
   Cycle project's separate `FC-BRIDGE-003` consent, security, and privacy
   review; it remains disabled by default.
5. ~~Rerun release preflight from a clean, branch-reachable candidate and
   record that exact commit in both repositories.~~ Complete locally at
   `324ff2fb5911e332ddb5c5f90eb41296e8faf7a9`; the consumer records the same
   freeze SHA in `baseline/runtime-freeze-v1.json` while preserving the
   immutable `8ace897` fixture provenance.
6. ~~Run the complete repository validation gate and update
   `PROJECT_STATUS.md`.~~ Complete on 2026-08-02. This closes the offline
   Runtime handoff only; it does not promote provider, desktop, application,
   or release evidence.
