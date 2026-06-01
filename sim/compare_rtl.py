#!/usr/bin/env python3
"""Compare Verilated RTL output against the Python hardware-behavior model."""

from __future__ import annotations

import argparse
import subprocess
import tempfile
from pathlib import Path

import numpy as np

import hist_nonlinear_model as model


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RTL_BIN = Path(__file__).resolve().parent / "obj_dir" / "Vhist_nonlinear_axi"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run bit-exact RTL comparison against the Python model.")
    parser.add_argument("--input", type=Path, default=REPO_ROOT / "data" / "corrected-videos" / "rec0.mkv")
    parser.add_argument("--rtl-bin", type=Path, default=DEFAULT_RTL_BIN)
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=512)
    parser.add_argument("--max-frames", type=int, default=2)
    parser.add_argument("--input-bits", type=int, default=14)
    parser.add_argument("--output-bits", type=int, default=10)
    parser.add_argument("--histogram-bits", type=int, default=10)
    parser.add_argument("--input-stall-period", type=int, default=0)
    parser.add_argument("--output-stall-period", type=int, default=0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.rtl_bin.is_file():
        raise FileNotFoundError(f"RTL simulator not found: {args.rtl_bin}. Run `make -C sim rtl-sim` first.")

    frames = model.load_frames(args.input, width=args.width, height=args.height, max_frames=args.max_frames)
    expected, stats = model.process_frames_previous_lut(
        frames,
        input_bits=args.input_bits,
        output_bits=args.output_bits,
        histogram_bits=args.histogram_bits,
    )

    with tempfile.TemporaryDirectory(prefix="hist-nonlinear-compare-") as tmpdir_name:
        tmpdir = Path(tmpdir_name)
        input_path = tmpdir / "input.raw"
        expected_path = tmpdir / "expected.raw"
        rtl_path = tmpdir / "rtl.raw"
        frames.astype(np.uint16).tofile(input_path)
        expected.astype(np.uint16).tofile(expected_path)

        command = [
            str(args.rtl_bin),
            "--input",
            str(input_path),
            "--output",
            str(rtl_path),
            "--width",
            str(frames.shape[2]),
            "--height",
            str(frames.shape[1]),
        ]
        if args.input_stall_period:
            command.extend(["--input-stall-period", str(args.input_stall_period)])
        if args.output_stall_period:
            command.extend(["--output-stall-period", str(args.output_stall_period)])
        subprocess.run(command, check=True)

        rtl = np.fromfile(rtl_path, dtype=np.uint16).reshape(expected.shape)

    if not np.array_equal(expected, rtl):
        mismatch = np.flatnonzero(expected.ravel() != rtl.ravel())
        first = int(mismatch[0])
        raise AssertionError(
            f"RTL mismatch count={mismatch.size}, first_index={first}, "
            f"expected={int(expected.ravel()[first])}, rtl={int(rtl.ravel()[first])}"
        )

    print(
        f"RTL matches Python model for {frames.shape[0]} frames; "
        f"first lut totals={[item.lut_total for item in stats[:3]]}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
