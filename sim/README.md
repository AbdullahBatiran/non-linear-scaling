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

Build with waveform tracing enabled:

```bash
make -C sim clean
make -C sim rtl-sim TRACE=1
```

Run the generated simulator on raw16 frames:

```bash
sim/obj_dir/Vhist_nonlinear_axi \
  --input /tmp/input.raw \
  --output /tmp/output.raw \
  --width 640 \
  --height 512
```

Generate a waveform from the generated simulator:

```bash
sim/obj_dir/Vhist_nonlinear_axi \
  --input /tmp/input.raw \
  --output /tmp/output.raw \
  --width 640 \
  --height 512 \
  --trace tmp/hist_nonlinear_axi.vcd
```

Open the waveform in GTKWave:

```bash
sim/view_waveform.sh tmp/hist_nonlinear_axi.vcd
# or
make -C sim view-wave WAVE=tmp/hist_nonlinear_axi.vcd
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
python sim/compare_rtl.py --max-frames 1 --trace tmp/compare_rtl.vcd
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

Generate a waveform for an RTL-backed video run:

```bash
python sim/view_video_stream.py \
  --recording rec0 \
  --backend rtl \
  --max-frames 1 \
  --trace tmp/rec0_rtl.vcd
```

Waveforms for full videos can become very large. Use `--max-frames 1` or a
small raw input when checking frame-boundary behavior.


## Commands I (Abdullah) Used
```python
# Print frames simulation status
uv run python sim/hist_nonlinear_model.py --input data/corrected-videos/rec0.mkv --output /tmp/rec0_model.raw --stats /tmp/rec0_stats.json --max-frames 4

# Build Verilator
make -C sim rtl-sim
make -C sim rtl-sim TRACE=1

# Compare SW vs HW output 
uv run python sim/compare_rtl.py --max-frames 2
# Apply backpressure
uv run python sim/compare_rtl.py --max-frames 2 --input-stall-period 7 --output-stall-period 11
# Create waveform
uv run python sim/compare_rtl.py --max-frames 1 --trace tmp/compare_rtl.vcd

# Show video
# From software
uv run python sim/view_video_stream.py --recording rec0 --max-frames 120 --fps 22

# From HW
uv run python sim/view_video_stream.py --recording rec0 --backend rtl --max-frames 120 --fps 22
uv run python sim/view_video_stream.py --recording rec0 --backend rtl --max-frames 1 --trace tmp/rec0_rtl.vcd




```
