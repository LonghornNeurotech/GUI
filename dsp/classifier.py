"""CSP spatial filter, LDA classifier, and BCI training pipeline.

Headless module -- no Qt imports. Fully testable with pytest.

Provides:
    - extract_epochs: Extract epoched trials from EEG data using marker timestamps
    - CSPFilter: Common Spatial Pattern spatial filter via scipy.linalg.eigh
    - LDAClassifier: Wrapper around sklearn LDA with predict_certainty
    - BCITrainer: Validates trial counts and orchestrates CSP + LDA training
    - save_weights / load_weights: JSON persistence for CSP W matrix + LDA coefficients
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from scipy.linalg import eigh
from sklearn.discriminant_analysis import LinearDiscriminantAnalysis


# ---------------------------------------------------------------------------
# Epoch extraction
# ---------------------------------------------------------------------------


def _parse_marker_label(label: str) -> str:
    """Parse a marker label, handling JSON-formatted markers.

    If label starts with '{', attempt JSON parse and extract "start" key.
    Otherwise return the raw string.
    """
    if label.startswith("{"):
        try:
            data = json.loads(label)
            return str(data.get("start", label))
        except (json.JSONDecodeError, TypeError):
            return label
    return label


def extract_epochs(
    eeg_data: np.ndarray,
    markers: list[tuple[str, float]],
    srate: float,
    window_sec: float = 4.0,
    classes: tuple[str, ...] = ("LEFT", "RIGHT"),
) -> dict[str, list[np.ndarray]]:
    """Extract epoched trials from EEG data using marker timestamps.

    Parameters
    ----------
    eeg_data : np.ndarray
        EEG data array of shape (n_channels, n_samples).
    markers : list[tuple[str, float]]
        List of (label, time_sec) tuples. Label may be a raw string or
        JSON like '{"start":"LEFT"}'.
    srate : float
        Sampling rate in Hz.
    window_sec : float
        Epoch window length in seconds (default 4.0).
    classes : tuple[str, ...]
        Class labels to extract (default ("LEFT", "RIGHT")).

    Returns
    -------
    dict[str, list[np.ndarray]]
        Mapping from class label to list of trial arrays (n_channels, window_samples).
    """
    window_samples = int(round(window_sec * srate))
    total_samples = eeg_data.shape[1]
    epochs: dict[str, list[np.ndarray]] = {c: [] for c in classes}

    for label, time_sec in markers:
        parsed = _parse_marker_label(label)
        if parsed not in classes:
            continue
        start_idx = int(round(time_sec * srate))
        end_idx = start_idx + window_samples
        if start_idx < 0 or end_idx > total_samples:
            continue
        epochs[parsed].append(eeg_data[:, start_idx:end_idx].copy())

    return epochs


def detect_axis(markers: list[tuple[str, float]]) -> str:
    """Detect whether markers belong to the LR or UD axis.

    Scans parsed marker labels for LEFT/RIGHT vs UP/DOWN presence.

    Parameters
    ----------
    markers : list[tuple[str, float]]
        List of (label, time_sec) tuples. Labels may be raw strings or
        JSON like '{"start":"LEFT"}'.

    Returns
    -------
    str
        "LR" if LEFT/RIGHT markers found, "UD" if UP/DOWN markers found.

    Raises
    ------
    ValueError
        If both axes found, or neither axis found.
    """
    lr_labels = {"LEFT", "RIGHT"}
    ud_labels = {"UP", "DOWN"}
    has_lr = False
    has_ud = False

    for label, _time in markers:
        parsed = _parse_marker_label(label)
        if parsed in lr_labels:
            has_lr = True
        if parsed in ud_labels:
            has_ud = True

    if has_lr and has_ud:
        raise ValueError(
            "Markers contain both LR and UD labels -- cannot determine axis"
        )
    if not has_lr and not has_ud:
        raise ValueError("No recognized axis labels (LEFT/RIGHT or UP/DOWN) found")

    return "LR" if has_lr else "UD"


# ---------------------------------------------------------------------------
# CSP Filter
# ---------------------------------------------------------------------------


def _mean_covariance(trials: list[np.ndarray]) -> np.ndarray:
    """Compute trace-normalized mean covariance across trials.

    For each trial X (n_channels, n_samples):
        C = X @ X.T
        C_norm = C / trace(C)
    Returns the mean of all C_norm.
    """
    covs = []
    for x in trials:
        c = x @ x.T
        trace = np.trace(c)
        if trace > 0:
            c = c / trace
        covs.append(c)
    return np.mean(covs, axis=0)


class CSPFilter:
    """Common Spatial Pattern spatial filter.

    Finds projection matrix W that maximizes variance ratio between two classes
    using generalized eigendecomposition via scipy.linalg.eigh.

    Parameters
    ----------
    n_components : int
        Number of CSP components to keep (default 4). Takes top n/2 and bottom n/2.
    """

    def __init__(self, n_components: int = 4) -> None:
        self.n_components = n_components
        self.W_: np.ndarray | None = None

    @property
    def fitted(self) -> bool:
        """True if the filter has been fitted."""
        return self.W_ is not None

    def fit(
        self,
        trials_class1: list[np.ndarray],
        trials_class2: list[np.ndarray],
    ) -> None:
        """Fit CSP filter from two classes of trial data.

        Parameters
        ----------
        trials_class1 : list[np.ndarray]
            List of trial arrays (n_channels, n_samples) for class 1.
        trials_class2 : list[np.ndarray]
            List of trial arrays (n_channels, n_samples) for class 2.
        """
        cov1 = _mean_covariance(trials_class1)
        cov2 = _mean_covariance(trials_class2)
        n_channels = cov1.shape[0]

        # Regularized composite covariance for numerical stability
        composite = cov1 + cov2 + 1e-10 * np.eye(n_channels)

        # Generalized eigenvalue problem: cov1 @ w = lambda * composite @ w
        # eigh returns eigenvalues in ascending order
        eigenvalues, eigenvectors = eigh(cov1, composite)

        # Select bottom m/2 (best for class 2) + top m/2 (best for class 1)
        m = self.n_components // 2
        indices = list(range(m)) + list(range(-m, 0))
        self.W_ = eigenvectors[:, indices]

    def transform(self, data: np.ndarray) -> np.ndarray:
        """Project data through CSP and compute log-variance features.

        Parameters
        ----------
        data : np.ndarray
            EEG data of shape (n_channels, n_samples).

        Returns
        -------
        np.ndarray
            Log-variance feature vector of shape (n_components,).
        """
        if self.W_ is None:
            raise RuntimeError("CSPFilter has not been fitted yet")
        z = self.W_.T @ data  # (n_components, n_samples)
        return np.log(np.var(z, axis=1) + 1e-12)


# ---------------------------------------------------------------------------
# LDA Classifier
# ---------------------------------------------------------------------------


class LDAClassifier:
    """Wrapper around sklearn LinearDiscriminantAnalysis with certainty output.

    Uses SVD solver for numerical stability.
    """

    def __init__(self) -> None:
        self._lda = LinearDiscriminantAnalysis(solver="svd")

    def fit(self, features: np.ndarray, labels: np.ndarray) -> None:
        """Fit LDA on feature matrix and labels.

        Parameters
        ----------
        features : np.ndarray
            Feature matrix of shape (n_trials, n_features).
        labels : np.ndarray
            Class labels of shape (n_trials,).
        """
        self._lda.fit(features, labels)

    def predict_certainty(self, features: np.ndarray) -> float:
        """Compute classification certainty in [-1, +1] range.

        Positive values indicate class 1 (RIGHT), negative indicate class 0 (LEFT).

        Parameters
        ----------
        features : np.ndarray
            Feature vector of shape (n_features,).

        Returns
        -------
        float
            Certainty value in [-1, +1].
        """
        proba = self._lda.predict_proba(features.reshape(1, -1))
        return float(proba[0, 1] - proba[0, 0])

    @property
    def coef_(self) -> np.ndarray:
        """LDA coefficient array."""
        return self._lda.coef_

    @property
    def intercept_(self) -> np.ndarray:
        """LDA intercept array."""
        return self._lda.intercept_

    @property
    def classes_(self) -> np.ndarray:
        """Fitted class labels."""
        return self._lda.classes_


# ---------------------------------------------------------------------------
# BCI Trainer
# ---------------------------------------------------------------------------


class BCITrainer:
    """Orchestrates CSP + LDA training with trial count validation.

    Parameters
    ----------
    min_trials_per_class : int
        Minimum trials required per class before training (default 40).
    n_components : int
        Number of CSP components (default 4).
    """

    def __init__(
        self, min_trials_per_class: int = 40, n_components: int = 4
    ) -> None:
        self.min_trials_per_class = min_trials_per_class
        self.n_components = n_components

    def fit(
        self, epochs: dict[str, list[np.ndarray]]
    ) -> tuple[CSPFilter, LDAClassifier]:
        """Train CSP filter and LDA classifier from epoched trial data.

        Parameters
        ----------
        epochs : dict[str, list[np.ndarray]]
            Mapping from class label to list of trial arrays.

        Returns
        -------
        tuple[CSPFilter, LDAClassifier]
            Fitted CSP filter and LDA classifier.

        Raises
        ------
        ValueError
            If any class has fewer than min_trials_per_class trials.
        """
        for label, trials in epochs.items():
            if len(trials) < self.min_trials_per_class:
                raise ValueError(
                    f"At least {self.min_trials_per_class} trials per class "
                    f"required, but class '{label}' has {len(trials)}"
                )

        classes = list(epochs.keys())
        trials_class1 = epochs[classes[0]]
        trials_class2 = epochs[classes[1]]

        csp = CSPFilter(n_components=self.n_components)
        csp.fit(trials_class1, trials_class2)

        # Extract log-variance features for all trials
        features = []
        labels = []
        for trial in trials_class1:
            features.append(csp.transform(trial))
            labels.append(0)
        for trial in trials_class2:
            features.append(csp.transform(trial))
            labels.append(1)

        lda = LDAClassifier()
        lda.fit(np.array(features), np.array(labels))

        return csp, lda


# ---------------------------------------------------------------------------
# Weight persistence
# ---------------------------------------------------------------------------


def save_weights(
    path: str, csp: CSPFilter, lda: LDAClassifier, axis: str = "LR"
) -> None:
    """Save CSP and LDA weights to JSON file.

    Parameters
    ----------
    path : str
        Output file path.
    csp : CSPFilter
        Fitted CSP filter.
    lda : LDAClassifier
        Fitted LDA classifier.
    axis : str
        Axis identifier stored in the file ("LR" or "UD"). Default "LR".
    """
    if csp.W_ is None:
        raise RuntimeError("CSPFilter has not been fitted yet")

    data = {
        "version": 1,
        "axis": axis,
        "n_components": csp.n_components,
        "csp_w": csp.W_.tolist(),
        "lda_coef": lda.coef_.tolist(),
        "lda_intercept": lda.intercept_.tolist(),
        "lda_classes": lda.classes_.tolist(),
    }
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def load_weights(path: str) -> tuple[CSPFilter, LDAClassifier, str]:
    """Load CSP and LDA weights from JSON file.

    Parameters
    ----------
    path : str
        Input file path.

    Returns
    -------
    tuple[CSPFilter, LDAClassifier, str]
        Reconstructed CSP filter, LDA classifier, and axis string.
        If the file has no "axis" key, defaults to "LR" for backward
        compatibility.

    Raises
    ------
    FileNotFoundError
        If path does not exist.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Weight file not found: {path}")

    with open(path) as f:
        data = json.load(f)

    # Reconstruct CSPFilter
    csp = CSPFilter(n_components=data["n_components"])
    csp.W_ = np.array(data["csp_w"])

    # Reconstruct LDAClassifier
    lda = LDAClassifier()
    lda._lda.coef_ = np.array(data["lda_coef"])
    lda._lda.intercept_ = np.array(data["lda_intercept"])
    lda._lda.classes_ = np.array(data["lda_classes"])

    axis = data.get("axis", "LR")

    return csp, lda, axis
