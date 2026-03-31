# Feature Research

**Domain:** BCI Motor Imagery Platform — EEG/EMG acquisition, signal processing, and cursor control
**Researched:** 2026-03-11
**Confidence:** HIGH (project requirements are well-specified; research validates domain expectations)

---

## Feature Landscape

### Table Stakes (Users Expect These)

Features a BCI research platform must have. Missing these means researchers cannot run a credible experiment or will distrust the system entirely.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Sequential filter pipeline (bandpass → notch → spatial) | Every published motor imagery BCI paper uses this exact pipeline order; researchers expect to configure it directly | MEDIUM | Must run at ≥200 Hz without sample drops; bandpass 8-32 Hz + notch at 50/60 Hz is the canonical starting point |
| Common Average Reference (CAR) spatial filter | Lowest-complexity spatial filter, unsupervised, universally applied before CSP in early experiment stages | LOW | Subtract mean of all channels from each channel; stable fallback before subject-specific filters are trained |
| Laplacian spatial filter | Second baseline spatial filter; enhances local electrode sources, especially C3/C4 for mu rhythm | LOW | Uses nearest neighbor channels; requires configurable neighbor definitions per headset layout |
| CSP (Common Spatial Pattern) spatial filter | Standard feature extraction for two-class motor imagery since ~2000; every BCI researcher expects it | HIGH | Supervised — requires class labels from offline data; produces filters that maximize variance ratio between classes |
| Band power extraction (mu 8-13 Hz, beta 18-26 Hz) | Mu ERD/ERS is the foundational neuroscience signal for motor imagery BCI | MEDIUM | Log-variance of filtered signal is standard; C4-C3 difference for LR; C3+C4 sum for UD |
| Real-time signal quality indicators (flatline, spike, SNR) | Without this, researchers cannot tell if electrodes are bad during a run — wasted session | MEDIUM | Color-coded per-channel; red=bad, yellow=marginal, green=good; visible both in main viewer and during task |
| Impedance estimation (proxy via signal variance) | Impedance cannot be measured mid-session on most EEG devices, but variance-based proxy catches bad contacts | LOW | True impedance = pre-session only; runtime quality = variance + SNR proxy; show both |
| 1D Left/Right offline motor imagery task | The entry point of every motor imagery training protocol; standard paradigm since Wolpaw et al. | MEDIUM | 4s cue → REST/LEFT/RIGHT cycles; blink prompts during rest; 60s mindfulness intro; XDF recording |
| 1D Up/Down offline motor imagery task | Required for 2D cursor; bilateral hand imagery → ERD at C3+C4 sum | MEDIUM | Same timing as LR task; C3+C4 average as UD control signal |
| Real-time classification feedback bar | Closed-loop feedback is the mechanism by which subjects learn to modulate their BCI signal | MEDIUM | Left/right bias indicator shown during online training; must update at display rate |
| Session marker synchronization with XDF | Markers aligned to EEG samples are required for offline analysis in any BCI study | LOW | Already existing — must work correctly with new task UI |
| Configurable C3/C4 channel selection | Different headsets place electrodes at different indices; hardcoding breaks device-agnostic design | LOW | Dropdown or text entry mapping channel name → array index |

### Differentiators (Competitive Advantage)

