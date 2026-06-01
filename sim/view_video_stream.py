#!/usr/bin/env python3
"""Operator visual test for the non-linear histogram stream behavior."""

from __future__ import annotations

import argparse
import subprocess
import tempfile
import time
from pathlib import Path

import cv2
import numpy as np

import hist_nonlinear_model as model


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VIDEO_DIR = REPO_ROOT / "data" / "corrected-videos"
DEFAULT_RTL_BIN = Path(__file__).resolve().parent / "obj_dir" / "Vhist_nonlinear_axi"


def find_video(recording: str | None, video: Path | None) -> Path:
    if video is not None:
        return video
    if recording is None:
        recording = "rec0"
    candidate = Path(recording)
    if candidate.is_file():
        return candidate
    if candidate.suffix == "":
        candidate = candidate.with_suffix(".mkv")
    if candidate.is_file():
        return candidate
    candidate = DEFAULT_VIDEO_DIR / candidate.name
    if candidate.is_file():
        return candidate
    raise FileNotFoundError(f"video not found: {recording}")


def display_u8(frame: np.ndarray, *, output_bits: int) -> np.ndarray:
    max_value = max((1 << output_bits) - 1, 1)
    clipped = np.clip(frame, 0, max_value).astype(np.float32, copy=False)
    return np.rint(clipped * (255.0 / max_value)).astype(np.uint8)


def run_python_backend(
    frames: np.ndarray,
    *,
    input_bits: int,
    output_bits: int,
    histogram_bits: int | None,
) -> np.ndarray:
    output, stats = model.process_frames_previous_lut(
        frames,
        input_bits=input_bits,
        output_bits=output_bits,
        histogram_bits=histogram_bits,
    )
    if stats:
        print(
            f"python backend: frame 0 bypassed, frame 1+ use previous-frame LUT, "
            f"{stats[0].build_cycles_after_frame} model build cycles/frame"
        )
    return output


def run_rtl_backend(
    frames: np.ndarray,
    *,
    rtl_bin: Path,
    width: int,
    height: int,
) -> np.ndarray:
    if not rtl_bin.is_file():
        raise FileNotFoundError(f"RTL simulator not found: {rtl_bin}. Run `make -C sim rtl-sim` first.")

    with tempfile.TemporaryDirectory(prefix="hist-nonlinear-rtl-") as tmpdir_name:
        tmpdir = Path(tmpdir_name)
        input_path = tmpdir / "input.raw"
        output_path = tmpdir / "output.raw"
        frames.astype(np.uint16).tofile(input_path)
        subprocess.run(
            [
                str(rtl_bin),
                "--input",
                str(input_path),
                "--output",
                str(output_path),
                "--width",
                str(width),
                "--height",
                str(height),
            ],
            check=True,
        )
        return model.load_raw16_video(output_path, width=width, height=height, max_frames=frames.shape[0])


def play_side_by_side(
    input_frames: np.ndarray,
    output_frames: np.ndarray,
    *,
    fps: float,
    output_bits: int,
) -> None:
    interval = 1.0 / max(fps, 0.1)
    start = time.perf_counter()
    slow_frames = 0

    for frame_index, (input_frame, output_frame) in enumerate(zip(input_frames, output_frames)):
        input_u8 = display_u8(input_frame & 0x3FFF, output_bits=14)
        output_u8 = display_u8(output_frame, output_bits=output_bits)
        combined = np.concatenate([input_u8, output_u8], axis=1)
        combined = cv2.cvtColor(combined, cv2.COLOR_GRAY2BGR)
        cv2.putText(combined, "input", (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
        cv2.putText(
            combined,
            "output",
            (input_u8.shape[1] + 12, 28),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (0, 255, 0),
            2,
        )
        cv2.imshow("Non-linear histogram stream test", combined)

        target_time = start + frame_index * interval
        remaining_ms = int(max((target_time - time.perf_counter()) * 1000.0, 1.0))
        if remaining_ms <= 1:
            slow_frames += 1
        key = cv2.waitKey(remaining_ms) & 0xFF
        if key in {ord("q"), 27}:
            break

    cv2.destroyAllWindows()
    if slow_frames:
        print(f"viewer warning: {slow_frames} frames could not be throttled to requested real-time FPS")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Display input/output stream behavior for operator review.")
    parser.add_argument("--video", type=Path, help="input corrected MKV, raw16, or .npy video")
    parser.add_argument("--recording", help="recording name under data/corrected-videos, default rec0")
    parser.add_argument("--max-frames", type=int, default=120)
    parser.add_argument("--fps", type=float, default=22.0)
    parser.add_argument("--input-bits", type=int, default=14)
    parser.add_argument("--output-bits", type=int, default=10)
    parser.add_argument("--histogram-bits", type=int, default=10)
    parser.add_argument("--backend", choices=("python", "rtl"), default="python")
    parser.add_argument("--rtl-bin", type=Path, default=DEFAULT_RTL_BIN)
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=512)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = find_video(args.recording, args.video)
    frames = model.load_frames(input_path, width=args.width, height=args.height, max_frames=args.max_frames)
    if args.backend == "python":
        output = run_python_backend(
            frames,
            input_bits=args.input_bits,
            output_bits=args.output_bits,
            histogram_bits=args.histogram_bits,
        )
    else:
        output = run_rtl_backend(frames, rtl_bin=args.rtl_bin, width=frames.shape[2], height=frames.shape[1])
    play_side_by_side(frames, output, fps=args.fps, output_bits=args.output_bits)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
