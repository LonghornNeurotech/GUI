"""
Myo Armband Integration
=======================
Connects to the Myo EMG armband via:
  - Direct BLE (pyomyo) — no external app required
  - OSC bridge (myo-osc / samyk/myo-osc) — receives UDP OSC packets

Features
--------
- 8-channel real-time EMG bar visualization
- 7-gesture calibration wizard (Rest, Open, Fist, Wrist Flex/Ext, Pronate, Supinate)
- LDA classifier trained on user's own calibration data
- LSL EMG outlet (8-ch, 200 Hz) — appears in main GUI stream picker
- LSL Gesture marker outlet — timestamps each predicted gesture
"""

import os
import sys
import time
import json
import threading
import numpy as np

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QGroupBox, QProgressBar, QComboBox, QSpinBox, QMessageBox, QSizePolicy,
    QStackedWidget, QFrame,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt6.QtGui import QPainter, QColor, QPen, QLinearGradient, QFont

# ── optional deps ────────────────────────────────────────────────────────────

try:
    import bleak
    BLEAK_AVAILABLE = True
except ImportError:
    BLEAK_AVAILABLE = False

PYOMYO_AVAILABLE = False  # replaced by bleak

try:
    from pythonosc.dispatcher import Dispatcher
    from pythonosc.osc_server import BlockingOSCUDPServer
    OSC_AVAILABLE = True
except ImportError:
    OSC_AVAILABLE = False

try:
    from pylsl import StreamInfo, StreamOutlet, cf_float32, cf_string
    LSL_AVAILABLE = True
except ImportError:
    LSL_AVAILABLE = False

try:
    from sklearn.discriminant_analysis import LinearDiscriminantAnalysis
    from sklearn.model_selection import cross_val_score
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False

# ── constants ────────────────────────────────────────────────────────────────

SRATE          = 200          # Hz (Myo native EMG rate)
N_CH           = 8
WIN_MS         = 200          # feature window length
WIN_SAMPLES    = int(SRATE * WIN_MS / 1000)   # 40
STEP_SAMPLES   = WIN_SAMPLES // 2             # 50 % overlap
CALIB_SEC      = 4.0          # seconds of data collected per gesture
CALIB_SAMPLES  = int(SRATE * CALIB_SEC)

GESTURES = [
    ("Rest",            "Relax your arm completely — no movement."),
    ("Open Hand",       "Spread all fingers wide open."),
    ("Fist",            "Close your hand into a tight fist."),
    ("Wrist Flexion",   "Bend your wrist downward (toward your palm)."),
    ("Wrist Extension", "Bend your wrist upward (back of hand up)."),
    ("Pronate",         "Rotate your forearm so palm faces down (clockwise)."),
    ("Supinate",        "Rotate your forearm so palm faces up (counter-clockwise)."),
]
N_GESTURES = len(GESTURES)

_PALETTE = {
    "bg":       "#1e1e1e",
    "panel":    "#252535",
    "border":   "#3a3a5a",
    "accent":   "#598BBC",
    "navy":     "#213C58",
    "gold":     "#FFEBAD",
    "orange":   "#BF5801",
    "green":    "#3dba55",
    "red":      "#e05050",
    "text":     "#e8e8e8",
    "subtext":  "#999",
}

# ── signals (thread → Qt) ────────────────────────────────────────────────────

class _Signals(QObject):
    emg_received    = pyqtSignal(list)      # 8 floats 0-1
    gesture_pred    = pyqtSignal(int, float) # class_idx, confidence
    status_changed  = pyqtSignal(str)
    connected       = pyqtSignal()
    disconnected    = pyqtSignal()

# ── EMG bar widget ───────────────────────────────────────────────────────────

