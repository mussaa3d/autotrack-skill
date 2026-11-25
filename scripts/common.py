"""Shared helpers for the animation-camera-track scripts (numpy + Pillow only).

Conventions used everywhere
  image : u right, v down, in After Effects comp coordinates (pixel i has its centre at i + 0.5),
          so (W/2, H/2) is the exact optical centre
  camera: OpenCV style, x right, y down, z forward ;  u = CX + F * x / z
  world : right-handed, Z up, metres. When a plane is solved it is z = 0 with the tracked corner at the origin,
          +X along the "B" edge and +Y along the "A" edge
  Xcam = R_n @ (Xworld - C)     with a fixed camera centre C (nodal pan / tilt / roll)
"""
import os, sys, json, math, glob
import numpy as np
from PIL import Image


def load_cfg(path):
    cfg = json.load(open(path, encoding="utf-8"))
    cfg["_path"] = os.path.abspath(path)
    cfg.setdefault("name", os.path.splitext(os.path.basename(cfg["video"]))[0])
    cfg.setdefault("lens", {})
    cfg["lens"].setdefault("focal_mm", 50.0)
    cfg["lens"].setdefault("sensor_mm", 36.0)
    return cfg


def wdir(cfg, *parts):
    p = os.path.join(cfg["work_dir"], *parts)
    return p


def meta(cfg):
    """written by prep_frames.py: width, height, frames, fps_num, fps_den, holds {dst: src}, blank [frames]"""
    m = json.load(open(wdir(cfg, "meta.json")))
    m["holds"] = {int(k): int(v) for k, v in m["holds"].items()}
    return m


def frame_path(cfg, n):
    return wdir(cfg, "frames", f"f_{n:04d}.png")


def load_rgb(cfg, n):
    return np.asarray(Image.open(frame_path(cfg, n)).convert("RGB"), dtype=np.float32)


def ink_mask(rgb, dark=150, max_sat=60):
    """dark, unsaturated pixels = pen lines (coloured fills are excluded)"""
    g = rgb.mean(2)
    sat = rgb.max(2) - rgb.min(2)
    return (g < dark) & (sat < max_sat)


def fit_stroke(ink, p1, p2, hw):
    """total-least-squares line through the ink inside a corridor (p1 -> p2, half-width hw)"""
    p1, p2 = np.array(p1, float), np.array(p2, float)
    d = p2 - p1
    L = np.linalg.norm(d)
    d /= L
    n = np.array([-d[1], d[0]])
    ys, xs = np.nonzero(ink)
    P = np.stack([xs, ys], 1).astype(float) + 0.5
    t = (P - p1) @ d
    s = (P - p1) @ n
    Q = P[(t > 0) & (t < L) & (np.abs(s) < hw)]
    if len(Q) < 30:
        raise ValueError(f"corridor {p1.tolist()} -> {p2.tolist()} contains almost no ink ({len(Q)} px); check the coordinates")
    for band in (hw, hw * 0.6, hw * 0.45):
        c0 = Q.mean(0)
        _, _, vt = np.linalg.svd(Q - c0, full_matrices=False)
        dd = vt[0]
        nn = np.array([-dd[1], dd[0]])
        Q = Q[np.abs((Q - c0) @ nn) < band]
    c0 = Q.mean(0)
    _, _, vt = np.linalg.svd(Q - c0, full_matrices=False)
    dd = vt[0]
    if dd[0] < 0:
        dd = -dd
    nn = np.array([-dd[1], dd[0]])
    tt = (Q - c0) @ dd
    return dict(c=c0, d=dd, ang=math.degrees(math.atan2(dd[1], dd[0])), span=float(tt.max() - tt.min()),
                rms=float(np.sqrt((((Q - c0) @ nn) ** 2).mean())), p1=c0 + dd * tt.min(), p2=c0 + dd * tt.max())


def avg_line(ls):
    w = np.array([l["span"] for l in ls])
    w = w / w.sum()
    c = sum(wi * l["c"] for wi, l in zip(w, ls))
    d = sum(wi * l["d"] for wi, l in zip(w, ls))
    d /= np.linalg.norm(d)
    return dict(c=c, d=d, ang=math.degrees(math.atan2(d[1], d[0])), span=float(sum(l["span"] for l in ls)))


def isect(l1, l2):
    A = np.array([[l1["d"][0], -l2["d"][0]], [l1["d"][1], -l2["d"][1]]])
    t = np.linalg.solve(A, l2["c"] - l1["c"])
    return l1["c"] + l1["d"] * t[0]


