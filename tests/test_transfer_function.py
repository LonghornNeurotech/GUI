"""Tests for dsp.transfer_function -- piecewise nonlinear transfer function."""

from __future__ import annotations

import pytest

from dsp.transfer_function import apply_transfer_function


# ---------------------------------------------------------------------------
# Dead zone: |x| <= 0.05 -> 0.0
# ---------------------------------------------------------------------------


class TestDeadZone:
    def test_dead_zone_zero(self) -> None:
        assert apply_transfer_function(0.0) == 0.0

    def test_dead_zone_boundary_positive(self) -> None:
        assert apply_transfer_function(0.05) == 0.0

    def test_dead_zone_boundary_negative(self) -> None:
        assert apply_transfer_function(-0.05) == 0.0

    def test_dead_zone_small_values(self) -> None:
        assert apply_transfer_function(0.03) == 0.0
        assert apply_transfer_function(-0.01) == 0.0


# ---------------------------------------------------------------------------
# Saturation: |x| >= 1.0 -> sign(x) * 0.9009
# ---------------------------------------------------------------------------


class TestSaturation:
    def test_saturation_positive(self) -> None:
        assert apply_transfer_function(1.0) == pytest.approx(0.9009, abs=1e-8)

    def test_saturation_negative(self) -> None:
        assert apply_transfer_function(-1.0) == pytest.approx(-0.9009, abs=1e-8)

    def test_saturation_large(self) -> None:
        assert apply_transfer_function(5.0) == pytest.approx(0.9009, abs=1e-8)
        assert apply_transfer_function(-10.0) == pytest.approx(-0.9009, abs=1e-8)


# ---------------------------------------------------------------------------
# Quadratic region: 0.05 < |x| < 1.0
#   y = sign(x) * (0.1 * R * |x|^2 + 0.3 * R * |x| + 2.25e-7)
# ---------------------------------------------------------------------------


class TestQuadratic:
    def test_quadratic_positive_sign(self) -> None:
        assert apply_transfer_function(0.5) > 0

    def test_quadratic_negative_sign(self) -> None:
        assert apply_transfer_function(-0.5) < 0

    def test_quadratic_formula_r1(self) -> None:
        # x=0.5, r=1.0: 0.1*0.25 + 0.3*0.5 + 2.25e-7 = 0.175000225
        expected = 0.1 * 0.25 + 0.3 * 0.5 + 2.25e-7
        assert apply_transfer_function(0.5, r=1.0) == pytest.approx(expected, abs=1e-8)

    def test_quadratic_formula_r3(self) -> None:
        # x=0.5, r=3.0: 0.3*0.25 + 0.9*0.5 + 2.25e-7 = 0.525000225
        expected = 0.3 * 0.25 + 0.9 * 0.5 + 2.25e-7
        assert apply_transfer_function(0.5, r=3.0) == pytest.approx(expected, abs=1e-8)

    def test_quadratic_output_can_exceed_saturation_value(self) -> None:
        # With R=3.0, x=0.99 -- output should exceed 0.9009
        # y = 3.0 * (0.1*0.99^2 + 0.3*0.99 + 2.25e-7) = 3*(0.09801+0.297+2.25e-7) ~ 1.18503
        result = apply_transfer_function(0.99, r=3.0)
        assert result > 0.9009


# ---------------------------------------------------------------------------
# R factor behaviour (XFER-04)
# ---------------------------------------------------------------------------


class TestRFactor:
    def test_r_factor_default(self) -> None:
        assert apply_transfer_function(0.5) == apply_transfer_function(0.5, r=1.0)

    def test_r_factor_scales_quadratic(self) -> None:
        assert apply_transfer_function(0.5, r=2.0) > apply_transfer_function(0.5, r=1.0)

    def test_r_factor_does_not_affect_dead_zone(self) -> None:
        assert apply_transfer_function(0.03, r=5.0) == 0.0

    def test_r_factor_does_not_affect_saturation(self) -> None:
        assert apply_transfer_function(1.5, r=5.0) == pytest.approx(0.9009, abs=1e-8)


# ---------------------------------------------------------------------------
# Symmetry: f(x) == -f(-x)
# ---------------------------------------------------------------------------


class TestSymmetry:
    @pytest.mark.parametrize("x", [0.0, 0.05, 0.1, 0.3, 0.5, 0.7, 0.99, 1.0, 3.0])
    def test_symmetry(self, x: float) -> None:
        assert apply_transfer_function(x) == pytest.approx(
            -apply_transfer_function(-x), abs=1e-12
        )
