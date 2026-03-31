# Project Research Summary

**Project:** Longhorn Neural Interface Platform — BCI Signal Processing Milestone
**Domain:** Real-time EEG-based motor imagery BCI (PyQt6 desktop)
**Researched:** 2026-03-11
**Confidence:** HIGH

## Executive Summary

This milestone adds a full offline-to-online BCI signal processing pipeline to an existing PyQt6 EEG viewer. The canonical approach for motor imagery BCIs is well-established: a sequential bandpass-notch-spatial filter chain feeds band power extraction, which drives a normalized control signal through a nonlinear transfer function to produce cursor velocity. The existing codebase already handles acquisition (BrainFlow), streaming (pylsl), recording (XDF), and visualization (pyqtgraph). New work fills the gap between raw signals and research-grade decoding — specifically: a formalized FilterPipeline module, a Common Spatial Pattern (CSP) training workflow, LDA-based classification, and a native PyQt6 task window replacing the current QWebEngineView canvas.

The recommended stack requires only one new runtime dependency (pyRiemann 0.10, as an optional fallback classifier) on top of the already-installed scipy, numpy, scikit-learn, and MNE. All signal processing must use causal `sosfilt` with persistent `zi` state for the online path, and `filtfilt` only for offline XDF post-processing. CSP weights are trained once per session from offline labeled data, then applied online as a fixed numpy matrix multiply. LDA with Ledoit-Wolf shrinkage is the correct classifier for the small trial counts (40-60 trials per class) typical of a lab session.

The single largest risk is the offline-to-online performance gap: CSP filters trained on clean calibration data degrade when applied to online feedback sessions due to distributional shift, EMG contamination, and session fatigue. Mitigations include sliding REST-period baseline normalization, mandatory trial-count gating before CSP fitting, bad-channel exclusion from the CAR reference average, and per-subject configurable transfer function parameters. Every one of these mitigations must be built into the initial architecture — retrofitting them after the fact carries medium-to-high recovery cost.

---

## Key Findings

### Recommended Stack

The signal processing stack is mature and well-matched to the existing codebase. scipy `sosfilt` in SOS form with persistent `zi` arrays is the correct real-time filter — numerically stable, C-implemented, and the same library already in use. MNE's `mne.decoding.CSP` is used only for offline weight estimation; the learned filter matrix is applied online as a pure numpy dot product. scikit-learn LDA (`solver='lsqr'`, `shrinkage='auto'`) is the proven classifier for small BCI datasets and provides calibrated class probabilities via `predict_proba`.

The only new runtime dependency is `pyRiemann==0.10`, added as an optional fallback: if LDA accuracy falls below 70% after five runs, switch to pyRiemann MDM (Minimum Distance to Mean on covariance matrices). Do not make it the default — it adds complexity for marginal gain on typical datasets. PyInstaller hidden imports for pyRiemann must be added to the CI build.

**Core technologies:**
- `scipy.signal.sosfilt` (SOS form, persistent zi): causal real-time IIR filtering — numerically stable for chained bandpass + notch at high orders; never use `sosfiltfilt` in the streaming loop
- `numpy` (inline): CAR spatial filter, Laplacian, CSP matrix multiply at inference — zero overhead vs. MNE for per-sample operations
- `mne.decoding.CSP`: offline CSP weight estimation only — sklearn-compatible, correct generalized eigendecomposition; apply the learned W matrix via numpy at runtime
- `scikit-learn LDA` (shrinkage='auto'): left/right decoder — robust to small training sets, provides `predict_proba` for certainty bar; has no `partial_fit` (open issue as of 2026), so online adaptation requires full refit on accumulated data
- `pyRiemann 0.10` (optional): MDM classifier fallback — use only when LDA underperforms; compatible with current numpy/sklearn versions
- `collections.deque` (stdlib): circular buffer for rolling epoch windows — O(1), no extra dependency
- `pytest` + `pytest-qt`: filter pipeline unit tests (headless) and Qt widget tests for CI

### Expected Features

The milestone scope is a complete offline-to-online motor imagery pipeline. Researchers must be able to run an entire BCI session — data collection, CSP training, and online cursor control — without leaving the GUI.

