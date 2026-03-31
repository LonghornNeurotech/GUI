# Pitfalls Research

**Domain:** Real-time BCI motor imagery platform — EEG signal processing, CSP spatial filters, nonlinear transfer functions, online decoding
**Researched:** 2026-03-11
**Confidence:** HIGH (signal processing pitfalls well-documented in peer-reviewed literature; GUI-specific pitfalls verified against existing codebase)

---

## Critical Pitfalls

### Pitfall 1: CSP Overfitting on Small Trial Counts

**What goes wrong:**
CSP spatial filters trained on fewer than ~40 trials per class produce components that capture noise rather than sensorimotor ERD/ERS. The filters look correct on the training set but generalize poorly to subsequent runs. Offline accuracy appears high (70-85%), online accuracy collapses to near-chance.

**Why it happens:**
CSP solves a joint diagonalization problem on the sample covariance matrices of each class. With small N, the sample covariance is a poor estimate of the true covariance — small eigenvalue components get amplified and fit session-specific noise. This effect worsens as channel count increases: a 16-channel array with 20 trials per class almost guarantees overfit filters.

**How to avoid:**
- Require a minimum of 40-60 trials per class before fitting CSP (enforce programmatically, not just by recommendation)
- Apply Tikhonov/ledoit-wolf regularization to the covariance estimates: `cov = (1-alpha)*sample_cov + alpha*np.eye(n_ch)*np.trace(sample_cov)/n_ch`
- Select only 2-4 CSP component pairs (not all N) to reduce variance of the estimate
- Validate by holding out the last 20% of trials and checking that spatial patterns (scalp topographies) are physiologically plausible — C3/C4 lateralization, not edge-channel dominance

**Warning signs:**
- CSP component topographies show maximum weights on peripheral/frontal channels rather than central electrodes
- Cross-validated offline accuracy is >90% but online performance immediately drops
- Adding more training trials does not stabilize performance

**Phase to address:** Signal Processing Pipeline phase (when CSP fitting is first implemented); also enforce in Training Protocol phase when session structure is defined.

---

### Pitfall 2: EMG Contamination Mistaken for Mu-Band ERD

**What goes wrong:**
Scalp EMG from jaw clenching, neck tension, or subtle facial movement produces broadband artifacts (20-500 Hz) with significant power in the 8-30 Hz range. The classifier learns to decode muscle tension rather than sensorimotor imagery. The system appears to work well but is controlling via EMG, not EEG. Performance degrades dramatically when the subject relaxes properly.

**Why it happens:**
The mu band (8-13 Hz) and low beta (13-20 Hz) overlap spectrally with EMG harmonics. EMG contamination is correlated with task trials — subjects tense slightly during LEFT/RIGHT cues — making it indistinguishable from genuine ERD in a naive decoder. EMG has high SNR relative to EEG, so classifiers readily exploit it.

**How to avoid:**
- Inspect channel topographies during training: genuine mu-ERD has a central (C3/C4) distribution; EMG artifacts peak at temporal/frontal electrodes
- Add explicit task instruction: no jaw clenching, no swallowing, completely relaxed neck/shoulders during imagery trials
- Include a Laplacian spatial filter (C3 minus average of neighbors) to emphasize focal cortical sources over diffuse muscle noise
- During signal validation, plot the >40 Hz power alongside the 8-13 Hz band — if they track together, EMG is the source
- For C3/C4 channels specifically: verify that mu power during REST is higher than during imagery (ERD means power decreases; EMG artifacts during movement would increase power in both bands simultaneously)

**Warning signs:**
- Decoder accuracy is very high from the first session (genuine MI rarely exceeds 75-80% in naïve subjects)
- Channel importance maps show temporal electrodes (T7/T8) dominating rather than C3/C4
- Subject reports they are "tensing" to produce control signals
- Removing bandpass floor from 8 Hz to 30 Hz (i.e., looking at 30-100 Hz power) shows task-correlated bursts

**Phase to address:** Signal Validation phase (build EMG detection into quality indicators); Task Design phase (provide subject instructions in GUI).

---

### Pitfall 3: IIR Filter Applied Per-Epoch Rather Than Continuously to Live Stream

