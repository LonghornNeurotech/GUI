# AGENTS.md

This file provides guidance when working with code in this repository.

## Running the App

```bash
pip install -r requirements.txt
python GUI.py
```

Python 3.13 is required (matches CI).

## Architecture

This is a single-file PyQt6 desktop application (`GUI.py`) for EEG/EMG neural data acquisition, visualization, and recording. The app is distributed as a standalone binary built with PyInstaller.

### Key Classes in GUI.py

- **`SegmentViewer`** (QMainWindow) — the root window. Manages all tabs, hardware connections, and streaming state. Operates in two modes: `'file'` (review recorded data) and `'stream'` (live EEG from hardware).
- **`XDFRecorder`** — writes EEG + marker data directly to XDF 1.0 format (no LSL inlet round-trip). Buffers samples in memory, flushes to disk on `stop()`.
- **`TaskWebBridge`** (QObject) — PyQt/JS bridge exposed to the embedded QWebEngineView. JS calls `send_marker`, `start_streams`, `pick_save_dir` via Qt WebChannel.
- **`SettingsDialog`** — theme picker (light/dark).

### Supporting Modules

- **`conversions.py`** — loads `.pkl` (pickle) and `.gdf` (GDF/MNE) EEG files into numpy arrays + metadata dicts.
- **`updater.py`** — checks GitHub Releases API at startup, downloads the platform asset, and spawns a platform-specific script (`.bat` / `.sh`) to replace the binary and relaunch. When doing this, make sure to create a new virtual environment by doing pip install -r requirements on terminal to install correct and updated versions of all libraries
- **`version.py`** — `CURRENT_VERSION` is "build-0" in source; CI replaces `_INJECTED` with "build-<run_number>" via `sed` before PyInstaller runs. Do not edit manually.
- **`Prosthetic/prosthetic_gui.py`** — self-contained EMG decoding dialog. Uses BrainFlow to read EMG channels, runs an RMS-based per-finger decoder, and renders a `HandWidget` (QPainter-drawn) colored green-to-red by flexion.
- **`tasks/motor_imagery/`** — embedded web app (HTML/CSS/JS) loaded in `QWebEngineView`. Communicates with Python via `QWebChannel`. Drives the motor imagery recording task; JS calls `TaskWebBridge` slots to start LSL streams and push markers.

### Hardware / External Libraries

The app gracefully degrades if any of these are unavailable (prints a warning, sets `X_AVAILABLE = False`):

- **BrainFlow** — hardware EEG/EMG board abstraction
- **pylsl** (Lab Streaming Layer) — real-time EEG and marker LSL outlets
- **pyserial** — serial port scanning for headset auto-detection
- **scipy** — bandpass/notch filters and signal processing
- **MNE** — reading `.gdf` files (via `conversions.py`)
- **pyxdf** — reading existing `.xdf` files

### PyInstaller / Resource Paths

Use `resource_path(relative_path)` (defined in `GUI.py`) to resolve bundled assets — it switches between `sys._MEIPASS` (frozen) and the script directory (dev). All assets added via `--add-data` in CI must go through this function.

### QTWEBENGINE_CHROMIUM_FLAGS

`--js-flags=--jitless` is set before any Qt object is created to avoid V8's large `CodeRange` virtual-memory reservation that fails inside PyInstaller/hardened-runtime bundles. Do not remove this.

## CI / Release Pipeline

Pushes to `main` that touch `.py`, `requirements.txt`, the workflow file, or asset files trigger `.github/workflows/build-release.yml`, which:

1. Builds with PyInstaller on Linux, Windows, and macOS in parallel.
2. On Windows: also builds an NSIS installer (`installer.nsi`) via `makensis`; only the installer `.exe` is shipped (standalone exe is removed).
3. On macOS: signs with Developer ID, notarizes via `xcrun notarytool`, staples the ticket, and zips the `.app`.
4. Creates a GitHub Release tagged `build-<run_number>` with all three platform artifacts.

Release tags must follow the `build-N` format — `updater.py` parses this format to compare versions numerically.

## PROTOCOL FOR IMAGERY TASK

Phase 1: Calibration (Single-Ear Baseline)
Goal: Record clean 37Hz and 43Hz neural "fingerprints" and habituate the participant.
Total Trials: 20 (10 Left, 10 Right, randomized):

1. Rest (3.0 – 5.0s): Blank screen. Jittered to prevent anticipatory ERPs.

2. Fixation (1.5 – 2.5s): Center Cross (+). Participant stops blinking.

3. Prime/Cue (1.5s):
    - Visual: "LEFT" (37Hz) or "RIGHT" (43Hz) text + Progress Bar filling up.
    - Audio: Mono LEFT_1000HZ_37HZAM.wav or RIGHT_1000HZ_43HZAM.wav.

4.Stimulation Task (6.0s):
    - Visual: Constant Green Border around the target side.
    - Audio: Continued Mono AM tone.
    - Action: Passive listening; maintain focus on the frequency.

    XDF Markers: 101 (Start 37Hz Left), 102 (Start 43Hz Right).


Phase 2: Main Dichotic Attention (Selective Task):
Goal: Measure the neural suppression of the unattended frequency during dichotic listening.
Total Trials: 40 (20 "Attend Left," 20 "Attend Right," randomized).

1. Inter-Trial Rest (3.0 – 5.0s): Blank screen. XDF Marker: 10 (Trial Reset).

2. Fixation / Warning (2.0 – 3.0s): Center Cross (+). Jittered.

3. The Target Prime (1.5s):
    - Visual: "FOCUS LEFT" or "FOCUS RIGHT" with filling letter (L or R).
    - Audio: 500ms "Probe" burst of the target frequency (e.g., 37Hz for Left) to "tune" the auditory cortex.

4. The Other Prime(1.5s):
    - Visual: "OTHER: RIGHT"(or left)
    - Audio: 500ms burst of non - target ear(depending on target shown in step 3)

4. Preparation Gap (0.5 – 1.0s): Silence. Blank screen. Clears echoic memory before the mix.

5. Dichotic Task (6.0s):
    - Audio: DICHOTIC_1000HZ_37VS43HZAM.wav (Both ears active).
    - Visual: Target side (L or R) stays highlighted/lit.
    - Action: Attend strictly to the cued frequency; ignore the "distractor" ear.
    - XDF Markers:
        - 201 (Dichotic Start - Attend Left/37Hz)
        - 202 (Dichotic Start - Attend Right/43Hz)

6. End of Trial: 1.0s buffer before returning to Rest.


GUI Configuration Settings:
Jitter Logic: Use a random float between the Min/Max values for every trial.
Marker Sync: Triggers must be sent at the Audio Buffer Start to ensure 1ms precision for FFT analysis.
Audio Duration: 6 seconds is the optimized window for ASSR stability vs. participant fatigue.
