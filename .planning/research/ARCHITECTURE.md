# Architecture Research

**Domain:** Real-time EEG-based BCI motor imagery platform (PyQt6 desktop)
**Researched:** 2026-03-11
**Confidence:** HIGH (pipeline stages), MEDIUM (specific Qt threading patterns), HIGH (signal processing boundaries)

## Standard Architecture

### System Overview

A BCI motor imagery pipeline has five canonical layers. All of them must exist in the final system, but the existing codebase already implements Acquisition and partial Signal Processing. New work adds a formalized Pipeline, Decoder, and Task layers that sit between the raw signal and the user-facing UI.

```
┌──────────────────────────────────────────────────────────────────┐
│                        UI / Task Layer                           │
│  ┌───────────────┐  ┌────────────────┐  ┌──────────────────┐    │
│  │  SegmentViewer │  │ MotorImagery   │  │  Signal Quality  │    │
│  │  (main window) │  │ TaskWindow     │  │  Indicators      │    │
│  └───────┬───────┘  └───────┬────────┘  └────────┬─────────┘    │
├──────────┼───────────────────┼────────────────────┼─────────────┤
│                     Decoder / Control Layer                      │
│  ┌────────────────────────────────────────────────────────┐      │
│  │  BandPowerExtractor → LRSignal → UDSignal →            │      │
│  │  TransferFunction → CursorPosition                     │      │
│  └────────────────────────────┬───────────────────────────┘      │
├───────────────────────────────┼──────────────────────────────────┤
│                  Signal Processing Pipeline Layer                │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────────────┐  │
│  │ Bandpass │→ │  Notch   │→ │ Spatial  │→ │ QualityMonitor │  │
│  │  Filter  │  │  Filter  │  │  Filter  │  │ (SNR/flatline) │  │
│  └──────────┘  └──────────┘  │(CAR/CSP) │  └────────────────┘  │
│                               └──────────┘                       │
├──────────────────────────────────────────────────────────────────┤
│                     Data Acquisition Layer                       │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────┐   │
│  │  BrainFlow Board │  │  LSL Outlet/     │  │ XDFRecorder  │   │
│  │  (BoardShim)     │  │  Marker Outlet   │  │              │   │
│  └──────────────────┘  └──────────────────┘  └──────────────┘   │
└──────────────────────────────────────────────────────────────────┘
```

The pipeline direction is always: Hardware → Acquisition → Signal Processing Pipeline → Decoder → UI.
Feedback from Decoder back to UI (cursor position, certainty bar) is the only upward data path.

### Component Responsibilities

| Component | Responsibility | Notes |
|-----------|---------------|-------|
| `BrainFlow BoardShim` | Hardware abstraction, raw sample delivery | Existing; device-agnostic via board ID |
| `LSL Outlets` | Network broadcast of EEG + markers | Existing; used by XDFRecorder and external tools |
| `XDFRecorder` | Buffered XDF 1.0 file writing | Existing; push-based, no round-trip via LSL inlet |
| `FilterPipeline` | Sequential bandpass → notch → spatial filter chain with per-channel `zi` state | New component; replaces inline filter calls in `update_plot()` |
| `SignalQualityMonitor` | SNR measurement, flatline detection, spike detection, impedance estimation | New component; reads same filtered or raw samples as pipeline |
| `BandPowerExtractor` | Sliding-window mu-band (8-13 Hz) power per channel | New component; consumes FilterPipeline output |
| `ControlSignalComputer` | C4-C3 difference (LR), C3+C4 sum (UD), z-score normalization vs. baseline | New component; converts band power to dimensionless control values |
| `TransferFunction` | Nonlinear mapping: dead zone → quadratic region → saturation. Subject-specific R weighting | New component; pure function, no state except R and baseline SD |
| `MotorImageryTaskWindow` | Native PyQt6 stimulus display (REST/LEFT/RIGHT/UP/DOWN), state machine, cue rendering | Replaces existing QWebEngineView task |
| `TaskBridge` | Connects task state machine to XDFRecorder and LSL marker outlet | Existing `TaskWebBridge`; adapt for native task |
| `CursorWidget` | 2D cursor rendering, target zones, trial feedback | New widget; owned by MotorImageryTaskWindow |
| `FeedbackBar` | 1D certainty bar during online training (left/right bias) | New widget; owned by MotorImageryTaskWindow |
| `SignalQualityIndicator` | Color-coded per-channel dot/LED in main GUI | New widget in SegmentViewer |

