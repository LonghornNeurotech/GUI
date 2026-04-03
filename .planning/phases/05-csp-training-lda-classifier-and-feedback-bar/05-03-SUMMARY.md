---
phase: 05-csp-training-lda-classifier-and-feedback-bar
plan: 03
subsystem: gui
tags: [feedback-bar, csp, lda, qpainter, pyqt6, real-time-inference, transfer-function]

# Dependency graph
requires:
  - phase: 05-csp-training-lda-classifier-and-feedback-bar
    provides: CSPFilter, LDAClassifier from dsp/classifier.py; TrainWorker, training UI, load/save weights from Plan 02
provides:
  - FeedbackBar QWidget with blue-gray-red gradient and white indicator line
  - Real-time CSP+LDA inference in update_stream_data() with transfer function shaping
  - Visibility management tied to streaming state and weight availability
affects: [05-04]

# Tech tracking
tech-stack:
  added: []
  patterns: [QPainter custom widget with gradient fill, real-time inference inline in streaming loop]

key-files:
  created: []
  modified: [GUI.py]

key-decisions:
  - "FeedbackBar placed after viz_tabs in main_layout -- fixed 30px height, no stretch"
  - "CSP+LDA inference runs every streaming chunk inline in update_stream_data (no separate timer)"
  - "Transfer function applied to raw LDA certainty before feeding to bar"

patterns-established:
  - "Feedback bar visibility pattern: show when weights loaded AND streaming, hide on stop or LSL error"

requirements-completed: [FDBK-01, FDBK-02, FDBK-03]

# Metrics
duration: 3min
completed: 2026-04-03
---

# Phase 05 Plan 03: Feedback Bar Widget and Real-Time CSP+LDA Inference Summary

**FeedbackBar QPainter widget with blue-gray-red gradient showing real-time LDA classification certainty post-transfer-function during streaming**

## Performance

- **Duration:** 3 min
- **Started:** 2026-04-03T02:23:22Z
- **Completed:** 2026-04-03T02:25:58Z
- **Tasks:** 2 (1 auto + 1 checkpoint auto-approved)
- **Files modified:** 1

## Accomplishments
- FeedbackBar custom QWidget with horizontal blue-gray-red gradient, white indicator line, and LEFT/RIGHT edge labels
- Real-time CSP+LDA inference wired into update_stream_data() after spatial filter, before band power extraction
- Transfer function (apply_transfer_function with R factor) shapes raw LDA certainty before bar display
- Bar visibility managed across all streaming state transitions: start, stop, LSL error, train finish, weight load

## Task Commits

Each task was committed atomically:

1. **Task 1: Add FeedbackBar widget and wire real-time CSP+LDA inference** - `6fe96db` (feat)
2. **Task 2: Visual verification of feedback bar** - auto-approved (checkpoint:human-verify)

## Files Created/Modified
- `GUI.py` - Added FeedbackBar class (QPainter widget), CSP+LDA inference block in update_stream_data(), feedback bar layout insertion, visibility management in all streaming handlers (+77 lines)

## Decisions Made
- FeedbackBar placed directly after viz_tabs in main_layout with fixed 30px height -- provides unobtrusive certainty readout
- CSP+LDA inference runs every streaming chunk (no separate timer or throttle) -- streaming loop already runs at ~60 Hz, well above the 30 Hz requirement
- Transfer function applied with current R factor spinbox value, matching the control signal pipeline pattern

## Deviations from Plan

None -- plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None -- no external service configuration required.

## Known Stubs

None -- FeedbackBar fully wired to CSPFilter.transform(), LDAClassifier.predict_certainty(), and apply_transfer_function().

## Next Phase Readiness
- Feedback bar complete and wired into streaming pipeline
- Plan 04 (full wiring and integration) can build on the complete CSP+LDA online inference chain
- All three FDBK requirements satisfied: bar visible during streaming (FDBK-01), updates at >=30 Hz (FDBK-02), shows post-transfer-function certainty (FDBK-03)

---
*Phase: 05-csp-training-lda-classifier-and-feedback-bar*
*Completed: 2026-04-03*
