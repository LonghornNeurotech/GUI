"""
Unit tests for dsp.band_power (BandPowerExtractor, RestBaselineTracker, ControlSignals).
All tests are headless -- no Qt imports required.

TDD RED phase: these tests are written before the implementation exists.
They should all fail with ImportError until dsp/band_power.py is created.
"""

import numpy as np
import pytest

from dsp.band_power import BandPowerExtractor, ControlSignals, RestBaselineTracker


# ---------------------------------------------------------------------------
# ControlSignals tests
# ---------------------------------------------------------------------------


def test_control_signals_frozen():
    """ControlSignals dataclass is immutable (frozen=True)."""
    cs = ControlSignals(lr=0.1, ud=0.2, mu_c3=1.0, mu_c4=2.0, baseline_ready=True)
    with pytest.raises(AttributeError):
        cs.lr = 999.0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# BandPowerExtractor tests
# ---------------------------------------------------------------------------


def test_mu_power_known_signal():
    """A 10 Hz sine (within mu band) produces non-zero mu power;
    a 30 Hz sine (outside mu) produces near-zero mu power.
    """
    fs = 250.0
    duration = 2.0  # enough samples to fill buffer
    t = np.arange(0, duration, 1.0 / fs)

    # 10 Hz sine -- inside mu band (8-13 Hz)
    sig_10hz = np.sin(2 * np.pi * 10 * t)
    # 30 Hz sine -- outside mu band
    sig_30hz = np.sin(2 * np.pi * 30 * t)

    ext = BandPowerExtractor(fs=fs)

    # Feed 10 Hz to C3, 30 Hz to C4
    result = ext.update(sig_10hz, sig_30hz)
    assert result is not None, "Expected tuple after >= 256 samples"

    mu_c3, mu_c4 = result
    assert mu_c3 > 0.0, f"10 Hz sine should have non-zero mu power, got {mu_c3}"
    assert mu_c4 < mu_c3 * 0.01, (
        f"30 Hz sine mu power ({mu_c4}) should be << 10 Hz mu power ({mu_c3})"
    )


def test_buffer_not_full_returns_none():
    """update() returns None when buffer has fewer than 256 samples."""
    ext = BandPowerExtractor(fs=250.0)
    # Feed only 100 samples -- not enough
    short_data = np.zeros(100)
    result = ext.update(short_data, short_data)
    assert result is None, f"Expected None for short buffer, got {result}"


def test_update_returns_tuple_when_full():
    """After feeding >= 256 samples, update() returns (float, float) tuple."""
    ext = BandPowerExtractor(fs=250.0)
    data = np.random.default_rng(42).normal(0, 1, size=300)
    result = ext.update(data, data)
    assert result is not None, "Expected tuple after 300 samples"
    assert isinstance(result, tuple), f"Expected tuple, got {type(result)}"
    assert len(result) == 2, f"Expected 2-element tuple, got {len(result)}"
    assert isinstance(result[0], float), f"Expected float, got {type(result[0])}"
    assert isinstance(result[1], float), f"Expected float, got {type(result[1])}"


def test_extractor_reset():
    """BandPowerExtractor.reset() clears internal buffers."""
    ext = BandPowerExtractor(fs=250.0)
    data = np.random.default_rng(7).normal(0, 1, size=300)
    result = ext.update(data, data)
    assert result is not None, "Should return tuple before reset"

    ext.reset()
    # After reset, buffer should be empty -- short data returns None
    short = np.zeros(50)
    result_after = ext.update(short, short)
    assert result_after is None, "After reset, short data should return None"


# ---------------------------------------------------------------------------
# RestBaselineTracker tests
# ---------------------------------------------------------------------------


def test_baseline_rest_gating():
    """Samples accumulated only when state is REST; CUE/LEFT/RIGHT are rejected."""
    tracker = RestBaselineTracker()
    tracker.set_state("REST")
    tracker.accumulate(1.0, 2.0)
    tracker.accumulate(1.5, 2.5)
    # Two REST samples should be stored
    assert len(tracker._c3_log) == 2, f"Expected 2, got {len(tracker._c3_log)}"

    # Switch to LEFT -- should not accumulate
    tracker.set_state("LEFT")
    tracker.accumulate(3.0, 4.0)
    assert len(tracker._c3_log) == 2, f"Expected still 2, got {len(tracker._c3_log)}"

    # Switch to RIGHT -- should not accumulate
    tracker.set_state("RIGHT")
    tracker.accumulate(3.0, 4.0)
    assert len(tracker._c3_log) == 2, f"Expected still 2, got {len(tracker._c3_log)}"

    # CUE should also not accumulate
    tracker.set_state("CUE")
    tracker.accumulate(3.0, 4.0)
    assert len(tracker._c3_log) == 2, f"Expected still 2, got {len(tracker._c3_log)}"


def test_baseline_sliding_window():
    """Deque maxlen=470 enforced -- oldest samples evicted when full."""
    tracker = RestBaselineTracker(max_samples=470)
    tracker.set_state("REST")
    for i in range(500):
        tracker.accumulate(float(i), float(i))
    assert len(tracker._c3_log) == 470, f"Expected 470, got {len(tracker._c3_log)}"
    assert len(tracker._c4_log) == 470, f"Expected 470, got {len(tracker._c4_log)}"


