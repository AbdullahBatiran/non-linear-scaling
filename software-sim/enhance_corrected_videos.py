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
DEFAULT_LINEAR_PERCENTILES = (1.0, 99.0)
DEFAULT_HISTOGRAM_OPTIONS = (256, "linear")


def output_format(output_bits: int) -> tuple[int, np.dtype]:
    """Return the maximum value and dtype for a supported output bit depth."""

    if output_bits == 8:
        return 255, np.dtype(np.uint8)
    if output_bits == 16:
        return 16383, np.dtype(np.uint16)
    raise ValueError("output_bits must be 8 or 16")


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

    output_max, output_dtype = output_format(output_bits)
    return nonlinear_histogram_scale(
        frame,
        input_levels=input_max + 1,
        input_min=0,
        input_max=input_max,
        output_max=output_max,
        output_dtype=output_dtype,
    )


def enhance_frame_linear(
    frame: np.ndarray,
    *,
    output_bits: int,
    input_max: int,
    lower_percentile: float = DEFAULT_LINEAR_PERCENTILES[0],
    upper_percentile: float = DEFAULT_LINEAR_PERCENTILES[1],
) -> np.ndarray:
    """Enhance one corrected frame with a percentile-clipped linear stretch."""

    output_max, output_dtype = output_format(output_bits)
    clipped = np.clip(frame, 0, input_max).astype(np.float64, copy=False)
    frame_min, frame_max = np.percentile(clipped, (lower_percentile, upper_percentile))
    frame_min = float(frame_min)
    frame_max = float(frame_max)
    if frame_max <= frame_min:
        return np.zeros(frame.shape, dtype=output_dtype)

    scaled = (clipped - frame_min) * (output_max / (frame_max - frame_min))
    return np.rint(np.clip(scaled, 0, output_max)).astype(output_dtype)


def preview_images_for_frame(
    frame: np.ndarray,
    *,
    output_bits: int,
    input_max: int,
    compare_original: bool,
    compare_linear: Optional[tuple[float, float]],
) -> list[tuple[str, np.ndarray, Optional[int], Optional[int]]]:
    """Build the titled image list for previewing one decoded frame."""

    images: list[tuple[str, np.ndarray, Optional[int], Optional[int]]] = []
    if compare_original:
        images.append(("Corrected", frame, None, None))
    if compare_linear is not None:
        lower_percentile, upper_percentile = compare_linear
        linear = enhance_frame_linear(
            frame,
            output_bits=output_bits,
            input_max=input_max,
            lower_percentile=lower_percentile,
            upper_percentile=upper_percentile,
        )
        title = f"Linear Stretch ({lower_percentile:g}-{upper_percentile:g}%)"
        images.append((title, linear, 0, (2**output_bits) - 1))

    enhanced = enhance_frame_nonlinear(frame, output_bits=output_bits, input_max=input_max)
    images.append(("Non-linear Enhanced", enhanced, 0, (2**output_bits) - 1))
    return images


def histogram_range(
    *,
    vmin: Optional[int],
    vmax: Optional[int],
    input_max: int,
) -> tuple[float, float]:
    if vmin is None or vmax is None:
        return 0.0, float(input_max)
    return float(vmin), float(vmax)


def histogram_counts(
    image: np.ndarray,
    *,
    bins: int,
    value_range: tuple[float, float],
) -> tuple[np.ndarray, np.ndarray]:
    counts, edges = np.histogram(image, bins=bins, range=value_range)
    centers = (edges[:-1] + edges[1:]) * 0.5
    return centers, counts


def create_histogram_preview(
    images: list[tuple[str, np.ndarray, Optional[int], Optional[int]]],
    *,
    bins: int,
    yscale: str,
    input_max: int,
):
    import matplotlib.pyplot as plt

    fig_width = 6 * len(images)
    fig, axes = plt.subplots(1, len(images), figsize=(fig_width, 4), constrained_layout=True)
    rendered_histograms = []

    for axis, (title, image, vmin, vmax) in zip(np.atleast_1d(axes), images):
        value_range = histogram_range(vmin=vmin, vmax=vmax, input_max=input_max)
        centers, counts = histogram_counts(image, bins=bins, value_range=value_range)
        (line,) = axis.plot(centers, counts, drawstyle="steps-mid")
        axis.set_title(title)
        axis.set_xlim(value_range)
        axis.set_ylim(histogram_ylim(counts, yscale))
        axis.set_yscale(yscale)
        rendered_histograms.append((line, axis, value_range))

    fig.suptitle(f"Histograms | {bins} bins | {yscale}")
    return fig, rendered_histograms


