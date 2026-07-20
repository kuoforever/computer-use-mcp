# Architecture decision records

Each record states one decision, the options that were rejected and why, and the
consequences the project accepted — including the negative ones.

These are not summaries of the code. A rule that is obvious from reading the
implementation does not need an ADR; these cover the three places where the
implementation looks over-strict until you know what the alternative costs.

| ADR | Decision | Short version |
| --- | --- | --- |
| [001](001-uncertain-dispatch-is-never-auto-replayed.md) | An uncertain dispatch is never automatically replayed | Missing completion means *we* do not know, not that it did not happen |
| [002](002-ref-actions-never-silently-fall-back-to-coordinates.md) | A ref action never silently falls back to a coordinate click | The cached box says where the element *was*; something else is there now |
| [003](003-custom-durability-vs-workflow-engine.md) | A project-owned ledger and WAL, not a workflow engine | Activity retry is not side-effect safety |

Related: [postmortems](../postmortems/) record what actually failed, and
[AI-assisted development](../AI_ASSISTED_DEVELOPMENT.md) records who is
responsible for these decisions.
