#!/usr/bin/env python3
"""Apply enhancement algorithms to corrected i3s MKV recordings."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

import numpy as np


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
SRC_DIR = SCRIPT_DIR / "src"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from histogram_nonlinear_scaling import nonlinear_histogram_scale
from show_i3s_frames import (
    ffmpeg_environment,
    probe_video,
    read_video_frame,
    start_video_decoder,
)


DEFAULT_VIDEO_DIR = REPO_ROOT / "data" / "corrected-videos"
DEFAULT_OUTPUT_DIR = DEFAULT_VIDEO_DIR / "enhanced"


def find_video(video_dir: Path, recording: Optional[str]) -> Path:
    """Return a selected MKV path, or the first MKV in the corrected-video folder."""

    if recording:
        video_path = Path(recording)
        if video_path.is_file():
            return video_path
        if not video_path.is_absolute():
            video_path = video_dir / video_path
        if video_path.is_file():
            return video_path
        if video_path.suffix == "":
            video_path = video_path.with_suffix(".mkv")
        if video_path.is_file():
            return video_path
        raise FileNotFoundError(f"video recording not found: {recording}")

    videos = sorted(video_dir.glob("*.mkv"))
    if not videos:
        raise FileNotFoundError(f"no MKV recordings found under {video_dir}")
    return videos[0]


def enhance_frame_nonlinear(
    frame: np.ndarray,
    *,
    output_bits: int,
    input_max: int,
) -> np.ndarray:
    """Enhance one corrected 16-bit frame with the histogram non-linear scaler."""

    if output_bits == 8:
        return nonlinear_histogram_scale(
            frame,
            input_levels=input_max + 1,
            input_min=0,
            input_max=input_max,
            output_max=255,
            output_dtype=np.uint8,
        )
    if output_bits == 16:
        return nonlinear_histogram_scale(
            frame,
            input_levels=input_max + 1,
            input_min=0,
            input_max=input_max,
            output_max=65535,
            output_dtype=np.uint16,
        )
    raise ValueError("output_bits must be 8 or 16")


def start_video_encoder(output_path: Path, *, width: int, height: int, fps: float, output_bits: int):
    import shutil
    import subprocess

    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path is None:
        raise RuntimeError("ffmpeg is required to export enhanced video, but it was not found on PATH")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    pixel_format = "gray" if output_bits == 8 else "gray16le"
    command = [
        ffmpeg_path,
        "-y",
        "-loglevel",
        "error",
        "-f",
        "rawvideo",
        "-pix_fmt",
        pixel_format,
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
    return subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.PIPE, env=ffmpeg_environment())


def export_enhanced_video(
    video_path: Path,
    *,
    output_path: Path,
    output_bits: int,
    fps_override: Optional[float],
    input_max: int,
) -> None:
    """Decode a corrected MKV, enhance every frame, and write a new MKV."""

    width, height, probed_fps, frame_count = probe_video(video_path)
    fps = fps_override or probed_fps or 22.0
    decoder = start_video_decoder(video_path)
    encoder = start_video_encoder(output_path, width=width, height=height, fps=fps, output_bits=output_bits)
    assert encoder.stdin is not None

    print(f"Enhancing {video_path}")
    print(f"Writing {output_bits}-bit enhanced video to {output_path}")

    frame_index = 0
    try:
        while True:
            frame = read_video_frame(decoder, height=height, width=width)
            if frame is None:
                break
            enhanced = enhance_frame_nonlinear(frame, output_bits=output_bits, input_max=input_max)
            encoder.stdin.write(enhanced.tobytes(order="C"))
            frame_index += 1
            if frame_index % 50 == 0 or frame_index == frame_count:
                total = frame_count if frame_count is not None else "?"
                print(f"  wrote {frame_index}/{total} frames")
    finally:
        if decoder.poll() is None:
            decoder.terminate()
        if not encoder.stdin.closed:
            encoder.stdin.close()

    stderr = encoder.stderr.read() if encoder.stderr is not None else b""
    return_code = encoder.wait()
    if return_code != 0:
        raise RuntimeError(stderr.decode("utf-8", errors="replace"))
    print(f"Done: {frame_index} frames")


def display_enhanced_video(
    video_path: Path,
    *,
    output_bits: int,
    fps_override: Optional[float],
    input_max: int,
    compare_original: bool,
) -> None:
    """Preview an enhanced corrected MKV without writing a new file."""

    import matplotlib.pyplot as plt
    from matplotlib.animation import FuncAnimation

    width, height, probed_fps, frame_count = probe_video(video_path)
    fps = fps_override or probed_fps or 22.0
    decoder = start_video_decoder(video_path)
    first_frame = read_video_frame(decoder, height=height, width=width)
    if first_frame is None:
        raise RuntimeError(f"no frames decoded from {video_path}")

    first_enhanced = enhance_frame_nonlinear(first_frame, output_bits=output_bits, input_max=input_max)
    if compare_original:
        fig, axes = plt.subplots(1, 2, figsize=(12, 5), constrained_layout=True)
        original_image = axes[0].imshow(first_frame, cmap="gray")
        enhanced_image = axes[1].imshow(first_enhanced, cmap="gray", vmin=0, vmax=(2**output_bits) - 1)
        axes[0].set_title("Corrected")
        axes[1].set_title("Enhanced")
        for axis in axes:
            axis.axis("off")
    else:
        fig, axis = plt.subplots(figsize=(8, 6), constrained_layout=True)
        original_image = None
        enhanced_image = axis.imshow(first_enhanced, cmap="gray", vmin=0, vmax=(2**output_bits) - 1)
        axis.axis("off")

    frame_label = fig.suptitle("")
    frame_number = 1
    interval_ms = 1000.0 / max(fps, 0.1)

    def close_decoder() -> None:
        if decoder.poll() is None:
            decoder.terminate()

    fig.canvas.mpl_connect("close_event", lambda _event: close_decoder())

    def update(_frame_number: int):
        nonlocal frame_number
        frame = read_video_frame(decoder, height=height, width=width)
        if frame is None:
            animation.event_source.stop()
            close_decoder()
            frame_label.set_text(f"{video_path.name} | ended at frame {frame_number}")
            return tuple(image for image in (original_image, enhanced_image, frame_label) if image is not None)

        enhanced = enhance_frame_nonlinear(frame, output_bits=output_bits, input_max=input_max)
        if original_image is not None:
            original_image.set_data(frame)
        enhanced_image.set_data(enhanced)
        frame_number += 1
        total = frame_count if frame_count is not None else "?"
        frame_label.set_text(f"{video_path.name} | frame {frame_number}/{total}")
        return tuple(image for image in (original_image, enhanced_image, frame_label) if image is not None)

    total = frame_count if frame_count is not None else "?"
    frame_label.set_text(f"{video_path.name} | frame 1/{total}")
    animation = FuncAnimation(fig, update, interval=interval_ms, blit=False, cache_frame_data=False)
    fig._i3s_animation = animation
    plt.show()
    close_decoder()


def default_output_path(video_path: Path, output_dir: Path, output_bits: int) -> Path:
    return output_dir / f"{video_path.stem}_nonlinear_{output_bits}bit.mkv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Apply enhancement algorithms to corrected i3s MKV recordings."
    )
    parser.add_argument("--video-dir", type=Path, default=DEFAULT_VIDEO_DIR)
    parser.add_argument(
        "--recording",
        help="MKV file name, stem such as rec0, or path. Defaults to the first MKV in data/corrected-videos.",
    )
    parser.add_argument("--output", type=Path, help="output MKV path for export mode")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--output-bits", type=int, choices=(8, 16), default=8)
    parser.add_argument("--input-max", type=int, default=65535, help="input range maximum for the scaler")
    parser.add_argument("--fps", type=float, help="override detected FPS")
    parser.add_argument("--export", action="store_true", help="write enhanced MKV instead of previewing")
    parser.add_argument("--compare-original", action="store_true", help="show corrected and enhanced frames side by side")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    video_path = find_video(args.video_dir, args.recording)

    if args.export:
        output_path = args.output or default_output_path(video_path, args.output_dir, args.output_bits)
        export_enhanced_video(
            video_path,
            output_path=output_path,
            output_bits=args.output_bits,
            fps_override=args.fps,
            input_max=args.input_max,
        )
        return

    display_enhanced_video(
        video_path,
        output_bits=args.output_bits,
        fps_override=args.fps,
        input_max=args.input_max,
        compare_original=args.compare_original,
    )


if __name__ == "__main__":
    main()
