---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: verifying
stopped_at: Completed 07-02-PLAN.md
last_updated: "2026-04-03T05:54:45.938Z"
last_activity: 2026-04-03
progress:
  total_phases: 8
  completed_phases: 7
  total_plans: 26
  completed_plans: 24
  percent: 12
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-30)

**Core value:** Researchers can run a complete motor imagery BCI experiment -- from signal conditioning through real-time cursor decoding -- entirely within this GUI.
**Current focus:** Phase 07 — asynchronous-free-cursor-mode

## Current Position

Phase: 07 (asynchronous-free-cursor-mode) — EXECUTING
Plan: 2 of 2
Status: Phase complete — ready for verification
Last activity: 2026-04-03

Progress: [██░░░░░░░░] 12%

## Performance Metrics

**Velocity:**

- Total plans completed: 3
- Average duration: ~15 min
- Total execution time: ~0.75 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| Phase 01 | 3 | 3 tasks | ~15 min |

**Recent Trend:**

- Last 5 plans: P01-01, P01-02, P01-03
- Trend: Stable

| Phase 01.5 P02 | 3min | 4 tasks | 1 files |
| Phase 01.5 P01.5-01 | 3 min | 4 tasks | 2 files |
| Phase 01.5 P04 | 1 min | 3 tasks | 0 files |
| Phase 01.5 P03 | 3min | 2 tasks | 1 files |
| Phase 03 P01 | 3min | 2 tasks | 3 files |
| Phase 03 P02 | 2min | 2 tasks | 1 files |
| Phase 03 P03 | 2min | 2 tasks | 3 files |
| Phase 04 P03 | 3min | 2 tasks | 1 files |
| Phase 04 P04 | 1min | 2 tasks | 0 files |
| Phase 05 P01 | 2min | 2 tasks | 3 files |
| Phase 05 P02 | 2min | 2 tasks | 1 files |
| Phase 05 P03 | 3min | 2 tasks | 1 files |
| Phase 05 P04 | 2min | 2 tasks | 1 files |
| Phase 06 P02 | 2min | 2 tasks | 2 files |
| Phase 06 P01 | 7min | 2 tasks | 4 files |
| Phase 06 P03 | 2min | 2 tasks | 1 files |
| Phase 07 P01 | 3min | 2 tasks | 2 files |
| Phase 07 P02 | 2min | 2 tasks | 1 files |

## Accumulated Context

### Decisions

- [Phase 01]: Causal sosfilt with persistent zi state for online path
- [Phase 01]: to_config parses stage name with split() not rstrip()
- [Phase 01]: calculate_filter_coefficients deprecated; FilterPipeline is sole engine
- [Phase 1.5]: Dual-stream XDF: raw (stream 1) + filtered (stream 3) with type Filtered_EEG
- [Phase 1.5]: _load_xdf prefers Filtered_EEG stream, falls back to raw EEG
- [Phase 1.5]: Filtering moved before visualization gate so filtered data records even when viz paused
- [Phase 1.5]: Magnitude scaling is display-only; filtered XDF stream stores true amplitude
- [Phase 03]: Used np.trapezoid instead of np.trapz (removed in NumPy 2.0)
- [Phase 03]: Z-score per-channel independently, then LR=z_C4-z_C3, UD=z_C3+z_C4
- [Phase 03]: Band power computed before streaming_active guard so control signals update even when viz paused
- [Phase 03]: Control signal push follows exact _push_quality_to_task_overlay pattern for consistency
- [Phase 03]: JS receiver stores data on window._lastControlSignals for Phase 4 transfer function consumption
- [Phase 04]: LR/UD readouts show transfer-function-shaped values, not raw z-scores
- [Phase 04]: Both raw and transformed control signals sent in payload for JS flexibility
- [Phase 04]: All Phase 4 components integrate correctly -- no code fixes needed at verification
- [Phase 05]: CSP uses scipy.linalg.eigh with 1e-10 regularization on composite covariance
- [Phase 05]: LDA certainty = proba[0,1] - proba[0,0] for [-1,+1] range
- [Phase 05]: JSON persistence with numpy .tolist() for human-readable weight files
- [Phase 05]: TrainWorker emits 3 coarse progress stages; marker tuple order swapped at call site
- [Phase 05]: Auto-save weights to XDF directory on training completion
- [Phase 05]: FeedbackBar placed after viz_tabs, fixed 30px, CSP+LDA inference inline in update_stream_data
- [Phase 05]: Synthetic EEG generator uses channel-specific 5x variance scaling for clean CSP class separation in integration tests
- [Phase 06]: Highlighted target square IS the cue in 2D mode -- no arrows; cursor clamped to [0.05,0.95]; cycle counter uses DIRECTIONS.length
- [Phase 06]: save_weights/load_weights extended with axis field; load returns 3-tuple (csp, lda, axis) backward-compatible
- [Phase 06]: UD weights auto-save as csp_lda_weights_ud.json; dual model slots _csp_filter_ud/_lda_classifier_ud
- [Phase 06]: 2D Cursor action gated via _update_2d_gate; CSP-decoded certainty overrides band-power tf when both decoders loaded
- [Phase 07]: FREE mode uses separate updateFree/drawFree loop to keep cued state machine untouched
- [Phase 07]: Cursor position markers sent as JSON with type=cursor_pos via existing send_marker channel
- [Phase 07]: Structural source-reading tests verify contracts without requiring full GUI/Qt runtime

### Pending Todos

None yet.

### Blockers/Concerns

- [Phase 2]: Laplacian neighbor channel sets for supported BrainFlow boards not yet defined
- [Phase 5]: Spatial pattern validation criterion for CSP is qualitative
- lhntdatacollection advanced filters: location not yet confirmed, search in progress

## Session Continuity

Last session: 2026-04-03T05:54:45.930Z
Stopped at: Completed 07-02-PLAN.md
Resume file: None
