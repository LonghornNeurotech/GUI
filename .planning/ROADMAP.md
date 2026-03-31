# Roadmap: Longhorn Neural Interface Platform — BCI Signal Processing & Motor Imagery v2

## Overview

This milestone builds the complete offline-to-online motor imagery BCI pipeline on top of the existing PyQt6 EEG viewer. The work flows strictly from the root dependency outward: a stateful filter pipeline first, then signal quality and spatial filters, then band power extraction and control signals, then the native task UI and transfer function, then supervised CSP training with the real-time feedback bar, then the 2D cursor task, and finally the asynchronous free-cursor mode. Each phase delivers a testable, independently verifiable capability that the next phase builds on.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Filter Pipeline Foundation** - Stateful sequential filter chain (bandpass, notch) with real-time streaming integration and per-session persistence (completed 2026-03-11)
- [ ] **Phase 1.5: GUI Visualization & UX Polish** - INSERTED: FFT range control, smooth realtime FFT/band power, dark mode contrast fixes, dual-stream XDF
- [ ] **Phase 2: Signal Quality and Spatial Filters** - Per-channel quality indicators, CAR/Laplacian spatial filters, configurable C3/C4 channel mapping
- [ ] **Phase 3: Band Power and Control Signals** - Mu-rhythm band power extraction, LR/UD control signal computation with sliding REST-period baseline
- [ ] **Phase 4: Transfer Function and 1D Motor Imagery Tasks** - Nonlinear transfer function, native PyQt6 1D LR and 1D UD task windows with XDF marker integration
- [ ] **Phase 5: CSP Training, LDA Classifier, and Feedback Bar** - Supervised CSP spatial filter from labeled offline data, LDA decoder, real-time classification certainty bar
- [ ] **Phase 6: 1D Up/Down Decoder and 2D Cursor Task** - UD axis CSP/LDA, combined 2D cursor task with target presentation and progression gating
- [ ] **Phase 7: Asynchronous Free-Cursor Mode** - Cue-free 2D decoding for real-world BCI performance testing with full XDF recording

## Phase Details

### Phase 1: Filter Pipeline Foundation
**Goal**: Researchers can apply a configurable, stateful filter chain to live EEG streams without dropping samples or restarting the stream
**Depends on**: Nothing (first phase)
**Requirements**: FILT-01, FILT-02, FILT-03, FILT-04, FILT-05, FILT-06
**Success Criteria** (what must be TRUE):
  1. User can add a bandpass filter with configurable low/high cutoff frequencies and see it applied immediately to the live waveform
  2. User can add a notch filter (50 or 60 Hz selectable) that applies after the bandpass in the chain
  3. User can add, remove, or reorder filters while the stream is running without restarting or losing data
  4. Filter pipeline sustains >=200 Hz sample throughput on a typical laptop with no drops detectable in the XDF recording
  5. Filter configuration saved for a session is restored automatically when the session is reopened
**Plans:** 3/3 plans complete
Plans:
- [ ] 01-01-PLAN.md — TDD: FilterPipeline core DSP module with full test coverage
- [ ] 01-02-PLAN.md — Wire FilterPipeline into GUI.py + filter configuration UI panel
- [ ] 01-03-PLAN.md — Config persistence to session directory + visual verification

### Phase 1.5: GUI Visualization & UX Polish (INSERTED)
**Goal**: FFT and band power plots are smooth, configurable, and the dark mode theme is consistent with no contrast issues
**Depends on**: Phase 1
**Requirements**: UX-01, UX-02, UX-03, UX-04, UX-05, FILT-07, FILT-08
**Success Criteria** (what must be TRUE):
  1. User can set FFT min/max frequency range via spinboxes above the FFT plot and the display updates immediately
  2. FFT and band power plots update every frame during streaming with no visible lag or stutter
  3. Dark mode has no white-on-white text anywhere -- filter list, scrollbars, inputs all use dark backgrounds with light text
  4. XDF recordings contain both raw and filtered EEG streams; loading prefers filtered
  5. All channels are selected by default when loading a file
**Plans**: TBD

### Phase 2: Signal Quality and Spatial Filters
**Goal**: Researchers can see per-channel signal quality in real-time and apply CAR or Laplacian spatial filters with bad channels automatically excluded from the reference average
**Depends on**: Phase 1
**Requirements**: SPAT-01, SPAT-02, QUAL-01, QUAL-02, QUAL-03, QUAL-04, QUAL-05, CHAN-01, CHAN-02, CHAN-03
**Success Criteria** (what must be TRUE):
  1. Each channel in the main GUI view shows a color-coded quality indicator (green/yellow/red) updating in real-time based on flatline, spike, and SNR checks
  2. Quality indicators remain visible during a running motor imagery task, not only in the main viewer
  3. User can enable CAR and channels flagged as bad are automatically excluded from the reference average without manual intervention
  4. User can enable Laplacian with neighbor channel assignments configurable per headset layout
  5. User can set which channel indices map to C3 and C4, and that mapping persists across sessions and devices
**Plans**: TBD