class EmgBarsWidget(QWidget):
    """8 vertical bars showing real-time EMG amplitude."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._values = [0.0] * N_CH
        self.setMinimumHeight(120)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_values(self, vals):
        self._values = list(vals)
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        margin = 4
        bar_w = (w - margin * (N_CH + 1)) / N_CH

        p.fillRect(0, 0, w, h, QColor(_PALETTE["bg"]))

        for i, v in enumerate(self._values):
            x = int(margin + i * (bar_w + margin))
            bar_h = max(2, int(v * (h - 20)))
            y = h - 18 - bar_h

            # gradient green → yellow → red
            grad = QLinearGradient(x, y + bar_h, x, y)
            grad.setColorAt(0.0, QColor("#3dba55"))
            grad.setColorAt(0.5, QColor("#f0c040"))
            grad.setColorAt(1.0, QColor("#e05050"))
            p.setBrush(grad)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(x, y, int(bar_w), bar_h, 3, 3)

            # channel label
            p.setPen(QColor(_PALETTE["subtext"]))
            p.setFont(QFont("Arial", 8))
            p.drawText(x, h - 4, int(bar_w), 14,
                       Qt.AlignmentFlag.AlignHCenter, f"Ch{i+1}")
        p.end()

# ── gesture display ──────────────────────────────────────────────────────────

class GestureDisplay(QWidget):
    """Shows current gesture prediction + confidence."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        self._name_lbl = QLabel("—")
        self._name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._name_lbl.setStyleSheet(
            f"font-size: 26px; font-weight: bold; color: {_PALETTE['accent']};")
        layout.addWidget(self._name_lbl)

        self._conf_bar = QProgressBar()
        self._conf_bar.setRange(0, 100)
        self._conf_bar.setValue(0)
        self._conf_bar.setFormat("Confidence: %p%")
        self._conf_bar.setStyleSheet(f"""
            QProgressBar {{
                border: 1px solid {_PALETTE['border']};
                border-radius: 4px;
                background: #2a2a3a;
                color: {_PALETTE['text']};
                text-align: center;
            }}
            QProgressBar::chunk {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 {_PALETTE['accent']}, stop:1 {_PALETTE['green']});
                border-radius: 3px;
            }}
        """)
        layout.addWidget(self._conf_bar)

        self.setStyleSheet(
            f"background: {_PALETTE['panel']}; border-radius: 6px;")

    def update_prediction(self, gesture_idx: int, confidence: float):
        name = GESTURES[gesture_idx][0] if 0 <= gesture_idx < N_GESTURES else "—"
        self._name_lbl.setText(name)
        self._conf_bar.setValue(int(confidence * 100))

# ── calibration wizard ───────────────────────────────────────────────────────

