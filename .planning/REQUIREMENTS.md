# Requirements: Longhorn Neural Interface Platform — BCI Signal Processing & Motor Imagery v2

**Defined:** 2026-03-11
**Core Value:** Researchers can run a complete motor imagery BCI experiment — from signal conditioning through real-time cursor decoding — entirely within this GUI.

## v1 Requirements

### Signal Processing Pipeline

- [x] **FILT-01**: User can add a bandpass filter with configurable low/high cutoff frequencies to the processing chain
- [x] **FILT-02**: User can add a notch filter (50/60 Hz selectable) to the processing chain
- [x] **FILT-03**: Filters are applied sequentially in the order added (bandpass → notch → spatial)
- [x] **FILT-04**: Filter pipeline runs in real-time at device sample rate (≥200 Hz) without dropping samples
- [x] **FILT-05**: User can add/remove/reorder filters without restarting the stream
- [x] **FILT-06**: Filter parameters persist across session (saved per configuration)
- [x] **FILT-07**: XDF recordings contain both raw and filtered EEG as separate streams
- [x] **FILT-08**: Loading an XDF file prefers the filtered EEG stream when available

### GUI Visualization & UX

- [x] **UX-01**: FFT plot has user-configurable min/max frequency range (spinboxes above the plot)
- [ ] **UX-02**: FFT and band power plots update every frame for smooth realtime display (no throttle)
- [x] **UX-03**: Dark mode: filter list widget uses dark background with light text (no white-on-white)
- [x] **UX-04**: Dark mode: scrollbars, input fields, spinboxes have consistent dark styling
- [ ] **UX-05**: All channels selected by default in file mode (matching streaming mode behavior)

### Spatial Filters

- [ ] **SPAT-01**: User can apply Common Average Reference (CAR) as a spatial filter
- [ ] **SPAT-02**: User can apply surface Laplacian spatial filter with configurable neighbor channels
- [ ] **SPAT-03**: User can apply CSP spatial filter trained from labeled offline session data
- [ ] **SPAT-04**: CSP training requires minimum 40 trials per class before allowing training (overfitting prevention)
- [ ] **SPAT-05**: CSP weights are saved per subject and loadable for online sessions

### Signal Quality & Validation

- [ ] **QUAL-01**: Real-time per-channel signal quality indicator: green (good), yellow (marginal), red (bad)
- [ ] **QUAL-02**: Quality based on: flatline detection (std < threshold), spike detection (IQR outliers), SNR proxy (variance ratio)
- [ ] **QUAL-03**: Quality indicators visible in main GUI channel view as color-coded labels
- [ ] **QUAL-04**: Quality indicators visible during motor imagery tasks (overlay or status bar)
- [ ] **QUAL-05**: Bad channels excluded from CAR computation automatically

### Channel Configuration

- [ ] **CHAN-01**: User can configure which channels map to C3 and C4 electrode positions
- [ ] **CHAN-02**: Channel mapping stored per device/subject and persists across sessions
- [ ] **CHAN-03**: Laplacian neighbor channels configurable per headset layout

### Band Power & Control Signals

- [ ] **BPOW-01**: Mu-rhythm (8-13 Hz) band power extracted from C3 and C4 in real-time
- [ ] **BPOW-02**: LR control signal computed as C4-C3 mu power difference
- [ ] **BPOW-03**: UD control signal computed as C3+C4 mu power sum
- [ ] **BPOW-04**: Sliding REST-period baseline normalization (not fixed session-start baseline)
- [ ] **BPOW-05**: Band power values normalized to standard deviations from baseline mean

### Motor Imagery Tasks — Offline 1D

- [ ] **TASK-01**: 1D Left/Right offline task with minimalist lab-style UI (native PyQt6 or clean web)
- [ ] **TASK-02**: Task timing: 60s mindfulness period → repeating 4s cue / 4s rest cycles
- [ ] **TASK-03**: LEFT and RIGHT cues presented in random or alternating order
- [ ] **TASK-04**: Blink prompts shown during REST periods only
- [ ] **TASK-05**: Central crosshair fixation point always visible during task
- [ ] **TASK-06**: All state transitions emit LSL markers recorded to XDF
- [ ] **TASK-07**: 1D Up/Down offline task with same timing structure
- [ ] **TASK-08**: Configurable number of cycles per run

### Nonlinear Transfer Function

- [ ] **XFER-01**: Dead zone: |x| ≤ 0.05 SD from baseline → output = 0
- [ ] **XFER-02**: Quadratic region: 0.05 < |x| < 1 → y = 0.1(Rx²) + 0.3·Rx + 2.25×10⁻⁷
- [ ] **XFER-03**: Saturation: |x| ≥ 1 → output clamps at ±0.9009
- [ ] **XFER-04**: Subject-specific R weighting factor exposed as configurable parameter (LR: 3-3.5, UD: 0.3-0.6)

### Real-Time Feedback

- [ ] **FDBK-01**: Horizontal bar/indicator showing LR classification certainty during online training
- [ ] **FDBK-02**: Feedback updates at display rate (≥30 Hz)
- [ ] **FDBK-03**: Bar position reflects decoded LR signal after transfer function