def test_baseline_not_ready_under_10_samples():
    """baseline_ready=False and lr=ud=0.0 when fewer than 10 REST samples."""
    tracker = RestBaselineTracker()
    tracker.set_state("REST")
    for i in range(9):
        tracker.accumulate(float(i + 1), float(i + 1))

    cs = tracker.compute_control_signals(5.0, 5.0)
    assert cs.baseline_ready is False, "Should not be ready with < 10 samples"
    assert cs.lr == 0.0, f"Expected lr=0.0, got {cs.lr}"
    assert cs.ud == 0.0, f"Expected ud=0.0, got {cs.ud}"


def test_zscore_normalization():
    """With known REST baseline mean/std, z-score output matches manual calculation."""
    tracker = RestBaselineTracker(min_baseline=5)
    tracker.set_state("REST")

    # Feed known values so we can compute expected mean/std
    raw_values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
    for v in raw_values:
        tracker.accumulate(v, v * 2.0)

    # Log-transformed values stored in deques
    log_c3 = [np.log(v + 1e-12) for v in raw_values]
    log_c4 = [np.log(v * 2.0 + 1e-12) for v in raw_values]

    mean_c3 = np.mean(log_c3)
    std_c3 = np.std(log_c3)
    mean_c4 = np.mean(log_c4)
    std_c4 = np.std(log_c4)

    # Current values to z-score
    test_c3, test_c4 = 5.5, 11.0
    log_test_c3 = np.log(test_c3 + 1e-12)
    log_test_c4 = np.log(test_c4 + 1e-12)

    expected_z_c3 = (log_test_c3 - mean_c3) / max(std_c3, 1e-12)
    expected_z_c4 = (log_test_c4 - mean_c4) / max(std_c4, 1e-12)
    expected_lr = expected_z_c4 - expected_z_c3
    expected_ud = expected_z_c3 + expected_z_c4

    cs = tracker.compute_control_signals(test_c3, test_c4)
    assert cs.baseline_ready is True, "Should be ready with 10 samples"
    np.testing.assert_allclose(cs.lr, expected_lr, atol=1e-6,
                               err_msg=f"LR mismatch: {cs.lr} vs {expected_lr}")
    np.testing.assert_allclose(cs.ud, expected_ud, atol=1e-6,
                               err_msg=f"UD mismatch: {cs.ud} vs {expected_ud}")


def test_lr_signal_computation():
    """With known C3/C4 mu power values, LR = z_C4 - z_C3."""
    tracker = RestBaselineTracker(min_baseline=5)
    tracker.set_state("REST")

    # All same values -- mean = log(3), std ~ 0
    for _ in range(20):
        tracker.accumulate(3.0, 3.0)

    # Now test with asymmetric values: C3=3, C4=10
    # z_C3 ~ 0 (same as baseline mean), z_C4 >> 0 (above mean)
    cs = tracker.compute_control_signals(3.0, 10.0)
    assert cs.baseline_ready is True
    # z_C3 should be near 0, z_C4 should be positive -> LR = z_C4 - z_C3 > 0
    assert cs.lr > 0, f"LR should be positive when C4 > C3, got {cs.lr}"


def test_ud_signal_computation():
    """With known C3/C4 mu power values, UD = z_C3 + z_C4."""
    tracker = RestBaselineTracker(min_baseline=5)
    tracker.set_state("REST")

    # Baseline with low values
    for _ in range(20):
        tracker.accumulate(1.0, 1.0)

    # Both channels high -> both z-scores positive -> UD = z_C3 + z_C4 > 0
    cs = tracker.compute_control_signals(10.0, 10.0)
    assert cs.baseline_ready is True
    assert cs.ud > 0, f"UD should be positive when both channels high, got {cs.ud}"


def test_rebaseline_clears_buffer():
    """After reset(), baseline_ready becomes False and buffer is empty."""
    tracker = RestBaselineTracker()
    tracker.set_state("REST")
    for i in range(20):
        tracker.accumulate(float(i + 1), float(i + 1))
    assert len(tracker._c3_log) == 20

    tracker.reset()
    assert len(tracker._c3_log) == 0, "Buffer should be empty after reset"
    assert len(tracker._c4_log) == 0, "Buffer should be empty after reset"

    cs = tracker.compute_control_signals(5.0, 5.0)
    assert cs.baseline_ready is False, "Should not be ready after reset"


def test_log_transform_applied():
    """Baseline stores log-transformed values, not raw power."""
    tracker = RestBaselineTracker()
    tracker.set_state("REST")
    tracker.accumulate(10.0, 20.0)

    # The stored value should be log(10 + 1e-12), not 10.0
    stored_c3 = tracker._c3_log[0]
    expected_log = np.log(10.0 + 1e-12)
    np.testing.assert_allclose(stored_c3, expected_log, atol=1e-10,
                               err_msg=f"Stored {stored_c3}, expected log(10)={expected_log}")