## Recommended Project Structure

```
GUI.py                        # Main window — no structural change
processing/
├── __init__.py
├── pipeline.py               # FilterPipeline: bandpass → notch → spatial, per-channel zi
├── spatial.py                # CAR, Laplacian, CSP implementations
├── quality.py                # SignalQualityMonitor: SNR, flatline, spike, impedance
├── band_power.py             # BandPowerExtractor: sliding-window FFT or Welch
└── decoder.py                # ControlSignalComputer + TransferFunction
tasks/
├── motor_imagery/            # Existing web task (kept for compatibility)
│   ├── index.html
│   ├── app.js
│   └── styles.css
└── mi_task_window.py         # New native PyQt6 task window
    # Contains: MotorImageryTaskWindow, CursorWidget, FeedbackBar, state machine
widgets/
└── signal_quality_indicator.py  # Color-coded channel quality dots for SegmentViewer
```

### Structure Rationale

- **processing/:** Isolated from Qt — pure numpy/scipy computation. This makes it testable without a display and reusable across task windows. Each file maps to one pipeline stage so phases can be built and tested independently.
- **tasks/mi_task_window.py:** One file owns the entire task UI. The state machine, cursor, and feedback bar are tightly coupled — separating them would only add indirection without benefit at this scale.
- **widgets/:** Small standalone Qt widgets that SegmentViewer embeds. Kept separate so they don't bloat GUI.py.

## Architectural Patterns

### Pattern 1: Staged Pipeline with Persistent Filter State

**What:** Each filter stage maintains a `zi` (initial conditions) array per channel. On every sample chunk, the stage calls `scipy.signal.sosfilt(sos, chunk, zi=zi, axis=-1)` and stores the returned updated `zi` for the next call.

**When to use:** Any filter that must operate continuously across chunk boundaries without phase discontinuities. Required for bandpass and notch stages. CSP/CAR are stateless matrix multiplications — they do not need `zi`.

**Trade-offs:** `zi` arrays are ~(n_sections, n_channels, 2) floats — negligible memory. Resetting `zi` on reconnect or parameter change prevents transient artifacts.

**Example:**
```python
class BandpassStage:
    def __init__(self, low, high, fs, order=4):
        self.sos = butter(order, [low, high], btype='band', fs=fs, output='sos')
        self.zi = None  # initialized on first chunk

    def process(self, chunk: np.ndarray) -> np.ndarray:
        # chunk shape: (n_channels, n_samples)
        if self.zi is None:
            zi_single = sosfilt_zi(self.sos)  # (n_sections, 2)
            self.zi = np.stack([zi_single] * chunk.shape[0], axis=1)
        out, self.zi = sosfilt(self.sos, chunk, zi=self.zi, axis=-1)
        return out
```

### Pattern 2: Timer-Driven Processing on the Qt Main Thread (Pull Model)

**What:** A `QTimer` fires at the streaming update rate (~50 ms). The callback pulls the latest samples from the BrainFlow board, runs them through the FilterPipeline, and dispatches results to the Decoder and Visualization. No background thread for the processing chain itself.

**When to use:** BrainFlow's `board.get_board_data()` is already thread-safe. The filter pipeline is fast enough (scipy sos on 50ms chunk at 256 Hz is <1ms). Running everything on the Qt main thread avoids mutex complexity and Qt's prohibition on touching widgets from background threads.

