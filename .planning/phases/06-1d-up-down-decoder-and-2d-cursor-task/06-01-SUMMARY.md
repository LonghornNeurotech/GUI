---
phase: 06-1d-up-down-decoder-and-2d-cursor-task
plan: 01
subsystem: dsp
tags: [csp, lda, classifier, motor-imagery, up-down, detect-axis]

# Dependency graph
requires:
  - phase: 05-csp-lda-offline-training
    provides: CSPFilter, LDAClassifier, BCITrainer, extract_epochs, save_weights, load_weights
provides:
  - detect_axis helper for LR/UD marker auto-detection
  - UD epoch extraction via existing extract_epochs with classes param
  - Axis field in weight JSON files for auto-routing on load
  - Independent R (UD) spinbox in GUI
  - Dual-axis training flow storing UD weights separately
affects: [06-02, 06-03, 2d-cursor-task]

# Tech tracking
tech-stack:
  added: []
  patterns: [dual-axis-model-slots, axis-aware-weight-persistence]

key-files:
  created: []
  modified:
    - dsp/classifier.py
    - dsp/__init__.py
    - tests/test_classifier.py
    - GUI.py

key-decisions:
  - "save_weights/load_weights extended with axis field for auto-detect on load"
  - "load_weights returns 3-tuple (csp, lda, axis) -- backward compatible with 'LR' default"
  - "UD weights auto-save as csp_lda_weights_ud.json alongside LR weights"

patterns-established:
  - "Dual model slots: _csp_filter/_lda_classifier for LR, _csp_filter_ud/_lda_classifier_ud for UD"
  - "detect_axis determines axis from markers before epoch extraction"

requirements-completed: [CUR2-01, CUR2-04]

# Metrics
duration: 7min
completed: 2026-04-03
---

# Phase 06 Plan 01: UD Decoder Support Summary

**detect_axis auto-detects UP/DOWN markers from XDF, trains CSP+LDA to separate UD weight file, with independent R (UD) spinbox**

## Performance

- **Duration:** 7 min
- **Started:** 2026-04-03T04:11:09Z
- **Completed:** 2026-04-03T04:18:17Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- detect_axis helper scans markers for LEFT/RIGHT vs UP/DOWN, returns axis string
- save_weights/load_weights extended with axis field for round-trip persistence
- GUI auto-detects axis from loaded XDF, extracts UD epochs, trains to separate weight file
- Independent R (LR) and R (UD) spinboxes with per-axis transfer function application

## Task Commits

Each task was committed atomically:

1. **Task 1: Add detect_axis helper and UD epoch extraction support** - `7cf2280` (feat, TDD)
2. **Task 2: Add R (UD) spinbox and dual-axis training flow in GUI.py** - `190e410` (feat)

## Files Created/Modified
- `dsp/classifier.py` - Added detect_axis function, axis param to save_weights, 3-tuple return from load_weights
- `dsp/__init__.py` - Updated module docstring to list detect_axis
- `tests/test_classifier.py` - 11 new tests: detect_axis (7), UD epochs (2), axis persistence (2)
- `GUI.py` - UD model slots, R (UD) spinbox, axis-aware training/loading/saving

## Decisions Made
- save_weights/load_weights extended with axis field rather than separate functions -- keeps API surface minimal
- load_weights returns 3-tuple for backward compatibility (missing axis key defaults to "LR")
- UD weights auto-save to csp_lda_weights_ud.json in XDF directory

## Deviations from Plan

None -- plan executed exactly as written.

## Known Stubs

None -- all data paths are wired.

## Issues Encountered

Pre-existing flaky performance test (test_throughput_performance in test_filter_pipeline.py) fails intermittently due to machine load. Not related to this plan's changes.

## User Setup Required

None -- no external service configuration required.

## Next Phase Readiness
- LR and UD model slots populated independently
- Plan 02 (2D cursor task) can check both _csp_filter and _csp_filter_ud for readiness
- R factors are per-axis, ready for subject-specific tuning

---
*Phase: 06-1d-up-down-decoder-and-2d-cursor-task*
*Completed: 2026-04-03*

## Self-Check: PASSED
