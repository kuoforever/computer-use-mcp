# Step protocol

> **Status: shared teaching protocol v1 with Guarded Desktop Agent profile
> revision 2.**

## Step granularity

Use one teaching step for one hypothesis, bounded change, or evidence gate.
Several commands may belong to one step; one command may contain several steps
only when it crosses separate authority or evidence boundaries.

Split a step when:

- the expected evidence or stop condition changes;
- a new external surface or permission is entered;
- an observation invalidates the working diagnosis;
- implementation ends and real-surface verification begins; or
- a valid result would move a different evidence level.

## Before a non-trivial step

State:

1. **Objective:** the observable result sought.
2. **Tracker and boundary:** why it is allowed now, the source of truth, and
   what remains out of scope.
3. **Concept:** the minimum required mental model or industry term.
4. **Decision or alternative:** the design being tested and one meaningful
   trade-off when relevant.
5. **Expected evidence:** what success should look like before seeing it.
6. **Failure meaning and stop condition:** what would falsify the assumption,
   trigger an in-scope repair, require a clean rerun, or stop for authority.

This prediction prevents post-hoc storytelling.

## During execution

Explain consequential code paths, state transitions, command flags, design
choices, and safety/privacy/compatibility trade-offs. Summarize mechanical
search, editing, formatting, installation, or polling.

When an observation changes the diagnosis, say so before changing direction:

- **Observation:** what exact evidence appeared?
- **Interpretation:** which assumption changed?
- **Effect on plan:** continue, repair within scope, invalidate/rerun, or stop?

Do not narrate an unobserved cause as fact.

## After the step

Classify the result first:

| Outcome | Meaning | Required response |
| --- | --- | --- |
| `PASS` | Expected evidence was observed and remains attributable | Close the step and state its evidence ceiling |
| `FAIL` | A valid run contradicted a requirement or assumption | Diagnose and repair only within the bounded scope; otherwise stop and obtain an explicit user or canonical-tracker re-scope |
| `INVALID` | The result cannot be attributed, such as plausible user input/focus interference | Preserve why it is invalid, re-observe, and rerun; do not call it a defect or success |
| `BLOCKED` | Authority, account, device, human judgment, consent, or clear external state is missing | Stop and name the exact unblock condition |

Then report:

1. exact evidence and expected-versus-observed result;
2. what it proves and what it does not prove;
3. the relevant failure mode or rejected alternative;
4. one interview angle;
5. `Resume delta: none | update GDA-xx | candidate`, with a reason; and
6. the exact next action or preserved resume point from `PROJECT_STATUS.md`.

## Compact templates

~~~text
Before
Objective:
Tracker and boundary:
Concept:
Decision or alternative:
Expected evidence:
Failure meaning and stop condition:
~~~

~~~text
During, only when consequential
Observation:
Interpretation:
Effect on plan:
~~~

~~~text
After
Outcome: PASS | FAIL | INVALID | BLOCKED
Exact evidence:
Expected vs observed:
Proves:
Does not prove:
Failure mode or alternative:
Interview angle:
Resume delta: none | update GDA-xx | candidate
Next action from PROJECT_STATUS.md:
~~~

These are thinking structures, not mandatory literal wording. Keep simple steps
simple and never let the template obscure the actual result.
