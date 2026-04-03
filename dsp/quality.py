"""
Signal quality metrics for EEG channels. No Qt imports.

Provides SignalQualityMonitor which evaluates per-channel quality using three
metrics: flatline detection (std below threshold), spike detection (samples
beyond IQR-based outlier threshold), and SNR proxy (variance ratio between
recent and full window).

Intended for real-time use: compute() accepts a (n_channels, n_samples) numpy
array and returns a dict mapping channel index to a quality label.
"""

from __future__ import annotations

import numpy as np


class SignalQualityMonitor:
    """Per-channel EEG signal quality monitor based on three numpy metrics.

    Parameters
    ----------
    flatline_std_uv : float
        Channels with std < this value are considered flatlined (default 1.0 uV).
    spike_iqr_multiplier : float
        Any sample more than this many IQRs from the median triggers spike
        detection (default 6.0).
    snr_variance_ratio : float
        If the ratio of recent-half variance to full-window variance exceeds
        this value (or its inverse falls below 1/this), the channel is flagged
        (default 2.0).
    """

    def __init__(
        self,
        flatline_std_uv: float = 1.0,
        spike_iqr_multiplier: float = 6.0,
        snr_variance_ratio: float = 2.0,
    ) -> None:
        self.flatline_std_uv = flatline_std_uv
        self.spike_iqr_multiplier = spike_iqr_multiplier
        self.snr_variance_ratio = snr_variance_ratio

    def compute(self, data: np.ndarray) -> dict[int, str]:
        """Compute per-channel quality labels.

        Parameters
        ----------
        data : np.ndarray
            Shape (n_channels, n_samples), float64. At least 4 samples required
            for IQR computation.

        Returns
        -------
        dict[int, str]
            Maps channel index to one of "good", "marginal", or "bad".
            "good"     -- 0 metrics triggered
            "marginal" -- exactly 1 metric triggered
            "bad"      -- 2 or more metrics triggered
        """
        n_channels = data.shape[0]
        result: dict[int, str] = {}

        for ch in range(n_channels):
            signal = data[ch]
            bad_count = 0

            # Metric 1: flatline detection
            if np.std(signal) < self.flatline_std_uv:
                bad_count += 1

            # Metric 2: spike detection (IQR-based outlier)
            q75 = float(np.percentile(signal, 75))
            q25 = float(np.percentile(signal, 25))
            iqr = q75 - q25
            median = float(np.median(signal))
            if iqr > 0.0:
                threshold = self.spike_iqr_multiplier * iqr
                if np.any(np.abs(signal - median) > threshold):
                    bad_count += 1
            else:
                # IQR == 0: signal is mostly constant at the median value.
                # Still flag as spiking if any sample deviates substantially
                # (more than spike_iqr_multiplier * 1.0 uV minimum sensitivity)
                # This catches the case of a near-flat baseline with rare extreme spikes.
                max_dev = float(np.max(np.abs(signal - median)))
                if max_dev > self.spike_iqr_multiplier:
                    bad_count += 1

            # Metric 3: SNR proxy (variance ratio between recent half and full)
            n = len(signal)
            half = n // 2
            var_full = float(np.var(signal))
            if var_full < 1e-12:
                # Near-zero full variance -- flatline already flagged; ratio is 0
                ratio = 0.0
            else:
                var_recent = float(np.var(signal[n - half:]))
                ratio = var_recent / var_full

            if ratio > self.snr_variance_ratio or (ratio > 0 and ratio < 1.0 / self.snr_variance_ratio):
                bad_count += 1

            if bad_count == 0:
                result[ch] = "good"
            elif bad_count == 1:
                result[ch] = "marginal"
            else:
                result[ch] = "bad"

        return result
