# Presence halo: three causes, none of them the suspected one

> **Status: postmortem, 2026-08-02.** Moved from `PROJECT_STATUS.md` on
> 2026-08-07. Blameless analysis; not capability evidence.


`GDA-HUD-001` opened with an operator reporting no visible halo. Chasing it by
eye across three complete Demo runs found one cause at a time, and each fix
looked correct in isolation while the symptom persisted. Instrumenting the run
settled it in one pass. The lesson is recorded because it generalises: a
surface that is capture-excluded by design cannot be verified by asking an
operator what they saw.

`scripts/demo_cross_app.py` now writes a presence probe report into
`final-state.json` — the projection sequence the halo was asked to show, plus
sample counts for painted, unpainted, and window-absent. The sampled run
`cross-app-demo-20260802-144124-559107` reported `projection_count: 0` and
`samples_window_absent: 32`, which named the third cause immediately.

The three causes were: a DPI source that always reports 96; a coordinator that
never pumped a message loop, so the window never painted and a colour-keyed
layered window that never paints is fully transparent; and a transient approval
yield expressed with the latching `release()`. The second had made the halo
invisible in every Demo run this repository has ever recorded.
