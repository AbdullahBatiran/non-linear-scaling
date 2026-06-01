# Non-Linear Histogram RTL Simulation

This directory contains the hardware-behavior model, Verilator harness, and
operator viewer for `src/hist_nonlinear_axi.v`.

## Behavior

- Input pixels are 14-bit and LSB-aligned on a 16-bit AXI-style bus.
- Output pixels are `OUTPUT_BITS` wide, default 14-bit, and zero-extended on the
  16-bit bus.
- Frame 0 is bypassed because no previous LUT exists yet.
- Frame N builds a histogram/LUT while it streams through, and the output uses
  the LUT built from frame N-1.
- The model uses the PDF-style 1024-entry compressed log-count table while
  keeping 16384 intensity histogram/LUT entries.

## Python Model

Run the behavior model on a corrected MKV or raw16 file:

```bash
python sim/hist_nonlinear_model.py \
  --input data/corrected-videos/rec0.mkv \
  --output /tmp/rec0_model.raw \
  --stats /tmp/rec0_model_stats.json \
  --max-frames 4
```

## RTL Simulation

Install Verilator, then build:

```bash
make -C sim rtl-sim
```

Run the generated simulator on raw16 frames:

```bash
sim/obj_dir/Vhist_nonlinear_axi \
  --input /tmp/input.raw \
  --output /tmp/output.raw \
  --width 640 \
  --height 512
```

Optional stall checks:

```bash
sim/obj_dir/Vhist_nonlinear_axi \
  --input /tmp/input.raw \
  --output /tmp/output.raw \
  --input-stall-period 7 \
  --output-stall-period 11
```

Bit-exact compare against the Python hardware-behavior model:

```bash
python sim/compare_rtl.py --max-frames 2
python sim/compare_rtl.py --max-frames 2 --input-stall-period 7 --output-stall-period 11
```

## Operator Viewer

Python backend, usable without Verilator:

```bash
python sim/view_video_stream.py --recording rec0 --max-frames 120 --fps 22
```

RTL backend, after building the Verilator simulator:

```bash
python sim/view_video_stream.py --recording rec0 --backend rtl --max-frames 120 --fps 22
```


## Commands I (Abdullah) Used
```python
# Print frames simulation status
uv run python sim/hist_nonlinear_model.py --input data/corrected-videos/rec0.mkv --output /tmp/rec0_model.raw --stats /tmp/rec0_stats.json --max-frames 4

# Build Verilator
make -C sim rtl-sim

# Compare SW vs HW output 
uv run python sim/compare_rtl.py --max-frames 2
# Apply backpressure
uv run python sim/compare_rtl.py --max-frames 2 --input-stall-period 7 --output-stall-period 11

# Show video
# From software
uv run python sim/view_video_stream.py --recording rec0 --max-frames 120 --fps 22

# From HW
uv run python sim/view_video_stream.py --recording rec0 --backend rtl --max-frames 120 --fps 22




```