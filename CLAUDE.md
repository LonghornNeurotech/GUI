# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

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
- **`updater.py`** — checks GitHub Releases API at startup, downloads the platform asset, and spawns a platform-specific script (`.bat` / `.sh`) to replace the binary and relaunch.
- **`version.py`** — `CURRENT_VERSION` is `"build-0"` in source; CI replaces `_INJECTED` with `"build-<run_number>"` via `sed` before PyInstaller runs. Do not edit manually.
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