**Must have (table stakes):**
- Sequential filter pipeline (bandpass 8-32 Hz, notch 50/60 Hz, spatial) — root dependency for everything downstream; must run at 200+ Hz without sample drops
- Common Average Reference (CAR) spatial filter — unsupervised baseline before CSP is trained; requires bad-channel gating
- Laplacian spatial filter — safer default for C3/C4 when electrode quality is uncertain; only uses 4 neighbors
- CSP spatial filter — supervised, trained from labeled offline data; minimum 40-60 trials per class enforced programmatically
- Band power extraction (mu 8-13 Hz, beta 18-26 Hz at C3/C4) — the core neuroscience feature; log-variance of filtered signal is standard
- Real-time signal quality indicators (flatline, spike, SNR per channel) — prevents wasted recording sessions; bad-channel output gates CAR application
- Configurable C3/C4 channel mapping — different BrainFlow board IDs return channels in different orders; hardcoding silently fails on new devices
- 1D Left/Right offline motor imagery task (native PyQt6) — replaces QWebEngineView canvas; primary data collection tool for CSP training
- 1D Up/Down offline motor imagery task — required for 2D cursor; C3+C4 sum as UD control signal
- Real-time classification feedback bar — closed-loop feedback is how subjects learn to modulate their BCI signal
- Nonlinear transfer function (dead zone, quadratic, saturation with subject-specific R weighting) — required for any cursor task; parameters must be per-subject configurable, not hardcoded
- 2D cursor task — the primary platform differentiator; requires both 1D tasks to be validated first

**Should have (competitive):**
- Asynchronous free-cursor mode — tests real-world BCI performance outside structured cues; add after 2D cursor is validated
- Progressive training criteria display — surfaces the 80% / 4-consecutive-trials threshold visually; add once training pipeline is exercised
- Band power time-series overlay in main viewer — lets researcher see mu ERD live during a session; useful but not blocking

**Defer (v2+):**
- FBCSP (Filter Bank CSP) — better classification but significantly more complex; validate standard CSP first
- Transfer learning across subjects — requires multi-subject data corpus; not yet applicable
- Error-related potential (ErrP) integration — major paradigm extension; out of current scope

**Anti-features to avoid:**
- Deep learning / neural nets — insufficient data per session (60-120 trials); LDA+CSP consistently outperforms in this data regime
- Real-time ICA artifact removal — computationally expensive, unpredictable latency; use Laplacian for live suppression
- P300/SSVEP paradigm support — different signal chain, different task, dilutes motor imagery focus

### Architecture Approach

The system has five canonical layers: Hardware → Acquisition (existing) → Signal Processing Pipeline (new) → Decoder (new) → Task UI (new). All processing must flow in one direction; the only upward path is decoded cursor position and certainty values back to the UI. The filter pipeline, band power extractor, control signal computer, and transfer function live in a new `processing/` package that is completely isolated from Qt — pure numpy/scipy, testable headless. The task window and cursor widget live in `tasks/mi_task_window.py`. A new `widgets/` directory holds the signal quality indicator for SegmentViewer.

The main design decision is threading: the timer callback pulls BrainFlow data, runs the filter pipeline, and updates visualization on the Qt main thread (fast, <5ms at 256 Hz / 50ms chunk). However, Welch PSD for band power and CSP projection must run in a QThread worker at a fixed 10 Hz decode rate to avoid blocking the UI during active decode sessions. CSP fitting runs in a separate QThread worker on demand (not in the timer loop).

**Major components:**
1. `FilterPipeline` (processing/pipeline.py) — bandpass → notch → spatial stages with per-channel `zi` state; replaces inline filter calls in `update_plot()`
2. `SignalQualityMonitor` (processing/quality.py) — SNR, flatline, spike, impedance proxy; gates bad-channel exclusion from CAR
3. `BandPowerExtractor` + `ControlSignalComputer` (processing/band_power.py, processing/decoder.py) — sliding-window mu-band power, LR/UD scalars, z-score normalization vs. sliding REST baseline
4. `TransferFunction` (processing/decoder.py) — dead zone / quadratic / saturation; pure function, subject-specific R and dead zone threshold
5. `MotorImageryTaskWindow` (tasks/mi_task_window.py) — native PyQt6 stimulus display, state machine, XDF marker integration; replaces QWebEngineView task
6. `CursorWidget` + `FeedbackBar` (tasks/mi_task_window.py) — 2D cursor rendering and 1D certainty bar; owned by the task window
7. `SignalQualityIndicator` (widgets/signal_quality_indicator.py) — color-coded per-channel dots embedded in SegmentViewer

### Critical Pitfalls

1. **CSP overfitting on small trial counts** — Enforce a minimum of 40-60 trials per class programmatically before fitting; apply Ledoit-Wolf regularization to covariance estimates; select only 2-4 component pairs; validate spatial pattern topographies show C3/C4 lateralization, not frontal/peripheral dominance.

2. **IIR filter applied per-epoch rather than continuously** — Feature extraction must read from the always-on filtered buffer, never re-filter a buffer slice. Maintain a dedicated mu-band bandpass with persistent `zi` updated every chunk. Assert no `lfilter` calls with `zi=None` in the decode path.

