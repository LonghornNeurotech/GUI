"""
Unit tests for dsp.quality (SignalQualityMonitor) and dsp.filter_pipeline (SpatialFilterStage).
All tests are headless -- no Qt imports required.

TDD RED phase: these tests are written before the implementations exist.
They should all fail with ImportError or AssertionError until implementation is complete.
"""

import numpy as np
import pytest
from dsp.quality import SignalQualityMonitor
from dsp.filter_pipeline import SpatialFilterStage


# ---------------------------------------------------------------------------
# SignalQualityMonitor tests
# ---------------------------------------------------------------------------


def test_quality_returns_per_channel():
    """SignalQualityMonitor.compute() returns dict[int, str] with one entry per channel."""
    monitor = SignalQualityMonitor()
    rng = np.random.default_rng(42)
    data = rng.normal(0, 10, size=(4, 250))
    result = monitor.compute(data)

    assert isinstance(result, dict), "compute() must return a dict"
    assert len(result) == 4, f"Expected 4 entries, got {len(result)}"
    valid = {"good", "marginal", "bad"}
    for ch, status in result.items():
        assert status in valid, f"Channel {ch} status '{status}' not in {valid}"


def test_flatline_detection():
    """A channel with constant values (std=0) is flagged 'bad' or 'marginal'."""
    monitor = SignalQualityMonitor()
    rng = np.random.default_rng(0)
    data = np.zeros((2, 250), dtype=np.float64)
    # Channel 0: constant (flatline)
    data[0, :] = 5.0
    # Channel 1: random normal with std >> threshold
    data[1, :] = rng.normal(0, 50, size=250)

    result = monitor.compute(data)

    assert result[0] in {"bad", "marginal"}, (
        f"Flatline channel 0 expected 'bad' or 'marginal', got '{result[0]}'"
    )
    assert result[1] == "good", (
        f"Clean channel 1 expected 'good', got '{result[1]}'"
    )


def test_spike_detection():
    """A channel with extreme outliers (> 6 IQR) is not flagged 'good'."""
    monitor = SignalQualityMonitor()
    rng = np.random.default_rng(1)
    data = np.zeros((2, 250), dtype=np.float64)
    # Channel 0: mostly normal, but 5 extreme spikes at 100x amplitude
    data[0, :] = rng.normal(0, 1, size=250)
    spike_indices = [10, 50, 100, 150, 200]
    data[0, spike_indices] = 100.0
    # Channel 1: clean normal
    data[1, :] = rng.normal(0, 1, size=250)

    result = monitor.compute(data)

    assert result[0] != "good", (
        f"Spiky channel 0 should not be 'good', got '{result[0]}'"
    )


def test_snr_variance_ratio():
    """A channel where recent variance wildly differs from full-window variance is flagged."""
    monitor = SignalQualityMonitor()
    data = np.zeros((1, 500), dtype=np.float64)
    # First 250 samples: very small amplitude
    data[0, :250] = np.random.default_rng(2).normal(0, 0.01, size=250)
    # Last 250 samples: large amplitude -- variance ratio will be extreme
    data[0, 250:] = np.random.default_rng(3).normal(0, 100, size=250)

    result = monitor.compute(data)

    assert result[0] in {"bad", "marginal"}, (
        f"High-variance-ratio channel expected 'bad' or 'marginal', got '{result[0]}'"
    )