**Trade-offs:** If the pipeline stalls (bug, heavy CSP recompute), it blocks the UI. Mitigated by: (a) CSP recompute happens on demand, not in the timer callback; (b) processing is provably <5 ms at 256 Hz / 50ms chunk.

**Example:**
```python
# In SegmentViewer, existing timer callback:
def _streaming_timer_tick(self):
    data = self.board.get_board_data()          # pull from BrainFlow ring buffer
    filtered = self.filter_pipeline.process(data)  # bandpass → notch → spatial
    quality = self.quality_monitor.update(filtered)
    self.update_plot(filtered)
    if self.decoder_active:
        control = self.decoder.compute(filtered)
        self.task_window.update_cursor(control)
```

### Pattern 3: Offline/Online Mode Switch

**What:** The processing module maintains two operational modes. In **offline mode**, it processes a fixed numpy array (loaded XDF/GDF file) in one pass — `filtfilt` for zero-phase filtering is preferred. In **online mode**, it uses `sosfilt` with persistent `zi` for causal real-time filtering.

**When to use:** Always. The same `FilterPipeline` class handles both modes with a `mode` flag. CSP matrices are always trained offline on labeled epochs, then applied online as a fixed spatial filter.

**Trade-offs:** `filtfilt` is non-causal and cannot be used online. Online-trained CSP (adapting in real-time) is a research topic — for this platform, CSP is trained once per session from offline data, then frozen.

## Data Flow

### Raw EEG → Cursor Position

```
BrainFlow board.get_board_data()
    ↓ (n_channels × n_samples numpy array)
FilterPipeline.process(chunk)
    ├── BandpassStage (8-13 Hz for mu, or 8-30 Hz wideband)
    ├── NotchStage (50/60 Hz)
    └── SpatialFilterStage (CAR or CSP matrix multiply)
    ↓ (same shape, filtered)
BandPowerExtractor.update(filtered_chunk)
    ↓ (n_channels float, band power per channel)
ControlSignalComputer.compute(band_power)
    ├── LR = band_power[C4] - band_power[C3]  (normalized by baseline SD)
    └── UD = band_power[C3] + band_power[C4]  (normalized by baseline SD)
    ↓ (lr: float, ud: float, both dimensionless z-scores)
TransferFunction.apply(lr, ud)
    ├── dead zone: |x| ≤ 0.05 → 0
    ├── quadratic: 0.05 < |x| < 1 → 0.1(Rx²) + 3e-1·Rx + 2.25e-7
    └── saturation: |x| ≥ 1 → ±0.9009
    ↓ (cursor_dx: float, cursor_dy: float, range [-1, +1])
CursorWidget.move(cursor_dx, cursor_dy)
    ↓ (pixel position on screen)
```

### Task State Machine → Marker Flow

```
MotorImageryTaskWindow state machine
    ├── REST (4s) → emits marker {"stop": prev, "start": "REST"}
    ├── LEFT (4s) → emits marker {"stop": "REST", "start": "LEFT"}
    └── RIGHT (4s) → emits marker {"stop": "LEFT", "start": "RIGHT"}
    ↓ (Python signal / slot, same thread)
TaskBridge.send_marker(json_str)
    ├── XDFRecorder.push_marker(timestamp, text)
    └── LSL MarkerOutlet.push_sample([text])
```

### Signal Quality → UI Indicators

```
SignalQualityMonitor.update(chunk)
    ├── SNR per channel (ratio of band power to broadband power)
    ├── flatline detection (std < threshold over sliding window)
    ├── spike detection (amplitude > N * rolling_std)
    └── impedance estimate (1/sqrt(broadband_power) heuristic)
    ↓ (dict: channel → {snr, flatline, spike, quality_level})
SignalQualityIndicator widgets (one per channel in SegmentViewer)
    ↓ color update: GREEN (good) / YELLOW (marginal) / RED (bad)
```