**What goes wrong:**
When the feature extraction window (e.g., 1-second epoch for band power) is extracted from the buffer and re-filtered independently each time, each epoch sees the IIR filter's startup transient. The first 100-200 ms of every epoch has distorted amplitude and phase, corrupting exactly the post-cue onset period that carries the most ERD information. This also resets the filter state on every call, so adjacent epochs are inconsistent.

**Why it happens:**
It is natural to write `butter_bandpass_filter(epoch_data)` as a standalone function. The existing `process_signal()` in `GUI.py` correctly uses persistent `lfilter_zi` states for visualization, but the new feature extraction path — which runs on a separate buffer slice for decoding — may inadvertently create fresh filter state per call.

**How to avoid:**
- Use the already-implemented stateful filter chain (`bandpass_zi`, `notch_zi` per channel) as the single processing path
- Feature extraction must read from `stream_buffer` (already filtered), never re-filter a buffer slice
- For the mu-band power feature specifically: maintain a dedicated 8-13 Hz bandpass filter with persistent state per channel, updated on every incoming chunk, not per decode call
- If a second filter chain is needed for mu/beta extraction, initialize it at stream start and keep its state across the entire session

**Warning signs:**
- Band power plots show a spike artifact at the beginning of each 1-second analysis window
- Baseline power computed during REST trials varies erratically across consecutive trials
- Filter coefficients are recomputed inside the feature extraction function on each call

**Phase to address:** Signal Processing Pipeline phase (architecture design of filter chain); must be explicitly validated in Feature Extraction phase.

---

### Pitfall 4: Baseline Normalization Using a Fixed Pre-Session Scalar

**What goes wrong:**
Band power values vary enormously across sessions, days, and electrode impedances. A fixed normalization constant computed at session start becomes stale within minutes as EEG amplitude drifts due to electrode settling, subject fatigue, and impedance changes. The LR control signal (C4-C3 difference in mu power) wanders away from zero baseline, so the dead zone no longer captures actual rest, and the cursor drifts in one direction continuously.

**Why it happens:**
Baseline normalization is typically computed as a single offline step. When ported to real-time, developers compute a 10-second baseline at session start and use those statistics for the entire session. EEG alpha/mu amplitude can shift 20-50% within a 20-minute session.

**How to avoid:**
- Use a sliding baseline: compute the running mean and standard deviation of band power over the last 30-60 seconds of REST-period data specifically (not all data, which includes active imagery)
- The z-score formula `(power - mu_rest) / sigma_rest` should use REST-period samples accumulated in a circular buffer
- Provide a "Re-baseline" button in the UI that resets the running statistics without stopping the session
- Log the raw (unnormalized) band power values alongside the normalized signal so drift can be detected in post-session review

**Warning signs:**
- Cursor rests at a non-center position when the subject is relaxed and attempting neutral imagery
- Control signal slowly drifts in one direction over a 10-minute session
- Subject reports needing to "fight" to return cursor to center position

**Phase to address:** Feature Extraction / Decoding phase (design normalized feature pipeline); also relevant to Transfer Function phase where the dead zone threshold is calibrated.

---

### Pitfall 5: Nonlinear Transfer Function Parameters Not Subject-Calibrated

**What goes wrong:**
The published transfer function (dead zone 0.05 SD, R weighting 3-3.5 for LR, saturation at ±0.9009) was derived for a specific population and device setup. Applying these parameters universally produces one of two failure modes: (a) too-large dead zone — subject cannot move cursor at all because all signals fall within the dead zone; (b) too-small dead zone — cursor is jittery at rest because noise exceeds the threshold. The R weighting factor compounds this: wrong R causes the quadratic region to feel either unresponsive or explosive.

**Why it happens:**
Published BCI papers report optimal parameters for their specific population, electrode system, and preprocessing chain. The parameters are not universal constants. They are tuning knobs that must be fit to each subject's signal distribution.

**How to avoid:**
- Expose dead zone threshold, R weighting, and saturation as per-subject configurable parameters (not hardcoded constants)
- Add a calibration step that estimates the subject's resting signal standard deviation over 30-60 seconds and sets the dead zone to a fixed fraction (e.g., 10-15% of that SD)
- Show the real-time control signal value alongside the transfer function visualization during calibration so the researcher can tune R interactively
- Store per-subject calibration parameters in a config file keyed to subject ID

