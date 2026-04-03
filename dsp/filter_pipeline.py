"""
Causal (streaming) IIR filter pipeline. Do not use sosfiltfilt here — it is non-causal.

This module provides FilterStage and FilterPipeline for real-time EEG/EMG signal
processing. All filtering uses sosfilt (second-order sections) with persistent
per-channel zi state vectors so that filter state is maintained across streaming
chunks without startup transients.

No Qt imports. This module is intentionally standalone and fully headless-testable.
"""

from __future__ import annotations

import numpy as np
from scipy.signal import butter, iirnotch, tf2sos, sosfilt, sosfilt_zi


class FilterStage:
    """Single IIR filter stage with per-channel stateful zi vectors.

    Parameters
    ----------
    name : str
        Human-readable label (e.g. "Bandpass 8.0-30.0 Hz").
    sos : np.ndarray
        Second-order sections array, shape (n_sections, 6).
    enabled : bool
        When False, process() returns data unchanged (zi is not updated).
    """

    def __init__(self, name: str, sos: np.ndarray, enabled: bool = True) -> None:
        self.name: str = name
        self.sos: np.ndarray = sos
        self.enabled: bool = enabled
        self._zi: dict[int, np.ndarray] = {}  # channel_idx -> zi array

    def reset_state(self, channel_idx: int | None = None) -> None:
        """Clear zi state for one channel or all channels.

        Parameters
        ----------
        channel_idx : int | None
            If None, clears all channels. Otherwise clears only that channel.
        """
        if channel_idx is None:
            self._zi.clear()
        else:
            self._zi.pop(channel_idx, None)

    def process(self, data: np.ndarray) -> np.ndarray:
        """Apply filter to data, maintaining zi state across calls.

        Parameters
        ----------
        data : np.ndarray
            Shape (n_channels, n_samples), float64.

        Returns
        -------
        np.ndarray
            Same shape as input. Returns input unchanged if ``self.enabled`` is False.
        """
        if not self.enabled:
            return data

        out = data.copy()
        # sosfilt_zi result is constant per SOS array — compute once outside the loop
        zi_template = sosfilt_zi(self.sos)  # shape: (n_sections, 2)

        for i in range(data.shape[0]):
            if i not in self._zi:
                # Initialize zi scaled to first sample to minimize startup transient
                self._zi[i] = zi_template * data[i, 0]
            out[i], self._zi[i] = sosfilt(self.sos, data[i], zi=self._zi[i])

        return out


