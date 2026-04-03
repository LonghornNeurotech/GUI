---
phase: 05-csp-training-lda-classifier-and-feedback-bar
plan: 02
subsystem: gui
tags: [csp, lda, qthread, training-ui, pyqt6, progress-bar, weight-persistence]

# Dependency graph
requires:
  - phase: 05-csp-training-lda-classifier-and-feedback-bar
    provides: CSPFilter, LDAClassifier, BCITrainer, extract_epochs, save_weights, load_weights from dsp/classifier.py
provides:
  - TrainWorker QThread for background CSP+LDA training
  - Training UI in Control Signals group (trial counts, train button, progress bar, load/save weights)
  - 40-trial-per-class gate enforced before training enabled
  - Epoch extraction on XDF load with trial count display
  - Auto-save weights to XDF directory on training completion
affects: [05-03, 05-04]

# Tech tracking
tech-stack:
  added: []
  patterns: [QThread worker with progress/finished/error signals, 40-trial gate UI pattern, auto-save weights on training completion]

key-files:
  created: []
  modified: [GUI.py]

key-decisions:
  - "TrainWorker emits progress at 3 stages (10%, 30%, 100%) -- sufficient for <2s training time"
  - "Marker tuple order swapped at call site: _load_xdf returns (time, label), extract_epochs expects (label, time)"
  - "Auto-save weights to XDF directory immediately after training completes"

patterns-established:
  - "QThread worker pattern: signals for progress/finished/error, main thread updates UI"
  - "40-trial gate: button disabled with tooltip explaining minimum until threshold met"

requirements-completed: [SPAT-03, SPAT-04, SPAT-05]

# Metrics
duration: 2min
completed: 2026-04-03
---

# Phase 05 Plan 02: CSP+LDA Training UI Summary

**QThread-based CSP+LDA training UI with 40-trial gate, progress bar, epoch extraction on XDF load, and load/save weight persistence buttons**

## Performance

- **Duration:** 2 min
- **Started:** 2026-04-03T02:19:00Z
- **Completed:** 2026-04-03T02:21:22Z
- **Tasks:** 2 (1 auto + 1 checkpoint auto-approved)
- **Files modified:** 1

## Accomplishments
- TrainWorker QThread class with progress/finished/error signals for non-blocking CSP+LDA training
- Training UI in Control Signals group: trial count label, Train button with 40-trial gate, progress bar, status label, load/save weights buttons
- Epoch extraction from XDF markers on file load with trial count display per class
- Train button disabled until both LEFT and RIGHT classes have 40+ trials, with tooltip explaining the requirement
- Auto-save weights to XDF directory on training completion, manual save/load via QFileDialog

## Task Commits

Each task was committed atomically:

1. **Task 1: Add training UI and QThread worker to GUI.py** - `506fcf3` (feat)
2. **Task 2: Visual verification of training UI** - auto-approved (checkpoint:human-verify)

## Files Created/Modified
- `GUI.py` - Added TrainWorker class, CSP+LDA training UI elements, epoch extraction on XDF load, training/weight handler methods (+202 lines)

## Decisions Made
- TrainWorker emits progress at 3 coarse stages (10%, 30%, 100%) since BCITrainer.fit runs in ~1-2s for 80 trials -- finer-grained progress not needed
- Marker tuple order swapped at call site rather than modifying extract_epochs signature -- preserves the existing (label, time) contract from Plan 01
- Auto-save on training completion means weights are immediately persisted without user action

## Deviations from Plan

None -- plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None -- no external service configuration required.

## Known Stubs

None -- all buttons fully wired to dsp/classifier.py functions.

## Next Phase Readiness
- CSP+LDA training fully wired into GUI, weights can be saved/loaded
- Plan 03 (feedback bar widget) can use self._csp_filter and self._lda_classifier for online inference
- Plan 04 (full wiring) can build on the training state stored in SegmentViewer

---
*Phase: 05-csp-training-lda-classifier-and-feedback-bar*
*Completed: 2026-04-03*
