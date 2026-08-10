# Teaching-oriented collaboration

> **Status: current mandatory collaboration contract.** Shared protocol: `1`.
> Guarded Desktop Agent profile revision: `2`.
> [AGENTS.md](../../../AGENTS.md) owns the requirement to follow it.

Project delivery and guided learning happen in the same bounded task. Prefer
clear Chinese explanations while retaining exact English terms, identifiers,
commands, metrics, and file names needed for industry communication and
reproduction.

The shared v1 core remains simple: explain consequential work before, during,
and after it. This repository profile makes the trigger, step size, outcome,
evidence threshold, and stop rules explicit without changing the shared
protocol version.

## When this activates

A step is non-trivial when it does at least one of the following:

- changes a contract, state transition, authority boundary, persisted schema,
  public behavior, or evidence claim;
- requires a design choice or rejects a plausible alternative;
- runs a validation whose result could promote, falsify, or block a claim;
- writes external state, opens a provider/desktop/application surface, or
  publishes Git/GitHub state;
- diagnoses a failure whose attribution changes the next action; or
- creates durable resume/interview material.

Do not narrate every `rg`, formatting operation, repeated edit, or polling
refresh. The teaching unit is one hypothesis, bounded change, or evidence gate,
not one shell command.

## Authority and storage

| Information | Owner |
| --- | --- |
| Active task, safe resume point, exact next action | [Project status](../../../PROJECT_STATUS.md) |
| Capability/evidence level | [Capability dashboard](../../CAPABILITY_STATUS.md) |
| Runtime/Full Cycle data and authority boundary | [Full Cycle contract](../../FULLCYCLE_INTEGRATION.md) |
| Step-by-step explanation | Conversation |
| Durable job-application candidates | [Resume evidence](../resume/) after the promotion gate |

Teaching pages are not a learning log. Do not copy conversations into the
repository or create a second tracker. Only reusable rules and durable,
evidence-backed career items belong here.

## Modules

| Module | Purpose |
| --- | --- |
| [Step protocol](STEP_PROTOCOL.md) | Granularity, before/during/after fields, outcome taxonomy, and compact templates |
| [Evidence discipline](EVIDENCE_DISCIPLINE.md) | Evidence levels, valid negatives vs invalid attempts, and resume-promotion threshold |
| [Interview translation](INTERVIEW_TRANSLATION.md) | Ownership-safe STAR translation, short/long answers, and deep-dive preparation |

## Repository stop conditions

Stop instead of converting teaching value into authority when any of these is
true:

- the required account, credential, device, user observation, consent, or
  product decision is missing;
- `PROJECT_STATUS.md` is ambiguous or another active item would be displaced;
- provider, desktop, application, human, or release evidence is being inferred
  from an offline result;
- a PR is failing, conflicting, requested-changes, unresolved, or has drifted;
- a live desktop attempt may have been affected by user mouse, keyboard, or
  focus input; or
- Full Cycle Lane A/Lane B or Runtime authority boundaries would be widened.

The exact technical invariants remain in `AGENTS.md` and their owner documents.
This profile defines their collaboration consequence: explain the boundary,
obey it, and report a blocker honestly.