Features that set this platform apart from generic EEG viewers or generic BCI toolboxes. These align with the core value of running a complete offline-to-online BCI experiment in a single GUI.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| 2D cursor task with nonlinear transfer function | Enables progression to higher-dimensional BCI control in the same GUI; most platforms stop at 1D | HIGH | Dead zone (|x| ≤ 0.05 SD → 0), quadratic region, saturation at ±0.9009; subject-specific R weighting (3-3.5 LR, 0.3-0.6 UD) from published drone BCI study |
| Asynchronous free-cursor mode | Tests real-world BCI performance outside structured cues; most training platforms only support synchronous paradigms | HIGH | Subject moves cursor without cue prompts; requires real-time 2D decoding at display rate |
| Progressive training criteria display | Surfaces the 80% / 4-consecutive-trials threshold visually; subjects understand where they are in training | MEDIUM | Per-trial accuracy tracker with visual progress toward unlock criteria for next stage |
| Unified offline/online pipeline in one tool | Researchers currently chain multiple tools (recording software → MATLAB/Python offline → separate online tool); this eliminates that | HIGH | The architectural claim is that the same filter objects trained offline are reused directly online |
| Minimalist lab-style task UI (native PyQt6) | Current QWebEngineView canvas adds compositor overhead and debugging complexity; native widget is faster and more auditable | MEDIUM | Replace JS canvas with QWidget paintEvent; removes WebEngineView dependency from hot path |
| Subject-specific R weighting factor tuning | Allows per-session calibration of control sensitivity; published BCI systems require this for reliable control | LOW | Exposed as a numeric parameter in session setup; persisted per subject ID |
| Band power time-series overlay on channel plot | Lets researcher see the mu ERD as it happens in the main viewer during a live session | MEDIUM | Optional overlay panel showing 8-13 Hz band power trace for C3/C4 alongside raw EEG |

### Anti-Features (Commonly Requested, Often Problematic)

Features that seem like improvements but would hurt reliability, scope, or the core research workflow.

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| Deep learning / neural net classifier | Higher accuracy in published benchmarks; researchers want state-of-the-art | Training time and overfitting make it unusable for real-time online sessions with few trials; CSP+LDA is proven, interpretable, and trains in seconds | Use LDA on CSP features as the production classifier; note DL as future research direction only |
| ICA artifact removal (real-time) | ICA is standard in offline EEG preprocessing | Real-time ICA is computationally expensive, requires sufficient data to converge, and adds unpredictable latency to the live pipeline | Use CAR or Laplacian for live noise suppression; reserve ICA for offline post-processing of saved XDF files |
| Cloud sync / multi-site recording | Seems useful for multi-lab studies | Violates the desktop-only, local-compute constraint; adds authentication complexity and network latency to a latency-sensitive system | Researchers share XDF files manually; LSL already provides local network streaming if needed |
| P300 / SSVEP paradigm support | Broadens user base beyond motor imagery | Completely different signal processing chain, different task UI, different electrode needs; adds scope that dilutes the motor imagery focus | Scope to motor imagery only; document clearly |
| Gamification / VR feedback | Proven to increase user engagement and learning rate in some studies | Increases stimulus complexity, adds asset pipeline, and the team has explicitly scoped to minimalist lab-style UI; gamification results are inconsistent for expert lab subjects | Unambiguous directional cue arrows + certainty bar is sufficient feedback for trained researchers |
| Automatic artifact rejection (trial gating) | Reduces noise in offline datasets | Real-time trial rejection based on amplitude thresholds can silently discard valid data; researcher should see artifacts, not have them silently removed | Flag artifact trials with visual marker in the waveform; let researcher decide post-hoc in the XDF file |
| Multi-subject simultaneous recording | Shared infrastructure sessions seem efficient | Single subject scope is explicitly out-of-scope; multi-subject adds session management complexity with no research benefit for this group | Run separate instances per subject |

---

## Feature Dependencies

```
[Configurable C3/C4 channel selection]
    └──requires──> [Band power extraction (mu 8-13 Hz)]
                       └──requires──> [Sequential filter pipeline]

[CSP spatial filter]
    └──requires──> [Offline 1D LR task] (needs labeled class epochs to train filters)
    └──requires──> [Sequential filter pipeline] (input must be bandpass filtered first)

[Real-time classification feedback bar]
    └──requires──> [Band power extraction]
    └──requires──> [CSP spatial filter] (trained weights applied at runtime)

[2D cursor task]
    └──requires──> [1D LR offline task] (progression gate: ≥80% accuracy, 4 consecutive trials)
    └──requires──> [1D UD offline task]
    └──requires──> [Real-time classification feedback bar] (both axes need live decoding)
    └──requires──> [Nonlinear transfer function]

[Asynchronous free-cursor mode]
    └──requires──> [2D cursor task] (same decoding architecture, no cue overlay)

[Signal quality indicators]
    └──requires──> [Sequential filter pipeline] (quality measured on filtered signal)

[Progressive training criteria display]
    └──enhances──> [1D LR offline task]
    └──enhances──> [1D UD offline task]

[Minimalist lab-style task UI (native PyQt6)]
    └──conflicts──> [QWebEngineView canvas task] (replacement, not addition)
```