### 2D Cursor Task

- [ ] **CUR2-01**: 2D cursor task combining LR and UD decoded control signals
- [ ] **CUR2-02**: Cursor position updated in real-time from transfer function outputs
- [ ] **CUR2-03**: 4 targets (top, bottom, left, right) presented as cues
- [ ] **CUR2-04**: Progression gate: requires 1D LR and 1D UD training completed first

### Asynchronous Free-Cursor

- [ ] **ASYN-01**: Free-cursor mode with no cue prompts — subject controls 2D cursor position freely
- [ ] **ASYN-02**: Real-time 2D decoding at display rate using trained CSP+LDA pipeline
- [ ] **ASYN-03**: Session recorded to XDF with continuous decoded position markers

## v2 Requirements

### Enhanced Training

- **TRNG-01**: Progressive training criteria display (per-trial accuracy tracker, visual progress toward 80% threshold)
- **TRNG-02**: Band power time-series overlay on main channel plot (mu power trace for C3/C4)
- **TRNG-03**: Session statistics summary after each run (accuracy, trial count, progression status)

### Advanced Filters

- **AFLT-01**: Kalman filter denoising option (random walk or position-velocity model)
- **AFLT-02**: Artifact flagging with visual markers in waveform (non-rejecting — researcher decides)

## Out of Scope

| Feature | Reason |
|---------|--------|
| Real-time ICA artifact removal | Computationally expensive, unpredictable latency, convergence issues online |
| Deep learning classifier | Overfits with few trials, slow training, not interpretable for research |
| P300/SSVEP paradigm support | Different signal chain, different UI, dilutes motor imagery focus |
| Gamification/VR feedback | Scope is minimalist lab-style; gamification results inconsistent |
| Cloud sync / multi-site | Desktop-only, local-compute constraint; adds network latency |
| Multi-subject simultaneous | Single-subject scope; multi adds session management complexity |
| Automatic trial rejection | Silently discards valid data; researcher should see artifacts, decide post-hoc |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| FILT-01 | Phase 1 | Complete |
| FILT-02 | Phase 1 | Complete |
| FILT-03 | Phase 1 | Complete |
| FILT-04 | Phase 1 | Complete |
| FILT-05 | Phase 1 | Complete |
| FILT-06 | Phase 1 | Complete |
| FILT-07 | Phase 1 | Complete |
| FILT-08 | Phase 1 | Complete |
| UX-01 | Phase 1.5 | Complete |
| UX-02 | Phase 1.5 | Pending |
| UX-03 | Phase 1.5 | Complete |
| UX-04 | Phase 1.5 | Complete |
| UX-05 | Phase 1.5 | Complete |
| SPAT-01 | Phase 2 | Pending |
| SPAT-02 | Phase 2 | Pending |
| QUAL-01 | Phase 2 | Pending |
| QUAL-02 | Phase 2 | Pending |
| QUAL-03 | Phase 2 | Pending |
| QUAL-04 | Phase 2 | Pending |
| QUAL-05 | Phase 2 | Pending |
| CHAN-01 | Phase 2 | Pending |
| CHAN-02 | Phase 2 | Pending |
| CHAN-03 | Phase 2 | Pending |
| BPOW-01 | Phase 3 | Pending |
| BPOW-02 | Phase 3 | Pending |
| BPOW-03 | Phase 3 | Pending |
| BPOW-04 | Phase 3 | Pending |
| BPOW-05 | Phase 3 | Pending |
| XFER-01 | Phase 4 | Pending |
| XFER-02 | Phase 4 | Pending |
| XFER-03 | Phase 4 | Pending |
| XFER-04 | Phase 4 | Pending |
| TASK-01 | Phase 4 | Pending |
| TASK-02 | Phase 4 | Pending |
| TASK-03 | Phase 4 | Pending |
| TASK-04 | Phase 4 | Pending |
| TASK-05 | Phase 4 | Pending |
| TASK-06 | Phase 4 | Pending |
| TASK-07 | Phase 4 | Pending |
| TASK-08 | Phase 4 | Pending |
| SPAT-03 | Phase 5 | Pending |
| SPAT-04 | Phase 5 | Pending |
| SPAT-05 | Phase 5 | Pending |
| FDBK-01 | Phase 5 | Pending |
| FDBK-02 | Phase 5 | Pending |
| FDBK-03 | Phase 5 | Pending |
| CUR2-01 | Phase 6 | Pending |
| CUR2-02 | Phase 6 | Pending |
| CUR2-03 | Phase 6 | Pending |
| CUR2-04 | Phase 6 | Pending |
| ASYN-01 | Phase 7 | Pending |
| ASYN-02 | Phase 7 | Pending |
| ASYN-03 | Phase 7 | Pending |

**Coverage:**
- v1 requirements: 49 total
- Mapped to phases: 49
- Unmapped: 0

---
*Requirements defined: 2026-03-11*
*Last updated: 2026-03-30 — added FILT-07/08 (dual-stream XDF), UX-01..05 (GUI polish), Phase 1.5 inserted*