**Warning signs:**
- Subject's cursor never moves despite clear task engagement
- Cursor is continuously drifting even when subject is at rest with eyes closed
- Subject reports the control is "all or nothing" with no fine-grained intermediate positions

**Phase to address:** Transfer Function & Cursor Control phase.

---

### Pitfall 6: Offline-to-Online Performance Gap from Calibration Session Mismatch

**What goes wrong:**
The CSP filter and LDA/threshold classifier are trained on clean calibration recordings where the subject is well-rested and knows exactly what to do. Online sessions occur later, with different electrode impedances, subject fatigue, and — critically — slightly different EEG distributions because the subject is now receiving real-time feedback and cognitively co-adapting. Accuracy that was 80% offline drops to 55-65% online.

**Why it happens:**
The calibration-to-control distributional shift is a well-documented phenomenon. Movement Related Cortical Potentials and ERD patterns measurably change between calibration (no feedback) and online control (feedback present, higher cognitive load, co-adaptation). The filter trained on calibration data is a mismatch for online data.

**How to avoid:**
- Include at least one "online with feedback" calibration block where the decoded signal is shown but the cursor does not move — this conditions the subject's imagery strategy to the feedback context before the model is trained
- Implement adaptive normalization (the sliding baseline described in Pitfall 4) which partially compensates for session drift
- Do not assume calibration accuracy predicts online accuracy; set realistic expectations in the GUI (e.g., "Calibration accuracy is an upper bound, expect 10-20% reduction online")
- Plan for a brief recalibration within long sessions (after 20-30 minutes) as EEG drifts

**Warning signs:**
- Offline cross-validation shows >80% accuracy but first online run is chaotic
- Subject's scalp ERD patterns (visible in real-time band power) look different from training session patterns
- Session-to-session variability is greater than trial-to-trial variability within a session

**Phase to address:** Training Protocol Design phase; also a key consideration for the Decoding phase architecture.

---

### Pitfall 7: CAR Contamination from a Bad Channel

**What goes wrong:**
Common Average Reference (CAR) subtracts the mean of all channels from each channel. If one electrode has artifactual noise (high impedance, loose contact, muscle artifact), that artifact gets distributed to every other channel after CAR. A single bad C1 electrode can inject a 50 Hz artifact into C3 and C4, corrupting exactly the channels used for motor imagery decoding.

**Why it happens:**
CAR is often applied as a blanket preprocessing step because it is simple and reduces common-mode noise. The requirement to exclude bad channels before applying CAR is understood in the literature but frequently overlooked in implementation.

**How to avoid:**
- Implement channel quality gating before CAR: exclude any channel whose variance exceeds 5x the median channel variance, or whose 50-60 Hz power exceeds a threshold, from the reference average
- Show per-channel signal quality indicators prominently in the GUI (planned feature) so the researcher can identify bad channels before starting a task
- Consider the small Laplacian filter as a safer default for C3/C4: it uses only the 4 neighboring channels, so one bad peripheral channel cannot corrupt the motor channels
- Validate CAR output: after applying CAR, the mean across all channels should be near zero; if it is not, a bad channel is dominating

**Warning signs:**
- After applying CAR, previously clean channels suddenly show correlated artifacts
- Signal quality indicator for one channel shows red/high noise, but CAR is still active
- Band power at C3/C4 spikes coincidentally with artifacts visible at distant channels (FP1/FP2, temporal)

**Phase to address:** Signal Processing Pipeline phase (spatial filter architecture); Signal Validation phase (bad-channel detection must feed into CAR exclusion logic).

---

### Pitfall 8: Qt Main Thread Blocking from Synchronous DSP in the Update Loop

**What goes wrong:**
The existing `update_stream()` is called on the main thread via `QTimer`. For the current visualization-only workload this is acceptable. Adding CSP projection, Welch PSD for 16 channels, and a nonlinear decode step into the same callback will periodically block the Qt event loop for 15-50 ms, causing the UI to stutter, drop LSL samples from the inlet buffer, and corrupt the XDF recording timeline.

**Why it happens:**
`lfilter` on 16 channels at 200 Hz is fast, but Welch PSD (`sp_signal.welch`) with a 2-second window and overlapping segments is O(N log N) per channel. At 16 channels it takes 5-15 ms per call. CSP projection (matrix multiply) is fast, but computing it alongside Welch every timer tick will exceed the 30 ms timer budget under load.

