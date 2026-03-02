"""
Prosthetic Control GUI
======================
Real-time EMG decoding with a per-finger heatmap hand visualization.

Features:
- Auto-detects EMG channels from a BrainFlow board (NOT EEG channels)
- Calibration wizard: relax baseline → per-channel flexion recording
- Real-time RMS-based decoder with adjustable sensitivity
- Stylized hand widget colored green (relaxed) → red (flexed) per finger
"""

import numpy as np
import time

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QGroupBox, QGridLayout, QProgressBar, QSlider, QSizePolicy,
    QMessageBox, QWidget,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QFont

try:
    from brainflow.board_shim import BoardShim
    BRAINFLOW_AVAILABLE = True
except ImportError:
    BRAINFLOW_AVAILABLE = False


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
FINGER_NAMES = ["Thumb", "Index", "Middle", "Ring", "Pinky"]

_BG       = QColor(28,  30,  40)
_PALM     = QColor(220, 190, 160, 200)
_OUTLINE  = QColor(160, 130, 100)


def _flex_color(flex: float) -> QColor:
    """Interpolate green → yellow → red based on flex [0..1]."""
    r = int(50  + 170 * flex)
    g = int(200 - 150 * flex)
    return QColor(r, g, 50, 230)


# ---------------------------------------------------------------------------
# Hand Widget
# ---------------------------------------------------------------------------
class HandWidget(QWidget):
    """Draws a stylized flat hand with per-finger heat colours."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(260, 360)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._flexion = [0.0] * 5   # [thumb, index, middle, ring, pinky]

    def set_flexion(self, values: list):
        self._flexion = list(values[:5]) + [0.0] * max(0, 5 - len(values))
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        W, H = self.width(), self.height()
        p.fillRect(0, 0, W, H, _BG)

        # --- palm ---
        pw = int(W * 0.46)
        ph = int(H * 0.38)
        px = (W - pw) // 2
        py = int(H * 0.47)
        p.setBrush(QBrush(_PALM))
        p.setPen(QPen(_OUTLINE, 1.5))
        p.drawRoundedRect(px, py, pw, ph, 14, 14)

        # --- fingers (index=1..4, drawn above palm) ---
        fw = int(pw * 0.17)
        gap = int(pw * 0.205)
        # Proportional heights: index, middle, ring, pinky
        h_ratios = [0.28, 0.32, 0.27, 0.22]
        for slot, fi in enumerate([1, 2, 3, 4]):  # finger index into FINGER_NAMES
            fh = int(H * h_ratios[slot])
            fx = px + int(slot * gap) + int(gap * 0.05)
            fy = py - fh
            p.setBrush(QBrush(_flex_color(self._flexion[fi])))
            p.setPen(QPen(_OUTLINE, 1))
            p.drawRoundedRect(fx, fy, fw, fh, 6, 6)
            # Label
            p.setPen(QPen(QColor(230, 230, 230), 1))
            font = QFont()
            font.setPointSize(6)
            p.setFont(font)
            p.drawText(fx + 1, fy - 3, FINGER_NAMES[fi][:3])

        # --- thumb (to the left of palm) ---
        tw = int(fw * 1.1)
        th = int(H * 0.22)
        tx = px - tw - 6
        ty = py + int(ph * 0.15)
        p.setBrush(QBrush(_flex_color(self._flexion[0])))
        p.setPen(QPen(_OUTLINE, 1))
        p.drawRoundedRect(tx, ty, tw, th, 6, 6)
        p.setPen(QPen(QColor(230, 230, 230), 1))
        font = QFont()
        font.setPointSize(6)
        p.setFont(font)
        p.drawText(tx + 1, ty - 3, "Thm")

        p.end()


# ---------------------------------------------------------------------------
# Calibration Dialog
# ---------------------------------------------------------------------------
class CalibrationDialog(QDialog):
    """
    Guides the user through:
      1. Relax baseline (3 s)
      2. Per-channel flexion recording (3 s each)
    Receives EMG samples via push_sample() called from an external timer.
    """

    RECORD_SECS = 3
    TICK_MS     = 33   # ~30 Hz UI update

    def __init__(self, channel_count: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("EMG Calibration")
        self.setModal(True)
        self.resize(420, 220)

        self.channel_count = channel_count
        self.calibration_data = {
            'relax': None,
            'flex' : [None] * channel_count,
        }

        self._phase    = 'intro'
        self._ch_idx   = 0
        self._buf      = []
        self._ticks    = 0
        self._max_ticks = int(self.RECORD_SECS * 1000 / self.TICK_MS)

        # --- UI ---
        layout = QVBoxLayout()

        self.info_lbl = QLabel(
            "This wizard will record your muscle activity.\n\n"
            "Step 1 — Relax all fingers for 3 seconds.\n"
            "Step 2 — Flex each finger individually for 3 seconds."
        )
        self.info_lbl.setWordWrap(True)
        self.info_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.info_lbl)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        layout.addWidget(self.progress)

        self.action_btn = QPushButton("Start")
        self.action_btn.clicked.connect(self._advance)
        layout.addWidget(self.action_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        layout.addWidget(cancel_btn)

        self.setLayout(layout)

        self._tick_timer = QTimer()
        self._tick_timer.timeout.connect(self._tick)

    # --- public API --------------------------------------------------------

    def push_sample(self, emg_sample):
        """Feed latest EMG snapshot (array length = channel_count)."""
        if self._phase in ('relax_rec', 'flex_rec'):
            self._buf.append(list(emg_sample))

    # --- internals ---------------------------------------------------------

    def _advance(self):
        if self._phase == 'intro':
            self._begin_record('relax_rec',
                               "RELAX all fingers…\nRecording for 3 seconds.")

        elif self._phase == 'relax_done':
            fname = FINGER_NAMES[self._ch_idx] if self._ch_idx < 5 else f"Channel {self._ch_idx}"
            self._begin_record('flex_rec',
                               f"FLEX your {fname} now…\nRecording for 3 seconds.")

        elif self._phase == 'flex_done':
            self._ch_idx += 1
            if self._ch_idx >= self.channel_count:
                self._phase = 'complete'
                self.info_lbl.setText("Calibration complete!")
                self.action_btn.setText("Done")
                self.action_btn.clicked.disconnect()
                self.action_btn.clicked.connect(self.accept)
            else:
                fname = FINGER_NAMES[self._ch_idx] if self._ch_idx < 5 else f"Channel {self._ch_idx}"
                self._phase = 'relax_done'   # re-use same gate
                self.info_lbl.setText(
                    f"Channel {self._ch_idx - 1} done!\n\n"
                    f"Next: FLEX {fname}.\nPress 'Next' when ready."
                )
                self.action_btn.setText("Next")

    def _begin_record(self, phase: str, msg: str):
        self._phase  = phase
        self._buf    = []
        self._ticks  = 0
        self.info_lbl.setText(msg)
        self.action_btn.setEnabled(False)
        self.progress.setValue(0)
        self._tick_timer.start(self.TICK_MS)

    def _tick(self):
        self._ticks += 1
        self.progress.setValue(int(100 * self._ticks / self._max_ticks))
        if self._ticks >= self._max_ticks:
            self._tick_timer.stop()
            arr = np.array(self._buf, dtype=float) if self._buf else np.zeros((1, self.channel_count))
            rms = np.sqrt(np.mean(arr ** 2, axis=0))  # (channel_count,)

            if self._phase == 'relax_rec':
                self.calibration_data['relax'] = rms
                self._phase = 'relax_done'
                fname = FINGER_NAMES[0] if self.channel_count > 0 else "Channel 0"
                self.info_lbl.setText(
                    f"Relax recorded.\n\nNext: FLEX {fname}.\nPress 'Next' when ready."
                )
                self.action_btn.setText("Next")
                self.action_btn.setEnabled(True)

            elif self._phase == 'flex_rec':
                self.calibration_data['flex'][self._ch_idx] = rms
                self._phase = 'flex_done'
                self.action_btn.setText("Next")
                self.action_btn.setEnabled(True)
                self._advance()   # auto-advance or prompt next


# ---------------------------------------------------------------------------
# Main Prosthetic Window
# ---------------------------------------------------------------------------
class ProstheticWindow(QDialog):
    """Real-time prosthetic control with EMG decoding and hand visualization."""

    _DECODE_MS = 33   # ~30 Hz

    def __init__(self, board=None, board_id=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Prosthetic Control")
        self.resize(750, 560)

        self.board    = board
        self.board_id = board_id

        # Detect EMG (not EEG) channels
        self.emg_channels: list[int] = []
        self.sampling_rate: int      = 250
        if board is not None and BRAINFLOW_AVAILABLE and board_id is not None:
            try:
                self.emg_channels  = list(BoardShim.get_emg_channels(board_id))
                self.sampling_rate = int(BoardShim.get_sampling_rate(board_id))
            except Exception:
                pass

        self.num_emg = len(self.emg_channels)

        # Calibration state
        self._calib_relax: np.ndarray | None = None   # (num_emg,)
        self._calib_flex:  np.ndarray | None = None   # (num_emg, num_emg)
        self._calibrated = False

        # Decode timer
        self._decode_timer = QTimer()
        self._decode_timer.timeout.connect(self._decode_step)

        self._setup_ui()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _setup_ui(self):
        root = QHBoxLayout()

        # ---- Left: hand + activity bars ----
        left = QVBoxLayout()

        self.hand_widget = HandWidget()
        left.addWidget(self.hand_widget)

        act_group = QGroupBox("EMG Activity")
        act_layout = QGridLayout()
        self._bars: list[QProgressBar] = []
        for i in range(self.num_emg):
            name = FINGER_NAMES[i] if i < 5 else f"Ch {i}"
            act_layout.addWidget(QLabel(name), i, 0)
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setTextVisible(False)
            act_layout.addWidget(bar, i, 1)
            self._bars.append(bar)
        act_group.setLayout(act_layout)
        left.addWidget(act_group)

        root.addLayout(left, stretch=2)

        # ---- Right: controls ----
        right = QVBoxLayout()
        right.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Status
        status_grp = QGroupBox("Status")
        status_lay = QVBoxLayout()
        if self.num_emg == 0:
            msg = "No EMG channels detected.\nConnect a BrainFlow board first."
            color = "orange"
        else:
            ch_str = ", ".join(str(c) for c in self.emg_channels)
            msg    = f"EMG channels: [{ch_str}]\n{self.num_emg} ch @ {self.sampling_rate} Hz"
            color  = "lime"
        self._status_lbl = QLabel(msg)
        self._status_lbl.setStyleSheet(f"color: {color};")
        self._status_lbl.setWordWrap(True)
        status_lay.addWidget(self._status_lbl)
        status_grp.setLayout(status_lay)
        right.addWidget(status_grp)

        # Calibration
        calib_grp = QGroupBox("Calibration")
        calib_lay = QVBoxLayout()
        self._calib_lbl = QLabel("Not calibrated")
        self._calib_lbl.setStyleSheet("color: orange;")
        calib_lay.addWidget(self._calib_lbl)
        calib_btn = QPushButton("Run Calibration Wizard")
        calib_btn.clicked.connect(self._run_calibration)
        calib_lay.addWidget(calib_btn)
        calib_grp.setLayout(calib_lay)
        right.addWidget(calib_grp)

        # Decoding
        decode_grp = QGroupBox("Decoding")
        decode_lay = QVBoxLayout()

        self._decode_btn = QPushButton("Start Decoding")
        self._decode_btn.setEnabled(False)
        self._decode_btn.setStyleSheet(
            "background-color: #4CAF50; color: white; font-weight: bold;"
        )
        self._decode_btn.clicked.connect(self._toggle_decoding)
        decode_lay.addWidget(self._decode_btn)

        sens_row = QHBoxLayout()
        sens_row.addWidget(QLabel("Sensitivity:"))
        self._sens_slider = QSlider(Qt.Orientation.Horizontal)
        self._sens_slider.setRange(10, 90)
        self._sens_slider.setValue(50)
        self._sens_lbl = QLabel("50%")
        self._sens_slider.valueChanged.connect(lambda v: self._sens_lbl.setText(f"{v}%"))
        sens_row.addWidget(self._sens_slider)
        sens_row.addWidget(self._sens_lbl)
        decode_lay.addLayout(sens_row)
        decode_grp.setLayout(decode_lay)
        right.addWidget(decode_grp)

        # Per-finger state labels
        pred_grp = QGroupBox("Finger State")
        pred_lay = QGridLayout()
        self._pred_lbls: list[QLabel] = []
        for i in range(min(self.num_emg, 5)):
            pred_lay.addWidget(QLabel(FINGER_NAMES[i] + ":"), i, 0)
            lbl = QLabel("—")
            lbl.setStyleSheet("color: gray;")
            pred_lay.addWidget(lbl, i, 1)
            self._pred_lbls.append(lbl)
        pred_grp.setLayout(pred_lay)
        right.addWidget(pred_grp)

        root.addLayout(right, stretch=1)
        self.setLayout(root)

    # ------------------------------------------------------------------
    # Calibration
    # ------------------------------------------------------------------
    def _run_calibration(self):
        if self.board is None:
            QMessageBox.warning(self, "No Board",
                                "No BrainFlow board is connected.\n"
                                "Connect a headset first, then open Prosthetic Control.")
            return
        if self.num_emg == 0:
            QMessageBox.warning(self, "No EMG Channels",
                                "No EMG channels were detected for this board.\n"
                                "Check BrainFlow board type.")
            return

        dlg = CalibrationDialog(self.num_emg, parent=self)

        # Feed EMG samples to the dialog at ~30 Hz
        feed_timer = QTimer(self)

        def _feed():
            if not dlg.isVisible():
                feed_timer.stop()
                return
            try:
                data = self.board.get_current_board_data(32)
                if data.shape[1] == 0:
                    return
                emg = data[self.emg_channels, :].T   # (N, num_emg)
                for row in emg:
                    dlg.push_sample(row)
            except Exception:
                pass

        feed_timer.timeout.connect(_feed)
        feed_timer.start(33)

        if dlg.exec() == QDialog.DialogCode.Accepted:
            cd = dlg.calibration_data
            if cd['relax'] is not None:
                self._calib_relax = cd['relax']
            flex_list = cd['flex']
            if all(f is not None for f in flex_list):
                self._calib_flex = np.array(flex_list)   # (num_emg, num_emg)
            self._calibrated = True
            self._calib_lbl.setText("Calibrated ✓")
            self._calib_lbl.setStyleSheet("color: lime;")
            self._decode_btn.setEnabled(True)

        feed_timer.stop()

    # ------------------------------------------------------------------
    # Decoding
    # ------------------------------------------------------------------
    def _toggle_decoding(self):
        if self._decode_timer.isActive():
            self._decode_timer.stop()
            self._decode_btn.setText("Start Decoding")
            self._decode_btn.setStyleSheet(
                "background-color: #4CAF50; color: white; font-weight: bold;"
            )
            self.hand_widget.set_flexion([0.0] * 5)
            for lbl in self._pred_lbls:
                lbl.setText("—")
                lbl.setStyleSheet("color: gray;")
        else:
            self._decode_timer.start(self._DECODE_MS)
            self._decode_btn.setText("Stop Decoding")
            self._decode_btn.setStyleSheet(
                "background-color: #f44336; color: white; font-weight: bold;"
            )

    def _decode_step(self):
        if self.board is None or not self.emg_channels:
            return
        try:
            win = max(10, int(0.2 * self.sampling_rate))   # 200 ms window
            data = self.board.get_current_board_data(win)
            if data.shape[1] < 5:
                return

            emg = data[self.emg_channels, :]            # (num_emg, N)
            rms = np.sqrt(np.mean(emg ** 2, axis=1))   # (num_emg,)

            # Update activity bars (scale to ~500 µV max)
            for i, (bar, r) in enumerate(zip(self._bars, rms)):
                bar.setValue(int(min(100, r / 500.0 * 100)))

            if not self._calibrated:
                return

            # Per-channel binary decode with continuous confidence
            sensitivity = self._sens_slider.value() / 100.0
            flexion: list[float] = []
            for i in range(self.num_emg):
                relax_rms = float(self._calib_relax[i]) if self._calib_relax is not None else 1.0
                flex_rms  = (float(self._calib_flex[i, i])
                             if self._calib_flex is not None else relax_rms * 3.0)
                span = flex_rms - relax_rms
                if span <= 0:
                    flexion.append(0.0)
                    continue
                # threshold moves closer to relax as sensitivity increases
                threshold = relax_rms + span * (1.0 - sensitivity)
                pred = float(np.clip((rms[i] - relax_rms) / span, 0.0, 1.0))
                flexion.append(pred)

            # Update hand (map up to 5 channels → fingers)
            hand_flex = (flexion[:5] + [0.0] * 5)[:5]
            self.hand_widget.set_flexion(hand_flex)

            # Update per-finger prediction labels
            for i, (lbl, f) in enumerate(zip(self._pred_lbls, flexion)):
                if f > 0.5:
                    lbl.setText("FLEXED")
                    lbl.setStyleSheet("color: #ff4444; font-weight: bold;")
                else:
                    lbl.setText("Relaxed")
                    lbl.setStyleSheet("color: #44ff44;")

        except Exception:
            pass

    # ------------------------------------------------------------------
    def closeEvent(self, event):
        self._decode_timer.stop()
        super().closeEvent(event)