def fit_frame_edges(cfg, n, spec):
    """spec = {"A": [[name,[x1,y1],[x2,y2],halfwidth],...], "B": [...], "cornerA": [names], "cornerB": [names]}"""
    ink = ink_mask(load_rgb(cfg, n))
    fits = {}
    for fam in ("A", "B"):
        for name, p1, p2, hw in spec[fam]:
            fits[name] = fit_stroke(ink, p1, p2, hw)
    cA = avg_line([fits[k] for k in spec["cornerA"]])
    cB = avg_line([fits[k] for k in spec["cornerB"]])
    return dict(fits=fits, A=[fits[x[0]] for x in spec["A"]], B=[fits[x[0]] for x in spec["B"]],
                names=dict(A=[x[0] for x in spec["A"]], B=[x[0] for x in spec["B"]]), cA=cA, cB=cB, corner=isect(cA, cB))


def expm(w):
    th = np.linalg.norm(w)
    if th < 1e-12:
        return np.eye(3)
    k = w / th
    K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) + math.sin(th) * K + (1 - math.cos(th)) * K @ K


def logm(R):
    c = max(-1.0, min(1.0, (np.trace(R) - 1) / 2))
    th = math.acos(c)
    if th < 1e-12:
        return np.zeros(3)
    return th / (2 * math.sin(th)) * np.array([R[2, 1] - R[1, 2], R[0, 2] - R[2, 0], R[1, 0] - R[0, 1]])


def wrap180(a):
    return (a + 90.0) % 180.0 - 90.0


class Camera:
    def __init__(self, W, H, focal_mm, sensor_mm):
        self.W, self.H = W, H
        self.F = focal_mm / sensor_mm * W
        self.CX, self.CY = W / 2.0, H / 2.0

    def project(self, R, C, Xw):
        Xc = (np.atleast_2d(Xw) - C) @ R.T
        return np.stack([self.CX + self.F * Xc[:, 0] / Xc[:, 2], self.CY + self.F * Xc[:, 1] / Xc[:, 2]], 1), Xc[:, 2]

    def ray(self, uv):
        return np.array([(uv[0] - self.CX) / self.F, (uv[1] - self.CY) / self.F, 1.0])

    def backproject_plane(self, R, C, uv):
        """pixel -> point on the world plane z = 0"""
        r = R.T @ self.ray(uv)
        return C + (-C[2] / r[2]) * r


def el(axis, a):
    """right-handed elementary rotation (radians) about x / y / z"""
    c, s = math.cos(a), math.sin(a)
    if axis == 0:
        return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])
    if axis == 1:
        return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


def covered_bars(obs, W, H):
    """Given one frame's track observations, return the indices of draft bars (3:1 rectangles drawn on each marker)
    that a nearer bar overlaps on screen. The visible centre of such a bar is biased, so checks must skip it."""
    from PIL import ImageDraw
    masks = []
    for o in obs:
        a = math.radians(o["ang"])
        h, w = o["major"] / 2.0 + 2.0, o["major"] / 6.0 + 2.0
        dx, dy = math.cos(a), math.sin(a)
        pts = [((o["u"] + sx * h * dx - sy * w * dy) / 2.0, (o["v"] + sx * h * dy + sy * w * dx) / 2.0) for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
        im = Image.new("1", (W // 2, H // 2))
        ImageDraw.Draw(im).polygon(pts, fill=1)
        masks.append(np.asarray(im))
    out = set()
    for i, o in enumerate(obs):
        for j, p in enumerate(obs):
            if j != i and p["depth"] < o["depth"] and (masks[i] & masks[j]).any():
                out.add(i)
    return out


def font(size, bold=True):
    from PIL import ImageFont
    try:
        return ImageFont.truetype("arialbd.ttf" if bold else "arial.ttf", size)
    except Exception:
        return ImageFont.load_default()


def contact_sheet(paths, labels, out_path, thumb_w=640, cols=4):
    """labelled contact sheet so frames can be reviewed with few image reads"""
    from PIL import ImageDraw
    ims = [Image.open(p).convert("RGB") for p in paths]
    th = int(thumb_w * ims[0].height / ims[0].width)
    rows = (len(ims) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * (thumb_w + 6) + 6, rows * (th + 6) + 6), (200, 0, 0))
    dr = ImageDraw.Draw(sheet)
    f = font(22)
    for i, (im, lab) in enumerate(zip(ims, labels)):
        x, y = 6 + (i % cols) * (thumb_w + 6), 6 + (i // cols) * (th + 6)
        sheet.paste(im.resize((thumb_w, th), Image.LANCZOS), (x, y))
        dr.rectangle([x, y, x + 14 * len(lab) + 10, y + 28], fill=(255, 255, 255))
        dr.text((x + 5, y + 2), lab, fill=(0, 0, 0), font=f)
    sheet.save(out_path)