**How to avoid:**
- Keep the main timer callback lightweight: buffer incoming samples only, no PSD
- Move Welch PSD, CSP projection, and decode steps to a `QThread` worker that communicates results back via `pyqtSignal`
- The decode worker should run at a fixed decode rate (e.g., 10 Hz) independent of the 30 ms acquisition timer
- Protect the shared stream buffer with a `threading.Lock` or copy the relevant window into the worker before processing
- Python's GIL means QThread workers still contend for the interpreter; use `numpy` operations (which release the GIL during C-level computation) to maximize parallelism

**Warning signs:**
- Qt UI becomes sluggish (>100 ms response to mouse clicks) when streaming with decoding active
- XDF timestamps show irregular gaps (not uniform 5 ms spacing) during active decode sessions
- LSL inlet buffer overflows (BrainFlow logs warnings about dropped samples)

**Phase to address:** Signal Processing Pipeline phase (architecture decision on threading); this must be decided before any DSP code is added to the main timer loop.

---

### Pitfall 9: Session Fatigue Degrading Signal Quality Mid-Task

**What goes wrong:**
Motor imagery is cognitively demanding. After 20+ minutes of continuous imagery trials, mu-band ERD diminishes, theta power increases (frontal fatigue signature), and classification accuracy declines. If the GUI does not enforce rest breaks, subjects complete the session in degraded state, collected data is low quality, and online performance drops. Because the system shows real-time feedback, subjects may incorrectly attribute classifier failure to their own inability rather than fatigue.

**Why it happens:**
Lab protocols from publications describe inter-trial rest periods and session length limits, but these are often not enforced by the software. A researcher running a subject for the first time has no baseline to recognize when fatigue is affecting the signal.

**How to avoid:**
- Hard-code minimum inter-trial rest intervals in the task state machine (REST period is already 4 seconds — do not allow this to be shortened below 3 seconds)
- Implement automatic session length warnings after 20 minutes of active task time (not wall clock time)
- Display a "signal quality trend" indicator: if average band power variance across the last 5 trials is increasing, flag a recommended rest break
- The mindfulness/calibration period (60s) at the start of each task block exists for this reason — do not make it skippable

**Warning signs:**
- Real-time band power display shows high theta (4-8 Hz) relative to alpha/mu over the session
- Trial-to-trial variance in the control signal increases over time (visible in session log)
- Subject reports difficulty maintaining clear mental imagery

**Phase to address:** Task Design / Motor Imagery Task phase.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Hardcode C3/C4 channel indices for a specific board | Faster initial implementation | Breaks device-agnostic design; every new device requires code change | Never — PROJECT.md explicitly requires configurability |
| Re-filter buffer slice per decode call instead of maintaining persistent filter state | Simpler function signature | Epoch-boundary transients corrupt every feature window | Never — persistent state already exists in codebase |
| Compute Welch PSD on main Qt timer thread | No threading complexity | UI stutter, dropped LSL samples under load | Only acceptable for visualization (already done); unacceptable for decode path |
| Skip bad-channel detection before applying CAR | Less UI complexity | CAR artifact spreading makes C3/C4 unusable | Only acceptable during offline file playback (no consequences), not during live sessions |
| Single fixed baseline scalar from session start | Simple normalization | Cursor drift within 10 minutes | Acceptable for very short demos (<5 min); unacceptable for full training sessions |
| Fix CSP R weighting at published values (3.0 for LR, 0.45 for UD) | No calibration step needed | Unusable for subjects whose signal distribution differs from publication cohort | Acceptable as default starting point only; must expose as tunable parameter |

