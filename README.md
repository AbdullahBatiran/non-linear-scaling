# Comamnds Example

```bash
# Play Raw Video
uv run python software-sim/show_i3s_frames.py --recording rec0

# Export Raw Video to Corrected One in MKV format
uv run python software-sim/show_i3s_frames.py --recording rec0 --export-video ./data/corrected-videos/rec1. mkv --export-only

# Play Corrected Video from MKV format
uv run python software-sim/show_i3s_frames.py --video ./data/corrected-videos/rec4.mkv --autoscale

```