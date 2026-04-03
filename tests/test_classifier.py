"""Tests for dsp/classifier.py -- CSP spatial filter, LDA classifier, BCITrainer.

Covers: extract_epochs, CSPFilter, LDAClassifier, BCITrainer, save_weights, load_weights.
"""

from __future__ import annotations

import time

import numpy as np
import pytest

from dsp.classifier import (
    BCITrainer,
    CSPFilter,
    LDAClassifier,
    extract_epochs,
    load_weights,
    save_weights,
)
from dsp.transfer_function import apply_transfer_function

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_RNG = np.random.default_rng(42)


def _make_separable_trials(
    n_channels: int = 8,
    n_samples: int = 1000,
    n_trials: int = 50,
) -> tuple[list[np.ndarray], list[np.ndarray]]:
    """Create two perfectly separable classes for CSP testing.

    Class 1: high variance on channel 0, low elsewhere.
    Class 2: high variance on channel 1, low elsewhere.
    """
    class1, class2 = [], []
    for _ in range(n_trials):
        x = _RNG.standard_normal((n_channels, n_samples)) * 0.1
        x[0, :] *= 10.0  # channel 0 dominant
        class1.append(x)
    for _ in range(n_trials):
        x = _RNG.standard_normal((n_channels, n_samples)) * 0.1
        x[1, :] *= 10.0  # channel 1 dominant
        class2.append(x)
    return class1, class2


# ---------------------------------------------------------------------------
# extract_epochs
# ---------------------------------------------------------------------------


def test_extract_epochs_basic() -> None:
    """Markers at 0.5s and 2.5s in 8-ch, 2000-sample (250 Hz) data."""
    eeg = _RNG.standard_normal((8, 2000))
    markers: list[tuple[float, str]] = [("LEFT", 0.5), ("RIGHT", 2.5)]
    epochs = extract_epochs(eeg, markers, srate=250.0, window_sec=4.0)

    assert "LEFT" in epochs
    assert "RIGHT" in epochs
    assert len(epochs["LEFT"]) == 1
    assert len(epochs["RIGHT"]) == 1
    assert epochs["LEFT"][0].shape == (8, 1000)
    assert epochs["RIGHT"][0].shape == (8, 1000)


def test_extract_epochs_skips_truncated() -> None:
    """Marker near end of data (not enough samples for 4s window) is skipped."""
    eeg = _RNG.standard_normal((8, 500))
    markers: list[tuple[float, str]] = [("LEFT", 1.5)]  # needs idx 375 + 1000 > 500
    epochs = extract_epochs(eeg, markers, srate=250.0, window_sec=4.0)
    assert len(epochs["LEFT"]) == 0


def test_extract_epochs_json_markers() -> None:
    """Markers formatted as JSON strings are parsed correctly."""
    eeg = _RNG.standard_normal((8, 2000))
    markers: list[tuple[float, str]] = [('{"start":"LEFT"}', 0.5)]
    epochs = extract_epochs(eeg, markers, srate=250.0, window_sec=4.0)
    assert len(epochs["LEFT"]) == 1


# ---------------------------------------------------------------------------
# BCITrainer -- min trials gate
# ---------------------------------------------------------------------------


def test_min_trials_gate() -> None:
    """BCITrainer.fit() raises ValueError when fewer than 40 trials per class."""
    trainer = BCITrainer(min_trials_per_class=40)
    few_trials = {
        "LEFT": [_RNG.standard_normal((8, 1000)) for _ in range(10)],
        "RIGHT": [_RNG.standard_normal((8, 1000)) for _ in range(10)],
    }
    with pytest.raises(ValueError, match="At least 40 trials per class required"):
        trainer.fit(few_trials)


# ---------------------------------------------------------------------------
# CSPFilter + LDAClassifier
# ---------------------------------------------------------------------------


def test_csp_fit_separable_classes() -> None:
    """CSP + LDA achieves >90% accuracy on perfectly separable synthetic data."""
    class1, class2 = _make_separable_trials()

    csp = CSPFilter(n_components=4)
    csp.fit(class1, class2)
    assert csp.W_.shape == (8, 4)

    # Extract features
    features = []
    labels = []
    for trial in class1:
        features.append(csp.transform(trial))
        labels.append(0)
    for trial in class2:
        features.append(csp.transform(trial))
        labels.append(1)

    X = np.array(features)
    y = np.array(labels)

    lda = LDAClassifier()
    lda.fit(X, y)

    preds = []
    for f in X:
        cert = lda.predict_certainty(f)
        preds.append(1 if cert > 0 else 0)
    accuracy = np.mean(np.array(preds) == y)
    assert accuracy > 0.90, f"Accuracy {accuracy:.2f} is below 90%"


def test_csp_regularization() -> None:
    """CSP fit does not raise LinAlgError with near-singular covariance (duplicate trials)."""
    trial = _RNG.standard_normal((4, 500))
    # Duplicate trials -- near-singular covariance
    class1 = [trial.copy() for _ in range(50)]
    class2 = [trial.copy() * 0.5 for _ in range(50)]

    csp = CSPFilter(n_components=4)
    csp.fit(class1, class2)  # should not raise
    assert csp.fitted