---

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| LSL inlet → filter pipeline | Calling `lfilter` with fresh `zi=None` on each chunk | Initialize `zi` from `lfilter_zi` at stream start; persist across chunks (already done for viz, replicate for decode path) |
| CAR spatial filter → CSP | Applying CAR after CSP projection | CAR must come first in the pipeline: raw → bandpass → notch → CAR → CSP → band power → decode |
| Welch PSD → sliding baseline | Computing baseline from all samples including active imagery | Maintain a separate circular buffer of REST-period samples only; update baseline only when state machine is in REST |
| CSP filter → new session | Reusing CSP weights from a previous session without re-checking validity | Always retrain or validate CSP on the current session's calibration data; inter-session EEG shifts make stale filters unreliable |
| PyQt6 QTimer (main thread) → decode result | Emitting decoded cursor position from worker without queuing | Use `pyqtSignal` to post results back to main thread; never call Qt widget methods from a background thread |
| XDF recorder → marker pipeline | Adding a CSP decode marker into the XDF stream before confirming recorder is ready | Reuse existing `_pending_markers` buffer pattern for all new marker types |

---

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Welch PSD on 16 channels every 30 ms | UI stutter; LSL inlet buffer overflow | Run Welch in a QThread at 10 Hz decode rate; share only the computed band power values with main thread | At >8 channels with a 2-second window |
| Recomputing CSP covariance matrix per epoch | High CPU usage; decode latency >50 ms | CSP is trained once per calibration block; online use is matrix multiply only (fast) | Every call if matrix is not cached |
| `scipy.signal.welch` with `nperseg` set to full buffer length | Memory allocation on every call; GC pressure | Pin `nperseg` to a fixed power-of-2 (e.g., 256 samples at 250 Hz = ~1 second resolution) | When buffer grows large (>2s at 250 Hz) |
| `np.copy()` of entire stream buffer for every decode | Memory bandwidth bottleneck | Copy only the analysis window (last 1-2 seconds), not the full rolling buffer | When buffer is >5 seconds at 250 Hz |
| Band power smoothing EMA on main thread + plot update every frame | Redundant computation; `pg.BarGraphItem.setOpts()` is slow | Throttle band power updates at 10-20 Hz; use existing `fft_update_interval` pattern | Negligible alone, compounds with decode path additions |

---

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| Showing raw (unnormalized) band power as the feedback signal | Subject cannot interpret the number; has no sense of whether 1.2 µV² is "good" | Show normalized control signal as percentage or directional bar (left/right bias) with clear zero-center reference |
| Classification certainty bar shows probability (0-1) rather than signal direction | Probability of "LEFT" is 0.6 — is that left control or right? Confusing for naïve subjects | Show the LR control signal sign and magnitude: a left/right bar with clear directional color coding |
| No visual distinction between calibration mode and online control mode | Subject unsure whether cursor movement is "real"; researcher unsure if decode is active | Use distinct UI state coloring (e.g., amber during calibration, green during active online control) |
| Task allows skipping the 60s mindfulness period | Subjects skip it; EEG is not settled; first trials are noisy | Make the mindfulness period unskippable with a countdown; allow early exit only for returning trained subjects |
| Signal quality indicators not visible during task | Researcher cannot intervene when electrode falls off during a trial run | Show at minimum a compact channel health banner (green/yellow/red per channel) on the task window, not just in the main GUI |
| Dead zone invisible to subject | Subject does not understand why small movements produce no cursor response | During calibration, render the dead zone threshold on the feedback bar as a visual "inactive zone" region |

---

## "Looks Done But Isn't" Checklist

- [ ] **CSP implementation:** Filters compute without error in unit test — verify that the spatial patterns show physiologically plausible C3/C4 lateralization, not just numerical convergence
- [ ] **Real-time band power:** Bar chart updates in the GUI — verify the feature is computed from the continuously-filtered buffer (not re-filtered epoch) and that the update path does not run on the main Qt thread
- [ ] **CAR spatial filter:** Subtraction code runs correctly — verify bad channels are excluded from the reference average before subtraction
- [ ] **Nonlinear transfer function:** Cursor moves in correct direction — verify that the dead zone uses a normalized signal (z-scored vs. REST baseline), not raw band power
- [ ] **Signal quality indicators:** Colored lights appear in the GUI — verify that bad-channel detection gates CAR application and that detected bad channels are logged to the XDF session record
- [ ] **Motor imagery task timing:** State machine fires LEFT/RIGHT/REST correctly — verify that marker timestamps in the XDF file are aligned within 50 ms of the actual visual cue onset (measure with a photodiode or frame-timestamped render)
- [ ] **Transfer function parameters:** R and dead zone fields are visible in settings — verify they are persisted to a per-subject config file and loaded on subsequent sessions
- [ ] **Decode thread:** Worker thread starts without error — verify that the thread holds a `threading.Lock` while reading `stream_buffer` and that it terminates cleanly when streaming stops

