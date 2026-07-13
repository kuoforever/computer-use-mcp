# Agent release evidence record

> **Template only.** Copy this document outside the source tree for a specific
> release review. Do not mark a gate passed without its referenced evidence.
> Never paste credentials, task/UI text, screenshots, typed values, raw provider
> traffic, or unredacted traces into this record.

## Candidate identity

| Field | Value |
| --- | --- |
| Version | pending |
| Commit | pending |
| Source tree clean | pending |
| Reviewer | pending |
| Review time (UTC) | pending |
| License/redistribution review | pending |

## Automated gates

| Gate | Result | Sanitized evidence |
| --- | --- | --- |
| Ruff | pending | command, UTC time, commit |
| Full offline pytest | pending | pass/skip counts, supported Python versions |
| E1/E2 | pending | report hash, case count, safety escapes (must be zero) |
| Wheel build | pending | wheel filename and SHA-256 |
| Clean wheel install | pending | environment and CLI smoke result |
| CI | pending | workflow run identifier and commit |

## Human integration gates

| Gate | Result | Sanitized evidence |
| --- | --- | --- |
| OpenAI E3 | `PASS`, `FAIL`, or `NOT RUN` | reviewed model ID, UTC time, fixed outcome |
| Claude E3 | `PASS`, `FAIL`, or `NOT RUN` | reviewed model ID, UTC time, fixed outcome |
| E4-OAI-RO | `PASS`, `FAIL`, or `NOT RUN` | E4 review-record hash |
| E4-OAI-ACT | `PASS`, `FAIL`, or `NOT RUN` | E4 review-record hash |
| E4-ANT-RO | `PASS`, `FAIL`, or `NOT RUN` | E4 review-record hash |
| E4-ANT-ACT | `PASS`, `FAIL`, or `NOT RUN` | E4 review-record hash |
| Failure trace review | pending | denial/e-stop/human/gate/unknown categories reviewed |
| Disclosure review | pending | trace samples contain no prohibited content |

Use the procedures in [Evaluation](EVALUATION.md) and the
[E4 isolated desktop smoke runbook](E4_SMOKE.md). `NOT RUN` is a disclosure,
not a passing result.

## Waivers and release classification

Record every skipped or failed gate with owner, rationale, expiry, and impact.

| Gate | Owner | Rationale | Expiry/revisit | Impact |
| --- | --- | --- | --- | --- |
| pending | pending | pending | pending | pending |

Classification rules:

- Any E3 or E4 value other than `PASS` requires an experimental prerelease.
- An experimental prerelease must state `E3 NOT RUN` and/or `E4 NOT RUN` in
  release notes and must not claim complete safety-MVP or production readiness.
- `UNKNOWN_OUTCOME`, a nonzero safety-escape count, disclosure, or a widened
  safety configuration is not waivable for a safety-MVP release.

## Final review

| Decision | Value |
| --- | --- |
| Changelog updated | pending |
| Version sources reconciled | pending |
| Known limitations disclosed | pending |
| Disable/recovery instructions reviewed | pending |
| Release classification | pending |
| Human decision | `APPROVE`, `REJECT`, or `EXPERIMENTAL ONLY` |
| Signature and UTC time | pending |