class CalibrationWizard(QWidget):
    """Step-by-step calibration: collect CALIB_SEC of data per gesture."""

    calibration_done = pyqtSignal(list, list)   # X (features), y (labels)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._gesture_idx = 0
        self._collecting = False
        self._buffer = []          # raw EMG windows during current gesture
        self._all_X = []
        self._all_y = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        self._step_lbl = QLabel("")
        self._step_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._step_lbl.setStyleSheet(
            f"font-size: 14px; font-weight: bold; color: {_PALETTE['gold']};")
        layout.addWidget(self._step_lbl)

        self._gesture_lbl = QLabel("")
        self._gesture_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._gesture_lbl.setStyleSheet(
            f"font-size: 22px; font-weight: bold; color: {_PALETTE['accent']};")
        layout.addWidget(self._gesture_lbl)

        self._desc_lbl = QLabel("")
        self._desc_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._desc_lbl.setWordWrap(True)
        self._desc_lbl.setStyleSheet(
            f"font-size: 12px; color: {_PALETTE['subtext']};")
        layout.addWidget(self._desc_lbl)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setStyleSheet(f"""
            QProgressBar {{
                border: 1px solid {_PALETTE['border']};
                border-radius: 4px;
                background: #2a2a3a;
                height: 18px;
            }}
            QProgressBar::chunk {{
                background: {_PALETTE['green']};
                border-radius: 3px;
            }}
        """)
        layout.addWidget(self._progress)

        self._status_lbl = QLabel("Press Start when ready.")
        self._status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_lbl.setStyleSheet(f"color: {_PALETTE['subtext']}; font-size: 11px;")
        layout.addWidget(self._status_lbl)

        btn_row = QHBoxLayout()
        self._start_btn = QPushButton("Start Recording")
        self._start_btn.setStyleSheet(f"""
            QPushButton {{
                background: {_PALETTE['green']};
                color: white;
                font-weight: bold;
                border: none;
                border-radius: 4px;
                padding: 6px 18px;
            }}
            QPushButton:hover {{ background: #4dcc65; }}
            QPushButton:disabled {{ background: #2a3a2a; color: #555; }}
        """)
        self._start_btn.clicked.connect(self._start_recording)
        btn_row.addWidget(self._start_btn)

        self._skip_btn = QPushButton("Reset All")
        self._skip_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {_PALETTE['subtext']};
                border: 1px solid {_PALETTE['border']};
                border-radius: 4px;
                padding: 6px 12px;
            }}
            QPushButton:hover {{ color: {_PALETTE['text']}; }}
        """)
        self._skip_btn.clicked.connect(self.reset)
        btn_row.addWidget(self._skip_btn)
        layout.addLayout(btn_row)

        self._timer = QTimer()
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._tick)
        self._collect_start = 0.0

        self._update_labels()

    def reset(self):
        self._gesture_idx = 0
        self._collecting = False
        self._buffer = []
        self._all_X = []
        self._all_y = []
        self._timer.stop()
        self._start_btn.setEnabled(True)
        self._progress.setValue(0)
        self._update_labels()
        self._status_lbl.setText("Press Start when ready.")

    def push_emg(self, sample: list):
        """Called from worker thread — always safe (just appends)."""
        if self._collecting:
            self._buffer.append(sample)

    def _update_labels(self):
        if self._gesture_idx < N_GESTURES:
            name, desc = GESTURES[self._gesture_idx]
            self._step_lbl.setText(
                f"Gesture {self._gesture_idx + 1} / {N_GESTURES}")
            self._gesture_lbl.setText(name)
            self._desc_lbl.setText(desc)
        else:
            self._step_lbl.setText("Calibration complete")
            self._gesture_lbl.setText("All gestures recorded")
            self._desc_lbl.setText("")

    def _start_recording(self):
        if self._gesture_idx >= N_GESTURES:
            return
        self._buffer = []
        self._collecting = True
        self._collect_start = time.time()
        self._start_btn.setEnabled(False)
        self._status_lbl.setText("Recording…  Hold the gesture steady.")
        self._timer.start()

    def _tick(self):
        elapsed = time.time() - self._collect_start
        pct = min(100, int(elapsed / CALIB_SEC * 100))
        self._progress.setValue(pct)

        if elapsed >= CALIB_SEC:
            self._timer.stop()
            self._collecting = False
            self._finalize_gesture()

    def _finalize_gesture(self):
        data = np.array(self._buffer, dtype=np.float32)
        if len(data) < WIN_SAMPLES:
            self._status_lbl.setText("Not enough data — try again.")
            self._start_btn.setEnabled(True)
            self._progress.setValue(0)
            return

        # Extract windowed MAV features
        feats = _extract_features(data)
        label = self._gesture_idx
        self._all_X.extend(feats)
        self._all_y.extend([label] * len(feats))

        self._gesture_idx += 1
        self._progress.setValue(0)

        if self._gesture_idx >= N_GESTURES:
            self._update_labels()
            self._start_btn.setEnabled(False)
            self._status_lbl.setText("All gestures collected — training classifier…")
            self.calibration_done.emit(self._all_X, self._all_y)
        else:
            self._update_labels()
            self._start_btn.setEnabled(True)
            name = GESTURES[self._gesture_idx][0]
            self._status_lbl.setText(
                f"Done! Next: {name} — press Start when ready.")

# ── feature extraction ───────────────────────────────────────────────────────

def _extract_features(data: np.ndarray) -> np.ndarray:
    """
    Slide a window over data (shape N x 8), return (M x 16) feature matrix.
    Features per window: MAV + RMS for each of 8 channels.
    """
    rows = []
    n = len(data)
    i = 0
    while i + WIN_SAMPLES <= n:
        seg = data[i: i + WIN_SAMPLES]                     # WIN_SAMPLES x 8
        mav = np.mean(np.abs(seg), axis=0)                 # 8
        rms = np.sqrt(np.mean(seg ** 2, axis=0))           # 8
        rows.append(np.concatenate([mav, rms]))
        i += STEP_SAMPLES
    return np.array(rows) if rows else np.empty((0, 16))

# ── connection workers ────────────────────────────────────────────────────────

class _DirectMyoWorker:
    """Connects directly to Myo via bleak (native Windows BLE, Python 3.14 compatible)."""

    # Myo GATT UUIDs
    _CMD_CHAR  = "d5060401-a904-deb9-4748-2c7f4a124842"
    _EMG_CHARS = [
        "d5060105-a904-deb9-4748-2c7f4a124842",
        "d5060205-a904-deb9-4748-2c7f4a124842",
        "d5060305-a904-deb9-4748-2c7f4a124842",
        "d5060405-a904-deb9-4748-2c7f4a124842",
    ]
    # Enable EMG streaming + disable sleep
    _CMD_EMG_ALL = bytes([0x01, 0x03, 0x03, 0x01, 0x00])

    def __init__(self, signals: _Signals, com_port: str = ""):
        self._sig = signals
        self._com_port = com_port.strip()  # unused for bleak, kept for UI compat
        self._running = False
        self._first_packet = True

    def start(self):
        self._running = True
        self._first_packet = True
        threading.Thread(target=self._run, daemon=True).start()

    def stop(self):
        self._running = False

    def _run(self):
        if not BLEAK_AVAILABLE:
            self._sig.status_changed.emit("bleak not installed — run: pip install bleak")
            return
        import asyncio
        try:
            asyncio.run(self._ble_main())
        except Exception as exc:
            self._sig.status_changed.emit(f"BLE error: {exc}")
            self._sig.disconnected.emit()

    async def _ble_main(self):
        import asyncio
        from bleak import BleakScanner, BleakClient

        self._sig.status_changed.emit("Scanning for Myo armband…")
        device = await BleakScanner.find_device_by_filter(
            lambda d, _: "myo" in (d.name or "").lower(), timeout=10.0)
        if device is None:
            self._sig.status_changed.emit(
                "Myo not found — make sure it is awake (tap pod twice) and BT is on")
            self._sig.disconnected.emit()
            return

        self._sig.status_changed.emit(f"Found {device.name} — connecting…")

        async with BleakClient(device, timeout=15.0) as client:
            # Send set_mode command: EMG_ALL=0x03, IMU_DATA=0x01, CLASSIFIER_OFF=0x00
            try:
                await client.write_gatt_char(
                    self._CMD_CHAR, self._CMD_EMG_ALL, response=True)
                self._sig.status_changed.emit("EMG mode set — waiting for data…")
            except Exception as exc:
                self._sig.status_changed.emit(
                    f"EMG enable warning: {exc} — trying anyway")

            notify_count = 0

            def _notify(_, data: bytearray):
                if self._first_packet:
                    self._first_packet = False
                    self._sig.status_changed.emit(
                        f"Connected to {device.name} — receiving EMG data")
                # Each notification = 16 bytes = 2 samples × 8 signed bytes
                for s in range(2):
                    raw = [data[s * 8 + i] for i in range(8)]
                    # Myo sends signed int8 (two's complement), centre around 0
                    signed = [(v if v < 128 else v - 256) for v in raw]
                    normed = [min(1.0, abs(v) / 127.0) for v in signed]
                    self._sig.emg_received.emit(normed)

            for uuid in self._EMG_CHARS:
                try:
                    await client.start_notify(uuid, _notify)
                    notify_count += 1
                except Exception as exc:
                    self._sig.status_changed.emit(f"Notify failed {uuid[:8]}…: {exc}")

            if notify_count == 0:
                self._sig.status_changed.emit(
                    "No EMG characteristics subscribed — check Myo firmware")
                self._sig.disconnected.emit()
                return

            self._sig.connected.emit()
            if self._first_packet:
                self._sig.status_changed.emit(
                    f"Connected to {device.name} ({notify_count}/4 EMG chars) — move arm to verify data")

            while self._running and client.is_connected:
                await asyncio.sleep(0.1)

            for uuid in self._EMG_CHARS:
                try:
                    await client.stop_notify(uuid)
                except Exception:
                    pass

            # Brief pause so WinRT scanner callbacks can finish before loop teardown
            await asyncio.sleep(0.3)

        self._sig.disconnected.emit()


class _OscMyoWorker:
    """Receives Myo EMG from myo-osc (samyk/myo-osc) over UDP/OSC."""

    def __init__(self, signals: _Signals, port: int = 8000):
        self._sig = signals
        self._port = port
        self._running = False
        self._server = None

    def start(self):
        self._running = True
        threading.Thread(target=self._run, daemon=True).start()

    def stop(self):
        self._running = False
        if self._server:
            self._server.shutdown()

    def _run(self):
        if not OSC_AVAILABLE:
            self._sig.status_changed.emit("python-osc not installed.")
            return
        try:
            disp = Dispatcher()
            disp.map("/myo/emg", self._on_emg)
            self._server = BlockingOSCUDPServer(("0.0.0.0", self._port), disp)
            self._sig.connected.emit()
            self._sig.status_changed.emit(
                f"Listening for myo-osc on UDP :{self._port}")
            self._server.serve_forever()
        except Exception as exc:
            self._sig.status_changed.emit(f"OSC error: {exc}")
            self._sig.disconnected.emit()

    def _on_emg(self, _addr, *args):
        if len(args) >= N_CH:
            normed = [min(1.0, abs(float(v)) / 127.0) for v in args[:N_CH]]
            self._sig.emg_received.emit(normed)

# ── LSL helpers ───────────────────────────────────────────────────────────────

def _make_emg_outlet():
    if not LSL_AVAILABLE:
        return None
    info = StreamInfo("MyoEMG", "EMG", N_CH, SRATE, cf_float32, "myo_emg_001")
    ch = info.desc().append_child("channels")
    for i in range(N_CH):
        c = ch.append_child("channel")
        c.append_child_value("label", f"EMG{i+1}")
        c.append_child_value("unit", "normalized")
        c.append_child_value("type", "EMG")
    return StreamOutlet(info, chunk_size=1)


def _make_gesture_outlet():
    if not LSL_AVAILABLE:
        return None
    info = StreamInfo("MyoGestures", "Markers", 1, 0, cf_string, "myo_gest_001")
    return StreamOutlet(info)

# ── main window ───────────────────────────────────────────────────────────────

_WINDOW_STYLE = f"""
    QMainWindow, QWidget {{ background-color: {_PALETTE['bg']}; color: {_PALETTE['text']}; }}
    QGroupBox {{
        border: 1px solid {_PALETTE['border']};
        border-radius: 5px;
        margin-top: 10px;
        padding-top: 8px;
        font-weight: bold;
        color: {_PALETTE['accent']};
    }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 8px; padding: 0 4px; }}
    QPushButton {{
        background: #3a3a5a;
        color: {_PALETTE['text']};
        border: 1px solid {_PALETTE['border']};
        border-radius: 4px;
        padding: 5px 12px;
    }}
    QPushButton:hover {{ background: #4a4a6a; }}
    QPushButton:disabled {{ color: #555; }}
    QComboBox {{
        background: #2a2a3a;
        border: 1px solid {_PALETTE['border']};
        border-radius: 4px;
        padding: 3px 8px;
        color: {_PALETTE['text']};
    }}
    QLabel {{ color: {_PALETTE['text']}; }}
"""


class MyoWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Myo Armband — EMG & Gesture Control")
        self.resize(700, 620)
        self.setStyleSheet(_WINDOW_STYLE)

        self._signals    = _Signals()
        self._worker     = None
        self._classifier = None          # trained LDA
        self._emg_outlet   = None
        self._gest_outlet  = None
        self._emg_ring   = np.zeros((WIN_SAMPLES * 2, N_CH), dtype=np.float32)
        self._ring_ptr   = 0

        # -- build UI --
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        root.addWidget(self._build_connection_panel())
        root.addWidget(self._build_emg_panel())

        self._stack = QStackedWidget()
        self._calib = CalibrationWizard()
        self._calib.calibration_done.connect(self._on_calibration_done)
        self._gest_display = GestureDisplay()
        self._stack.addWidget(self._calib)       # index 0
        self._stack.addWidget(self._gest_display) # index 1
        self._stack.setCurrentIndex(0)

        calib_group = QGroupBox("Calibration & Gesture Prediction")
        calib_layout = QVBoxLayout(calib_group)

        tab_row = QHBoxLayout()
        self._calib_tab_btn = QPushButton("Calibration")
        self._pred_tab_btn  = QPushButton("Live Prediction")
        for btn, idx in [(self._calib_tab_btn, 0), (self._pred_tab_btn, 1)]:
            b = btn
            i = idx
            b.clicked.connect(lambda _, x=i: self._stack.setCurrentIndex(x))
        tab_row.addWidget(self._calib_tab_btn)
        tab_row.addWidget(self._pred_tab_btn)
        calib_layout.addLayout(tab_row)
        calib_layout.addWidget(self._stack)
        root.addWidget(calib_group)

        self._status_bar = QLabel("Not connected")
        self._status_bar.setStyleSheet(
            f"color: {_PALETTE['subtext']}; font-size: 11px; padding: 2px 4px;")
        root.addWidget(self._status_bar)

        # -- wire signals --
        self._signals.emg_received.connect(self._on_emg)
        self._signals.gesture_pred.connect(self._gest_display.update_prediction)
        self._signals.status_changed.connect(self._status_bar.setText)
        self._signals.connected.connect(self._on_connected)
        self._signals.disconnected.connect(self._on_disconnected)

        # -- smooth display timer --
        self._display_timer = QTimer()
        self._display_timer.setInterval(33)   # ~30 fps
        self._display_timer.timeout.connect(self._update_display)

    # ── UI builders ──────────────────────────────────────────────────────────

    def _build_connection_panel(self):
        grp = QGroupBox("Connection")
        row = QHBoxLayout(grp)

        self._mode_combo = QComboBox()
        modes = []
        if BLEAK_AVAILABLE:
            modes.append("Direct BLE (bleak)")
        if OSC_AVAILABLE:
            modes.append("OSC Bridge (myo-osc)")
        if not modes:
            modes.append("Install bleak or python-osc")
        self._mode_combo.addItems(modes)
        row.addWidget(QLabel("Mode:"))
        row.addWidget(self._mode_combo)

        # COM port entry (for USB dongle or OSC port)
        from PyQt6.QtWidgets import QLineEdit
        self._com_edit = QLineEdit()
        self._com_edit.setPlaceholderText("COM port (e.g. COM4) — blank = auto")
        self._com_edit.setMaximumWidth(200)
        self._com_edit.setVisible(False)  # bleak uses BLE name scan, no COM port needed
        row.addWidget(self._com_edit)

        self._port_spin = QSpinBox()
        self._port_spin.setRange(1024, 65535)
        self._port_spin.setValue(8000)
        self._port_spin.setPrefix("Port: ")
        self._port_spin.setVisible(False)
        row.addWidget(self._port_spin)

        def _on_mode_changed():
            is_osc = "OSC" in self._mode_combo.currentText()
            self._port_spin.setVisible(is_osc)
            self._com_edit.setVisible(not is_osc and PYOMYO_AVAILABLE)

        self._mode_combo.currentIndexChanged.connect(lambda _: _on_mode_changed())

        self._connect_btn = QPushButton("Connect")
        self._connect_btn.setStyleSheet(f"""
            QPushButton {{
                background: {_PALETTE['green']};
                color: white;
                font-weight: bold;
                border: none;
                border-radius: 4px;
                padding: 5px 16px;
            }}
            QPushButton:hover {{ background: #4dcc65; }}
        """)
        self._connect_btn.clicked.connect(self._toggle_connect)
        row.addWidget(self._connect_btn)

        self._lsl_btn = QPushButton("Start LSL Stream")
        self._lsl_btn.setEnabled(False)
        self._lsl_btn.clicked.connect(self._toggle_lsl)
        row.addWidget(self._lsl_btn)

        return grp

    def _build_emg_panel(self):
        grp = QGroupBox("Raw EMG  (8 channels)")
        lay = QVBoxLayout(grp)
        self._emg_bars = EmgBarsWidget()
        lay.addWidget(self._emg_bars)
        return grp

    # ── slots ────────────────────────────────────────────────────────────────

    def _toggle_connect(self):
        if self._worker is not None:
            self._disconnect()
            return
        mode = self._mode_combo.currentText()
        if "BLE" in mode or "pyomyo" in mode:
            self._worker = _DirectMyoWorker(self._signals, self._com_edit.text())
        elif "OSC" in mode:
            self._worker = _OscMyoWorker(self._signals, self._port_spin.value())
        else:
            QMessageBox.warning(self, "No Driver",
                "Install pyomyo (direct BLE) or python-osc (myo-osc bridge).")
            return
        self._worker.start()
        self._connect_btn.setText("Disconnect")
        self._connect_btn.setStyleSheet(f"""
            QPushButton {{
                background: {_PALETTE['orange']};
                color: white;
                font-weight: bold;
                border: none;
                border-radius: 4px;
                padding: 5px 16px;
            }}
        """)
        self._status_bar.setText("Connecting…")

    def _disconnect(self):
        if self._worker:
            self._worker.stop()
            self._worker = None
        self._display_timer.stop()
        self._connect_btn.setText("Connect")
        self._connect_btn.setStyleSheet(f"""
            QPushButton {{
                background: {_PALETTE['green']};
                color: white;
                font-weight: bold;
                border: none;
                border-radius: 4px;
                padding: 5px 16px;
            }}
        """)
        self._status_bar.setText("Disconnected")

    def _on_connected(self):
        self._display_timer.start()
        self._lsl_btn.setEnabled(True)

    def _on_disconnected(self):
        self._display_timer.stop()
        self._lsl_btn.setEnabled(False)
        self._worker = None
        self._connect_btn.setText("Connect")

    def _toggle_lsl(self):
        if self._emg_outlet is None:
            self._emg_outlet   = _make_emg_outlet()
            self._gest_outlet  = _make_gesture_outlet()
            if self._emg_outlet:
                self._lsl_btn.setText("Stop LSL Stream")
                self._status_bar.setText(
                    "LSL stream active — 'MyoEMG' visible to main GUI")
            else:
                self._status_bar.setText("pylsl not available — install pylsl")
        else:
            self._emg_outlet  = None
            self._gest_outlet = None
            self._lsl_btn.setText("Start LSL Stream")
            self._status_bar.setText("LSL stream stopped")

    # latest EMG snapshot (updated from Qt main thread via signal)
    _latest_emg: list = [0.0] * N_CH

    def _on_emg(self, vals: list):
        self._latest_emg = vals

        # Feed calibration wizard's ring buffer
        sample = np.array(vals, dtype=np.float32)
        self._emg_ring[self._ring_ptr % len(self._emg_ring)] = sample
        self._ring_ptr += 1
        self._calib.push_emg(vals)

        # Push to LSL
        if self._emg_outlet:
            try:
                self._emg_outlet.push_sample(vals)
            except Exception:
                pass

        # Run classifier if trained
        if self._classifier is not None and self._ring_ptr % STEP_SAMPLES == 0:
            seg = np.roll(self._emg_ring, -self._ring_ptr, axis=0)[-WIN_SAMPLES:]
            feat = np.concatenate([
                np.mean(np.abs(seg), axis=0),
                np.sqrt(np.mean(seg ** 2, axis=0)),
            ]).reshape(1, -1)
            try:
                pred  = int(self._classifier.predict(feat)[0])
                proba = float(np.max(self._classifier.predict_proba(feat)))
                self._signals.gesture_pred.emit(pred, proba)
                if self._gest_outlet:
                    self._gest_outlet.push_sample([GESTURES[pred][0]])
            except Exception:
                pass

    def _update_display(self):
        self._emg_bars.set_values(self._latest_emg)

    def _on_calibration_done(self, X: list, y: list):
        if not SKLEARN_AVAILABLE:
            self._status_bar.setText(
                "scikit-learn not installed — install sklearn to enable classifier")
            return

        X_arr = np.array(X, dtype=np.float32)
        y_arr = np.array(y, dtype=int)

        self._classifier = LinearDiscriminantAnalysis(solver="svd")
        try:
            scores = cross_val_score(self._classifier, X_arr, y_arr, cv=5)
            acc = float(np.mean(scores)) * 100
        except Exception:
            acc = 0.0

        self._classifier.fit(X_arr, y_arr)
        self._status_bar.setText(
            f"Classifier trained  |  CV accuracy: {acc:.1f}%  |  Switch to Live Prediction tab")
        self._stack.setCurrentIndex(1)

    def closeEvent(self, event):
        self._disconnect()
        super().closeEvent(event)
