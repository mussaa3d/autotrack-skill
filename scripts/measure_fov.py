"""Step 2: estimate the lens implied by the drawn perspective.
usage: python -I measure_fov.py <config.json>

Reads plane.frames from the config (two families of edges, A and B, that are perpendicular in 3D and lie on one
plane, e.g. the edges of a roof, floor tiles, a wall). For each frame:
  vanishing point of each family  ->  f^2 = -(vpA - c) . (vpB - c)      (principal point c = frame centre)
and a Monte-Carlo run with 1 degree of stroke wobble, because hand-drawn lines are not exact.

How to read the result
  - a tight spread across frames and combinations  -> that is the lens
  - few valid combinations / values in the thousands of px -> the lines barely converge: a long lens (or a flat,
    "no perspective" drawing). Report a range and pick a standard focal length inside it.
  - the estimate says nothing about how the CHARACTER is foreshortened; drawn characters often cheat a wider lens.
"""
import sys, os, math, json
sys.dont_write_bytecode = True          # never leave __pycache__ inside the skill folder
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from PIL import Image, ImageDraw
from common import load_cfg, wdir, meta, load_rgb, fit_frame_edges

cfg = load_cfg(sys.argv[1])
m = meta(cfg)
W, H = m["width"], m["height"]
C = np.array([W / 2.0, H / 2.0])
os.makedirs(wdir(cfg, "fov"), exist_ok=True)
rng = np.random.default_rng(1)

def homog(l):
    a = np.array([l["c"][0], l["c"][1], 1.0])
    return np.cross(a, a + np.array([l["d"][0], l["d"][1], 0.0]))

def vp(lines):
    A = [homog(l) / np.linalg.norm(homog(l)[:2]) * l["span"] for l in lines]
    return np.linalg.svd(np.array(A))[2][-1]

def focal(vA, vB):
    a = np.array([vA[0] - C[0] * vA[2], vA[1] - C[1] * vA[2]])
    b = np.array([vB[0] - C[0] * vB[2], vB[1] - C[1] * vB[2]])
    den = vA[2] * vB[2]
    if abs(den) < 1e-30:
        return float("nan")
    f2 = -(a @ b) / den
    return math.sqrt(f2) if f2 > 0 else float("nan")

def rot(l, deg):
    r = math.radians(deg)
    c, s = math.cos(r), math.sin(r)
    o = dict(l)
    o["d"] = np.array([c * l["d"][0] - s * l["d"][1], s * l["d"][0] + c * l["d"][1]])
    return o

def mm(fpx, sensor=36.0):
    return sensor * fpx / W

medians = []
for key in sorted(cfg["plane"]["frames"], key=int):
    n = int(key)
    e = fit_frame_edges(cfg, n, cfg["plane"]["frames"][key])
    im = Image.fromarray((255 - (255 - load_rgb(cfg, n)) * 0.4).astype(np.uint8))
    dr = ImageDraw.Draw(im)
    print(f"--- frame {n}")
    for fam, col in (("A", (230, 0, 0)), ("B", (0, 80, 230))):
        for name, l in zip(e["names"][fam], e[fam]):
            print(f"  {fam} {name:14s} angle {l['ang']:7.2f}  length {l['span']:6.0f}  rms {l['rms']:.2f}")
            dr.line([tuple(l["c"] - l["d"] * 4000), tuple(l["c"] + l["d"] * 4000)], fill=col, width=1)
            dr.line([tuple(l["p1"]), tuple(l["p2"])], fill=col, width=4)
    im.save(wdir(cfg, "fov", f"fit_{n:04d}.png"))
    A, B = e["A"], e["B"]
    spreadA = max(l["ang"] for l in A) - min(l["ang"] for l in A)
    spreadB = max(l["ang"] for l in B) - min(l["ang"] for l in B)
    print(f"  angle spread inside family: A {spreadA:.1f} deg, B {spreadB:.1f} deg   (small spread = little convergence)")
    mc = np.array([focal(vp([rot(l, rng.normal(0, 1.0)) for l in A]), vp([rot(l, rng.normal(0, 1.0)) for l in B])) for _ in range(4000)])
    good = mc[np.isfinite(mc)]
    if len(good) > 200:
        q = np.percentile(good, [10, 50, 90])
        print(f"  focal (1 deg wobble): valid {len(good) / len(mc) * 100:.0f}%   p10/p50/p90 = {mm(q[0]):.0f} / {mm(q[1]):.0f} / {mm(q[2]):.0f} mm (36 mm sensor)")
        medians.append(q[1])
    else:
        print("  focal: no usable convergence in this frame (lines are parallel within drawing noise)")
    loo = []                                        # which single stroke drives the estimate?
    for fam, lines, other in (("A", A, B), ("B", B, A)):
        if len(lines) < 3:
            continue
        for i, nm in enumerate(e["names"][fam]):
            rest = lines[:i] + lines[i + 1:]
            f1 = focal(vp(rest), vp(other)) if fam == "A" else focal(vp(other), vp(rest))
            loo.append(f"{nm} {mm(f1):.0f} mm" if math.isfinite(f1) else f"{nm} none")
    if loo:
        print("  estimate with each stroke left out in turn: " + ", ".join(loo) + "   (one stroke that swings it is a stroke to distrust)")

print()
if medians:
    g = float(np.exp(np.mean(np.log(medians))))
    presets = [15, 20, 24, 28, 35, 50, 85, 135, 200]
    near = min(presets, key=lambda p: abs(math.log(p / mm(g))))
    print(f"per-frame medians: {', '.join('%.0f mm' % mm(v) for v in medians)}  -> geometric mean {mm(g):.0f} mm")
    print(f"nearest standard lens: {near} mm   (horizontal FOV {math.degrees(2 * math.atan(18.0 / near)):.1f} deg, After Effects zoom {near / 36.0 * W:.0f} px)")
    print("Put the chosen value in config lens.focal_mm. State the spread honestly: a drawing has no physical lens.")
else:
    print("No frame gave a usable estimate. Treat the layout as flat: choose a long lens (85-135 mm) and say it is a choice, not a measurement.")
