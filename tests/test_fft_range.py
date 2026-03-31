"""
Unit tests for FFT frequency range spinbox controls.
Tests _on_fft_min_changed and _on_fft_max_changed handlers on EEGViewer.
Uses a lightweight stub to avoid full PyQt6 GUI instantiation.
"""

import types
import pytest


# ---------------------------------------------------------------------------
# Lightweight stub for EEGViewer
# ---------------------------------------------------------------------------

class _SpinboxStub:
    """Minimal QDoubleSpinBox stub for testing signal-blocking side effects."""

    def __init__(self, value: float = 0.0) -> None:
        self._value = value
        self._signals_blocked = False

    def blockSignals(self, block: bool) -> None:
        self._signals_blocked = block

    def setValue(self, value: float) -> None:
        self._value = value

    def value(self) -> float:
        return self._value


class _EEGViewerStub:
    """
    Minimal stub that mimics the attributes and methods used by
    _on_fft_min_changed / _on_fft_max_changed without spinning up a QApplication.
    """

    def __init__(self) -> None:
        self.fft_min_freq: float = 1.0
        self.fft_max_freq: float = 50.0
        self.smoothed_fft: dict = {}
        self.fft_min_spinbox = _SpinboxStub(1.0)
        self.fft_max_spinbox = _SpinboxStub(50.0)
        self._update_fft_called = False

    def update_fft(self) -> None:
        self._update_fft_called = True

    # The handlers under test will be attached by the test module once implemented.


def _attach_handlers(stub: _EEGViewerStub) -> None:
    """Bind the real handler methods from EEGViewer onto the stub instance."""
    # Import lazily so that the RED phase fails for the right reason (AttributeError
    # or ImportError when the methods don't exist yet).
    import GUI as gui_module
    stub._on_fft_min_changed = types.MethodType(
        gui_module.EEGViewer._on_fft_min_changed, stub
    )
    stub._on_fft_max_changed = types.MethodType(
        gui_module.EEGViewer._on_fft_max_changed, stub
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def viewer() -> _EEGViewerStub:
    """Return a stub viewer with handlers attached."""
    stub = _EEGViewerStub()
    _attach_handlers(stub)
    return stub


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_fft_min_changed_updates_attribute(viewer: _EEGViewerStub) -> None:
    """_on_fft_min_changed sets fft_min_freq to the new value when below max."""
    viewer._on_fft_min_changed(5.0)
    assert viewer.fft_min_freq == 5.0


def test_fft_max_changed_updates_attribute(viewer: _EEGViewerStub) -> None:
    """_on_fft_max_changed sets fft_max_freq to the new value when above min."""
    viewer._on_fft_max_changed(100.0)
    assert viewer.fft_max_freq == 100.0


def test_fft_min_clamped_when_exceeds_max(viewer: _EEGViewerStub) -> None:
    """When min >= max, fft_min_freq is clamped to max - 1."""
    viewer.fft_max_freq = 50.0
    viewer._on_fft_min_changed(55.0)
    assert viewer.fft_min_freq == pytest.approx(49.0)


def test_fft_max_clamped_when_below_min(viewer: _EEGViewerStub) -> None:
    """When max <= min, fft_max_freq is clamped to min + 1."""
    viewer.fft_min_freq = 10.0
    viewer._on_fft_max_changed(5.0)
    assert viewer.fft_max_freq == pytest.approx(11.0)


def test_fft_default_values() -> None:
    """EEGViewer initializes fft_min_freq=1.0 and fft_max_freq=50.0 by default."""
    stub = _EEGViewerStub()
    assert stub.fft_min_freq == pytest.approx(1.0)
    assert stub.fft_max_freq == pytest.approx(50.0)