3. **Stale baseline normalization causing cursor drift** — Use a sliding baseline updated only from REST-period samples in a circular buffer. The z-score formula `(power - mu_rest) / sigma_rest` must use REST-only statistics. Provide a "Re-baseline" button for mid-session reset.

4. **Qt main thread blocking from Welch PSD in the update loop** — Welch on 16 channels at 2-second windows takes 5-15 ms per call — unacceptable in a 30 ms timer tick. Run band power computation and decode in a QThread worker at 10 Hz; share only the result scalars with the main thread.

5. **CAR contamination from a bad channel** — Always gate bad-channel detection before applying CAR. Exclude any channel with variance >5x median or excessive 50/60 Hz power from the reference average. The signal quality monitor output must feed into the CAR channel selection list, not run in parallel with no connection.

---

## Implications for Roadmap

Based on combined research, the component dependency graph dictates a strict build order. Each phase delivers a testable artifact that the next phase builds on. No phase should be started until its predecessor is validated.

### Phase 1: Filter Pipeline Foundation
**Rationale:** Everything downstream depends on a correctly running, stateful filter chain. This is the root of the dependency graph with no external dependencies beyond scipy. Must be built and unit-tested before any other component is added.
**Delivers:** `FilterPipeline` class with bandpass and notch stages, persistent per-channel `zi` state, offline (filtfilt) and online (sosfilt) modes, headless pytest suite with synthetic sinusoid validation.
**Addresses:** Sequential filter pipeline (P1 table stakes); eliminates the IIR-per-epoch pitfall by establishing the single-path filtered-buffer pattern from the start.
**Avoids:** Pitfall 3 (IIR per-epoch transients), Pitfall 8 (Qt main thread blocking — threading architecture decided here before any DSP is added).
**Research flag:** Standard patterns — well-documented scipy/numpy implementation; no additional research phase needed.

### Phase 2: Signal Quality Monitor and CAR Spatial Filter
**Rationale:** Signal quality indicators are independent of the decoder and can be integrated with the existing SegmentViewer immediately after FilterPipeline is validated. CAR is stateless (no training required) and immediately improves downstream signal quality. Bad-channel detection must be wired to CAR exclusion before any spatial filter is applied.
**Delivers:** `SignalQualityMonitor` (SNR, flatline, spike), `SignalQualityIndicator` widgets in SegmentViewer, `SpatialFilterStage` with CAR implementation that excludes flagged bad channels, Laplacian implementation.
**Addresses:** Signal quality indicators (P1), CAR/Laplacian spatial filters (P1), configurable C3/C4 channel mapping (P1).
**Avoids:** Pitfall 7 (CAR bad-channel contamination — gating is built in, not added later).
**Research flag:** Standard patterns — no additional research phase needed.

### Phase 3: Band Power Extraction and Control Signal
**Rationale:** Depends on FilterPipeline with spatial filter active. Produces the LR/UD scalars that feed the cursor. The sliding REST-period baseline must be designed here, not retrofitted after the fact.
**Delivers:** `BandPowerExtractor` (Welch PSD in QThread at 10 Hz), `ControlSignalComputer` (C4-C3 LR, C3+C4 UD, sliding z-score normalization), Re-baseline UI button.
**Addresses:** Band power extraction (P1), configurable channel mapping (consumed here), baseline normalization.
**Avoids:** Pitfall 4 (stale baseline normalization), Pitfall 8 (Welch in QThread at 10 Hz, not main thread).
**Research flag:** Standard patterns — Welch PSD and QThread worker patterns are well-documented.

### Phase 4: Transfer Function and 1D Left/Right Task (Native PyQt6)
**Rationale:** Transfer function is a pure function with no dependencies; it can be implemented and unit-tested in isolation before the task window is built. The 1D LR task is the first end-to-end test of the complete pipeline — from BrainFlow to cursor position. It also replaces the existing QWebEngineView canvas task, which removes the WebEngine compositor dependency from the hot path.
**Delivers:** `TransferFunction` class (dead zone, quadratic, saturation, per-subject R and dead zone threshold), native PyQt6 `MotorImageryTaskWindow` for 1D LR, `FeedbackBar` widget (LR bias indicator), XDF marker integration via existing `TaskBridge` pattern, per-subject config persistence.
**Addresses:** Nonlinear transfer function (P1), 1D LR offline task (P1), real-time classification feedback bar (P1), subject-specific R weighting (P1).
**Avoids:** Pitfall 5 (transfer function miscalibration — exposed as configurable from day one), Pitfall 9 (session fatigue — mindfulness period is unskippable, inter-trial REST minimum enforced in state machine).
**Research flag:** Standard patterns for the transfer function. The task state machine and native Qt rendering are straightforward; no additional research needed.