### Dependency Notes

- **CSP requires offline 1D LR task:** CSP is a supervised spatial filter. It cannot be trained until labeled LEFT/RIGHT epochs are collected. The 1D offline task is the data collection mechanism that enables CSP training.
- **2D cursor requires both 1D tasks:** The two axes are decoded independently (LR = C4-C3 difference, UD = C3+C4 sum). Both decoders must be trained before 2D control is attempted.
- **Sequential filter pipeline is the root:** All feature extraction, spatial filtering, and quality metrics depend on a correctly running bandpass+notch+spatial pipeline. This must be implemented and validated first.
- **Native task UI conflicts with WebEngineView task:** The replacement should be built as a drop-in for the existing task launcher. The old JS canvas and QWebChannel bridge can be removed after the new task is validated.

---

## MVP Definition

This is a subsequent milestone (not initial MVP). The "launch" here means: researchers at Longhorn Neurotech can run a full offline-to-online motor imagery session for the first time without external tools.

### Launch With (this milestone)

- [ ] Sequential filter pipeline (bandpass → notch → CAR/Laplacian/CSP) — prerequisite for everything else
- [ ] Signal quality indicators (flatline, spike, SNR per channel) — prevents wasted recording sessions
- [ ] Configurable C3/C4 channel mapping — required for device-agnostic operation
- [ ] Band power extraction (mu ERD/ERS at C3/C4) — the core neuroscience signal
- [ ] 1D Left/Right offline task (native PyQt6 UI) — replaces existing JS canvas task; primary data collection tool
- [ ] 1D Up/Down offline task — required to enable 2D cursor
- [ ] Real-time classification feedback bar (online training mode) — closed-loop feedback is how subjects learn
- [ ] Nonlinear transfer function implementation — required for any cursor task
- [ ] 2D cursor task — the primary research output and platform differentiator
- [ ] Subject-specific R weighting factor configuration — required for reliable 2D control

### Add After Validation (v1.x)

- [ ] Asynchronous free-cursor mode — add when 2D cursor task is validated and subjects are performing at ≥80% on 1D tasks
- [ ] Progressive training criteria display — add once the training pipeline is exercised enough to know what metrics matter
- [ ] Band power time-series overlay in main viewer — useful visual but not required for the experiment to run

### Future Consideration (v2+)

- [ ] FBCSP (Filter Bank CSP) — better classification but significantly more complex; validate standard CSP first
- [ ] Transfer learning across subjects — reduce calibration time; requires multi-subject data corpus
- [ ] Error-related potential (ErrP) integration — can improve decoding by detecting user error signals; major paradigm extension

---

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| Sequential filter pipeline | HIGH | MEDIUM | P1 |
| Signal quality indicators | HIGH | MEDIUM | P1 |
| Configurable C3/C4 channel mapping | HIGH | LOW | P1 |
| Band power extraction (mu 8-13 Hz) | HIGH | MEDIUM | P1 |
| 1D LR offline task (native PyQt6) | HIGH | MEDIUM | P1 |
| 1D UD offline task | HIGH | MEDIUM | P1 |
| Real-time classification feedback bar | HIGH | MEDIUM | P1 |
| Nonlinear transfer function | HIGH | LOW | P1 |
| 2D cursor task | HIGH | HIGH | P1 |
| Subject-specific R weighting | MEDIUM | LOW | P1 |
| Asynchronous free-cursor mode | HIGH | MEDIUM | P2 |
| Progressive training criteria display | MEDIUM | LOW | P2 |
| Band power overlay in main viewer | MEDIUM | MEDIUM | P2 |
| CAR spatial filter | HIGH | LOW | P1 |
| Laplacian spatial filter | MEDIUM | LOW | P1 |
| CSP spatial filter | HIGH | HIGH | P1 |

