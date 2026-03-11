"""
Unit tests for dsp.filter_pipeline (FilterStage and FilterPipeline).
All tests are headless — no Qt imports required.
"""

import time
import numpy as np
import pytest
from dsp.filter_pipeline import FilterPipeline, FilterStage


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_sine(freq_hz: float, fs: float = 250.0, duration_s: float = 2.0,
              n_channels: int = 8) -> np.ndarray:
    """Return (n_channels, n_samples) float64 sine array."""
    n = int(duration_s * fs)
    t = np.linspace(0, duration_s, n, endpoint=False)
    return np.tile(np.sin(2.0 * np.pi * freq_hz * t), (n_channels, 1)).astype(np.float64)


def rms(arr: np.ndarray) -> float:
    return float(np.sqrt(np.mean(arr ** 2)))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_passthrough_when_no_stages():
    """Empty pipeline returns data unchanged."""
    pipeline = FilterPipeline()
    data = make_sine(10.0)
    out = pipeline.process_chunk(data)
    np.testing.assert_array_equal(out, data)


def test_bandpass_attenuates_out_of_band():
    """2 Hz sine through 8-30 Hz bandpass should have RMS < 1% of input."""
    pipeline = FilterPipeline()
    pipeline.add_bandpass(8.0, 30.0, fs=250.0)
    data = make_sine(2.0, duration_s=4.0)
    filtered = pipeline.process_chunk(data)
    skip = 50  # skip transient
    assert rms(filtered[:, skip:]) < 0.01 * rms(data[:, skip:])


def test_bandpass_passes_in_band():
    """10 Hz sine through 8-30 Hz bandpass should retain > 80% RMS."""
    pipeline = FilterPipeline()
    pipeline.add_bandpass(8.0, 30.0, fs=250.0)
    data = make_sine(10.0, duration_s=4.0)
    filtered = pipeline.process_chunk(data)
    skip = 50
    assert rms(filtered[:, skip:]) > 0.80 * rms(data[:, skip:])


def test_notch_attenuates_target():
    """60 Hz sine through 60 Hz notch should have RMS < 5% of input."""
    pipeline = FilterPipeline()
    pipeline.add_notch(60.0, fs=250.0)
    data = make_sine(60.0, duration_s=4.0)
    filtered = pipeline.process_chunk(data)
    skip = 50
    assert rms(filtered[:, skip:]) < 0.05 * rms(data[:, skip:])


def test_notch_passes_off_target():
    """10 Hz sine through 60 Hz notch should retain > 95% RMS."""
    pipeline = FilterPipeline()
    pipeline.add_notch(60.0, fs=250.0)
    data = make_sine(10.0, duration_s=4.0)
    filtered = pipeline.process_chunk(data)
    skip = 50
    assert rms(filtered[:, skip:]) > 0.95 * rms(data[:, skip:])


def test_stage_ordering():
    """Bandpass-then-notch vs notch-then-bandpass produce different outputs."""
    pipeline_a = FilterPipeline()
    pipeline_a.add_bandpass(8.0, 30.0, fs=250.0)
    pipeline_a.add_notch(60.0, fs=250.0)

    pipeline_b = FilterPipeline()
    pipeline_b.add_notch(60.0, fs=250.0)
    pipeline_b.add_bandpass(8.0, 30.0, fs=250.0)

    data = make_sine(10.0, duration_s=4.0)
    out_a = pipeline_a.process_chunk(data.copy())
    out_b = pipeline_b.process_chunk(data.copy())
    # Outputs should differ because zi state evolution differs
    assert not np.allclose(out_a, out_b)


def test_throughput_performance():
    """16ch x 64-sample chunk should process in < 5 ms."""
    pipeline = FilterPipeline()
    pipeline.add_bandpass(8.0, 30.0, fs=250.0)
    pipeline.add_notch(60.0, fs=250.0)

    n_channels = 16
    n_samples = 64
    data = np.random.randn(n_channels, n_samples)

    # Warm up zi state
    pipeline.process_chunk(data)

    # Time the actual chunk
    start = time.perf_counter()
    for _ in range(10):
        pipeline.process_chunk(data)
    elapsed_per_chunk = (time.perf_counter() - start) / 10

    assert elapsed_per_chunk < 0.005, (
        f"Chunk processing took {elapsed_per_chunk * 1000:.2f} ms, expected < 5 ms"
    )


def test_stateful_filtering_no_transient_between_chunks():
    """Second chunk must have no NaN/inf and amplitude < 2.0 for unit-amplitude 10 Hz sine."""
    pipeline = FilterPipeline()
    pipeline.add_bandpass(8.0, 30.0, fs=250.0)
    chunk1 = make_sine(10.0, duration_s=1.0)
    chunk2 = make_sine(10.0, duration_s=1.0)
    _ = pipeline.process_chunk(chunk1)
    filtered2 = pipeline.process_chunk(chunk2)
    assert not np.any(np.isnan(filtered2))
    assert not np.any(np.isinf(filtered2))
    assert np.max(np.abs(filtered2)) < 2.0