def test_lda_certainty_range() -> None:
    """predict_certainty returns float in [-1, +1] range."""
    class1, class2 = _make_separable_trials()
    csp = CSPFilter(n_components=4)
    csp.fit(class1, class2)

    features = [csp.transform(t) for t in class1 + class2]
    labels = np.array([0] * len(class1) + [1] * len(class2))
    X = np.array(features)

    lda = LDAClassifier()
    lda.fit(X, labels)

    for f in features:
        cert = lda.predict_certainty(f)
        assert isinstance(cert, float)
        assert -1.0 <= cert <= 1.0, f"Certainty {cert} out of range"


# ---------------------------------------------------------------------------
# save / load weights
# ---------------------------------------------------------------------------


def test_save_load_roundtrip(tmp_path: object) -> None:
    """save_weights then load_weights returns W with np.allclose match."""
    class1, class2 = _make_separable_trials()
    csp = CSPFilter(n_components=4)
    csp.fit(class1, class2)

    features = [csp.transform(t) for t in class1 + class2]
    labels = np.array([0] * len(class1) + [1] * len(class2))
    X = np.array(features)

    lda = LDAClassifier()
    lda.fit(X, labels)

    path = str(tmp_path / "weights.json")  # type: ignore[operator]
    save_weights(path, csp, lda)

    csp2, lda2 = load_weights(path)
    assert np.allclose(csp.W_, csp2.W_)
    assert np.allclose(lda.coef_, lda2.coef_)
    assert np.allclose(lda.intercept_, lda2.intercept_)
    assert list(lda.classes_) == list(lda2.classes_)