### Phase 5: CSP Training Flow and LDA Classifier
**Rationale:** CSP requires labeled LEFT/RIGHT epochs from the 1D LR task (Phase 4). Cannot be built before labeled data can be collected. CSP fitting runs in a QThread worker to avoid blocking the UI during eigendecomposition.
**Delivers:** Offline CSP training flow (load XDF → extract epochs → CSP.fit in QThread → serialize W matrix), `SpatialFilterStage.set_weights(W)` integration for online apply, LDA classifier (`shrinkage='auto'`) training and `predict_proba` decode, trial-count gating (minimum 40-60 trials per class enforced), per-subject config storage.
**Addresses:** CSP spatial filter (P1), real-time classification feedback bar (P1, now with trained decoder).
**Avoids:** Pitfall 1 (CSP overfitting — trial count gating and regularization built in), Pitfall 6 (offline-to-online gap — at least one feedback-exposure calibration block before model is used for control).
**Research flag:** Needs validation of spatial pattern topographies post-implementation to confirm C3/C4 lateralization. CSP regularization parameter tuning may need a brief research-phase consultation.

### Phase 6: 1D Up/Down Task and 2D Cursor
**Rationale:** Requires both 1D axes to be trained and validated. UD task is structurally identical to LR task. CursorWidget extends the task window built in Phase 4.
**Delivers:** 1D UD offline task (C3+C4 sum decoder), combined 2D cursor task, `CursorWidget` (QWidget paintEvent, 2D cursor rendering, target zones), independent transfer functions for LR and UD axes with separate R values.
**Addresses:** 1D UD offline task (P1), 2D cursor task (P1 — primary platform differentiator).
**Avoids:** Pitfall 5 (both axes need separate R calibration), Pitfall 6 (UD decoder trained from UD calibration data, not reused from LR session).
**Research flag:** Standard patterns — extends work already validated in Phase 4/5.

### Phase 7: Asynchronous Free-Cursor Mode and Polish
**Rationale:** Add only after 2D cursor task is validated and subjects are performing at 80% or better on 1D tasks. Asynchronous mode reuses the same decoding architecture with the cue overlay removed.
**Delivers:** Asynchronous free-cursor mode, progressive training criteria display (80% / 4-consecutive-trials threshold), band power time-series overlay in main SegmentViewer, pyRiemann MDM fallback classifier integration.
**Addresses:** P2 features (async free-cursor, progressive criteria display, band power overlay).
**Avoids:** No new critical pitfalls — these are additive features on top of validated infrastructure.
**Research flag:** Standard patterns — no additional research phase needed.

### Phase Ordering Rationale

- **FilterPipeline first:** It is the root of the dependency graph. No feature extraction, spatial filtering, or quality monitoring is valid without it. Building it first also forces the threading architecture decision before any DSP is added to the timer loop.
- **Quality + CAR before decoder:** Bad-channel detection must gate CAR application from the start. Adding quality monitoring after the spatial filter is already in production would require auditing all previously collected data for contamination.
- **Band power before task window:** The task window needs a working band power and control signal to test against. Building it first would produce an unverifiable state machine.
- **Transfer function before 1D task:** The transfer function is a pure function that can be fully unit-tested in isolation. Having it validated before the task window is built means the first end-to-end test exercises a known-correct component.
- **CSP after 1D task:** CSP requires labeled data. The 1D task is the labeled data collection mechanism. This is a hard dependency.
- **2D cursor last:** Depends on both 1D decoders being validated. Any bug in the LR or UD axis will manifest in the 2D task and be harder to diagnose there.

### Research Flags

Phases needing deeper research during planning:
- **Phase 5 (CSP + LDA):** Covariance regularization parameter selection and spatial pattern validation require domain-specific judgment. Recommend a brief research-phase consultation when planning this phase to confirm regularization approach and minimum trial count enforcement strategy.

