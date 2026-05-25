"""Library API for histogram-based non-linear image scaling."""

from .nonlinear import NonLinearResult, build_nonlinear_lut, nonlinear_histogram_scale

__all__ = ["NonLinearResult", "build_nonlinear_lut", "nonlinear_histogram_scale"]