def test_save_load_file_not_found() -> None:
    """load_weights on nonexistent path raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        load_weights("/tmp/nonexistent_classifier_weights_xyz.json")


# ---------------------------------------------------------------------------
# Performance
# ---------------------------------------------------------------------------


def test_online_inference_speed() -> None:
    """Single inference completes in < 5ms for 8-channel, 1000-sample input."""
    class1, class2 = _make_separable_trials()
    csp = CSPFilter(n_components=4)
    csp.fit(class1, class2)

    features = [csp.transform(t) for t in class1 + class2]
    labels = np.array([0] * len(class1) + [1] * len(class2))
    lda = LDAClassifier()
    lda.fit(np.array(features), labels)

    data = _RNG.standard_normal((8, 1000))

    # Warm up
    _ = lda.predict_certainty(csp.transform(data))

    start = time.perf_counter()
    _ = lda.predict_certainty(csp.transform(data))
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    assert elapsed_ms < 5.0, f"Inference took {elapsed_ms:.2f}ms (limit 5ms)"


# ---------------------------------------------------------------------------
# Inference chain (CSP -> log-var -> LDA -> transfer function)
# ---------------------------------------------------------------------------


def test_inference_chain() -> None:
    """Full chain: CSP project -> log-var -> LDA predict -> transfer function."""
    class1, class2 = _make_separable_trials()
    csp = CSPFilter(n_components=4)
    csp.fit(class1, class2)

    features = [csp.transform(t) for t in class1 + class2]
    labels = np.array([0] * len(class1) + [1] * len(class2))
    lda = LDAClassifier()
    lda.fit(np.array(features), labels)

    data = _RNG.standard_normal((8, 1000))
    feat = csp.transform(data)
    certainty = lda.predict_certainty(feat)
    assert isinstance(certainty, float)

    shaped = apply_transfer_function(certainty, r=1.0)
    assert isinstance(shaped, float)
    # Transfer function output is in [-0.9009, 0.9009] or 0.0
    assert -1.0 <= shaped <= 1.0


# ---------------------------------------------------------------------------
# Integration Tests -- full pipeline
# ---------------------------------------------------------------------------

_INT_RNG = np.random.default_rng(99)


def _generate_synthetic_session(
    n_channels: int = 8,
    srate: float = 250.0,
    n_trials_per_class: int = 50,
    trial_duration: float = 4.0,
    inter_trial_gap: float = 2.0,
) -> tuple[np.ndarray, list[tuple[str, float]]]:
    """Generate synthetic EEG session with LEFT/RIGHT class separation.

    Class 1 (LEFT): elevated variance on channels 0-1 (multiply by 5).
    Class 2 (RIGHT): elevated variance on channels 6-7 (multiply by 5).
    Markers alternate LEFT/RIGHT at evenly spaced intervals.

    Returns
    -------
    tuple[np.ndarray, list[tuple[str, float]]]
        (eeg_data, markers) where eeg_data is (n_channels, n_samples).
    """
    total_trials = n_trials_per_class * 2
    trial_samples = int(trial_duration * srate)
    gap_samples = int(inter_trial_gap * srate)
    segment_samples = trial_samples + gap_samples
    total_samples = total_trials * segment_samples + int(srate)  # +1s buffer

    eeg = _INT_RNG.standard_normal((n_channels, total_samples)) * 0.5
    markers: list[tuple[str, float]] = []

    classes = ["LEFT", "RIGHT"]
    for i in range(total_trials):
        cls = classes[i % 2]
        start_sample = i * segment_samples + int(srate * 0.5)  # 0.5s offset
        end_sample = start_sample + trial_samples
        if end_sample > total_samples:
            break
        if cls == "LEFT":
            eeg[0:2, start_sample:end_sample] *= 5.0
        else:
            eeg[6:8, start_sample:end_sample] *= 5.0
        markers.append((cls, start_sample / srate))

    return eeg, markers


class TestFullPipelineIntegration:
    """Integration tests: extract_epochs -> BCITrainer -> save -> load -> inference."""

    def test_full_pipeline_roundtrip(self, tmp_path: object) -> None:
        """Full pipeline: extract -> train -> save -> load -> identical inference."""
        eeg, markers = _generate_synthetic_session()
        epochs = extract_epochs(eeg, markers, srate=250.0, window_sec=4.0)

        assert len(epochs["LEFT"]) == 50
        assert len(epochs["RIGHT"]) == 50

        trainer = BCITrainer(min_trials_per_class=40, n_components=4)
        csp, lda = trainer.fit(epochs)

        # Generate a test chunk matching class 1 pattern
        test_chunk = _INT_RNG.standard_normal((8, 1000)) * 0.5
        test_chunk[0:2, :] *= 5.0

        original_feat = csp.transform(test_chunk)
        original_certainty = lda.predict_certainty(original_feat)

        # Save and reload
        weight_path = str(tmp_path / "test_weights.json")  # type: ignore[operator]
        save_weights(weight_path, csp, lda)
        csp_loaded, lda_loaded = load_weights(weight_path)

        loaded_feat = csp_loaded.transform(test_chunk)
        loaded_certainty = lda_loaded.predict_certainty(loaded_feat)

        assert np.isclose(original_certainty, loaded_certainty), (
            f"Original {original_certainty} != Loaded {loaded_certainty}"
        )

    def test_full_pipeline_with_transfer_function(self) -> None:
        """Pipeline output through transfer function stays in valid range."""
        eeg, markers = _generate_synthetic_session()
        epochs = extract_epochs(eeg, markers, srate=250.0, window_sec=4.0)

        trainer = BCITrainer(min_trials_per_class=40, n_components=4)
        csp, lda = trainer.fit(epochs)

        test_chunk = _INT_RNG.standard_normal((8, 1000)) * 0.5
        test_chunk[6:8, :] *= 5.0  # RIGHT-like pattern

        feat = csp.transform(test_chunk)
        certainty = lda.predict_certainty(feat)
        shaped = apply_transfer_function(certainty, r=1.0)

        assert isinstance(shaped, float)
        assert abs(shaped) <= 0.9009 + 1e-6, (
            f"Transfer function output {shaped} exceeds 0.9009"
        )

    def test_gate_rejects_insufficient_trials(self) -> None:
        """BCITrainer rejects sessions with fewer than 40 trials per class."""
        eeg, markers = _generate_synthetic_session(n_trials_per_class=20)
        epochs = extract_epochs(eeg, markers, srate=250.0, window_sec=4.0)

        assert len(epochs["LEFT"]) == 20
        assert len(epochs["RIGHT"]) == 20

        trainer = BCITrainer(min_trials_per_class=40, n_components=4)
        with pytest.raises(ValueError, match="40 trials"):
            trainer.fit(epochs)

    def test_extract_epochs_real_format(self) -> None:
        """Markers in JSON format '{"start":"LEFT"}' are extracted correctly."""
        eeg, _ = _generate_synthetic_session(n_trials_per_class=5)
        json_markers: list[tuple[str, float]] = [
            ('{"start":"LEFT"}', 1.0),
            ('{"start":"RIGHT"}', 8.0),
            ('{"start":"LEFT"}', 15.0),
        ]
        epochs = extract_epochs(eeg, json_markers, srate=250.0, window_sec=4.0)
        assert len(epochs["LEFT"]) == 2
        assert len(epochs["RIGHT"]) == 1

    def test_loaded_weights_inference_matches_trained(
        self, tmp_path: object
    ) -> None:
        """Loaded classifier matches trained on 10 random test chunks."""
        eeg, markers = _generate_synthetic_session()
        epochs = extract_epochs(eeg, markers, srate=250.0, window_sec=4.0)

        trainer = BCITrainer(min_trials_per_class=40, n_components=4)
        csp, lda = trainer.fit(epochs)

        weight_path = str(tmp_path / "multi_weights.json")  # type: ignore[operator]
        save_weights(weight_path, csp, lda)
        csp_loaded, lda_loaded = load_weights(weight_path)

        rng = np.random.default_rng(123)
        for _ in range(10):
            chunk = rng.standard_normal((8, 1000))
            orig_cert = lda.predict_certainty(csp.transform(chunk))
            load_cert = lda_loaded.predict_certainty(csp_loaded.transform(chunk))
            assert np.isclose(orig_cert, load_cert), (
                f"Mismatch: original={orig_cert}, loaded={load_cert}"
            )
