"""Non-linear histogram based image scaling.

The algorithm follows the fourth method in the histogram-based gain-control
description: histogram counts are converted to integer base-2 logarithms,
accumulated, normalized to the output range, and then used as an image LUT.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple, Union

import numpy as np


ArrayLikeResult = Union[np.ndarray, Tuple[np.ndarray, np.ndarray], "NonLinearResult"]


@dataclass(frozen=True)
class NonLinearResult:
    """Detailed output for a non-linear scaling operation."""

    image: np.ndarray
    lut: np.ndarray
    histogram: np.ndarray
    modified_histogram: np.ndarray
    cumulative_modified_histogram: np.ndarray


def _validate_output_range(output_min: int, output_max: int) -> None:
    if not isinstance(output_min, (int, np.integer)):
        raise TypeError("output_min must be an integer")
    if not isinstance(output_max, (int, np.integer)):
        raise TypeError("output_max must be an integer")
    if output_max <= output_min:
        raise ValueError("output_max must be greater than output_min")


def _validate_output_dtype(dtype: Union[np.dtype, type], output_min: int, output_max: int) -> np.dtype:
    dtype = np.dtype(dtype)
    if not np.issubdtype(dtype, np.integer):
        raise TypeError("output dtype must be an integer dtype")

    info = np.iinfo(dtype)
    if output_min < info.min or output_max > info.max:
        raise ValueError(
            f"output range {output_min}..{output_max} does not fit in dtype {dtype}"
        )
    return dtype


def _infer_levels(image: np.ndarray, input_levels: Optional[int]) -> int:
    if input_levels is not None:
        if not isinstance(input_levels, (int, np.integer)):
            raise TypeError("input_levels must be an integer")
        if input_levels < 2:
            raise ValueError("input_levels must be at least 2")
        return int(input_levels)

    if np.issubdtype(image.dtype, np.integer):
        info = np.iinfo(image.dtype)
        if info.min < 0:
            data_min = int(np.min(image))
            data_max = int(np.max(image))
            if data_min < 0:
                raise ValueError(
                    "signed integer images with negative values require input_levels "
                    "and input_min"
                )
            return max(data_max + 1, 2)
        return int(info.max) + 1

    data_max = float(np.nanmax(image))
    if data_max <= 1.0:
        return 256
    return max(int(np.ceil(data_max)) + 1, 2)


def _quantize_image(
    image: np.ndarray,
    *,
    input_levels: Optional[int],
    input_min: Optional[float],
    input_max: Optional[float],
) -> Tuple[np.ndarray, int]:
    if image.size == 0:
        raise ValueError("image must not be empty")
    if not np.issubdtype(image.dtype, np.number):
        raise TypeError("image must contain numeric data")
    if not np.all(np.isfinite(image)):
        raise ValueError("image must not contain NaN or infinite values")

    levels = _infer_levels(image, input_levels)

    if input_min is None:
        input_min = 0.0
    if input_max is None:
        input_max = float(levels - 1)
    if input_max <= input_min:
        raise ValueError("input_max must be greater than input_min")

    if np.issubdtype(image.dtype, np.integer) and input_min == 0 and input_max == levels - 1:
        quantized = np.clip(image, 0, levels - 1).astype(np.int64, copy=False)
    else:
        normalized = (image.astype(np.float64, copy=False) - input_min) / (input_max - input_min)
        quantized = np.rint(np.clip(normalized, 0.0, 1.0) * (levels - 1)).astype(np.int64)

    print(f"levels: {levels}")
    print(f"quantized image: {quantized}")

    return quantized, levels


def integer_log2_counts(histogram: np.ndarray) -> np.ndarray:
    """Return floor(log2(count)) for every non-zero histogram count.

    Zero-count bins remain zero because the hardware logarithm table has no
    useful logarithmic contribution for an absent intensity level.
    """

    if histogram.ndim != 1:
        raise ValueError("histogram must be one-dimensional")
    if np.any(histogram < 0):
        raise ValueError("histogram counts must be non-negative")

    modified = np.zeros_like(histogram, dtype=np.uint64)
    mask = histogram > 0
    modified[mask] = np.floor(np.log2(histogram[mask].astype(np.float64))).astype(np.uint64)
    return modified


def build_nonlinear_lut(
    histogram: np.ndarray,
    *,
    output_min: int = 0,
    output_max: int = 255,
    dtype: Union[np.dtype, type] = np.uint8,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Build a non-linear conversion LUT from a histogram.

    Parameters
    ----------
    histogram:
        One-dimensional array where index is the input intensity and value is
        the number of pixels with that intensity.
    output_min, output_max:
        Inclusive output value range. The PDF uses 0 and 255.
    dtype:
        NumPy dtype for the returned LUT.

    Returns
    -------
    tuple
        ``(lut, modified_histogram, cumulative_modified_histogram)``.
    """

    _validate_output_range(output_min, output_max)
    dtype = _validate_output_dtype(dtype, output_min, output_max)
    histogram = np.asarray(histogram)
    if histogram.ndim != 1:
        raise ValueError("histogram must be one-dimensional")
    if np.any(histogram < 0):
        raise ValueError("histogram counts must be non-negative")

    histogram = histogram.astype(np.uint64, copy=False)
    modified = integer_log2_counts(histogram)
    cumulative = np.cumsum(modified, dtype=np.uint64)

    total = int(cumulative[-1]) if cumulative.size else 0
    if total == 0:
        lut = np.full(histogram.shape, output_min, dtype=dtype)
        return lut, modified, cumulative

    scale = (output_max - output_min) / total
    lut_float = output_min + cumulative.astype(np.float64) * scale
    lut = np.rint(np.clip(lut_float, output_min, output_max)).astype(dtype)
    return lut, modified, cumulative