Phases with standard patterns (skip research-phase):
- **Phase 1 (FilterPipeline):** scipy sosfilt pattern is documented in official scipy docs and well-understood.
- **Phase 2 (Signal Quality + CAR):** Variance-based quality metrics and CAR implementation are straightforward numpy operations.
- **Phase 3 (Band Power):** Welch PSD and QThread worker patterns are established in existing codebase patterns.
- **Phase 4 (Transfer Function + 1D LR Task):** Transfer function is a pure function from a published formula. Native PyQt6 task window follows patterns already used in SegmentViewer.
- **Phase 6 (2D Cursor):** Extends Phase 4/5 work; no new patterns.
- **Phase 7 (Polish):** Additive features on validated infrastructure.

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Core libraries (scipy, numpy, sklearn, MNE) are verified against official docs with specific version compatibility confirmed. pyRiemann 0.10 is MEDIUM — released January 2026, compatibility stated but not deeply verified against edge cases. |
| Features | HIGH | Feature set is well-specified in PROJECT.md and cross-validated against published BCI literature (PubMed, Frontiers, arXiv). Feature dependencies and MVP boundary are clear. |
| Architecture | HIGH (pipeline stages), MEDIUM (threading) | Five-layer pipeline architecture is backed by published BCI system papers. The specific Qt threading recommendation (main thread for filter, QThread for Welch at 10 Hz) is sound but the exact performance threshold (when the main thread becomes a bottleneck) depends on the target machine and channel count. |
| Pitfalls | HIGH | Signal processing pitfalls are extensively documented in peer-reviewed BCI literature. GUI-specific pitfalls (Qt blocking, CAR contamination) are verified against the existing codebase patterns. |

**Overall confidence:** HIGH

### Gaps to Address

- **pyRiemann 0.10 PyInstaller compatibility:** The hidden import list is specified but not verified against a live PyInstaller build. Validate during the Phase 5 CI build that pyRiemann bundles correctly on all three platforms (Windows, macOS, Linux).
- **Welch PSD performance threshold:** The recommendation to move Welch to a QThread at >8 channels is based on published benchmarks, not a measurement on the actual target hardware. Profile during Phase 3 development on the lab machine before committing to the threading architecture.
- **Spatial pattern validation criteria:** The "physiologically plausible C3/C4 lateralization" check for CSP is described qualitatively. During Phase 5 planning, define a quantitative criterion (e.g., top CSP component must have maximum weight within 3 cm of C3 or C4 on the standard 10-20 layout) to make the validation step auditable.
- **Minimum trial count for Laplacian neighbors:** The Laplacian implementation requires configurable neighbor definitions per headset layout. The specific neighbor sets for supported BrainFlow boards are not yet defined. Address during Phase 2 planning.

---

## Sources

### Primary (HIGH confidence)
- [scipy.signal.sosfilt — SciPy v1.17.0](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.sosfilt.html) — stateful real-time filtering, SOS form
- [mne.decoding.CSP — MNE 1.11.0](https://mne.tools/stable/generated/mne.decoding.CSP.html) — CSP API, fit/transform, sklearn compatibility
- [LinearDiscriminantAnalysis — scikit-learn 1.8.0](https://scikit-learn.org/stable/modules/generated/sklearn.discriminant_analysis.LinearDiscriminantAnalysis.html) — shrinkage, predict_proba
- [sklearn issue #30042](https://github.com/scikit-learn/scikit-learn/issues/30042) — confirmed partial_fit absent in LDA as of 2026
- [MNE CSP example](https://mne.tools/stable/auto_examples/decoding/decoding_csp_eeg.html) — offline CSP training and feature extraction pattern
- PMC2918755 — Model-based generalization analysis of CSP — overfitting and noise sensitivity
- Frontiers fnhum.2021.625983 — closed-loop feedback design and certainty visualization
- Nature s41598-019-44166-7 — BCI decoder design and nonlinear transfer function parameter selection
- arXiv 2511.23384 — Cybathlon 2024 BCI pipeline: four-module architecture, 117ms median latency
- PMC10335802 — BCI-HIL modular pipeline with LSL and DAG scheduling

### Secondary (MEDIUM confidence)
- [pyriemann PyPI](https://pypi.org/project/pyriemann/) / [pyRiemann GitHub](https://github.com/pyRiemann/pyRiemann) — v0.10 release, MDM classifier, dependency requirements
- [real-time-iir-filter GitHub](https://github.com/what-in-the-nim/real-time-iir-filter) — multichannel sosfilt zi stateful pattern
- arXiv 2403.15431 — Transferring BCI models from calibration to control: EEG feature distributional shift
- ResearchGate — CAR spatial filter bad-channel contamination and median average reference alternatives
- arXiv 1707.08152 — Baseline correction requirements in EEG

### Tertiary (LOW confidence)
- scipy ENH issue #21644 — multichannel sosfilt zi usability note (GitHub issue, not official docs)
- Qt Forum / pythonguis.com — GIL interaction with QThread in PyQt6 (community forum, needs validation against actual performance profile)

---
*Research completed: 2026-03-11*
*Ready for roadmap: yes*
