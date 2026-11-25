"""Step 2 helper: find long straight pen strokes in one frame (iterative Hough + least-squares refine).
usage: python -I find_lines.py <config.json> <frame_number> [min_len=140] [max_segments=45]

Writes <work_dir>/lines/ov_<frame>.png (numbered overlay) and seg_<frame>.json, and prints every segment with
its endpoints and angle. Use it to see which strokes form the two edge families of a rigid structure, then
copy endpoints into the config's plane.frames corridors. Solid fills and coloured areas are ignored.
"""
import sys, os, json, math
sys.dont_write_bytecode = True          # never leave __pycache__ inside the skill folder
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from PIL import Image, ImageDraw
from common import load_cfg, wdir, load_rgb, ink_mask, font

cfg = load_cfg(sys.argv[1])
n = int(sys.argv[2])
MIN_LEN = float(sys.argv[3]) if len(sys.argv) > 3 else 140.0
MAX_SEG = int(sys.argv[4]) if len(sys.argv) > 4 else 45
os.makedirs(wdir(cfg, "lines"), exist_ok=True)

rgb = load_rgb(cfg, n)
H, W = rgb.shape[:2]
ink = ink_mask(rgb)

def box(a, r):
    p = np.pad(a.astype(np.float64), ((r + 1, r), (r + 1, r)), mode="edge")
    c = p.cumsum(0).cumsum(1)
    k = 2 * r + 1
    return (c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]) / (k * k)

stroke = ink & (box(ink, 14) < 0.33)          # drop solid fills, keep pen lines
ys, xs = np.nonzero(stroke)
pts = np.stack([xs, ys], 1).astype(np.float32)
if len(pts) > 90000:
    pts = pts[np.random.default_rng(0).choice(len(pts), 90000, replace=False)]

TH = np.deg2rad(np.arange(0, 180, 0.25)).astype(np.float32)
cosT, sinT = np.cos(TH), np.sin(TH)
RMAX = int(math.hypot(W, H)) + 2
NR = 2 * RMAX + 1

def votes(P):
    acc = np.zeros((len(TH), NR), dtype=np.int32)
    for i in range(0, len(P), 8000):
        c = P[i:i + 8000]
        rho = np.rint(c[:, 0:1] * cosT[None] + c[:, 1:2] * sinT[None]).astype(np.int64) + RMAX
        idx = rho + (np.arange(len(TH), dtype=np.int64) * NR)[None]
        acc += np.bincount(idx.ravel(), minlength=len(TH) * NR).reshape(len(TH), NR).astype(np.int32)
    return acc

acc = votes(pts)
alive = np.ones(len(pts), bool)
segs, tries = [], 0
while len(segs) < MAX_SEG and tries < 400 and alive.sum() > 200:
    tries += 1
    a2 = acc[:, 1:-1] + acc[:, :-2] + acc[:, 2:]
    k = int(a2.argmax())
    ti, ri = divmod(k, a2.shape[1])
    ri += 1
    if a2[ti, ri - 1] < MIN_LEN * 0.35:
        break
    th = TH[ti]
    nrm = np.array([math.cos(th), math.sin(th)], dtype=np.float32)
    d = np.array([-nrm[1], nrm[0]], dtype=np.float32)
    idxs = np.nonzero(alive)[0]
    P = pts[idxs]
    near = np.abs(P @ nrm - (ri - RMAX)) < 4.0
    if near.sum() < 20:
        acc[ti, max(ri - 2, 0):ri + 3] = 0
        continue
    Pn, In = P[near], idxs[near]
    t = Pn @ d
    order = np.argsort(t)
    t_s = t[order]
    gaps = np.nonzero(np.diff(t_s) > 28)[0]
    kill = []
    for s, e in zip(np.r_[0, gaps + 1], np.r_[gaps, len(t_s) - 1]):
        sel = order[s:e + 1]
        kill.append(In[sel])
        if t_s[e] - t_s[s] < MIN_LEN:
            continue
        Q = Pn[sel].astype(np.float64)
        for band in (4.0, 2.5):
            c0 = Q.mean(0)
            _, _, vt = np.linalg.svd(Q - c0, full_matrices=False)
            keep = np.abs((Q - c0) @ np.array([-vt[0][1], vt[0][0]])) < band
            if keep.sum() < 20:
                break
            Q = Q[keep]
        c0 = Q.mean(0)
        _, _, vt = np.linalg.svd(Q - c0, full_matrices=False)
        dd = vt[0]
        tt = (Q - c0) @ dd
        res = (Q - c0) @ np.array([-dd[1], dd[0]])
        p1, p2 = c0 + dd * tt.min(), c0 + dd * tt.max()
        if p1[0] > p2[0]:
            p1, p2 = p2, p1
        L2 = float(np.hypot(*(p2 - p1)))
        if L2 >= MIN_LEN and len(Q) / max(L2, 1.0) > 0.45:
            segs.append(dict(x1=float(p1[0]) + 0.5, y1=float(p1[1]) + 0.5, x2=float(p2[0]) + 0.5, y2=float(p2[1]) + 0.5, len=L2,
                             ang=float(math.degrees(math.atan2(p2[1] - p1[1], p2[0] - p1[0]))), rms=float(np.sqrt((res ** 2).mean()))))
    rem = np.concatenate(kill) if kill else In
    acc -= votes(pts[rem])
    alive[rem] = False

segs.sort(key=lambda s: -s["len"])
for i, s in enumerate(segs):
    s["id"] = i
json.dump(dict(W=W, H=H, segments=segs), open(wdir(cfg, "lines", f"seg_{n:04d}.json"), "w"), indent=1)
base = Image.fromarray((255 - (255 - rgb) * 0.35).astype(np.uint8))
dr = ImageDraw.Draw(base)
f = font(22)
fg = font(16, bold=False)
for gx in range(0, W, 100):                      # same coordinate grid as the grid frames, so one image is enough
    dr.line([(gx, 0), (gx, H)], fill=(210, 225, 255), width=1)
    dr.text((gx + 2, 2), str(gx), fill=(90, 120, 200), font=fg)
for gy in range(0, H, 100):
    dr.line([(0, gy), (W, gy)], fill=(210, 225, 255), width=1)
    dr.text((2, gy + 2), str(gy), fill=(90, 120, 200), font=fg)
cols = [(230, 0, 0), (0, 140, 0), (0, 60, 230), (200, 0, 200), (0, 160, 170), (220, 120, 0), (120, 60, 0), (90, 0, 160)]
for s in segs:
    c = cols[s["id"] % len(cols)]
    dr.line([(s["x1"], s["y1"]), (s["x2"], s["y2"])], fill=c, width=3)
    mx, my = (s["x1"] + s["x2"]) / 2, (s["y1"] + s["y2"]) / 2
    dr.rectangle([mx - 2, my - 2, mx + 28, my + 22], fill=(255, 255, 255))
    dr.text((mx, my - 2), str(s["id"]), fill=c, font=f)
base.save(wdir(cfg, "lines", f"ov_{n:04d}.png"))
print(f"frame {n}: {len(segs)} straight strokes (angle in degrees, image y is down)")
for s in segs:
    print(f'{s["id"]:2d}  ({s["x1"]:7.1f},{s["y1"]:7.1f})-({s["x2"]:7.1f},{s["y2"]:7.1f})  len={s["len"]:6.0f}  ang={s["ang"]:7.2f}  rms={s["rms"]:.2f}')
