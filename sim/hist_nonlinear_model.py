#!/usr/bin/env python3
"""Hardware-behavior model for the Verilog non-linear histogram enhancer."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Optional

import numpy as np


DEFAULT_WIDTH = 640
DEFAULT_HEIGHT = 512
DEFAULT_INPUT_BITS = 14
DEFAULT_OUTPUT_BITS = 14
DEFAULT_AXIS_BITS = 16
DEFAULT_LOG_TABLE_ENTRIES = 1024


@dataclass(frozen=True)
class FrameStats:
    frame_index: int
    source_lut_frame: Optional[int]
    output_bypassed: bool
    histogram_bits: int
    lut_total: int
    build_cycles_after_frame: int


@dataclass(frozen=True)
class AxiPixel:
    tdata: int
    tuser: int
    tlast: int


def output_max(output_bits: int) -> int:
    return (1 << output_bits) - 1


def intensity_levels(input_bits: int) -> int:
    return 1 << input_bits


def validate_bits(*, input_bits: int, output_bits: int, histogram_bits: Optional[int]) -> int:
    if input_bits < 1:
        raise ValueError("input_bits must be positive")
    if not 1 <= output_bits <= input_bits:
        raise ValueError("output_bits must satisfy 1 <= output_bits <= input_bits")
    if histogram_bits is None:
        histogram_bits = input_bits
    if not 1 <= histogram_bits <= input_bits:
        raise ValueError("histogram_bits must satisfy 1 <= histogram_bits <= input_bits")
    return histogram_bits


def histogram_levels(histogram_bits: int) -> int:
    return 1 << histogram_bits


def histogram_addresses(frame: np.ndarray, *, input_bits: int, histogram_bits: int) -> np.ndarray:
    max_input = intensity_levels(input_bits) - 1
    quantized = np.clip(frame, 0, max_input).astype(np.uint16, copy=False)
    shift = input_bits - histogram_bits
    if shift == 0:
        return quantized
    return np.right_shift(quantized, shift).astype(np.uint16, copy=False)


def paper_log_address(count: int) -> int:
    """Return the 10-bit compressed log-table address described by the PDF."""

    if count < 0:
        raise ValueError("histogram count must be non-negative")
    if count < 512:
        return count & 0x1FF
    upper_index = count >> 9
    if upper_index > 511:
        upper_index = 511
    return 0x200 | upper_index


def _floor_log2(value: int) -> int:
    if value <= 0:
        return 0
    return value.bit_length() - 1


def paper_log_table_value(address: int) -> int:
    """Return the compressed log-table value for one 10-bit address.

    The upper half represents count groups of 512 pixels. For frame counts at
    or above 2**18, paper_log_count applies a small overflow guard because the
    PDF's bit slice omits that 19th count bit even though its example frame can
    exceed 2**18 pixels.
    """

    if not 0 <= address < DEFAULT_LOG_TABLE_ENTRIES:
        raise ValueError("log table address must be 0..1023")
    if address < 512:
        return _floor_log2(address)
    return _floor_log2((address & 0x1FF) << 9)


def paper_log_count(count: int) -> int:
    if count <= 0:
        return 0
    if count >= (1 << 18):
        return 18
    return paper_log_table_value(paper_log_address(count))


def modified_histogram_from_counts(histogram: np.ndarray) -> np.ndarray:
    vectorized = np.frompyfunc(paper_log_count, 1, 1)
    return vectorized(histogram.astype(np.uint64, copy=False)).astype(np.uint32)


def build_lut_from_frame(
    frame: np.ndarray,
    *,
    input_bits: int = DEFAULT_INPUT_BITS,
    output_bits: int = DEFAULT_OUTPUT_BITS,
    histogram_bits: Optional[int] = None,
) -> tuple[np.ndarray, int]:
    histogram_bits = validate_bits(
        input_bits=input_bits,
        output_bits=output_bits,
        histogram_bits=histogram_bits,
    )
    levels = histogram_levels(histogram_bits)
    addresses = histogram_addresses(frame, input_bits=input_bits, histogram_bits=histogram_bits)
    histogram = np.bincount(addresses.ravel(), minlength=levels).astype(np.uint32, copy=False)
    modified = modified_histogram_from_counts(histogram)
    cumulative = np.cumsum(modified, dtype=np.uint64)
    total = int(cumulative[-1]) if cumulative.size else 0
    if total == 0:
        return np.zeros(levels, dtype=np.uint16), total

    max_output = output_max(output_bits)
    lut = ((cumulative * max_output) + (total // 2)) // total
    return lut.astype(np.uint16), total


def apply_lut(frame: np.ndarray, lut: np.ndarray, *, input_bits: int, histogram_bits: Optional[int] = None) -> np.ndarray:
    histogram_bits = validate_bits(
        input_bits=input_bits,
        output_bits=input_bits,
        histogram_bits=histogram_bits,
    )
    addresses = histogram_addresses(frame, input_bits=input_bits, histogram_bits=histogram_bits)
    return lut[addresses].astype(np.uint16, copy=False)


def bypass_frame(frame: np.ndarray, *, output_bits: int) -> np.ndarray:
    return (frame.astype(np.uint16, copy=False) & output_max(output_bits)).astype(np.uint16, copy=False)


def process_frames_previous_lut(
    frames: np.ndarray,
    *,
    input_bits: int = DEFAULT_INPUT_BITS,
    output_bits: int = DEFAULT_OUTPUT_BITS,
    histogram_bits: Optional[int] = None,
) -> tuple[np.ndarray, list[FrameStats]]:
    if frames.ndim != 3:
        raise ValueError("frames must have shape (frame_count, height, width)")

    histogram_bits = validate_bits(
        input_bits=input_bits,
        output_bits=output_bits,
        histogram_bits=histogram_bits,
    )
    current_lut: Optional[np.ndarray] = None
    output_frames = []
    stats = []
    build_cycles = histogram_levels(histogram_bits) * 3

    for frame_index, frame in enumerate(frames):
        if current_lut is None:
            output = bypass_frame(frame, output_bits=output_bits)
            source_lut_frame = None
            output_bypassed = True
        else:
            output = apply_lut(
                frame,
                current_lut,
                input_bits=input_bits,
                histogram_bits=histogram_bits,
            )
            source_lut_frame = frame_index - 1
            output_bypassed = False

        next_lut, lut_total = build_lut_from_frame(
            frame,
            input_bits=input_bits,
            output_bits=output_bits,
            histogram_bits=histogram_bits,
        )
        current_lut = next_lut
        output_frames.append(output)
        stats.append(
            FrameStats(
                frame_index=frame_index,
                source_lut_frame=source_lut_frame,
                output_bypassed=output_bypassed,
                histogram_bits=histogram_bits,
                lut_total=lut_total,
                build_cycles_after_frame=build_cycles,
            )
        )

    return np.stack(output_frames).astype(np.uint16), stats


def frames_to_axis(frames: np.ndarray, *, axis_bits: int = DEFAULT_AXIS_BITS) -> list[AxiPixel]:
    if frames.ndim != 3:
        raise ValueError("frames must have shape (frame_count, height, width)")
    axis_mask = (1 << axis_bits) - 1
    result = []
    for frame in frames:
        height, width = frame.shape
        for y in range(height):
            for x in range(width):
                result.append(
                    AxiPixel(
                        tdata=int(frame[y, x]) & axis_mask,
                        tuser=1 if y == 0 and x == 0 else 0,
                        tlast=1 if x == width - 1 else 0,
                    )
                )
    return result


def load_raw16_video(path: Path, *, width: int, height: int, max_frames: Optional[int] = None) -> np.ndarray:
    frame_values = width * height
    raw = np.fromfile(path, dtype=np.uint16)
    if raw.size % frame_values != 0:
        raise ValueError(f"{path} does not contain a whole number of {width}x{height} frames")
    frames = raw.reshape((-1, height, width))
    if max_frames is not None:
        frames = frames[:max_frames]
    return frames


def decode_mkv_gray16(path: Path, *, max_frames: Optional[int] = None) -> np.ndarray:
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    stream = json.loads(probe.stdout)["streams"][0]
    width = int(stream["width"])
    height = int(stream["height"])
    command = [
        "ffmpeg",
        "-v",
        "error",
        "-i",
        str(path),
        "-f",
        "rawvideo",
        "-pix_fmt",
        "gray16le",
        "-",
    ]
    decoded = subprocess.run(command, check=True, capture_output=True).stdout
    raw = np.frombuffer(decoded, dtype=np.uint16)
    frames = raw.reshape((-1, height, width))
    if max_frames is not None:
        frames = frames[:max_frames]
    return frames


def load_frames(path: Path, *, width: int, height: int, max_frames: Optional[int] = None) -> np.ndarray:
    suffix = path.suffix.lower()
    if suffix == ".npy":
        frames = np.load(path)
        if max_frames is not None:
            frames = frames[:max_frames]
        return frames.astype(np.uint16, copy=False)
    if suffix == ".mkv":
        return decode_mkv_gray16(path, max_frames=max_frames)
    return load_raw16_video(path, width=width, height=height, max_frames=max_frames)


def save_stats(path: Path, stats: Iterable[FrameStats]) -> None:
    path.write_text(json.dumps([asdict(item) for item in stats], indent=2), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the hardware-behavior non-linear histogram model.")
    parser.add_argument("--input", type=Path, required=True, help="input .npy, .mkv, or raw uint16 video")
    parser.add_argument("--output", type=Path, required=True, help="output raw uint16 video path")
    parser.add_argument("--stats", type=Path, help="optional JSON frame stats path")
    parser.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    parser.add_argument("--height", type=int, default=DEFAULT_HEIGHT)
    parser.add_argument("--max-frames", type=int)
    parser.add_argument("--input-bits", type=int, default=DEFAULT_INPUT_BITS)
    parser.add_argument("--output-bits", type=int, default=DEFAULT_OUTPUT_BITS)
    parser.add_argument(
        "--histogram-bits",
        type=int,
        help="histogram/LUT address bits; defaults to input-bits for full precision",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    frames = load_frames(args.input, width=args.width, height=args.height, max_frames=args.max_frames)
    output_frames, stats = process_frames_previous_lut(
        frames,
        input_bits=args.input_bits,
        output_bits=args.output_bits,
        histogram_bits=args.histogram_bits,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    output_frames.astype(np.uint16).tofile(args.output)
    if args.stats:
        args.stats.parent.mkdir(parents=True, exist_ok=True)
        save_stats(args.stats, stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
