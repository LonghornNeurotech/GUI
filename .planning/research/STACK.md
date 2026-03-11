# Stack Research

**Domain:** Real-time BCI signal processing, motor imagery decoding, cursor control
**Researched:** 2026-03-11
**Confidence:** HIGH (core DSP/ML stack), MEDIUM (spatial filter impl strategy)

---

## Scope

This file covers only the **new** technology needed for the signal processing milestone. The
existing stack (PyQt6, pyqtgraph, BrainFlow, pylsl, pyxdf, MNE, scipy, numpy) is already
established and not reconsidered here.

---

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| scipy.signal | 1.17.0 (already in use) | Bandpass/notch IIR filters — sosfilt + sosfilt_zi | sosfilt with SOS form is the standard for real-time causal EEG filtering: numerically stable, C-implemented, supports per-channel state persistence between calls. `lfilter` (already used) is acceptable but SOS form preferred for high-order filters. Do NOT use sosfiltfilt — it is non-causal (forward+reverse pass), introducing unacceptable latency in online streaming. |
| numpy | 2.4.2 (already in use) | CAR and Laplacian spatial filters, band-power computation | CAR is a single matrix subtraction (`X - X.mean(axis=0)`); Laplacian is a weighted neighbor subtraction. Both are pure numpy, zero-dependency. No external library needed for these two filter types — MNE's `set_eeg_reference` adds overhead unsuitable for per-sample processing. |
| mne.decoding.CSP | 1.11.0 (already in use) | Common Spatial Pattern filter estimation (offline training phase) | MNE's CSP implements the generalized eigendecomposition correctly, exposes `fit(epochs, labels)` → `transform(epochs)` sklearn-compatible interface, and integrates cleanly into a sklearn Pipeline. Use for offline CSP weight estimation only. At inference, apply the learned spatial filter matrix as a numpy dot product — do not call mne.decoding.CSP.transform() on single samples in the streaming loop due to epoch-shape expectations. |
| scikit-learn | 1.8.0 | LDA classifier for left/right decoding, predict_proba for certainty feedback | LinearDiscriminantAnalysis with `solver='lsqr'`, `shrinkage='auto'` (Ledoit-Wolf) is the proven BCI choice: robust with small training sets (60 trials typical), provides calibrated class probabilities via `predict_proba`, and is fast enough for per-epoch inference. LDA does NOT support `partial_fit` (open issue as of 2026) — online adaptation requires full refit on accumulated data, which is acceptable at 4s epochs. |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pyRiemann | 0.10 (new dependency) | Riemannian geometry-based covariance classification (MDM, FgMDA) | Use as an **alternative classifier** for subjects where LDA underperforms. pyRiemann's MDM (Minimum Distance to Mean) classifier on covariance matrices consistently outperforms LDA on small datasets in BCI literature. Add as optional: if LDA accuracy < 70% after 5 runs, switch to pyRiemann MDM. Do not make it the default — adds 15-20MB and a non-obvious mental model. |
| collections.deque (stdlib) | stdlib | Circular buffer for streaming sample windows | Use `deque(maxlen=N)` for maintaining the rolling epoch window (e.g., 1-second window at 250 Hz = 250 samples). Zero-copy append, O(1) popleft. No external dependency. |
| threading (stdlib) | stdlib | Signal processing thread isolation | Run the filter pipeline in a QThread (already used in the codebase) — keep the pipeline class pure Python/numpy with no Qt imports to enable testing without a display. |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| pytest | Unit testing for filter pipeline and transfer function | Filter correctness (known input → known output), transfer function boundary conditions, SNR calculation. Tests must run headless (no Qt). Parametrize over filter orders and sample rates. |
| pytest-qt | PyQt6 widget testing | For testing the cursor task widget and signal quality indicator widgets. Required for CI. |

---

## Installation

```bash
# New dependency only — everything else already installed
pip install pyriemann==0.10

# Dev dependencies
pip install pytest pytest-qt
```

