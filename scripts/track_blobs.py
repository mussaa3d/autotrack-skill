"""Step 3a: segment the flat-coloured shapes that will become track points.
usage: python -I track_blobs.py <config.json>

Flat fills are the one thing in line art that can be segmented exactly, so they make far better track points
than outlines. Two kinds of shape are read from the config:

  marker.color              the primary marker (a bow, scarf, logo ...). One per character copy; its centre,
                            length and angle become the track, and its length sets the depth.
  marker.attached[].mask    optional extra shape classes that hang off a marker (e.g. the dark body fill).

A colour/mask is either {"expr": "(R>150)&(R-G>70)&(R-B>45)"}  (numpy expression on R,G,B in 0-255, np allowed)
                     or {"rgb": [214, 56, 92], "tol": 60}       (every channel within tol)
"solid": true keeps only filled areas (drops pen lines of the same colour).

Writes <work_dir>/blobs/blobs.json and numbered overlays + contact sheets so detections can be checked by eye.
"""
import sys, os, json, math
sys.dont_write_bytecode = True          # never leave __pycache__ inside the skill folder
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from PIL import Image, ImageDraw
from common import load_cfg, wdir, meta, load_rgb, font, contact_sheet

cfg = load_cfg(sys.argv[1])
m = meta(cfg)
mk = cfg["marker"]
os.makedirs(wdir(cfg, "blobs"), exist_ok=True)


def mask_of(rgb, c):
    R, G, B = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    if "expr" in c:
        return eval(c["expr"], {"__builtins__": {}}, {"R": R, "G": G, "B": B, "np": np})
    return np.abs(rgb - np.array(c["rgb"], dtype=np.float32)[None, None]).max(2) < c.get("tol", 60)


def box(a, r):
    p = np.pad(a.astype(np.float64), ((r + 1, r), (r + 1, r)), mode="edge")
    c = p.cumsum(0).cumsum(1)
    k = 2 * r + 1
    return (c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]) / (k * k)


def components(mask, diag):
    """connected components by row runs + union-find (fast in pure Python); diag=True -> 8-connectivity"""
    H, W = mask.shape
    parent = []

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    runs, prev, pad = [], [], (1 if diag else 0)
    for y in range(H):
        d = np.diff(np.concatenate([[0], mask[y].view(np.int8), [0]]))
        starts, ends = np.nonzero(d == 1)[0], np.nonzero(d == -1)[0]
        cur, j = [], 0
        for s, e in zip(starts, ends):
            rid = len(parent)
            parent.append(rid)
            while j < len(prev) and prev[j][1] + pad <= s:
                j += 1
            k = j
            while k < len(prev) and prev[k][0] < e + pad:
                a, b = find(rid), find(prev[k][2])
                if a != b:
                    parent[max(a, b)] = min(a, b)
                k += 1
            cur.append((s, e, rid))
            runs.append((y, s, e, rid))
        prev = cur
    comps = {}
    for y, s, e, rid in runs:
        comps.setdefault(find(rid), []).append((y, s, e))
    return comps.values()


def describe(mask, min_area, diag):
    out = []
    for c in components(mask, diag):
        a = np.array(c)
        if int((a[:, 2] - a[:, 1]).sum()) < min_area:
            continue
        ys = np.repeat(a[:, 0], a[:, 2] - a[:, 1])
        xs = np.concatenate([np.arange(s, e) for _, s, e in c])
        P = np.stack([xs, ys], 1).astype(float)
        cen = P.mean(0)
        _, _, vt = np.linalg.svd(P - cen, full_matrices=False)
        d = vt[0]
        if d[0] < 0:
            d = -d
        t = (P - cen) @ d
        s2 = (P - cen) @ np.array([-d[1], d[0]])
        e0, e1 = cen + d * t.min(), cen + d * t.max()
        out.append(dict(area=int(len(xs)), cx=float(cen[0]), cy=float(cen[1]), ang=float(math.degrees(math.atan2(d[1], d[0]))),
                        major=float(t.max() - t.min()), minor=float(s2.max() - s2.min()),
                        x0=int(xs.min()), y0=int(ys.min()), x1=int(xs.max()), y1=int(ys.max()),
                        e0=[float(e0[0]), float(e0[1])], e1=[float(e1[0]), float(e1[1])]))
    out.sort(key=lambda b: -b["area"])
    return out


classes = [("marker", mk["color"], mk.get("min_area", 150), False, True)]
for a in mk.get("attached", []):
    classes.append((a["name"], a["mask"], a.get("min_area", 2500), a.get("solid", True), False))
res = {name: {} for name, *_ in classes}
ov_paths, labels = [], []
f = font(20)
cols = {0: (0, 90, 255), 1: (0, 150, 0), 2: (200, 120, 0)}
for n in range(1, m["frames"] + 1):
    if n in m["holds"]:
        for name, *_ in classes:
            res[name][n] = res[name][m["holds"][n]]
        continue
    rgb = load_rgb(cfg, n)
    im = Image.fromarray((255 - (255 - rgb) * 0.5).astype(np.uint8))
    dr = ImageDraw.Draw(im)
    line = []
    for ci, (name, spec, min_area, solid, diag) in enumerate(classes):
        mask = mask_of(rgb, spec)
        if solid:
            mask = mask & (box(mask, 5) > 0.80)
        blobs = [] if n in m["blank"] else describe(mask, min_area, diag)
        res[name][n] = blobs
        for j, b in enumerate(blobs):
            dr.rectangle([b["x0"], b["y0"], b["x1"], b["y1"]], outline=cols[ci % 3], width=3)
            dr.ellipse([b["cx"] - 6, b["cy"] - 6, b["cx"] + 6, b["cy"] + 6], fill=cols[ci % 3])
            dr.text((b["x0"], max(b["y0"] - 24, 0)), f"{name[0]}{j}", fill=cols[ci % 3], font=f)
        if ci == 0:
            line = [f"[{j}] a={b['area']} c=({b['cx']:.0f},{b['cy']:.0f}) maj={b['major']:.0f} min={b['minor']:.0f} ang={b['ang']:.0f}" for j, b in enumerate(blobs)]
        else:
            line.append(f"| {name}: {len(blobs)}")
    p = wdir(cfg, "blobs", f"ov_{n:04d}.png")
    im.resize((im.width // 2, im.height // 2), Image.LANCZOS).save(p)
    ov_paths.append(p)
    labels.append(str(n))
    print(f"f{n:02d}: " + "  ".join(line))
json.dump({name: {str(k): v for k, v in d.items()} for name, d in res.items()}, open(wdir(cfg, "blobs", "blobs.json"), "w"))
for k in range(0, len(ov_paths), 12):
    contact_sheet(ov_paths[k:k + 12], labels[k:k + 12], wdir(cfg, "blobs", f"contact_{k // 12 + 1:02d}.png"), thumb_w=800, cols=3)
print("blobs.json + overlay contact sheets written to", wdir(cfg, "blobs"))
