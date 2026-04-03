---
phase: 03-band-power-and-control-signals
plan: 03
subsystem: gui
tags: [control-signals, motor-imagery, web-bridge, runJavaScript, pyqt6, integration-test]

# Dependency graph
requires:
  - phase: 03-band-power-and-control-signals
    plan: 02
    provides: "_last_control_signals instance variable, _push_quality_to_task_overlay pattern"
provides:
  - "_push_control_signals_to_task() method pushing lr/ud/mu_c3/mu_c4/baseline_ready to JS"
  - "updateControlSignals(data) global JS receiver storing data on window._lastControlSignals"
  - "End-to-end integration test validating BandPowerExtractor -> RestBaselineTracker -> ControlSignals"
affects: [04-motor-imagery-tasks, 05-cursor-decoding]

# Tech tracking
tech-stack:
  added: []
  patterns: [control-signal-push-to-task, js-global-receiver-pattern]

key-files:
  created: []
  modified: [GUI.py, tasks/motor_imagery/app.js, tests/test_band_power.py]

key-decisions:
  - "Control signal push follows exact same guard/typeof/try-except pattern as _push_quality_to_task_overlay"
  - "JS receiver stores data on window._lastControlSignals for Phase 4 transfer function consumption"
  - "Values rounded to 4 decimal places (lr/ud) and 6 decimal places (mu power) to limit JS payload size"

patterns-established:
  - "Python-to-JS push: guard web_view, typeof check, json.dumps payload, swallow exceptions"
  - "Global JS receiver function pattern for QWebChannel bridge communication"

requirements-completed: [BPOW-01, BPOW-02]

# Metrics
duration: 2min
completed: 2026-04-03
---

# Phase 03 Plan 03: Control Signal Push to Task Window Summary

**Control signals (LR, UD, mu power, baseline state) pushed to motor imagery JS window every streaming chunk with end-to-end pipeline integration test**

## Performance

- **Duration:** 2 min
- **Started:** 2026-04-03T00:49:04Z
- **Completed:** 2026-04-03T00:51:01Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- _push_control_signals_to_task() method added to GUI.py following established push pattern
- updateControlSignals(data) global JS receiver in app.js storing signals on window._lastControlSignals
- End-to-end integration test proving BandPowerExtractor -> RestBaselineTracker -> ControlSignals pipeline
- Full test suite passes (49 tests, 0 failures)

## Task Commits

Each task was committed atomically:

1. **Task 1: Add control signal push to task window and JS receiver** - `088d0b1` (feat)
2. **Task 2: End-to-end integration verification** - `9a744e0` (test)

## Files Created/Modified
- `GUI.py` - Added _push_control_signals_to_task() method and call from update_stream_data()
- `tasks/motor_imagery/app.js` - Added updateControlSignals(data) global receiver function
- `tests/test_band_power.py` - Added test_full_pipeline_integration() end-to-end test

## Decisions Made
- Control signal push follows the exact _push_quality_to_task_overlay pattern for consistency
- JS receiver is a minimal global function -- Phase 4 will add the transfer function and cursor logic that consumes the stored values
- Rounded lr/ud to 4 decimals, mu power to 6 decimals to balance precision and payload size

## Deviations from Plan

None -- plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None -- no external service configuration required.

## Known Stubs
None -- updateControlSignals stores data for Phase 4 consumption, which is the intended design (not a stub).

## Next Phase Readiness
- Control signals now available in JS via window._lastControlSignals every streaming chunk
- Ready for Phase 4: transfer function, cursor decoding, and motor imagery task integration
- Full pipeline verified: streaming -> filtering -> spatial filter -> band power -> z-score -> control signals -> JS push

---
*Phase: 03-band-power-and-control-signals*
*Completed: 2026-04-03*