**Priority key:**
- P1: Must have for milestone launch — experiment cannot run without it
- P2: Should have — improves usability and research value, not blocking
- P3: Nice to have, deferred to future milestone

---

## Competitor Feature Analysis

| Feature | BCI2000 | MNE-Python (offline) | This Platform |
|---------|---------|---------------------|---------------|
| Real-time streaming + recording | Yes (complex setup) | No (offline only) | Yes (existing, via BrainFlow/LSL) |
| Sequential filter pipeline | Yes (module-based) | Yes (offline) | Planned — single Python DSP chain |
| CSP spatial filter | Yes | Yes (scikit-learn interface) | Planned — scipy/numpy implementation |
| Signal quality indicators | Basic (impedance pre-session) | No | Planned — real-time SNR + flatline + spike |
| Motor imagery task UI | Yes (cursor paradigm built-in) | No | Planned — native PyQt6 replacement |
| Nonlinear transfer function | Configurable | N/A | Planned — from published BCI drone study |
| 2D cursor task | Yes | No | Planned |
| Offline-to-online pipeline in one GUI | No (requires separate tools) | No | Target differentiator |
| Cross-platform desktop binary | Partial | No (Python environment required) | Yes (PyInstaller CI builds) |
| Myo EMG integration | No | No | Yes (existing) |

---

## Sources

- [Effects of Different Preprocessing Pipelines on Motor Imagery-Based BCIs — PubMed (2025)](https://pubmed.ncbi.nlm.nih.gov/40031268/) — validates bandpass+notch as highest-value preprocessing
- [An Online Data Visualization Feedback Protocol for Motor Imagery-Based BCI Training — Frontiers in Human Neuroscience (2021)](https://www.frontiersin.org/journals/human-neuroscience/articles/10.3389/fnhum.2021.625983/full) — closed-loop feedback design; certainty visualization
- [Continuous Tracking with Deep Learning Decoding for Noninvasive BCI — PNAS Nexus (2024)](https://academic.oupom/pnasnexus/article/3/4/pgae145/7656016) — 2D cursor and continuous pursuit paradigm
- [Brain-Computer Interfaces Using Sensorimotor Rhythms: Current State and Future Perspectives — PMC (2014, still authoritative)](https://pmc.ncbi.nlm.nih.gov/articles/PMC4082720/) — mu ERD/ERS mechanism, C3/C4 lateralization
- [Motor Imagery Decoding Methods for 2024 Cybathlon — arXiv (2024)](https://arxiv.org/html/2511.23384v1) — real-world pipeline implementation and training progression
- [Adaptive Laplacian Filtering for SMR-Based BCIs — PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC3602341/) — Laplacian filter design for sensorimotor rhythms
- [MNE-Python CSP Example](https://mne.tools/stable/auto_examples/decoding/decoding_csp_eeg.html) — CSP implementation reference
- [BCI2000 Mu Rhythm Tutorial](https://www.bci2000.org/mediawiki/index.php/User_Tutorial:Introduction_to_the_Mu_Rhythm) — canonical 1D cursor paradigm details
- [Progressive Training with Gamification — Frontiers in Human Neuroscience (2019)](https://www.frontiersin.org/journals/human-neuroscience/articles/10.3389/fnhum.2019.00329/full) — training protocol design; 80% threshold conventions
- [EEG Signal Quality Evaluation — BrainAccess](https://www.brainaccess.ai/tutorials/eeg-signal-quality/) — runtime signal quality indicator design; impedance vs. variance proxy
- PROJECT.md (this repository) — authoritative source for in-scope features, constraints, and nonlinear transfer function parameters

---
*Feature research for: BCI Motor Imagery Platform — signal processing, validation, tasks, decoding*
*Researched: 2026-03-11*
