import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from hist_nonlinear_model import (  # noqa: E402
    apply_lut,
    build_lut_from_frame,
    frames_to_axis,
    histogram_addresses,
    paper_log_address,
    paper_log_count,
    process_frames_previous_lut,
)


def test_paper_log_count_matches_integer_log_for_frame_count_range():
    counts = [0, 1, 2, 3, 4, 511, 512, 513, 1023, 1024, 2047, 2048, 262143, 262144, 327680]

    for count in counts:
        expected = 0 if count == 0 else count.bit_length() - 1
        assert paper_log_count(count) == expected


def test_paper_log_address_uses_compressed_1024_entry_table():
    assert paper_log_address(0) == 0
    assert paper_log_address(511) == 511
    assert paper_log_address(512) == 513
    assert paper_log_address(1024) == 514
    assert paper_log_address(262143) == 1023
    assert paper_log_address(327680) == 1023


def test_previous_lut_frame_behavior_and_first_frame_bypass():
    frame0 = np.array(
        [
            [1, 1, 1, 1],
            [2, 2, 2, 2],
            [3, 3, 3, 3],
            [4, 4, 4, 4],
        ],
        dtype=np.uint16,
    )
    frame1 = np.array(
        [
            [1, 2, 3, 4],
            [1, 2, 3, 4],
            [4, 3, 2, 1],
            [4, 3, 2, 1],
        ],
        dtype=np.uint16,
    )
    frames = np.stack([frame0, frame1])

    output, stats = process_frames_previous_lut(frames, input_bits=4, output_bits=4)
    lut0, total0 = build_lut_from_frame(frame0, input_bits=4, output_bits=4)

    np.testing.assert_array_equal(output[0], frame0)
    np.testing.assert_array_equal(output[1], lut0[frame1])
    assert stats[0].output_bypassed is True
    assert stats[0].source_lut_frame is None
    assert stats[1].output_bypassed is False
    assert stats[1].source_lut_frame == 0
    assert stats[0].histogram_bits == 4
    assert stats[0].lut_total == total0
    assert stats[0].build_cycles_after_frame == 3 * 16


def test_reduced_histogram_bits_quantize_lut_addresses():
    frame = np.array([[0, 1, 2, 3], [4, 5, 14, 15]], dtype=np.uint16)
    addresses = histogram_addresses(frame, input_bits=4, histogram_bits=2)

    np.testing.assert_array_equal(addresses, np.array([[0, 0, 0, 0], [1, 1, 3, 3]], dtype=np.uint16))

    lut, _total = build_lut_from_frame(frame, input_bits=4, output_bits=4, histogram_bits=2)
    assert lut.shape == (4,)
    mapped = apply_lut(frame, lut, input_bits=4, histogram_bits=2)
    np.testing.assert_array_equal(mapped, lut[addresses])


def test_axis_markers_are_frame_start_and_end_of_line():
    frames = np.arange(2 * 2 * 3, dtype=np.uint16).reshape((2, 2, 3))
    stream = frames_to_axis(frames)

    assert len(stream) == 12
    assert [item.tuser for item in stream] == [1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0]
    assert [item.tlast for item in stream] == [0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1]


def test_real_video_frames_smoke_if_available():
    video = Path(__file__).resolve().parents[1] / "data" / "corrected-videos" / "rec0.mkv"
    if not video.exists():
        return

    import hist_nonlinear_model as model

    frames = model.load_frames(video, width=640, height=512, max_frames=2)
    output, stats = process_frames_previous_lut(frames, input_bits=14, output_bits=14)

    assert output.shape == frames.shape
    assert output.dtype == np.uint16
    assert len(stats) == 2
    np.testing.assert_array_equal(output[0], frames[0] & 0x3FFF)