def histogram_ylim(counts: np.ndarray, yscale: str) -> tuple[float, float]:
    max_count = max(int(np.max(counts)) if counts.size else 0, 1)
    if yscale == "log":
        return 0.8, max_count * 1.25
    return 0.0, max_count * 1.1


def update_histogram_preview(
    rendered_histograms,
    images: list[tuple[str, np.ndarray, Optional[int], Optional[int]]],
    *,
    bins: int,
    yscale: str,
) -> None:
    for (line, axis, value_range), (_title, image, _vmin, _vmax) in zip(rendered_histograms, images):
        centers, counts = histogram_counts(image, bins=bins, value_range=value_range)
        line.set_data(centers, counts)
        axis.set_ylim(histogram_ylim(counts, yscale))


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
    compare_linear: Optional[tuple[float, float]],
    show_hist: Optional[tuple[int, str]],
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

    first_images = preview_images_for_frame(
        first_frame,
        output_bits=output_bits,
        input_max=input_max,
        compare_original=compare_original,
        compare_linear=compare_linear,
    )
    hist_fig = None
    rendered_histograms = None
    if show_hist is not None:
        hist_bins, hist_yscale = show_hist
        hist_fig, rendered_histograms = create_histogram_preview(
            first_images,
            bins=hist_bins,
            yscale=hist_yscale,
            input_max=input_max,
        )
    else:
        hist_bins = DEFAULT_HISTOGRAM_OPTIONS[0]
        hist_yscale = DEFAULT_HISTOGRAM_OPTIONS[1]

    if len(first_images) > 1:
        fig_width = 6 * len(first_images)
        fig, axes = plt.subplots(1, len(first_images), figsize=(fig_width, 5), constrained_layout=True)
        rendered_images = []
        for axis, (title, image, vmin, vmax) in zip(np.atleast_1d(axes), first_images):
            rendered_images.append(axis.imshow(image, cmap="gray", vmin=vmin, vmax=vmax))
            axis.set_title(title)
            axis.axis("off")
    else:
        fig, axis = plt.subplots(figsize=(8, 6), constrained_layout=True)
        title, image, vmin, vmax = first_images[0]
        rendered_images = [axis.imshow(image, cmap="gray", vmin=vmin, vmax=vmax)]
        axis.set_title(title)
        axis.axis("off")

    frame_label = fig.suptitle("")
    frame_number = 1
    interval_ms = 1000.0 / max(fps, 0.1)

    def close_decoder() -> None:
        if decoder.poll() is None:
            decoder.terminate()

    def close_histogram_preview() -> None:
        nonlocal rendered_histograms
        rendered_histograms = None

    def close_preview() -> None:
        close_decoder()
        if hist_fig is not None:
            plt.close(hist_fig)

    fig.canvas.mpl_connect("close_event", lambda _event: close_preview())
    if hist_fig is not None:
        hist_fig.canvas.mpl_connect("close_event", lambda _event: close_histogram_preview())

    def update(_frame_number: int):
        nonlocal frame_number
        frame = read_video_frame(decoder, height=height, width=width)
        if frame is None:
            animation.event_source.stop()
            close_decoder()
            frame_label.set_text(f"{video_path.name} | ended at frame {frame_number}")
            return (*rendered_images, frame_label)

        frame_images = preview_images_for_frame(
            frame,
            output_bits=output_bits,
            input_max=input_max,
            compare_original=compare_original,
            compare_linear=compare_linear,
        )
        for rendered_image, (_title, image, _vmin, _vmax) in zip(rendered_images, frame_images):
            rendered_image.set_data(image)
        if rendered_histograms is not None:
            update_histogram_preview(
                rendered_histograms,
                frame_images,
                bins=hist_bins,
                yscale=hist_yscale,
            )
            if hist_fig is not None:
                hist_fig.canvas.draw_idle()
        frame_number += 1
        total = frame_count if frame_count is not None else "?"
        frame_label.set_text(f"{video_path.name} | frame {frame_number}/{total}")
        return (*rendered_images, frame_label)

    total = frame_count if frame_count is not None else "?"
    frame_label.set_text(f"{video_path.name} | frame 1/{total}")
    animation = FuncAnimation(fig, update, interval=interval_ms, blit=False, cache_frame_data=False)
    fig._i3s_animation = animation
    plt.show()
    close_decoder()


