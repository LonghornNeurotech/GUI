"""
Band power extraction and control signal computation for BCI. No Qt imports.

Provides BandPowerExtractor for mu-rhythm (8-13 Hz) power via Welch PSD,
RestBaselineTracker for z-score normalization against REST-period baseline,
and ControlSignals as a frozen output dataclass.

Intended for real-time use: feed per-sample C3/C4 data, get control signals
for cursor decoding (LR = z_C4 - z_C3, UD = z_C3 + z_C4).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import numpy as np
from scipy.signal import welch


@dataclass(frozen=True)
class ControlSignals:
    """Immutable output of the band power pipeline.

    Attributes
    ----------
    lr : float
        Left-right control signal (z_C4 - z_C3). Positive = right imagery.
    ud : float
        Up-down control signal (z_C3 + z_C4). Positive = bilateral ERD.
    mu_c3 : float
        Raw mu power at C3 (not log-transformed).
    mu_c4 : float
        Raw mu power at C4 (not log-transformed).
    baseline_ready : bool
        True when enough REST samples have been collected for z-scoring.
    """

    lr: float
    ud: float
    mu_c3: float
    mu_c4: float
    baseline_ready: bool


class BandPowerExtractor:
    """Per-channel mu-rhythm band power via Welch PSD.

    Accumulates samples in ring buffers (one per channel). When the buffer
    reaches nperseg samples, computes band power via scipy.signal.welch and
    numpy.trapz integration over the mu band.

    Parameters
    ----------
    fs : float
        Sampling frequency in Hz (default 250.0).
    mu_low : float
        Lower bound of mu band in Hz (default 8.0).
    mu_high : float
        Upper bound of mu band in Hz (default 13.0).
    nperseg : int
        Welch window length in samples (default 256).
    """

    def __init__(
        self,
        fs: float = 250.0,
        mu_low: float = 8.0,
        mu_high: float = 13.0,
        nperseg: int = 256,
    ) -> None:
        self.fs = fs
        self.mu_low = mu_low
        self.mu_high = mu_high
        self.nperseg = nperseg
        self._buffers: dict[str, deque[float]] = {
            "c3": deque(maxlen=nperseg),
            "c4": deque(maxlen=nperseg),
        }

    def update(
        self, c3_data: np.ndarray, c4_data: np.ndarray
    ) -> tuple[float, float] | None:
        """Feed new samples and compute mu power if buffer is full.

        Parameters
        ----------
        c3_data : np.ndarray
            New C3 samples (1-D array).
        c4_data : np.ndarray
            New C4 samples (1-D array).

        Returns
        -------
        tuple[float, float] | None
            (mu_c3, mu_c4) if buffer has >= nperseg samples, else None.
        """
        self._buffers["c3"].extend(c3_data.ravel())
        self._buffers["c4"].extend(c4_data.ravel())

        if len(self._buffers["c3"]) < self.nperseg:
            return None

        mu_c3 = self._compute_mu_power(np.array(self._buffers["c3"]))
        mu_c4 = self._compute_mu_power(np.array(self._buffers["c4"]))
        return (float(mu_c3), float(mu_c4))

    def _compute_mu_power(self, signal: np.ndarray) -> float:
        """Compute mu-band power from a signal segment via Welch PSD.

        Parameters
        ----------
        signal : np.ndarray
            1-D signal array of length nperseg.

        Returns
        -------
        float
            Integrated power in the mu band (mu_low..mu_high Hz).
        """
        freqs, psd = welch(signal, fs=self.fs, nperseg=self.nperseg)
        mask = (freqs >= self.mu_low) & (freqs <= self.mu_high)
        return float(np.trapezoid(psd[mask], freqs[mask]))

    def reset(self) -> None:
        """Clear all internal buffers."""
        for buf in self._buffers.values():
            buf.clear()


class RestBaselineTracker:
    """Accumulates log mu power during REST and produces z-scored control signals.

    Only accumulates when the current state is REST. Z-scores C3 and C4
    independently, then computes LR = z_C4 - z_C3 and UD = z_C3 + z_C4.

    Parameters
    ----------
    max_samples : int
        Maximum number of REST samples to retain (rolling window, default 470).
    min_baseline : int
        Minimum REST samples before z-scoring is valid (default 10).
    """

    def __init__(self, max_samples: int = 470, min_baseline: int = 10) -> None:
        self.max_samples = max_samples
        self.min_baseline = min_baseline
        self._c3_log: deque[float] = deque(maxlen=max_samples)
        self._c4_log: deque[float] = deque(maxlen=max_samples)
        self._is_rest: bool = False

    def set_state(self, state: str) -> None:
        """Set the current task state. Only 'REST' enables accumulation.

        Parameters
        ----------
        state : str
            Task state label (e.g. "REST", "LEFT", "RIGHT", "CUE").
        """
        self._is_rest = state.upper() == "REST"

    def accumulate(self, mu_c3: float, mu_c4: float) -> None:
        """Store log-transformed mu power if currently in REST state.

        Parameters
        ----------
        mu_c3 : float
            Raw mu power at C3.
        mu_c4 : float
            Raw mu power at C4.
        """
        if not self._is_rest:
            return
        self._c3_log.append(np.log(mu_c3 + 1e-12))
        self._c4_log.append(np.log(mu_c4 + 1e-12))

    def compute_control_signals(
        self, mu_c3: float, mu_c4: float
    ) -> ControlSignals:
        """Compute z-scored control signals from current mu power.

        Parameters
        ----------
        mu_c3 : float
            Current raw mu power at C3.
        mu_c4 : float
            Current raw mu power at C4.

        Returns
        -------
        ControlSignals
            Frozen dataclass with lr, ud, mu_c3, mu_c4, baseline_ready.
            If baseline not ready, lr=0.0, ud=0.0, baseline_ready=False.
        """
        if len(self._c3_log) < self.min_baseline:
            return ControlSignals(
                lr=0.0, ud=0.0, mu_c3=mu_c3, mu_c4=mu_c4, baseline_ready=False
            )

        log_c3 = np.log(mu_c3 + 1e-12)
        log_c4 = np.log(mu_c4 + 1e-12)

        c3_arr = np.array(self._c3_log)
        c4_arr = np.array(self._c4_log)

        z_c3 = (log_c3 - float(np.mean(c3_arr))) / max(float(np.std(c3_arr)), 1e-12)
        z_c4 = (log_c4 - float(np.mean(c4_arr))) / max(float(np.std(c4_arr)), 1e-12)

        lr = z_c4 - z_c3
        ud = z_c3 + z_c4

        return ControlSignals(
            lr=float(lr),
            ud=float(ud),
            mu_c3=mu_c3,
            mu_c4=mu_c4,
            baseline_ready=True,
        )

    def reset(self) -> None:
        """Clear baseline buffers (re-baseline)."""
        self._c3_log.clear()
        self._c4_log.clear()