class FilterPipeline:
    """Ordered chain of FilterStage objects applied sequentially to streaming data.

    Stages are applied in the order they were added. Adding or removing a stage
    does not reset the zi state of unaffected stages. Reordering (move_stage)
    resets all zi states because the filter order has changed.

    Example
    -------
    >>> pipeline = FilterPipeline()
    >>> pipeline.add_bandpass(8.0, 30.0, fs=250.0)
    >>> pipeline.add_notch(60.0, fs=250.0)
    >>> filtered = pipeline.process_chunk(raw_data)  # shape (n_channels, n_samples)
    """

    def __init__(self) -> None:
        self._stages: list[FilterStage] = []

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def stages(self) -> list[FilterStage]:
        """Read-only view of the ordered stage list."""
        return list(self._stages)

    def __len__(self) -> int:
        return len(self._stages)

    # ------------------------------------------------------------------
    # Stage construction helpers
    # ------------------------------------------------------------------

    def add_bandpass(
        self,
        lowcut: float,
        highcut: float,
        fs: float,
        order: int = 4,
    ) -> FilterStage:
        """Design and append a Butterworth bandpass stage.

        Parameters
        ----------
        lowcut, highcut : float
            Passband edges in Hz.
        fs : float
            Sample rate in Hz.
        order : int
            Filter order (default 4 — two second-order sections, good roll-off).

        Returns
        -------
        FilterStage
            The newly created stage (already appended to pipeline).
        """
        sos = butter(order, [lowcut, highcut], btype="band", fs=fs, output="sos")
        stage = FilterStage(f"Bandpass {lowcut}-{highcut} Hz", sos)
        self._stages.append(stage)
        return stage

    def add_notch(
        self,
        freq: float,
        q: float = 30.0,
        fs: float = 250.0,
    ) -> FilterStage:
        """Design and append a notch filter stage.

        iirnotch returns (b, a) coefficients; tf2sos converts to SOS form for
        numerical stability in the stateful sosfilt path.

        Parameters
        ----------
        freq : float
            Notch center frequency in Hz (commonly 50 or 60).
        q : float
            Quality factor — controls notch bandwidth (higher Q = narrower notch).
        fs : float
            Sample rate in Hz.

        Returns
        -------
        FilterStage
            The newly created stage (already appended to pipeline).
        """
        b, a = iirnotch(freq, q, fs=fs)
        sos = tf2sos(b, a)
        stage = FilterStage(f"Notch {freq} Hz", sos)
        self._stages.append(stage)
        return stage

    # ------------------------------------------------------------------
    # Stage management
    # ------------------------------------------------------------------

    def remove_stage(self, index: int) -> None:
        """Remove the stage at *index*.

        Does NOT reset zi state of remaining stages — only the removed stage
        is gone; all other stages retain their filter state.
        """
        if 0 <= index < len(self._stages):
            self._stages.pop(index)

    def move_stage(self, from_idx: int, to_idx: int) -> None:
        """Move a stage from *from_idx* to *to_idx* and reset ALL zi states.

        Reordering changes which filter sees which input signal, so all
        existing zi states are stale. A brief transient is acceptable.
        """
        if not (0 <= from_idx < len(self._stages)):
            return
        stage = self._stages.pop(from_idx)
        insert_at = max(0, min(to_idx, len(self._stages)))
        self._stages.insert(insert_at, stage)
        for s in self._stages:
            s.reset_state()

    # ------------------------------------------------------------------
    # Processing
    # ------------------------------------------------------------------

    def process_chunk(self, data: np.ndarray) -> np.ndarray:
        """Apply all enabled stages in order.

        Parameters
        ----------
        data : np.ndarray
            Shape (n_channels, n_samples).

        Returns
        -------
        np.ndarray
            Filtered data, same shape as input.
        """
        for stage in self._stages:
            data = stage.process(data)
        return data

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_config(self) -> list[dict]:
        """Serialize pipeline to a JSON-compatible list of dicts.

        Each dict has keys: ``type``, ``enabled``, and type-specific params
        (``lowcut``/``highcut`` for bandpass; ``freq`` for notch).

        Returns
        -------
        list[dict]
        """
        result: list[dict] = []
        for stage in self._stages:
            if stage.name.startswith("Bandpass"):
                # Name format: "Bandpass {lowcut}-{highcut} Hz"
                # Split on spaces: ["Bandpass", "{lowcut}-{highcut}", "Hz"]
                parts = stage.name.split()
                lo_str, hi_str = parts[1].split("-")
                result.append(
                    {
                        "type": "bandpass",
                        "lowcut": float(lo_str),
                        "highcut": float(hi_str),
                        "enabled": stage.enabled,
                    }
                )
            elif stage.name.startswith("Notch"):
                # Name format: "Notch {freq} Hz"
                # Split on spaces: ["Notch", "{freq}", "Hz"]
                parts = stage.name.split()
                result.append(
                    {
                        "type": "notch",
                        "freq": float(parts[1]),
                        "enabled": stage.enabled,
                    }
                )
        return result

    @classmethod
    def from_config(cls, config: list[dict], fs: float) -> "FilterPipeline":
        """Restore a FilterPipeline from a serialized config list.

        Parameters
        ----------
        config : list[dict]
            As produced by :meth:`to_config`.
        fs : float
            Sample rate in Hz (required to redesign filter coefficients).

        Returns
        -------
        FilterPipeline
        """
        pipeline = cls()
        for entry in config:
            t = entry.get("type", "")
            if t == "bandpass":
                stage = pipeline.add_bandpass(
                    float(entry["lowcut"]),
                    float(entry["highcut"]),
                    fs=fs,
                )
                stage.enabled = bool(entry.get("enabled", True))
            elif t == "notch":
                stage = pipeline.add_notch(float(entry["freq"]), fs=fs)
                stage.enabled = bool(entry.get("enabled", True))
        return pipeline


