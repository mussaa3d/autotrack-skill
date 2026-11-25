"""Step 5b: run the delivered Blender script in real Blender, save a .blend and prove the camera.
usage: python -I verify_blender.py <config.json>

Needs a Blender executable: config "blender_exe", or `blender` on PATH, or a standard install, or a portable copy
under ~/Downloads/blender_portable. If there is none, do NOT silently skip: tell the user the Blender script is
untested and ask before downloading Blender (portable zip + its .sha256 from download.blender.org/release/).

Checks
  A  Blender's own camera (world_to_camera_view) on every keyed empty, every frame, vs the tracked pixels
  B  a Workbench render of the draft bars, measured outside Blender, vs the tracked pixels
Writes <out_dir>/<name>_camera_track.blend and <out_dir>/check/Blender_render_frame_XX.png
"""
import sys, os, json, math, glob, shutil, subprocess
sys.dont_write_bytecode = True          # never leave __pycache__ inside the skill folder
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from PIL import Image
from common import load_cfg, wdir, frame_path, covered_bars

cfg = load_cfg(sys.argv[1])
solve = json.load(open(wdir(cfg, "solve", "solve.json")))
M = solve["meta"]
NAME, N = M["name"], M["frames"]
out_dir = cfg["out_dir"]
scratch = wdir(cfg, "bl_verify")
if os.path.isdir(scratch):
    shutil.rmtree(scratch)
os.makedirs(scratch)
os.makedirs(os.path.join(out_dir, "check"), exist_ok=True)

exe = cfg.get("blender_exe") or shutil.which("blender")
if not exe:
    cands = sorted(glob.glob("C:/Program Files/Blender Foundation/*/blender.exe")
                   + glob.glob(os.path.expanduser("~/Downloads/blender_portable/*/blender.exe")))
    exe = cands[-1] if cands else None
if not exe or not os.path.isfile(exe):
    sys.exit("Blender not found. Set \"blender_exe\" in the config, or ask the user before downloading it. Until then the Blender script is UNTESTED.")

here = os.path.dirname(os.path.abspath(__file__))
blend = os.path.join(out_dir, NAME + "_camera_track.blend")
CHECK_FRAMES = sorted(set(M["measured_camera_frames"][:3] + [max(1, N // 3), max(1, 2 * N // 3)]))
r = subprocess.run([exe, "-b", "--factory-startup", "--python", os.path.join(here, "blender_inner.py"), "--",
                    os.path.join(out_dir, NAME + "_blender_camera.py"), wdir(cfg, "solve", "solve.json"), blend, scratch,
                    ",".join(str(n) for n in CHECK_FRAMES)],
                   capture_output=True, text=True, timeout=1800)
lines = [l for l in (r.stdout + "\n" + r.stderr).splitlines() if l.startswith(("BLENDER", "CHECK_")) or "Traceback" in l or "Error" in l]
print("\n".join(lines))
if r.returncode != 0 or "CHECK_A" not in r.stdout:
    print(r.stdout[-3000:]); sys.exit("Blender run failed - the script has an error on this Blender version; fix export.py and re-run")

PALETTE = [[1, 0, 0], [0, 1, 0], [0, 0, 1], [1, 1, 0], [1, 0, 1], [0, 1, 1], [1, 0.5, 0], [0.5, 0, 1]]
pos, rel, missing, hidden = [], [], [], 0
if os.path.exists(os.path.join(scratch, "bl_0001.png")):
    for n in range(1, N + 1):
        rgba = np.asarray(Image.open(os.path.join(scratch, f"bl_{n:04d}.png")).convert("RGBA"), dtype=np.float32) / 255.0
        present = [(ti, t["obs"][str(n)]) for ti, t in enumerate(solve["tracks"]) if str(n) in t["obs"]]
        covered = {present[i][0] for i in covered_bars([o for _, o in present], M["width"], M["height"])}
        for ti, t in enumerate(solve["tracks"]):
            o = t["obs"].get(str(n))
            m = (np.abs(rgba[..., :3] - np.array(PALETTE[ti % len(PALETTE)], dtype=np.float32)[None, None]).max(2) < 0.25) & (rgba[..., 3] > 0.9)
            if not o:
                if m.sum() > 20: missing.append(f"frame {n} {t['name']}: bar visible without data")
                continue
            if m.sum() < 20:
                missing.append(f"frame {n} {t['name']}: bar missing"); continue
            if o["partial"] or o["extrapolated"] or m[0].any() or m[-1].any() or m[:, 0].any() or m[:, -1].any():
                continue
            if ti in covered:                                # a nearer bar overlaps this one: its visible centre is biased
                hidden += 1; continue
            ys, xs = np.nonzero(m); P = np.stack([xs + 0.5, ys + 0.5], 1)
            c = P.mean(0); d = np.linalg.svd(P - c, full_matrices=False)[2][0]
            tt = (P - c) @ d
            pos.append((float(np.hypot(c[0] - o["u"], c[1] - o["v"])), n, t["name"]))
            rel.append(abs((tt.max() - tt.min() + 1) - o["major"]) / o["major"])
    if pos:
        pe = np.array([p[0] for p in pos])
        print(f"Blender render vs tracked centre: {len(pe)} checks, mean {pe.mean():.2f} px, max {pe.max():.2f} px (frame {max(pos)[1]}, {max(pos)[2]}); "
              f"bar length within {max(rel) * 100:.1f} % ; {hidden} bars not measured because a nearer bar covers part of them")
    print("render visibility problems:", missing if missing else "none")
    for n in CHECK_FRAMES:
        ref = Image.open(frame_path(cfg, n)).convert("RGBA")
        full = os.path.join(scratch, f"full_{n:04d}.png")       # bars + plane outline + grid, when the plane exists
        bl = Image.open(full if os.path.exists(full) else os.path.join(scratch, f"bl_{n:04d}.png")).convert("RGBA")
        bl.putalpha(bl.getchannel("A").point(lambda v: int(v * 0.7)))
        Image.alpha_composite(ref, bl).convert("RGB").save(os.path.join(out_dir, "check", f"Blender_render_frame_{n:02d}.png"))
else:
    print("no Blender render was produced (check B skipped) - check A above still stands")
ok = "problems: none" in r.stdout and (not pos or float(np.mean([p[0] for p in pos])) < 0.5)
print("saved", blend)
print("BLENDER VERIFY:", "PASS" if ok else "FAIL - investigate before delivering")
sys.exit(0 if ok else 2)
