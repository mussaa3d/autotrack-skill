"""Step 1: extract frames, find held drawings and blank frames, make gridded copies and contact sheets.
usage: python -I prep_frames.py <config.json>

Writes into <work_dir>:
  frames/f_0001.png ...      every frame, untouched
  grid/grid_f_0001.png ...   same frames with a labelled 100 px coordinate grid (read coordinates off these)
  contact_01.png ...         labelled contact sheets, 24 frames each
  meta.json                  width, height, frames, fps, holds {held frame: source frame}, blank frames
"""
import sys, os, json, subprocess, glob
sys.dont_write_bytecode = True          # never leave __pycache__ inside the skill folder
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from PIL import Image, ImageDraw
from common import load_cfg, wdir, font, contact_sheet

cfg = load_cfg(sys.argv[1])
video = cfg["video"]
for sub in ("frames", "grid"):
    os.makedirs(wdir(cfg, sub), exist_ok=True)

probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height,r_frame_rate,nb_frames,sample_aspect_ratio", "-of", "json", video],
                       capture_output=True, text=True, check=True)
st = json.loads(probe.stdout)["streams"][0]
fps_num, fps_den = (int(x) for x in st["r_frame_rate"].split("/"))
if st.get("sample_aspect_ratio", "1:1") not in ("1:1", "N/A", "0:1"):
    print("WARNING: non-square pixels (%s); the solve assumes square pixels" % st["sample_aspect_ratio"])
for old in glob.glob(wdir(cfg, "frames", "f_*.png")):
    os.remove(old)
subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", video, "-fps_mode", "passthrough", wdir(cfg, "frames", "f_%04d.png")], check=True)
paths = sorted(glob.glob(wdir(cfg, "frames", "f_*.png")))
N = len(paths)

holds, blank, prev, src = {}, [], None, 1
print("frame  diff_to_prev  ink%   note")
for i, p in enumerate(paths, 1):
    g = np.asarray(Image.open(p).convert("L"), dtype=np.float32)
    ink = float((g < 128).mean() * 100)
    note = ""
    if ink > 97 or ink < 0.05:
        blank.append(i); note = "blank"
    if prev is not None:
        d = float(np.abs(g - prev).mean())
        if d < 0.6:
            holds[i] = src; note = (note + " hold of %d" % src).strip()
        else:
            src = i
        print(f"{i:4d}   {d:9.3f}   {ink:5.1f}  {note}")
    else:
        print(f"{i:4d}   {'-':>9}   {ink:5.1f}  {note}")
    prev = g

W, H = Image.open(paths[0]).size
json.dump(dict(width=W, height=H, frames=N, fps_num=fps_num, fps_den=fps_den, holds=holds, blank=blank, video=video),
          open(wdir(cfg, "meta.json"), "w"), indent=1)

f = font(18, bold=False)
for p in paths:
    im = Image.open(p).convert("RGB")
    dr = ImageDraw.Draw(im)
    for x in range(0, W, 100):
        dr.line([(x, 0), (x, H)], fill=(255, 0, 255) if x % 500 == 0 else (0, 160, 255), width=1)
        dr.text((x + 2, 2), str(x), fill=(0, 90, 200), font=f)
        dr.text((x + 2, H - 22), str(x), fill=(0, 90, 200), font=f)
    for y in range(0, H, 100):
        dr.line([(0, y), (W, y)], fill=(255, 0, 255) if y % 500 == 0 else (0, 160, 255), width=1)
        dr.text((2, y + 2), str(y), fill=(0, 90, 200), font=f)
        dr.text((W - 48, y + 2), str(y), fill=(0, 90, 200), font=f)
    im.save(wdir(cfg, "grid", "grid_" + os.path.basename(p)))

uniq = [i for i in range(1, N + 1) if i not in holds]
for k in range(0, len(uniq), 24):
    chunk = uniq[k:k + 24]
    contact_sheet([paths[i - 1] for i in chunk], [str(i) for i in chunk], wdir(cfg, f"contact_{k // 24 + 1:02d}.png"), thumb_w=640, cols=4)
print(f"\n{N} frames, {W}x{H}, {fps_num}/{fps_den} fps; {len(uniq)} unique drawings, {len(holds)} held frames, blank: {blank or 'none'}")
print("contact sheets:", ", ".join(sorted(os.path.basename(p) for p in glob.glob(wdir(cfg, 'contact_*.png')))))