class SpatialFilterStage:
    """Spatial filter stage applying a linear mixing matrix W to EEG data.

    Encapsulates both Common Average Reference (CAR) and surface Laplacian
    spatial filters as an (n_channels x n_channels) weight matrix. The
    process() interface matches FilterStage so both can be used in the same
    pipeline loop.

    Parameters
    ----------
    name : str
        Human-readable label (e.g. "CAR 8ch" or "Laplacian 8ch").
    w : np.ndarray
        Weight matrix, shape (n_channels, n_channels).
    filter_type : str
        "car" or "laplacian".
    neighbors : dict[int, list[int]] | None
        Neighbor map used to construct Laplacian W. None for CAR stages.
    enabled : bool
        When False, process() returns data unchanged.
    """

    def __init__(
        self,
        name: str,
        w: np.ndarray,
        filter_type: str,
        neighbors: dict[int, list[int]] | None = None,
        enabled: bool = True,
    ) -> None:
        self.name = name
        self.w = w
        self.filter_type = filter_type
        self.neighbors = neighbors
        self.enabled = enabled

    # ------------------------------------------------------------------
    # Processing
    # ------------------------------------------------------------------

    def process(self, data: np.ndarray) -> np.ndarray:
        """Apply spatial filter to data.

        Parameters
        ----------
        data : np.ndarray
            Shape (n_channels, n_samples), float64.

        Returns
        -------
        np.ndarray
            Same shape as input. Returns input unchanged if ``self.enabled``
            is False.
        """
        if not self.enabled:
            return data
        return self.w @ data

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_config(self) -> dict:
        """Serialize to a JSON-compatible dict.

        The W matrix is stored as a nested list for lossless roundtrip. This
        ensures from_config can exactly reproduce the original filter regardless
        of which bad channels were excluded at construction time.

        Returns
        -------
        dict
            Keys: type, subtype, n_channels, w, neighbors, enabled.
        """
        return {
            "type": "spatial",
            "subtype": self.filter_type,
            "n_channels": self.w.shape[0],
            "w": self.w.tolist(),
            "neighbors": self.neighbors,
            "enabled": self.enabled,
        }

    @classmethod
    def from_config(cls, config: dict) -> "SpatialFilterStage":
        """Restore a SpatialFilterStage from a serialized config dict.

        Reconstructs the exact W matrix from the stored ``w`` field, so
        bad-channel exclusions are preserved across serialization roundtrips.

        Parameters
        ----------
        config : dict
            As produced by :meth:`to_config`.

        Returns
        -------
        SpatialFilterStage
        """
        subtype = config["subtype"]
        n_channels = int(config["n_channels"])
        enabled = bool(config.get("enabled", True))

        # Prefer stored W matrix for exact reconstruction
        if "w" in config:
            w = np.array(config["w"], dtype=np.float64)
            neighbors_raw = config.get("neighbors") or {}
            neighbors: dict[int, list[int]] | None = None
            if subtype == "laplacian" and neighbors_raw:
                neighbors = {int(k): v for k, v in neighbors_raw.items()}
            stage = cls(
                name=f"{'CAR' if subtype == 'car' else 'Laplacian'} {n_channels}ch",
                w=w,
                filter_type=subtype,
                neighbors=neighbors,
                enabled=enabled,
            )
            return stage

        # Legacy path: reconstruct from parameters (no W stored)
        if subtype == "car":
            stage = cls.make_car(n_channels=n_channels)
        elif subtype == "laplacian":
            neighbors_raw = config.get("neighbors") or {}
            neighbors_int = {int(k): v for k, v in neighbors_raw.items()}
            stage = cls.make_laplacian(n_channels=n_channels, neighbors=neighbors_int)
        else:
            stage = cls(
                name=f"Spatial {n_channels}ch",
                w=np.eye(n_channels),
                filter_type=subtype,
                enabled=enabled,
            )

        stage.enabled = enabled
        return stage

    # ------------------------------------------------------------------
    # Factory methods
    # ------------------------------------------------------------------

    @staticmethod
    def make_car(
        n_channels: int,
        bad_channels: set[int] | None = None,
    ) -> "SpatialFilterStage":
        """Build a Common Average Reference spatial filter stage.

        The reference signal is the mean of all *good* channels. Bad channels
        are excluded from the reference computation but their output is still
        computed (each channel minus the good-channel mean).

        If all channels are bad (empty good set), returns an identity matrix
        (passthrough) to avoid ZeroDivisionError.

        Parameters
        ----------
        n_channels : int
            Total number of EEG channels.
        bad_channels : set[int] | None
            Indices of channels to exclude from the reference mean. If None,
            treated as empty set (all channels used as reference).

        Returns
        -------
        SpatialFilterStage
        """
        if bad_channels is None:
            bad_channels = set()

        good = [i for i in range(n_channels) if i not in bad_channels]

        if len(good) == 0:
            # All channels bad -- return identity (passthrough)
            w = np.eye(n_channels)
        else:
            # W = I - (1/n_good) * reference_columns
            # Each column j is 1/n_good if j is a good channel, else 0
            w = np.eye(n_channels, dtype=np.float64)
            for j in good:
                w[:, j] -= 1.0 / len(good)

        return SpatialFilterStage(
            name=f"CAR {n_channels}ch",
            w=w,
            filter_type="car",
            neighbors=None,
            enabled=True,
        )

    @staticmethod
    def make_laplacian(
        n_channels: int,
        neighbors: dict[int, list[int]],
    ) -> "SpatialFilterStage":
        """Build a surface Laplacian spatial filter stage.

        For each channel with neighbors, the output is channel_input minus
        the mean of its neighbors' inputs. Channels with no entry in
        ``neighbors`` are passed through unchanged (identity row).

        If ``neighbors`` is empty, returns an identity matrix (passthrough).

        Parameters
        ----------
        n_channels : int
            Total number of EEG channels.
        neighbors : dict[int, list[int]]
            Maps each channel index to a list of its neighbor channel indices.

        Returns
        -------
        SpatialFilterStage
        """
        w = np.eye(n_channels, dtype=np.float64)

        for ch, nbrs in neighbors.items():
            if len(nbrs) == 0:
                continue
            weight = 1.0 / len(nbrs)
            for nbr in nbrs:
                w[ch, nbr] -= weight

        return SpatialFilterStage(
            name=f"Laplacian {n_channels}ch",
            w=w,
            filter_type="laplacian",
            neighbors=neighbors,
            enabled=True,
        )