def default_output_path(video_path: Path, output_dir: Path, output_bits: int) -> Path:
    return output_dir / f"{video_path.stem}_nonlinear_{output_bits}bit.mkv"


def parse_linear_percentiles(value: str) -> tuple[float, float]:
    parts = value.split(",")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError("expected LOW,HIGH percentiles, for example 1,99")

    try:
        lower_percentile = float(parts[0])
        upper_percentile = float(parts[1])
    except ValueError as error:
        raise argparse.ArgumentTypeError("linear percentiles must be numeric") from error

    if not 0.0 <= lower_percentile < upper_percentile <= 100.0:
        raise argparse.ArgumentTypeError("linear percentiles must satisfy 0 <= LOW < HIGH <= 100")
    return lower_percentile, upper_percentile


def parse_histogram_options(value: str) -> tuple[int, str]:
    if not value:
        return DEFAULT_HISTOGRAM_OPTIONS

    parts = value.split(",")
    if len(parts) > 2:
        raise argparse.ArgumentTypeError("expected BINS or BINS,linear|log")

    if len(parts) == 1 and parts[0].strip().lower() in {"linear", "log"}:
        return DEFAULT_HISTOGRAM_OPTIONS[0], parts[0].strip().lower()

    try:
        bins = int(parts[0])
    except ValueError as error:
        raise argparse.ArgumentTypeError("histogram bins must be an integer") from error

    if bins < 2:
        raise argparse.ArgumentTypeError("histogram bins must be at least 2")

    yscale = DEFAULT_HISTOGRAM_OPTIONS[1]
    if len(parts) == 2:
        yscale = parts[1].strip().lower()
        if yscale not in {"linear", "log"}:
            raise argparse.ArgumentTypeError("histogram y-scale must be linear or log")

    return bins, yscale


def normalize_comma_option_args(argv: list[str]) -> list[str]:
    normalized = []
    for arg in argv:
        if arg.startswith("--compare-linear,"):
            normalized.append(f"--compare-linear={arg.split(',', 1)[1]}")
        elif arg.startswith("--show-hist,"):
            normalized.append(f"--show-hist={arg.split(',', 1)[1]}")
        else:
            normalized.append(arg)
    return normalized


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
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
    parser.add_argument("--input-max", type=int, default=2**14-1, help="input range maximum for the scaler")
    parser.add_argument("--fps", type=float, help="override detected FPS")
    parser.add_argument("--export", action="store_true", help="write enhanced MKV instead of previewing")
    parser.add_argument("--compare-original", action="store_true", help="show corrected and enhanced frames side by side")
    parser.add_argument(
        "--compare-linear",
        nargs="?",
        const="1,99",
        default=None,
        metavar="LOW,HIGH",
        type=parse_linear_percentiles,
        help="show percentile-clipped linear stretch beside non-linear enhanced frames; defaults to 1,99",
    )
    parser.add_argument(
        "--show-hist",
        nargs="?",
        const=f"{DEFAULT_HISTOGRAM_OPTIONS[0]},{DEFAULT_HISTOGRAM_OPTIONS[1]}",
        default=None,
        metavar="BINS[,linear|log]",
        type=parse_histogram_options,
        help="show per-frame histograms in a second window; defaults to 256,linear",
    )
    return parser.parse_args(normalize_comma_option_args(argv if argv is not None else sys.argv[1:]))


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
        compare_linear=args.compare_linear,
        show_hist=args.show_hist,
    )


if __name__ == "__main__":
    main()