### Phase 3: Band Power and Control Signals
**Goal**: The system extracts mu-rhythm band power from C3 and C4 in real-time and produces normalized LR and UD control scalars referenced against a sliding REST-period baseline
**Depends on**: Phase 2
**Requirements**: BPOW-01, BPOW-02, BPOW-03, BPOW-04, BPOW-05
**Success Criteria** (what must be TRUE):
  1. Mu-rhythm (8-13 Hz) band power is computed live at C3 and C4 at a continuous decode rate during streaming
  2. An LR control signal (C4-C3 mu power difference) and UD control signal (C3+C4 mu power sum) are available as real-time scalar outputs
  3. Baseline normalization draws only from REST-period samples in a sliding buffer — not a fixed session-start snapshot
  4. Control signal values are expressed in standard deviations from the sliding REST-period mean, and a Re-baseline button resets the buffer mid-session
**Plans**: TBD

### Phase 4: Transfer Function and 1D Motor Imagery Tasks
**Goal**: Researchers can run complete 1D Left/Right and 1D Up/Down offline motor imagery sessions in a native PyQt6 task window, with a transfer function shaping the decoded control signal using subject-specific parameters
**Depends on**: Phase 3
**Requirements**: XFER-01, XFER-02, XFER-03, XFER-04, TASK-01, TASK-02, TASK-03, TASK-04, TASK-05, TASK-06, TASK-07, TASK-08
**Success Criteria** (what must be TRUE):
  1. The 1D Left/Right task opens as a native PyQt6 window with a crosshair fixation point, directional cues, and blink prompts shown during REST periods only
  2. Task timing follows: 60s mindfulness period -> repeating 4s cue / 4s rest cycles with a configurable total number of cycles
  3. All task state transitions emit LSL markers captured in the XDF recording
  4. Transfer function applies dead zone (|x| <= 0.05 SD -> 0), quadratic scaling, and saturation (>=1 SD -> +/-0.9009) to the raw control signal, with the subject-specific R factor exposed as a configurable parameter
  5. The 1D Up/Down task is available with identical timing structure, using the C3+C4 UD control signal
**Plans**: TBD

### Phase 5: CSP Training, LDA Classifier, and Feedback Bar
**Goal**: Researchers can train a CSP spatial filter and LDA classifier from labeled offline session data and see real-time classification certainty during online streaming without leaving the GUI
**Depends on**: Phase 4
**Requirements**: SPAT-03, SPAT-04, SPAT-05, FDBK-01, FDBK-02, FDBK-03
**Success Criteria** (what must be TRUE):
  1. The GUI prevents CSP training from starting until at least 40 labeled trials per class are confirmed in the loaded session data
  2. CSP fitting runs in the background without freezing the UI; a progress indicator is visible during eigendecomposition
  3. Trained CSP weights and LDA classifier are saved to a per-subject file and loadable in a future session without retraining
  4. During online streaming with loaded weights, a horizontal feedback bar shows LDA classification certainty (left/right bias) updating at >=30 Hz, reflecting the transfer-function output rather than raw band power
**Plans**: TBD

### Phase 6: 1D Up/Down Decoder and 2D Cursor Task
**Goal**: Researchers can run a 2D cursor task combining independently trained LR and UD decoders, with four directional targets and progression gating
**Depends on**: Phase 5
**Requirements**: CUR2-01, CUR2-02, CUR2-03, CUR2-04
**Success Criteria** (what must be TRUE):
  1. The 2D cursor task is inaccessible until trained CSP+LDA weights exist for both the LR and UD axes
  2. A cursor moves in 2D in real-time, with the LR and UD axes driven by their respective independently trained decoders and transfer functions
  3. Four directional targets (top, bottom, left, right) are presented as cues; the cursor visibly responds to correct motor imagery
  4. Subject-specific R weighting factors for LR and UD axes are configurable independently
**Plans**: TBD

### Phase 7: Asynchronous Free-Cursor Mode
**Goal**: Researchers can run a cue-free 2D cursor session to evaluate real-world BCI performance, with continuous decoded position recorded to XDF
**Depends on**: Phase 6
**Requirements**: ASYN-01, ASYN-02, ASYN-03
**Success Criteria** (what must be TRUE):
  1. Free-cursor mode presents no directional cues and no target prompts — the subject controls the 2D cursor position freely through imagery
  2. Real-time 2D decoding runs at display rate using the trained CSP+LDA pipeline with no additional configuration required beyond loading saved weights
  3. The session records to XDF with continuous decoded cursor position as markers, using the same format as cued task recordings
**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 -> 2 -> 3 -> 4 -> 5 -> 6 -> 7

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Filter Pipeline Foundation | 3/3 | Complete   | 2026-03-11 |
| 1.5 GUI Visualization & UX Polish | 0/TBD | Not started | - |
| 2. Signal Quality and Spatial Filters | 0/TBD | Not started | - |
| 3. Band Power and Control Signals | 0/TBD | Not started | - |
| 4. Transfer Function and 1D Motor Imagery Tasks | 0/TBD | Not started | - |
| 5. CSP Training, LDA Classifier, and Feedback Bar | 0/TBD | Not started | - |
| 6. 1D Up/Down Decoder and 2D Cursor Task | 0/TBD | Not started | - |
| 7. Asynchronous Free-Cursor Mode | 0/TBD | Not started | - |