PyInstaller hidden import to add for pyRiemann:
```
--hidden-import pyriemann --hidden-import pyriemann.classification --hidden-import pyriemann.estimation
```

---

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| scipy sosfilt (causal, SOS form) | scipy lfilter (already in codebase) | lfilter is fine for low-order filters (≤4th order bandpass). For notch + bandpass chained = higher effective order, switch to SOS to avoid coefficient quantization errors. |
| numpy CAR / Laplacian (inline) | MNE set_eeg_reference() for CAR | MNE's reference function is designed for offline epochs. For per-sample streaming, a single `X - X.mean(axis=0)` is sufficient and adds zero overhead. |
| mne.decoding.CSP (offline fit only) | pyRiemann CSP | pyRiemann CSP supports multiclass via approximate joint diagonalization — use if extending beyond binary LR/UD. For binary classification with the standard 2-class problem, MNE CSP is simpler. |
| scikit-learn LDA shrinkage='auto' | scikit-learn QDA | QDA is unstable with small BCI training sets (n_samples << n_features after CSP). LDA with Ledoit-Wolf shrinkage is the standard choice in published BCI motor imagery work. |
| pyRiemann MDM (optional fallback) | MOABB + Riemannian pipeline | MOABB is a benchmarking framework — too heavy for embedded use in a desktop GUI. Extract pyRiemann alone. |
| scipy sosfilt (causal) | scipy sosfiltfilt (zero-phase) | sosfiltfilt requires the full signal to be in memory (forward+reverse pass). It is correct for offline preprocessing of loaded XDF files. Do NOT use for the live streaming pipeline — it introduces half-filter-length latency equivalent. |

