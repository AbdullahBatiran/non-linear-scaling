# Histogram Non-Linear Scaling

This package implements the fourth algorithm from `docs/Histogram Based Methods Description_1.pdf`.
It accepts an arbitrary NumPy image, builds a histogram, replaces each bin count with the integer
base-2 logarithm of that count, accumulates the modified histogram, and maps pixels through the
resulting LUT.

## Install

```bash
pip install -e .
```

## Usage

```python
import numpy as np
from histogram_nonlinear_scaling import nonlinear_histogram_scale

image = np.array([[0, 1, 1], [2, 3, 3]], dtype=np.uint16)
scaled = nonlinear_histogram_scale(image, input_levels=4)
```

For hardware-style 14-bit input and 8-bit output:

```python
scaled = nonlinear_histogram_scale(image, input_levels=2**14, output_max=255)
```

To inspect or reuse the conversion table:

```python
scaled, lut = nonlinear_histogram_scale(image, input_levels=2**14, return_lut=True)
```

## i3s Frame Viewer

`show_i3s_frames.py` loads i3s raw NumPy recordings from `data/i3s_0_7200`, applies bad-pixel replacement, gain correction, and offset correction, then displays the corrected IR frames.

Install the Python dependencies first:

```bash
pip install -e .
```

Show the newest recording:

```bash
python show_i3s_frames.py --compare-raw
```

Show a specific recording:

```bash
python show_i3s_frames.py --recording 20260519_153557_598066_live_recording --compare-raw
```

Export corrected frames to a lossless 16-bit grayscale MKV video:

```bash
python show_i3s_frames.py --recording 20260519_153557_598066_live_recording --export-video --export-only
```

Play a previously exported MKV without applying correction again:

```bash
python show_i3s_frames.py --video ../data/i3s_0_7200/20260519_153557_598066_live_recording/corrected_frames_16bit.mkv
```

Useful options:

- `--autoscale`: update display contrast on every frame.
- `--fps 20`: override playback or export FPS.
- `--start-frame 100`: start NumPy playback from a selected frame.
- `--export-video output.mkv`: write the MKV to a chosen path.

Video export and MKV playback require `ffmpeg` and `ffprobe` on `PATH`.

## Enhanced Video Comparison

`enhance_corrected_videos.py` can preview or export enhanced corrected MKV recordings from
`data/corrected-videos`.

Preview original, linear stretch, and non-linear enhanced frames:

```bash
python enhance_corrected_videos.py --recording rec0 --compare-original --compare-linear
```

Export a shareable side-by-side MP4 with original, linear stretch, and non-linear enhanced panels:

```bash
python enhance_corrected_videos.py --recording rec0 --export-comparison
```

The default comparison export writes to `data/corrected-videos/enhanced/rec0_comparison.mp4`.
Use `--output path/to/file.mp4` to choose a different file, `--compare-linear LOW,HIGH` to adjust
the linear stretch percentiles, `--fps FPS` to override the detected frame rate, and
`--max-frames N` to export a short sample.
