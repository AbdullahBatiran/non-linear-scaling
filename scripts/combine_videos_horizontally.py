# python - <<'PY'
from pathlib import Path
import subprocess, json
import cv2
import numpy as np
import sys

sys.path.insert(0, 'sim')
import hist_nonlinear_model as model

out_dir = Path('data/corrected-videos/histogram-resolution')
paths = [
    out_dir / 'rec2_nonlinear_hist14bit_out14bit.mkv',
    out_dir / 'rec2_nonlinear_hist10bit_out14bit.mkv',
    out_dir / 'rec2_nonlinear_hist8bit_out14bit.mkv',
]
labels = ['hist 14-bit', 'hist 10-bit', 'hist 8-bit']
preview_path = out_dir / 'rec2_nonlinear_hist14_10_8_preview.mp4'

frames_list = [model.decode_mkv_gray16(path) for path in paths]
frame_count = min(frames.shape[0] for frames in frames_list)
height, width = frames_list[0].shape[1:]

probe = subprocess.run([
    'ffprobe', '-v', 'error', '-select_streams', 'v:0',
    '-show_entries', 'stream=r_frame_rate', '-of', 'json', str(paths[0])
], check=True, capture_output=True, text=True)
rate = json.loads(probe.stdout)['streams'][0].get('r_frame_rate', '22/1')
num, den = rate.split('/')
fps = float(num) / float(den) if float(den) else 22.0

command = [
    'ffmpeg', '-y', '-v', 'error',
    '-f', 'rawvideo', '-pix_fmt', 'bgr24',
    '-s:v', f'{width * 3}x{height}',
    '-r', f'{fps:.6f}',
    '-i', '-',
    '-an', '-c:v', 'libx264',
    '-preset', 'veryfast',
    '-crf', '18',
    '-pix_fmt', 'yuv420p',
    str(preview_path),
]
process = subprocess.Popen(command, stdin=subprocess.PIPE)
assert process.stdin is not None

for i in range(frame_count):
    panels = []
    for frames, label in zip(frames_list, labels):
        panel = np.rint(np.clip(frames[i], 0, 16383) * (255.0 / 16383.0)).astype(np.uint8)
        panel = cv2.cvtColor(panel, cv2.COLOR_GRAY2BGR)
        cv2.putText(panel, label, (16, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2, cv2.LINE_AA)
        panels.append(panel)

    combined = np.concatenate(panels, axis=1)
    process.stdin.write(combined.tobytes(order='C'))

process.stdin.close()
rc = process.wait()
if rc != 0:
    raise SystemExit(rc)

print(f'wrote {preview_path} ({frame_count} frames)')
# PY