---

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| CSP overfitting discovered after multiple sessions | MEDIUM | Add regularization parameter, reprocess all session data offline to validate, collect new calibration block with more trials |
| EMG confound discovered post-collection | HIGH | Must recollect sessions with proper electrode/artifact monitoring; the collected data cannot be recovered (EMG and EEG are indistinguishable post-hoc without source separation) |
| IIR filter per-epoch startup transient | LOW | Refactor feature extraction to read from always-on filtered buffer; no data loss |
| Main thread blocking from DSP | LOW-MEDIUM | Extract decode path to QThread worker; existing signal/slot architecture in the codebase supports this |
| Stale baseline causing cursor drift | LOW | Add sliding REST-period baseline; existing band power infrastructure is mostly reusable |
| Wrong transfer function parameters per subject | LOW | Expose parameters in UI settings; store per-subject config |
| CAR bad-channel contamination | MEDIUM | Add channel quality gate before CAR; must re-examine sessions collected without the gate for contamination |

---

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| CSP overfitting | Signal Processing Pipeline (filter chain + CSP architecture) | Check spatial pattern topographies show central lateralization; verify cross-validation uses proper trial count gating |
| EMG contamination | Signal Validation (quality indicators) + Task Design (subject instructions) | Confirm >40 Hz power is not task-correlated during motor imagery trials |
| IIR filter per-epoch transients | Signal Processing Pipeline (filter chain architecture) | Verify all feature extraction reads from the continuously-filtered buffer; assert no `lfilter` calls with `zi=None` in decode path |
| Stale baseline normalization | Feature Extraction / Decoding | Confirm baseline statistics update only from REST-period samples; confirm cursor rests at center after 15 minutes |
| Transfer function miscalibration | Transfer Function & Cursor Control | Per-subject calibration step produces stable dead zone; R weighting stored in config file |
| Offline-to-online gap | Training Protocol Design | First online run follows at least one feedback-exposure calibration block |
| CAR bad-channel contamination | Signal Processing Pipeline (spatial filters) + Signal Validation | Bad-channel detection output gates CAR channel list; validated in live stream test |
| Qt main thread blocking | Signal Processing Pipeline (threading architecture — decide before adding DSP) | Frame rate stays >30 fps during active decode; XDF timestamps show <5 ms jitter |
| Session fatigue | Task Design | Session duration warnings fire at 20 min; inter-trial REST is enforced at minimum 3 s |

---

## Sources

- PMC12745444 — Real-world evaluation of deep learning decoders for motor imagery EEG-based BCIs (2024 PMC)
- PMC2918755 — Model-based generalization analysis of CSP in BCI — overfitting and noise sensitivity documentation
- PMC5066028 — Mu and Beta Rhythms of EEG with Strong Uncorrelating Transform — EMG contamination context
- Nature Scientific Reports s41598-024-69013-2 — Mental fatigue during long-term motor imagery (2024)
- Frontiers fnins.2021.733546 — Signal processing approaches to reduce calibration time in EEG-BCI
- arXiv 2403.15431 — Transferring BCI models from calibration to control: observing shifts in EEG features (2024)
- Sapienlabs.org — Pitfalls of Filtering the EEG Signal — IIR transient and causal/acausal filtering
- MNE-Python docs — Background information on filtering (mne.tools/stable)
- EEGLAB Wiki — Filtering FAQ — IIR startup transient handling
- Nature Scientific Reports s41598-019-44166-7 — Principled BCI decoder design and nonlinear transfer function parameter selection
- Qt Forum / pythonguis.com — GIL interaction with QThread in PyQt6; QThread threading patterns
- ResearchGate — CAR spatial filter with bad-channel contamination and median average reference alternatives
- arXiv 1707.08152 — How much baseline correction do we need in EEG
- ScienceDirect — Covariate shift and adaptive ensemble learning for EEG nonstationarity

---
*Pitfalls research for: BCI motor imagery platform — real-time signal processing, CSP spatial filters, nonlinear transfer function, online decoding*
*Researched: 2026-03-11*
