#!/usr/bin/env python3
"""Display corrected i3s IR raw video frames from NumPy recordings."""

from __future__ import annotations

import argparse
import json
import warnings
from pathlib import Path
from typing import Optional, Tuple

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = REPO_ROOT / "data" / "i3s_0_7200"
DEFAULT_CORRECTION_DIR = REPO_ROOT / "data" / "i3s-bpr-gain-offset-values"


def find_recording(data_dir: Path, recording: Optional[str]) -> Path:
    """Return the raw_frames.npy path for a selected or latest recording."""

    if recording:
        recording_path = Path(recording)
        if recording_path.is_file():
            return recording_path
        if not recording_path.is_absolute():
            recording_path = data_dir / recording_path
        raw_frames = recording_path / "raw_frames.npy"
        if raw_frames.is_file():
            return raw_frames
        raise FileNotFoundError(f"recording not found: {recording}")

    recordings = sorted(data_dir.glob("*/raw_frames.npy"))
    if not recordings:
        raise FileNotFoundError(f"no raw_frames.npy files found under {data_dir}")
    return recordings[-1]


def load_metadata(raw_frames_path: Path) -> dict:
    metadata_path = raw_frames_path.with_name("metadata.json")
    if not metadata_path.is_file():
        return {}
    return json.loads(metadata_path.read_text(encoding="utf-8"))


def validate_shapes(
    frames: np.ndarray,
    gain_map: np.ndarray,
    offset_map: np.ndarray,
    bad_pixel_mask: np.ndarray,
) -> Tuple[int, int, int]:
    if frames.ndim != 3:
        raise ValueError(f"expected frames with shape (frame_count, height, width), got {frames.shape}")

    frame_count, height, width = frames.shape
    expected_shape = (height, width)
    for name, array in (
        ("gain_map", gain_map),
        ("offset_map", offset_map),
        ("bad_pixel_mask", bad_pixel_mask),
    ):
        if array.shape != expected_shape:
            raise ValueError(f"{name} shape {array.shape} does not match frame shape {expected_shape}")

    return frame_count, height, width


def replace_bad_pixels(frame: np.ndarray, bad_pixel_mask: np.ndarray) -> np.ndarray:
    """Replace masked pixels with the median of valid neighboring pixels."""

    frame_float = frame.astype(np.float32, copy=False)
    bad_pixels = bad_pixel_mask.astype(bool, copy=False)
    if not np.any(bad_pixels):
        return frame_float.copy()

    padded_frame = np.pad(frame_float, 1, mode="edge")
    padded_bad = np.pad(bad_pixels, 1, mode="constant", constant_values=True)
    neighbors = []
    valid_neighbors = []

    for row_offset in (-1, 0, 1):
        for col_offset in (-1, 0, 1):
            if row_offset == 0 and col_offset == 0:
                continue
            row_start = 1 + row_offset
            col_start = 1 + col_offset
            neighbors.append(
                padded_frame[
                    row_start : row_start + frame.shape[0],
                    col_start : col_start + frame.shape[1],
                ]
            )
            valid_neighbors.append(
                ~padded_bad[
                    row_start : row_start + frame.shape[0],
                    col_start : col_start + frame.shape[1],
                ]
            )

    neighbor_values = np.stack(neighbors, axis=0)
    valid_neighbor_mask = np.stack(valid_neighbors, axis=0)
    neighbor_values = np.where(valid_neighbor_mask, neighbor_values, np.nan)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        replacement = np.nanmedian(neighbor_values, axis=0)

    replacement = np.where(np.isfinite(replacement), replacement, frame_float)
    corrected = frame_float.copy()
    corrected[bad_pixels] = replacement[bad_pixels]
    return corrected


def apply_gain_offset(
    frame: np.ndarray,
    gain_map: np.ndarray,
    offset_map: np.ndarray,
    bad_pixel_mask: np.ndarray,
) -> np.ndarray:
    """Apply bad-pixel replacement followed by offset and gain correction."""

    replaced = replace_bad_pixels(frame, bad_pixel_mask)
    return (replaced - offset_map.astype(np.float32, copy=False)) * gain_map.astype(np.float32, copy=False)


