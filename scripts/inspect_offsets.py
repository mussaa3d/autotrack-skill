"""Helper for writing marker.secondary and marker.attached: where does every other shape sit relative to each marker?
usage: python -I inspect_offsets.py <config.json> [frame ...]        (default: about ten frames spread over the clip)

Run it after a first solve.py (the solve decides which blobs are the main markers). For every listed frame it prints
each blob that is NOT a main marker, with its offset from the two nearest markers in units of that marker's length:

    dx, dy   offset of the blob centre (image axes: +x right, +y down), in marker lengths
    size     blob length / marker length          -> attached "max_size"
    mass     blob area / marker length squared    -> attached "min_mass"

Pick windows that bracket the values of the blobs you want and exclude the rest:
    secondary: {"name", "dx": [min,max], "dy": [min,max], "expect": [dx,dy]}
    attached : {"name", "mask", "expect": [dx,dy], "max_dist": how far from expect (marker lengths), "max_size", "min_mass"}
A blob that fits two markers belongs to the one whose offset matches the pattern seen on unambiguous frames.
"""
import sys, os, json, math
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import load_cfg, wdir, meta

cfg = load_cfg(sys.argv[1])
m = meta(cfg)
W, H = m["width"], m["height"]
solve = json.load(open(wdir(cfg, "solve", "solve.json")))
blobs = json.load(open(wdir(cfg, "blobs", "blobs.json")))
uniq = [n for n in range(1, m["frames"] + 1) if n not in m["holds"] and n not in m["blank"]]
frames = [int(a) for a in sys.argv[2:]] or uniq[::max(1, len(uniq) // 10)]

for n in frames:
    mains = [(t["name"], t["obs"][str(n)]) for t in solve["tracks"] if str(n) in t["obs"]]
    if not mains:
        print(f"frame {n}: no markers"); continue
    print(f"frame {n}: markers " + ", ".join(f"{nm} ({o['u']:.0f},{o['v']:.0f}) len {o['major']:.0f}{'*' if o['partial'] else ''}" for nm, o in mains))
    for cls, per_frame in blobs.items():
        for b in per_frame.get(str(n), []):
            cx, cy = b["cx"] + 0.5, b["cy"] + 0.5
            if cls == "marker" and any(math.hypot(cx - o["u"], cy - o["v"]) < 2.0 for _, o in mains):
                continue
            cut = b["x0"] <= 1 or b["y0"] <= 1 or b["x1"] >= W - 2 or b["y1"] >= H - 2
            near = sorted(mains, key=lambda q: math.hypot(cx - q[1]["u"], cy - q[1]["v"]) / q[1]["major"])[:2]
            print(f"   {cls:7s} ({cx:6.0f},{cy:6.0f}) len {b['major']:5.0f} area {b['area']:7d}{' CUT' if cut else '    '} | " + "   ".join(
                f"vs {nm}: dx {(cx - o['u']) / o['major']:+.2f} dy {(cy - o['v']) / o['major']:+.2f} size {b['major'] / o['major']:.2f} mass {b['area'] / o['major'] ** 2:.2f}"
                for nm, o in near))
