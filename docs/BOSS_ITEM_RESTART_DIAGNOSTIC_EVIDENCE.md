# Bounded BOSS item/restart diagnostic evidence

> **Status: partial on-device diagnostic retained 2026-07-23.**
> This record proves three read-only identity-presence commits and one clean
> post-fix stale-owner restart. It also records two integration defects found
> during the sequence. It is not pristine acceptance evidence, semantic job
> extraction, automatic navigation, provider rotation, or a 100-item result.

## Boundary

- Surface: the project-local Agent CLI, `StdioDesktopMCP`, and the existing
  signed-in BOSS interested-jobs view in Chrome.
- Campaign: `boss_live_20260723_overlap`, created after re-login because the
  earlier discovery set no longer described the current list.
- Discovery used two distinct overlapping views: eight identities in pass 1;
  pass 2 retained four duplicates and five new identities, for thirteen total.
- Each item run executed exactly one foreground `ui_snapshot`, required the
  exact coordinator-selected public identity, and persisted only source and
  canonical identity-presence digests.
- The path accepted no item, URL, page, scope, batch, or campaign-kind
  selector. It made zero provider calls, used zero tokens, and performed no
  application action beyond operator-controlled scrolling.

## Result

| Run | Boundary | Result |
| --- | --- | --- |
| `boss_overlap_item_1` | first batch | ordinal 1 committed; `TOOL_CALL_LIMIT`; handoff to ordinal 2 |
| `boss_overlap_item_2` | fresh-run transfer | ordinal 2 durably committed and handed off to ordinal 3; the CLI then falsely reported failure because cumulative completion was incorrectly compared with literal `1` |
| `boss_overlap_item_3` | stale-owner recovery after fixes | stale heartbeat proven with no claim, ownership atomically recovered, ordinal 3 committed, and clean handoff written to ordinal 4 |

Final durable state:

- thirteen discovered identities;
- three `COMMITTED`, ten `DISCOVERED`;
- three `STARTED` and three matching `FINISHED` transitions;
- no active batch or item lease;
- last stop code `TOOL_CALL_LIMIT`;
- handoff `completed_count = 3`, `next_item_ordinal = 4`.

## Defects exposed and fixed

1. The zero-port restart boundary wrote a terminal standard run trace using the
   same run ID required by subsequent item execution. The restart boundary is
   now control-state-only and does not occupy that trace namespace. The
   original zero-call control record from run 2 was byte-preserved under the
   local `resume-control-records` evidence directory before its standard path
   was released.
2. Item handoff validation compared cumulative `completed_count` with literal
   `1`. It now compares the handoff with the current durable ledger projection.
   The original false-failure checkpoint was preserved under
   `corrected-records`; the live checkpoint was corrected only after verifying
   two committed items, a finished batch, matching handoff, one successful tool
   result, and zero provider calls.
3. A finished handoff could not resume after its heartbeat became stale.
   Restart now uses the existing strict `recover_stale_heartbeat` boundary when
   inspection proves `STALE` and no stale or active item claim remains.

The fixed resume-to-second-item and stale-owner paths are covered by regression
tests. The full offline gate after the fixes passed with `1236 passed, 5
skipped`; Ruff, mypy, documentation consistency, and `git diff --check` also
passed.

## Privacy and artifact integrity

Sanitized SHA-256 values:

- item ledger:
  `F26D87A3EF448D81021D6A70B214BE70458946F081ADF19EADE6A2EB8BDC6791`;
- discovery ledger:
  `29C5FAC4E8D5B55CE50EC31649BB6AD672E8329A144083C0A62CB50E1CA9E0FC`;
- batch ledger:
  `66677E431B6F7271DA76958BCA9162B0FC228B5BD4730547C54820CB94DE4555`;
- handoff:
  `717D0CC702981DA533ADC65DFE4D2DDC3611B76D0DA7E9B4610A15E04507230B`;
- item traces 1, 2, and 3:
  `212CB9FB148678F3A3CBD74F1712AA58A9AEE9636F1C380D51527EFBB77BC9B3`,
  `F73BA30E2F00095176E037A15C12966DC21F4AE2C1AFC72C446640CDCE933005`,
  and
  `27A1D89A685400677FCB0F052AA8578CBDD7296FAD5A7C345CBA66182F05EA31`.

The campaign directory and three item traces contained zero matches for full
HTTPS URLs, `securityId`, discovery source-marker query names, or raw job keys
inside traces.

## Supported claim

This is diagnostic evidence that the fixed current code can recover a proven
stale finished owner in a fresh run and complete the next exact read-only
identity commit without provider or selector authority. Because run 2 required
local evidence-preserving correction while the defects were being fixed, this
sequence must not be promoted to clean application acceptance. The next gate is
a fresh, uncorrected multi-item run on the fixed code. That later gate is now
retained separately in
[clean item/restart evidence](BOSS_ITEM_RESTART_CLEAN_EVIDENCE.md); this record
remains the historical defect diagnostic.