def display_frames(
    frames: np.ndarray,
    gain_map: np.ndarray,
    offset_map: np.ndarray,
    bad_pixel_mask: np.ndarray,
    *,
    fps: float,
    start_frame: int,
    autoscale: bool,
    compare_raw: bool,
    title: str,
) -> None:
    import matplotlib.pyplot as plt
    from matplotlib.animation import FuncAnimation

    frame_count = frames.shape[0]
    start_frame = max(0, min(start_frame, frame_count - 1))
    first_corrected = apply_gain_offset(frames[start_frame], gain_map, offset_map, bad_pixel_mask)

    if autoscale:
        vmin = vmax = None
    else:
        vmin, vmax = np.percentile(first_corrected, (1, 99))
        if vmin == vmax:
            vmin, vmax = float(np.min(first_corrected)), float(np.max(first_corrected))

    if compare_raw:
        fig, axes = plt.subplots(1, 2, figsize=(12, 5), constrained_layout=True)
        raw_image = axes[0].imshow(frames[start_frame], cmap="gray")
        corrected_image = axes[1].imshow(first_corrected, cmap="gray", vmin=vmin, vmax=vmax)
        axes[0].set_title("Raw")
        axes[1].set_title("Corrected")
        for axis in axes:
            axis.axis("off")
    else:
        fig, axis = plt.subplots(figsize=(8, 6), constrained_layout=True)
        corrected_image = axis.imshow(first_corrected, cmap="gray", vmin=vmin, vmax=vmax)
        raw_image = None
        axis.axis("off")

    frame_label = fig.suptitle("")
    interval_ms = 1000.0 / max(fps, 0.1)

    def update(frame_number: int):
        frame_index = (start_frame + frame_number) % frame_count
        raw_frame = frames[frame_index]
        corrected_frame = apply_gain_offset(raw_frame, gain_map, offset_map, bad_pixel_mask)

        if raw_image is not None:
            raw_image.set_data(raw_frame)
        corrected_image.set_data(corrected_frame)
        if autoscale:
            low, high = np.percentile(corrected_frame, (1, 99))
            corrected_image.set_clim(low, high)
        frame_label.set_text(f"{title} | frame {frame_index + 1}/{frame_count}")
        return tuple(image for image in (raw_image, corrected_image, frame_label) if image is not None)

    animation = FuncAnimation(fig, update, frames=frame_count, interval=interval_ms, blit=False, repeat=True)
    fig._i3s_animation = animation
    plt.show()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Show i3s IR raw frames with bad-pixel, offset, and gain correction."
    )
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR, help="directory containing recordings")
    parser.add_argument(
        "--recording",
        help="recording folder name, recording folder path, or raw_frames.npy path; defaults to newest recording",
    )
    parser.add_argument("--correction-dir", type=Path, default=DEFAULT_CORRECTION_DIR)
    parser.add_argument("--fps", type=float, help="display FPS; defaults to recording metadata or 22")
    parser.add_argument("--start-frame", type=int, default=0)
    parser.add_argument("--autoscale", action="store_true", help="rescale contrast on every frame")
    parser.add_argument("--compare-raw", action="store_true", help="show raw and corrected frames side by side")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    raw_frames_path = find_recording(args.data_dir, args.recording)
    metadata = load_metadata(raw_frames_path)

    frames = np.load(raw_frames_path, mmap_mode="r")
    offset_map = np.load(args.correction_dir / "offset_map.npy")
    gain_map = np.load(args.correction_dir / "gain_map.npy")
    bad_pixel_mask = np.load(args.correction_dir / "bad_pixel_mask.npy")
    frame_count, height, width = validate_shapes(frames, gain_map, offset_map, bad_pixel_mask)

    fps = args.fps or float(metadata.get("recorded_fps_estimate", 22.0))
    title = f"{raw_frames_path.parent.name} ({frame_count} frames, {width}x{height}, {fps:.2f} FPS)"
    print(f"Showing {raw_frames_path}")
    print(f"Using correction maps from {args.correction_dir}")
    print(f"Bad pixels in mask: {int(np.count_nonzero(bad_pixel_mask))}")

    display_frames(
        frames,
        gain_map,
        offset_map,
        bad_pixel_mask,
        fps=fps,
        start_frame=args.start_frame,
        autoscale=args.autoscale,
        compare_raw=args.compare_raw,
        title=title,
    )


if __name__ == "__main__":
    main()
