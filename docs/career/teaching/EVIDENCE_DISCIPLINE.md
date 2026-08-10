# Evidence and claim discipline

> **Status: shared teaching protocol v1 with Guarded Desktop Agent profile
> revision 2.**

## Evidence classes and dimensions

Keep these classes distinct. `Implemented` and `Offline` describe source and
deterministic verification, while Provider, Desktop, Application, Human, and
Release identify different executable or observational surfaces; they are not
a single automatic promotion ladder.

| Class | Required basis |
| --- | --- |
| Implemented | Current code and owner contract |
| Offline | Deterministic tests, fakes, static checks, or offline manifests |
| Provider | Exact credentialed provider/model/route result |
| Desktop | Exact native Windows/VM result |
| Application | Named end-to-end application postconditions |
| Human | Named person/environment/setting observation |
| Release | Exact candidate artifact plus all required release gates and approval |

Planned work remains planned. A detailed contract, mock, green CI job, earlier
candidate, or model-generated summary cannot fill another evidence class or
support a broader or stronger claim.

## Positive, negative, invalid, and blocked evidence

- A valid positive result supports only the exact surface that passed.
- A valid negative result can support engineering judgment, a diagnosis, a
  rejected alternative, or a fail-closed guarantee.
- An invalid attempt records why attribution failed and why a rerun is needed;
  it proves neither success nor a product defect.
- A blocked gate records a missing prerequisite. `NOT RUN` or unavailable
  hardware never becomes a pass or a waiver.

For supervised desktop work, plausible user mouse, keyboard, or focus
intervention makes the attempt `INVALID` until a fresh observation and rerun
separate interference from code behavior.

## Resume-promotion gate

A result may create or update a resume item only when all of these are true:

1. a current owner document and exact evidence source exist;
2. the result is a meaningful durable design, implementation, verified result,
   valid negative result, or postmortem;
3. its evidence class or classes are explicit;
4. its claim limits and unverified next gate are explicit;
5. any owner-document conflict has been resolved rather than hidden in the
   derived career view;
6. before candidate wording is adopted or copied as a personal submission
   claim, the user's contribution is confirmed and supports personal verbs
   such as `designed`, `built`, `implemented`, or `led`; and
7. it adds a distinct hiring signal instead of duplicating an existing item.

If any gate is missing, use `Resume delta: none` and keep teaching in the
conversation. Do not create a speculative bullet to remember planned work.

## Personal ownership

Repository evidence proves project behavior, not individual contribution.
Before submission, distinguish:

- the contract/threat model/product decision you personally made;
- the implementation, tests, debugging, evidence run, or review you performed;
- work drafted by coding agents or supplied by libraries/other contributors;
  and
- what you can explain and reproduce independently.

Candidate files under [resume evidence](../resume/) therefore keep `Personal
ownership: TBC` until the user fills the private `My scope` checkpoint.

## Tracker and data boundaries

Conversation teaches; owner documents track project truth; resume files index
selected durable facts. Never create a second project or learning tracker.

Safe automatic Full Cycle Lane A evidence remains structurally redacted and is
not rich training data. Lane B, L5, training, serving, and Multi-Agent claims
require their own consent and evidence; career wording cannot authorize them.