def nonlinear_histogram_scale(
    image: np.ndarray,
    *,
    input_levels: Optional[int] = None,
    input_min: Optional[float] = None,
    input_max: Optional[float] = None,
    output_min: int = 0,
    output_max: int = 255,
    output_dtype: Union[np.dtype, type] = np.uint8,
    return_lut: bool = False,
    return_details: bool = False,
) -> ArrayLikeResult:
    """Apply non-linear histogram scaling to a NumPy image.

    Parameters
    ----------
    image:
        Numeric NumPy array of any shape. Integer images are used directly as
        LUT addresses. Floating-point images are quantized to ``input_levels``.
    input_levels:
        Number of possible input intensity levels. For 14-bit hardware input,
        pass ``2**14``. Unsigned integer arrays default to the full dtype range.
    input_min, input_max:
        Input range to quantize into ``input_levels``. Values outside the range
        are clipped. Defaults to ``0`` and ``input_levels - 1``.
    output_min, output_max:
        Inclusive output range. Defaults to 8-bit ``0..255``.
    output_dtype:
        NumPy dtype for the scaled image.
    return_lut:
        Return ``(scaled_image, lut)`` instead of only the scaled image.
    return_details:
        Return a ``NonLinearResult`` with intermediate tables. This takes
        precedence over ``return_lut``.
    """

    image_array = np.asarray(image)
    quantized, levels = _quantize_image(
        image_array,
        input_levels=input_levels,
        input_min=input_min,
        input_max=input_max,
    )
    histogram = np.bincount(quantized.ravel(), minlength=levels).astype(np.uint64, copy=False)
    lut, modified, cumulative = build_nonlinear_lut(
        histogram,
        output_min=output_min,
        output_max=output_max,
        dtype=output_dtype,
    )
    scaled = lut[quantized].astype(output_dtype, copy=False)

    if return_details:
        return NonLinearResult(
            image=scaled,
            lut=lut,
            histogram=histogram,
            modified_histogram=modified,
            cumulative_modified_histogram=cumulative,
        )
    if return_lut:
        return scaled, lut
    return scaled
