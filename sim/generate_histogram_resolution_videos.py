#!/usr/bin/env python3
"""Generate MKV videos for different histogram/LUT address resolutions."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import numpy as np

import hist_nonlinear_model as model


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = REPO_ROOT / "data" / "corrected-videos" / "rec0.mkv"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "data" / "corrected-videos" / "histogram-resolution"


def probe_fps(path: Path) -> float:
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=r_frame_rate",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    rate = json.loads(probe.stdout)["streams"][0].get("r_frame_rate", "22/1")
    numerator, denominator = rate.split("/")
    denominator_value = float(denominator)
    if denominator_value == 0:
        return 22.0
    return float(numerator) / denominator_value


def encode_gray16_mkv(frames: np.ndarray, output_path: Path, *, fps: float) -> None:
    frame_count, height, width = frames.shape
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg",
        "-y",
        "-v",
        "error",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "gray16le",
        "-s:v",
        f"{width}x{height}",
        "-r",
        f"{fps:.6f}",
        "-i",
        "-",
        "-an",
        "-c:v",
        "ffv1",
        "-level",
        "3",
        "-g",
        "1",
        "-slicecrc",
        "1",
        str(output_path),
    ]
    process = subprocess.Popen(command, stdin=subprocess.PIPE)
    assert process.stdin is not None
    try:
        process.stdin.write(frames.astype(np.uint16, copy=False).tobytes(order="C"))
    finally:
        process.stdin.close()
    return_code = process.wait()
    if return_code != 0:
        raise RuntimeError(f"ffmpeg failed while writing {output_path}")
    print(f"wrote {output_path} ({frame_count} frames)")


def parse_histogram_bits(value: str) -> list[int]:
    bits = [int(part.strip()) for part in value.split(",") if part.strip()]
    if not bits:
        raise argparse.ArgumentTypeError("at least one histogram bit width is required")
    for bit_width in bits:
        if not 1 <= bit_width <= model.DEFAULT_INPUT_BITS:
            raise argparse.ArgumentTypeError(f"histogram bit width must be 1..{model.DEFAULT_INPUT_BITS}")
    return bits


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate hardware-model videos for histogram bit-depth comparison.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--histogram-bits", type=parse_histogram_bits, default=[14, 12, 10])
    parser.add_argument("--output-bits", type=int, default=14)
    parser.add_argument("--max-frames", type=int)
    parser.add_argument("--fps", type=float, help="override detected input FPS")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    fps = args.fps if args.fps is not None else probe_fps(args.input)
    frames = model.load_frames(args.input, width=model.DEFAULT_WIDTH, height=model.DEFAULT_HEIGHT, max_frames=args.max_frames)
    input_stem = args.input.stem

    for histogram_bits in args.histogram_bits:
        print(f"processing histogram_bits={histogram_bits}")
        output_frames, stats = model.process_frames_previous_lut(
            frames,
            input_bits=model.DEFAULT_INPUT_BITS,
            output_bits=args.output_bits,
            histogram_bits=histogram_bits,
        )
        output_path = args.output_dir / (
            f"{input_stem}_nonlinear_hist{histogram_bits}bit_out{args.output_bits}bit.mkv"
        )
        stats_path = output_path.with_suffix(".json")
        encode_gray16_mkv(output_frames, output_path, fps=fps)
        model.save_stats(stats_path, stats)
        print(f"wrote {stats_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
