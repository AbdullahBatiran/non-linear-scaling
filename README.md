# Comamnds Example

```bash
# Play Raw Video
uv run python software-sim/show_i3s_frames.py --recording rec0

# Export Raw Video to Corrected One in MKV format
uv run python software-sim/show_i3s_frames.py --recording rec0 --export-video ./data/corrected-videos/rec1. mkv --export-only

# Play Corrected Video from MKV format
uv run python software-sim/show_i3s_frames.py --video ./data/corrected-videos/rec4.mkv --autoscale

# Run Vivado Synthesis + Impl
./src/synth_hist_nonlinear_axi.sh --mode impl --build-dir tmp/hist_nonlinear_axi_8bito --param OUTPUT_BITS=8 --param INPUT_BITS=14 --param ADDR_BITS=10 --param INTENSITY_LEVELS=1024
```


