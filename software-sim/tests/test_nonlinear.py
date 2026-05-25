import numpy as np
import pytest

from histogram_nonlinear_scaling import build_nonlinear_lut, nonlinear_histogram_scale


def test_build_nonlinear_lut_uses_integer_log2_and_cumulative_scaling():
    histogram = np.array([0, 1, 2, 4, 8], dtype=np.uint64)

    lut, modified, cumulative = build_nonlinear_lut(histogram)

    np.testing.assert_array_equal(modified, np.array([0, 0, 1, 2, 3], dtype=np.uint64))
    np.testing.assert_array_equal(cumulative, np.array([0, 0, 1, 3, 6], dtype=np.uint64))
    np.testing.assert_array_equal(lut, np.array([0, 0, 42, 128, 255], dtype=np.uint8))


def test_nonlinear_histogram_scale_maps_image_through_lut():
    image = np.array([[0, 1, 1], [2, 2, 2], [3, 3, 3]], dtype=np.uint16)

    scaled, lut = nonlinear_histogram_scale(image, input_levels=4, return_lut=True)

    np.testing.assert_array_equal(lut, np.array([0, 85, 170, 255], dtype=np.uint8))
    np.testing.assert_array_equal(scaled, np.array([[0, 85, 85], [170, 170, 170], [255, 255, 255]], dtype=np.uint8))


def test_float_images_are_quantized_to_requested_levels():
    image = np.array([[0.0, 0.25], [0.5, 1.0]], dtype=np.float32)

    result = nonlinear_histogram_scale(
        image,
        input_levels=5,
        input_min=0.0,
        input_max=1.0,
        output_max=1023,
        output_dtype=np.uint16,
        return_details=True,
    )

    assert result.image.dtype == np.uint16
    assert result.lut.dtype == np.uint16
    assert result.lut.shape == (5,)


def test_zero_log_contribution_returns_output_min_when_no_count_repeats():
    image = np.array([0, 1, 2, 3], dtype=np.uint8)

    scaled = nonlinear_histogram_scale(image, input_levels=4)

    np.testing.assert_array_equal(scaled, np.zeros_like(image, dtype=np.uint8))


def test_invalid_input_rejected():
    with pytest.raises(ValueError, match="empty"):
        nonlinear_histogram_scale(np.array([], dtype=np.uint8))

    with pytest.raises(ValueError, match="NaN"):
        nonlinear_histogram_scale(np.array([0.0, np.nan]))