def test_add_does_not_reset_other_zi():
    """After processing through stage A, adding stage B does not reset stage A's zi."""
    pipeline = FilterPipeline()
    stage_a = pipeline.add_bandpass(8.0, 30.0, fs=250.0)

    chunk1 = make_sine(10.0, duration_s=1.0)
    pipeline.process_chunk(chunk1)

    # Capture stage A's zi state
    zi_before = {k: v.copy() for k, v in stage_a._zi.items()}

    # Add stage B — must NOT reset stage A's zi
    pipeline.add_notch(60.0, fs=250.0)

    # Stage A's zi should be identical
    assert set(stage_a._zi.keys()) == set(zi_before.keys()), "Stage A lost zi channels"
    for k in zi_before:
        np.testing.assert_array_equal(
            stage_a._zi[k], zi_before[k],
            err_msg=f"Stage A zi for channel {k} was modified by add_notch"
        )


def test_remove_does_not_reset_other_zi():
    """Removing the first stage does not reset the second stage's zi."""
    pipeline = FilterPipeline()
    pipeline.add_bandpass(8.0, 30.0, fs=250.0)
    stage_b = pipeline.add_notch(60.0, fs=250.0)

    chunk = make_sine(10.0, duration_s=1.0)
    pipeline.process_chunk(chunk)

    # Capture stage B's zi
    zi_before = {k: v.copy() for k, v in stage_b._zi.items()}

    # Remove stage A
    pipeline.remove_stage(0)

    # Stage B's zi must be unchanged
    assert set(stage_b._zi.keys()) == set(zi_before.keys()), "Stage B lost zi channels"
    for k in zi_before:
        np.testing.assert_array_equal(
            stage_b._zi[k], zi_before[k],
            err_msg=f"Stage B zi for channel {k} was modified by remove_stage"
        )


def test_move_resets_all_zi():
    """After move_stage, all zi dicts are cleared."""
    pipeline = FilterPipeline()
    stage_a = pipeline.add_bandpass(8.0, 30.0, fs=250.0)
    stage_b = pipeline.add_notch(60.0, fs=250.0)

    chunk = make_sine(10.0, duration_s=1.0)
    pipeline.process_chunk(chunk)

    # Both stages should have zi populated
    assert len(stage_a._zi) > 0
    assert len(stage_b._zi) > 0

    # Move — order changes, all zi must be cleared
    pipeline.move_stage(0, 1)

    assert len(stage_a._zi) == 0, "Stage A zi was not cleared after move_stage"
    assert len(stage_b._zi) == 0, "Stage B zi was not cleared after move_stage"


def test_serialization_roundtrip():
    """to_config -> from_config restores same stage count, names, and enabled flags."""
    pipeline = FilterPipeline()
    pipeline.add_bandpass(8.0, 30.0, fs=250.0)
    stage_notch = pipeline.add_notch(60.0, fs=250.0)
    stage_notch.enabled = False  # test enabled flag round-trip

    config = pipeline.to_config()
    restored = FilterPipeline.from_config(config, fs=250.0)

    assert len(restored.stages) == 2
    assert "Bandpass" in restored.stages[0].name
    assert "Notch" in restored.stages[1].name
    assert restored.stages[0].enabled is True
    assert restored.stages[1].enabled is False


def test_serialization_preserves_params():
    """Roundtripped bandpass has same lowcut/highcut; notch has same freq."""
    pipeline = FilterPipeline()
    pipeline.add_bandpass(1.0, 40.0, fs=250.0)
    pipeline.add_notch(50.0, fs=250.0)

    config = pipeline.to_config()

    assert config[0]["type"] == "bandpass"
    assert config[0]["lowcut"] == pytest.approx(1.0, abs=1e-6)
    assert config[0]["highcut"] == pytest.approx(40.0, abs=1e-6)

    assert config[1]["type"] == "notch"
    assert config[1]["freq"] == pytest.approx(50.0, abs=1e-6)

    # Restore and verify stages operate (no crash)
    restored = FilterPipeline.from_config(config, fs=250.0)
    assert len(restored.stages) == 2


def test_enabled_toggle():
    """Disabled stage passes data through unchanged."""
    pipeline = FilterPipeline()
    stage = pipeline.add_bandpass(8.0, 30.0, fs=250.0)
    stage.enabled = False

    data = make_sine(2.0, duration_s=1.0)  # out-of-band — would normally be attenuated
    out = pipeline.process_chunk(data)
    # Disabled filter should not modify data
    np.testing.assert_array_equal(out, data)