### CSP Training Flow (Offline)

```
User loads labeled XDF file (LEFT/RIGHT markers present)
    ↓
Epoch extraction: slice ±1s around each marker
    ↓
Offline FilterPipeline.process_offline(epochs)  [filtfilt, causal=False]
    ↓
CSP.fit(left_epochs, right_epochs)
    → eigenvector decomposition, select top-k filters
    → store W matrix (n_filters × n_channels)
    ↓
User clicks "Apply CSP" → SpatialFilterStage.set_weights(W)
    → subsequent online chunks multiplied by W
```

## Integration Points

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| `BrainFlow → FilterPipeline` | Direct numpy array pass in timer callback | No queue needed; timer period matches data availability |
| `FilterPipeline → BandPowerExtractor` | Direct numpy array pass | BandPowerExtractor maintains its own sliding window internally |
| `BandPowerExtractor → ControlSignalComputer` | Float array (one value per channel) | Called every timer tick; lightweight |
| `ControlSignalComputer → TransferFunction` | Two floats (lr, ud) | Pure function; no shared state |
| `TransferFunction → CursorWidget` | PyQt signal `cursor_moved(float, float)` | Keeps decoder layer decoupled from Qt widget |
| `FilterPipeline → SignalQualityMonitor` | Direct numpy array pass (same chunk) | Quality monitor runs in parallel to decoder in same timer tick |
| `SignalQualityMonitor → SignalQualityIndicator` | PyQt signal `quality_updated(dict)` | Qt signal ensures thread-safety if quality ever moved to background thread |
| `TaskStateM achine → TaskBridge` | Direct Python method call (same thread) | No async needed; markers are timestamped at call time |
| `TaskBridge → XDFRecorder` | Direct method call `push_marker()` | Existing pattern; unchanged |

### External Integrations

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| BrainFlow | `board.get_board_data()` pull in timer | Existing; board runs own background thread internally |
| LSL (pylsl) | Push-based outlet; no inlet in main pipeline | Existing pattern; decoder does not consume from LSL |
| XDF files (offline) | `pyxdf.load_xdf()` → numpy array | Existing; offline CSP training reads these |

## Anti-Patterns

### Anti-Pattern 1: Running scipy filters in a background thread

**What people do:** Move the filter pipeline to a `QThread` to "avoid blocking the UI."

**Why it's wrong:** At 256 Hz with 50ms chunks, the entire filter chain (bandpass + notch + CAR) takes <1ms. The overhead of thread synchronization, data copying across thread boundaries, and Qt signal marshaling would exceed the processing time itself. It also requires thread-safe access to `zi` state. The existing codebase uses a timer-callback pull model which is correct here.

**Do this instead:** Keep FilterPipeline on the Qt main thread. Profile first. Only offload if measured latency exceeds 10ms per tick.

### Anti-Pattern 2: Recomputing scipy filter coefficients on every chunk

**What people do:** Call `butter()` or `iirnotch()` inside the timer callback to "stay flexible."

**Why it's wrong:** Filter design (coefficient computation) is ~10-100x more expensive than applying the filter. At 50ms ticks this causes measurable jitter.

**Do this instead:** Compute `sos` once at construction or when the user changes filter parameters. Store `sos` on the stage object. Recompute only when `fs`, `low`, `high`, or `order` change — and reset `zi` when you do.

### Anti-Pattern 3: Using filtfilt in online streaming mode

**What people do:** Use `filtfilt` everywhere because it's "zero-phase" and "better."

**Why it's wrong:** `filtfilt` is non-causal — it requires the full signal to be available before filtering. It cannot be applied to a live stream chunk by chunk. It also resets filter state to zero each call, producing edge artifacts if called on consecutive chunks.

**Do this instead:** Use `sosfilt` with persistent `zi` for all online processing. Reserve `filtfilt` for offline file-mode processing where the full recording is in memory.