---

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| scipy.signal.sosfiltfilt in the streaming loop | Non-causal: requires future samples. Valid for offline file processing only. Using it in streaming introduces unbounded latency and defeats real-time feedback. | scipy.signal.sosfilt with persisted zi state |
| scipy.signal.lfilter for the chained pipeline | Direct-form II TF coefficients accumulate floating-point error for the effective order of bandpass+notch in series. Silent degradation at high sampling rates. | scipy.signal.sosfilt with output='sos' coefficient design |
| MNE for any per-sample streaming operation | MNE's processing functions expect Epochs or Raw objects with full header metadata. Forcing individual samples through MNE types adds ~1ms overhead per call — fatal at 250 Hz. | numpy operations on raw arrays for streaming; MNE only for offline CSP fitting and file I/O |
| MOABB | Full benchmarking framework (datasets, pipelines, results DB). Massive install, not needed for runtime. | pyRiemann alone for the Riemannian classifier |
| PyTorch / EEGNet / deep learning | Motor imagery decoding with 60-120 training epochs per subject per session does not have enough data to train deep networks from scratch. LDA+CSP consistently outperforms in this data regime per BCI literature. | LDA with shrinkage or pyRiemann MDM |
| OpenBCI GUI software or BCI2000 | External processes that duplicate what BrainFlow+pylsl already provide. Adds IPC complexity, latency, and a separate process to install. | BrainFlow (already in use) |
| sklearn partial_fit for online LDA adaptation | LinearDiscriminantAnalysis.partial_fit() does not exist in scikit-learn as of 1.8.0 (open GitHub issue #30042). The method will raise AttributeError silently if wrapped. | Full refit on all accumulated trial data after each run — fast enough at epoch counts used |

---

## Stack Patterns by Variant

**For the offline training phase (loading XDF, computing CSP weights):**
- Use MNE to load epochs, extract events, bandpass-filter the stored data
- Use mne.decoding.CSP.fit(epochs_data, labels) to learn the spatial filter
- Serialize the learned CSP matrix (W) and LDA weights to disk (numpy .npy or pickle)

**For the online streaming phase (live decoding):**
- Apply learned CSP matrix as `W @ sample_chunk` — pure numpy dot product
- Compute log-variance of CSP-filtered epochs: `np.log(np.var(filtered_epoch, axis=-1))`
- Feed log-variance features to LDA.predict_proba() — returns [p_left, p_right]
- Apply nonlinear transfer function to difference: `p_right - p_left` → cursor velocity

**For the transfer function:**
- Use pure numpy: dead zone, quadratic, and saturation are all scalar operations
- Keep R (subject weighting) as a float slider in the GUI, not hardcoded
- Transfer function formula from PROJECT.md: y = 0.1(Rx²) + 3×10⁻¹·Rx + 2.25×10⁻⁷ for |x| in (0.05, 1)

**For 2D cursor (LR + UD combined):**
- C4-C3 mu-band power difference → LR control signal (x-axis)
- C3+C4 mu-band power sum → UD control signal (y-axis)
- Each axis runs through its own independent transfer function with separate R values
- pyqtgraph ScatterPlotItem or a custom QWidget paintEvent for cursor rendering — both are sufficient; QWidget paintEvent gives more control over appearance

**For signal quality visualization:**
- Color-coded QLabel or custom QWidget with colored circle indicators (green/yellow/red)
- SNR threshold: >10 dB = green, 5-10 dB = yellow, <5 dB = red
- Flatline detection: std(last 1s window) < 0.5 µV → red
- Spike detection: |sample - rolling_mean| > 100 µV → flag that sample

---

## Version Compatibility

| Package A | Compatible With | Notes |
|-----------|-----------------|-------|
| scikit-learn 1.8.0 | numpy 2.4.2 | Verified: sklearn 1.8 supports numpy 2.x |
| pyRiemann 0.10 | scikit-learn 1.8.0, numpy 2.x | v0.10 released January 2026; requires sklearn ≥ 1.0 and numpy ≥ 1.23. Compatible with current stack. |
| mne.decoding.CSP 1.11.0 | scikit-learn 1.8.0 | MNE's decoding module uses sklearn estimator API — compatible across sklearn 1.x |
| scipy 1.17.0 sosfilt | numpy 2.4.2 | No known incompatibilities. sosfilt is a pure C extension with stable ABI. |

---

## Sources

- [mne.decoding.CSP — MNE 1.11.0](https://mne.tools/stable/generated/mne.decoding.CSP.html) — CSP API, fit/transform, sklearn compatibility — HIGH confidence
- [Motor imagery decoding CSP example — MNE 1.11.0](https://mne.tools/stable/auto_examples/decoding/decoding_csp_eeg.html) — CSP+LDA Pipeline pattern — HIGH confidence
- [scipy.signal.sosfilt — SciPy v1.17.0](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.sosfilt.html) — stateful real-time filtering, SOS form recommendation — HIGH confidence
- [scipy.signal.sosfilt_zi — SciPy v1.17.0](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.sosfilt_zi.html) — initial condition computation for stateful filtering — HIGH confidence
- [LinearDiscriminantAnalysis — scikit-learn 1.8.0](https://scikit-learn.org/stable/modules/generated/sklearn.discriminant_analysis.LinearDiscriminantAnalysis.html) — shrinkage, solver options, predict_proba — HIGH confidence
- [Add partial_fit to LDA — sklearn issue #30042](https://github.com/scikit-learn/scikit-learn/issues/30042) — confirmed partial_fit absent as of 2026 — HIGH confidence
- [pyriemann — PyPI](https://pypi.org/project/pyriemann/) — v0.10 release date, dependency requirements — MEDIUM confidence
- [pyRiemann GitHub](https://github.com/pyRiemann/pyRiemann) — MDM classifier, covariance estimation — MEDIUM confidence
- [real-time-iir-filter — GitHub](https://github.com/what-in-the-nim/real-time-iir-filter) — sosfilt multichannel stateful pattern — MEDIUM confidence
- [scipy ENH issue #21644](https://github.com/scipy/scipy/issues/21644) — multichannel sosfilt zi usability note — MEDIUM confidence

---

*Stack research for: BCI signal processing and motor imagery decoding milestone*
*Researched: 2026-03-11*