def test_quality_thresholds_green_yellow_red():
    """0 bad metrics -> 'good', exactly 1 -> 'marginal', 2+ -> 'bad'."""
    monitor = SignalQualityMonitor()

    # Clean signal -- should be green (0 bad metrics)
    rng = np.random.default_rng(10)
    clean = rng.normal(0, 10, size=(1, 500))
    result_clean = monitor.compute(clean)
    assert result_clean[0] == "good", (
        f"Clean signal expected 'good', got '{result_clean[0]}'"
    )

    # Flatline channel -- std=0 triggers flatline metric -> at least 1 metric bad
    flatline = np.full((1, 250), 5.0, dtype=np.float64)
    result_flat = monitor.compute(flatline)
    assert result_flat[0] in {"marginal", "bad"}, (
        f"Flatline expected 'marginal' or 'bad', got '{result_flat[0]}'"
    )

    # Combined flatline + spikes: triggers 2+ metrics -> should be 'bad'
    # Use small spikes (6.5) so overall std stays < 1.0 uV (flatline triggers)
    # while max deviation > 6 (spike triggers with IQR=0 fallback path).
    # 245 zeros + 5 spikes of 6.5 -> std ~ 0.92 < 1.0, max_dev = 6.5 > 6.
    combined = np.zeros((1, 250), dtype=np.float64)
    combined[0, [10, 50, 100, 150, 200]] = 6.5
    result_combined = monitor.compute(combined)
    assert result_combined[0] == "bad", (
        f"Flatline+spike combo expected 'bad', got '{result_combined[0]}'"
    )


def test_configurable_thresholds():
    """Custom threshold parameters make a signal that is 'good' by default become 'marginal'/'bad'."""
    # With default thresholds (flatline_std_uv=1.0), a signal with std=5 is fine
    default_monitor = SignalQualityMonitor()
    rng = np.random.default_rng(20)
    data = rng.normal(0, 5, size=(1, 250))  # std ~ 5 uV -- passes flatline (>1uV)
    result_default = default_monitor.compute(data)
    assert result_default[0] == "good", (
        f"std=5 signal should be 'good' with default threshold, got '{result_default[0]}'"
    )

    # With stricter thresholds (flatline_std_uv=10.0), std=5 signal fails flatline
    strict_monitor = SignalQualityMonitor(flatline_std_uv=10.0)
    result_strict = strict_monitor.compute(data)
    assert result_strict[0] in {"marginal", "bad"}, (
        f"std=5 signal expected 'marginal'/'bad' with threshold=10, got '{result_strict[0]}'"
    )


# ---------------------------------------------------------------------------
# SpatialFilterStage tests
# ---------------------------------------------------------------------------


def test_car_output_correct():
    """CAR with 4 channels, no bad channels: output[k] = channel_k - mean(all channels)."""
    # Data: channel k has constant value (k+1) for all samples
    n_channels = 4
    n_samples = 100
    data = np.zeros((n_channels, n_samples), dtype=np.float64)
    for k in range(n_channels):
        data[k, :] = float(k + 1)  # ch0=1, ch1=2, ch2=3, ch3=4

    stage = SpatialFilterStage.make_car(n_channels=n_channels)
    out = stage.process(data)

    # mean of [1,2,3,4] = 2.5
    expected_mean = 2.5
    for k in range(n_channels):
        expected = float(k + 1) - expected_mean
        np.testing.assert_allclose(
            out[k, :], expected, atol=1e-10,
            err_msg=f"Channel {k}: expected {expected}, got mean={out[k, 0]:.6f}"
        )


def test_car_excludes_bad_channels():
    """CAR with channel 2 flagged bad: reference uses only channels {0,1,3}."""
    n_channels = 4
    n_samples = 50
    data = np.zeros((n_channels, n_samples), dtype=np.float64)
    for k in range(n_channels):
        data[k, :] = float(k + 1)  # ch0=1, ch1=2, ch2=3, ch3=4

    stage = SpatialFilterStage.make_car(n_channels=n_channels, bad_channels={2})
    out = stage.process(data)

    # Reference mean uses only good channels {0,1,3}: values [1,2,4], mean = 7/3
    good_mean = (1.0 + 2.0 + 4.0) / 3.0
    for k in range(n_channels):
        expected = float(k + 1) - good_mean
        np.testing.assert_allclose(
            out[k, :], expected, atol=1e-10,
            err_msg=f"Channel {k} (bad_ch={2}): expected {expected:.4f}, got {out[k,0]:.6f}"
        )