### Anti-Pattern 4: Hardcoding C3/C4 channel indices

**What people do:** Index directly — `band_power[3]` for C3, `band_power[5]` for C4 — based on a specific board's layout.

**Why it's wrong:** Different BrainFlow board IDs return channels in different orders. OpenBCI Cyton 8-channel and Neurable layouts differ. A hardcoded index silently uses the wrong channel on a different device.

**Do this instead:** Store user-configured channel names → index mapping. Let the user select "C3 channel" and "C4 channel" in settings. `ControlSignalComputer` receives the indices at construction.

### Anti-Pattern 5: Blocking the UI during CSP training

**What people do:** Call `CSP.fit()` synchronously when the user clicks "Train CSP."

**Why it's wrong:** CSP eigendecomposition on a full recording (~minutes of data) can take 2-10 seconds. This freezes the entire PyQt6 UI.

**Do this instead:** Run `CSP.fit()` in a `QThread` worker. Emit a `training_complete(W_matrix)` signal when done. SegmentViewer receives it and calls `SpatialFilterStage.set_weights(W)` on the main thread.

## Build Order Implications

The component dependency graph dictates this build order:

1. **FilterPipeline** (bandpass + notch stages only, no spatial) — everything downstream depends on it. No external dependencies beyond scipy. Testable with synthetic sinusoids.

2. **SignalQualityMonitor + SignalQualityIndicator** — depends only on FilterPipeline output. Gives researchers immediate signal feedback during development. No decoder required.

3. **SpatialFilterStage (CAR)** — extends FilterPipeline. CAR is a fixed matrix; no training required. Immediately improves signal quality for downstream stages.

4. **BandPowerExtractor + ControlSignalComputer** — depends on FilterPipeline with spatial filter. Produces the LR/UD scalars that feed the cursor.

5. **TransferFunction** — pure function, no dependencies. Can be implemented and unit-tested in isolation.

6. **MotorImageryTaskWindow (1D LR, native PyQt6)** — depends on TransferFunction + ControlSignalComputer. State machine, cue display, XDF marker integration. First end-to-end test of full pipeline.

7. **CursorWidget + 2D decoder (UD + combined)** — extends 1D task. Requires BandPowerExtractor to return both C3 and C4.

8. **CSP training flow** — depends on FilterPipeline (offline mode), XDF file loading (existing). Can be added after 1D task is validated.

9. **FeedbackBar (certainty display)** — UI addition to MotorImageryTaskWindow. Depends on decoder producing a confidence scalar, which requires CSP or a trained classifier.

## Sources

- BCI-HIL open-source framework paper (PMC10335802): modular pipeline with LSL, Timeflux, DAG scheduling — [link](https://pmc.ncbi.nlm.nih.gov/articles/PMC10335802/)
- Cybathlon 2024 BCI pipeline paper (arxiv 2511.23384): four-module architecture, 117ms median latency, parallel execution rationale — [link](https://arxiv.org/html/2511.23384v3)
- Frontiers 2D cursor stLSTM paper (fncom 799019): band power extraction, LR/UD decoupling, velocity-constrained decoder — [link](https://www.frontiersin.org/journals/computational-neuroscience/articles/10.3389/fncom.2022.799019/full)
- scipy sosfilt documentation: zi state management for chunk-based processing — [link](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.sosfilt.html)
- MNE-Python CSP example: offline CSP training and feature extraction pattern — [link](https://mne.tools/stable/auto_examples/decoding/decoding_csp_eeg.html)
- EEG-based BCI techniques review (PMC6471241): ERD/ERS neurophysiology, mu-band spatial distribution — [link](https://pmc.ncbi.nlm.nih.gov/articles/PMC6471241/)

---
*Architecture research for: BCI Motor Imagery Platform (Longhorn Neural Interface)*
*Researched: 2026-03-11*
