"""Piecewise nonlinear transfer function for BCI control signals.

Shapes raw z-scored control signals through three regions:
  Dead zone:   |x| <= 0.05  -> 0.0
  Quadratic:   0.05 < |x| < 1.0  -> sign(x) * (0.1*r*|x|^2 + 0.3*r*|x| + 2.25e-7)
  Saturation:  |x| >= 1.0  -> sign(x) * 0.9009

Based on published BCI drone study transfer function. The R parameter is a
subject-specific weighting factor (XFER-04).
"""

from __future__ import annotations

import numpy as np


def apply_transfer_function(x: float, r: float = 1.0) -> float:
    """Apply piecewise nonlinear transfer function to z-scored control signal.

    Three regions (per XFER-01, XFER-02, XFER-03):
      Dead zone:   |x| <= 0.05  -> 0.0
      Quadratic:   0.05 < |x| < 1.0  -> sign(x) * (0.1*r*|x|^2 + 0.3*r*|x| + 2.25e-7)
      Saturation:  |x| >= 1.0  -> sign(x) * 0.9009

    Parameters
    ----------
    x : float
        Z-scored control signal (SD from REST baseline).
    r : float
        Subject-specific weighting factor (per XFER-04, default 1.0).

    Returns
    -------
    float
        Shaped control signal value.
    """
    ax = abs(x)
    if ax <= 0.05:
        return 0.0
    if ax >= 1.0:
        return float(np.sign(x)) * 0.9009
    y = 0.1 * r * ax ** 2 + 0.3 * r * ax + 2.25e-7
    return float(np.sign(x)) * y