def test_car_all_bad_passthrough():
    """CAR with all channels flagged bad returns input unchanged (identity/passthrough)."""
    n_channels = 3
    n_samples = 50
    rng = np.random.default_rng(42)
    data = rng.normal(0, 1, size=(n_channels, n_samples))

    # No ZeroDivisionError should be raised
    stage = SpatialFilterStage.make_car(
        n_channels=n_channels,
        bad_channels={0, 1, 2}
    )
    out = stage.process(data)

    np.testing.assert_array_equal(out, data, err_msg="All-bad CAR must return input unchanged")


def test_laplacian_output_correct():
    """Laplacian: output[k] = channel_k - mean(neighbors_k)."""
    n_channels = 4
    n_samples = 50
    # Channel k has constant value (k+1)*10
    data = np.zeros((n_channels, n_samples), dtype=np.float64)
    for k in range(n_channels):
        data[k, :] = float((k + 1) * 10)  # ch0=10, ch1=20, ch2=30, ch3=40

    neighbors = {0: [1, 2], 1: [0, 3], 2: [0, 3], 3: [1, 2]}
    stage = SpatialFilterStage.make_laplacian(n_channels=n_channels, neighbors=neighbors)
    out = stage.process(data)

    # ch0: 10 - mean([20, 30]) = 10 - 25 = -15
    # ch1: 20 - mean([10, 40]) = 20 - 25 = -5
    # ch2: 30 - mean([10, 40]) = 30 - 25 = 5
    # ch3: 40 - mean([20, 30]) = 40 - 25 = 15
    expected = [-15.0, -5.0, 5.0, 15.0]
    for k in range(n_channels):
        np.testing.assert_allclose(
            out[k, :], expected[k], atol=1e-10,
            err_msg=f"Laplacian ch{k}: expected {expected[k]}, got {out[k, 0]:.6f}"
        )


def test_laplacian_empty_neighbors():
    """Laplacian with empty neighbors dict returns input unchanged (identity passthrough)."""
    n_channels = 4
    n_samples = 50
    rng = np.random.default_rng(7)
    data = rng.normal(0, 1, size=(n_channels, n_samples))

    stage = SpatialFilterStage.make_laplacian(n_channels=n_channels, neighbors={})
    out = stage.process(data)

    np.testing.assert_array_equal(out, data, err_msg="Empty neighbors Laplacian must be identity")


def test_spatial_stage_process_signature():
    """SpatialFilterStage.process() accepts (n_channels, n_samples) and returns same shape.
    Disabled stage returns input unchanged.
    """
    n_channels = 8
    n_samples = 128
    rng = np.random.default_rng(99)
    data = rng.normal(0, 1, size=(n_channels, n_samples))

    stage = SpatialFilterStage.make_car(n_channels=n_channels)
    out = stage.process(data)
    assert out.shape == data.shape, f"Output shape {out.shape} != input shape {data.shape}"

    # Disabled stage must return input unchanged
    stage.enabled = False
    out_disabled = stage.process(data)
    np.testing.assert_array_equal(
        out_disabled, data,
        err_msg="Disabled stage must return input unchanged"
    )


def test_spatial_stage_serialization():
    """to_config/from_config roundtrip preserves W matrix within allclose tolerance."""
    n_channels = 4
    stage = SpatialFilterStage.make_car(n_channels=n_channels, bad_channels={1})

    config = stage.to_config()

    # Verify required config fields
    assert config["type"] == "spatial", f"config type should be 'spatial', got '{config['type']}'"
    assert config["subtype"] in {"car", "laplacian"}, (
        f"config subtype should be 'car' or 'laplacian', got '{config['subtype']}'"
    )

    # Roundtrip: restore from config and verify W is preserved
    restored = SpatialFilterStage.from_config(config)
    np.testing.assert_allclose(
        restored.w, stage.w, atol=1e-10,
        err_msg="Roundtrip W matrix must be allclose to original"
    )
    assert restored.enabled == stage.enabled, "Roundtrip enabled flag mismatch"
