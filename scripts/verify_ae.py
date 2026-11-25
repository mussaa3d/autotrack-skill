"""Step 5a: build the After Effects project from the delivered script and prove it with AE's own renderer.
usage: python -I verify_ae.py <config.json>

What it does (AE must not already be running with unsaved work - it launches a window-less instance):
  1. runs <name>_AE_camera.jsx unchanged inside AE (AfterFX.com -noui) and saves <out_dir>/<name>_camera_track.aep
  2. makes three render-queue items: the comp itself, the draft bars alone, the 2D dots alone (unique colours)
  3. renders them with aerender and measures, per frame, how far AE's pixels are from the tracked data
  4. writes <out_dir>/check/AE_render_frame_XX.png and AE_comp_preview.mp4

Lessons baked in (AE 23.2): in -noui mode app.newProject() kills AE and comp.saveFrameToPng() silently writes
nothing, so rendering goes through the render queue + aerender; logs are appended line by line because a
buffered log is lost when AE dies.
"""
import sys, os, json, math, glob, subprocess, shutil
sys.dont_write_bytecode = True          # never leave __pycache__ inside the skill folder
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from PIL import Image
from common import load_cfg, wdir, covered_bars

cfg = load_cfg(sys.argv[1])
solve = json.load(open(wdir(cfg, "solve", "solve.json")))
ae_data = json.load(open(wdir(cfg, "solve", "ae_data.json")))
M = solve["meta"]
NAME, N, F, W, H = M["name"], M["frames"], M["focal_px"], M["width"], M["height"]
out_dir = cfg["out_dir"]
scratch = wdir(cfg, "ae_verify").replace("\\", "/")
if os.path.isdir(scratch):
    shutil.rmtree(scratch)
os.makedirs(scratch)
os.makedirs(os.path.join(out_dir, "check"), exist_ok=True)

ae_dir = cfg.get("ae_dir")
if not ae_dir:
    cands = sorted(glob.glob("C:/Program Files/Adobe/Adobe After Effects */Support Files"))
    if not cands:
        sys.exit("After Effects not found. Set \"ae_dir\" in the config to its 'Support Files' folder, or skip this step and say so.")
    ae_dir = cands[-1]
tasks = subprocess.run(["tasklist", "/FI", "IMAGENAME eq AfterFX.exe"], capture_output=True, text=True).stdout
if "AfterFX.exe" in tasks:
    sys.exit("After Effects is already running. Ask the user to save and close it first (a second headless instance would attach to it).")

BAR_PALETTE = [[1, 0, 0], [0, 1, 0], [0, 0, 1], [1, 1, 0], [1, 0, 1], [0, 1, 1], [1, 0.5, 0], [0.5, 0, 1]]
npts = sum(len(t["pts"]) for t in ae_data["tracks"])
L = 3
while L ** 3 - (L - 1) ** 3 < max(npts, 1):
    L += 1
levels = [i / (L - 1) for i in range(L)]
# only colours whose brightest channel is 1: anti-aliased rims (darker multiples) then never match another dot's colour
dot_palette = [[r, g, b] for r in levels for g in levels for b in levels if max(r, g, b) == 1.0][:max(npts, 1)]
TOL = 0.4 / (L - 1)

WRAPPER = r'''var ACT_HEADLESS = true;
(function () {
    var scratch = "__SCRATCH__";
    var log = new File(scratch + "/log.txt"); log.open("w"); log.close();
    function L(s) { log.open("a"); log.writeln(s); log.close(); }
    function tp(layer, name) { return layer.property("ADBE Transform Group").property(name); }
    try {
        app.beginSuppressDialogs();
        $.evalFile(new File("__JSX__"));
        var comp = null, i, g;
        for (i = 1; i <= app.project.numItems; i++) if (app.project.item(i) instanceof CompItem && app.project.item(i).name === "__COMP__") comp = app.project.item(i);
        if (!comp) throw new Error("comp not created");
        L("comp: " + comp.numLayers + " layers, fps " + comp.frameRate + ", duration " + comp.duration);
        app.project.save(new File("__AEP__"));
        L("clean project saved");
        var palette = __PALETTE__;
        // bars only (+ white marker on the plane corner)
        var v = comp.duplicate(); v.name = "VERIFY_BARS"; v.bgColor = [0, 0, 0];
        var planePos = null;
        for (i = 1; i <= v.numLayers; i++) {
            var ly = v.layer(i);
            if (ly instanceof CameraLayer) continue;
            if (ly.name === "DRAFT ROOF") planePos = tp(ly, "ADBE Position").value;
            if (ly instanceof ShapeLayer) { ly.enabled = false; continue; }
            if (ly.name.indexOf("DRAFT ") === 0) { tp(ly, "ADBE Opacity").setValue(100); continue; }
            if (ly.name.indexOf("REFERENCE") === 0) ly.enabled = false;
        }
        if (planePos) {
            var m = v.layers.addSolid([1, 1, 1], "CORNER", 60, 60, 1.0);
            m.threeDLayer = true; tp(m, "ADBE Position").setValue(planePos); m.moveToEnd();
        }
        // dots only, unique colour per dot
        var d = comp.duplicate(); d.name = "VERIFY_DOTS"; d.bgColor = [0, 0, 0];
        for (i = 1; i <= d.numLayers; i++) {
            var dl = d.layer(i);
            if (dl instanceof CameraLayer) continue;
            if (dl.name !== "DRAFT 2D POINTS") { dl.enabled = false; continue; }
            var root = dl.property("ADBE Root Vectors Group");
            for (g = 1; g <= root.numProperties; g++) {
                var vec = root.property(g).property("ADBE Vectors Group");
                var c = palette[g - 1];
                vec.property("ADBE Vector Graphic - Fill").property("ADBE Vector Fill Color").setValue([c[0], c[1], c[2], 1]);
                dl.property("ADBE Root Vectors Group").property(g).property("ADBE Vectors Group").property("ADBE Vector Graphic - Stroke").property("ADBE Vector Stroke Width").setValue(0);
                dl.property("ADBE Root Vectors Group").property(g).property("ADBE Vectors Group").property("ADBE Vector Shape - Ellipse").property("ADBE Vector Ellipse Size").setValue([8, 8]);
            }
        }
        function queue(c, base) {
            var rq = app.project.renderQueue.items.add(c);
            var om = rq.outputModule(1);
            om.applyTemplate("TIFF Sequence with Alpha");
            om.file = new File(scratch + "/" + base + "_[##]");
        }
        queue(v, "bars"); queue(d, "dots"); queue(comp, "main");
        app.project.save(new File(scratch + "/verify.aep"));
        L("verify project saved");
    } catch (e) {
        L("ERROR " + e.toString() + " line " + e.line);
    }
    L("done");
    try { app.project.close(CloseOptions.DO_NOT_SAVE_CHANGES); } catch (e2) {}
    app.quit();
})();
'''
jsx = os.path.join(out_dir, NAME + "_AE_camera.jsx").replace("\\", "/")
aep = os.path.join(out_dir, NAME + "_camera_track.aep").replace("\\", "/")
wrapper = os.path.join(scratch, "build_and_verify.jsx")
open(wrapper, "w", encoding="utf-8").write(WRAPPER.replace("__SCRATCH__", scratch).replace("__JSX__", jsx).replace("__AEP__", aep)
                                           .replace("__COMP__", ae_data["compName"]).replace("__PALETTE__", json.dumps(dot_palette)))
subprocess.run([os.path.join(ae_dir, "AfterFX.com"), "-noui", "-r", wrapper], capture_output=True, text=True, timeout=900)
log = open(os.path.join(scratch, "log.txt")).read() if os.path.exists(os.path.join(scratch, "log.txt")) else ""
print(log.strip())
if "verify project saved" not in log:
    sys.exit("After Effects did not finish the build - read the log above (an ERROR line names the failing script line).")
r = subprocess.run([os.path.join(ae_dir, "aerender.exe"), "-project", os.path.join(scratch, "verify.aep"), "-sound", "OFF"],
                   capture_output=True, text=True, timeout=1800)
if r.returncode != 0:
    print(r.stdout[-1500:]); sys.exit("aerender failed")

def load(base, n):
    return np.asarray(Image.open(os.path.join(scratch, f"{base}_{n - 1:02d}.tif")).convert("RGB"), dtype=np.float32) / 255.0

def touches_edge(m):
    return m[0].any() or m[-1].any() or m[:, 0].any() or m[:, -1].any()

C = np.array(solve["camera"]["center"]); R = {int(k): np.array(v) for k, v in solve["camera"]["R"].items()}
pos, rel, ang, corner, notes, hidden = [], [], [], [], [], 0
for n in range(1, N + 1):
    im = load("bars", n)
    if solve["roof"]:
        m = np.abs(im - 1.0).max(2) < 0.2
        Xc = R[n] @ (-C); exp = np.array([W / 2 + F * Xc[0] / Xc[2], H / 2 + F * Xc[1] / Xc[2]])
        if m.sum() > 40 and not touches_edge(m):
            ys, xs = np.nonzero(m); got = np.array([xs.mean() + 0.5, ys.mean() + 0.5])
            corner.append(float(np.linalg.norm(got - exp)))
            if str(n) in solve["roof"]["corner_px"]:
                me = np.array(solve["roof"]["corner_px"][str(n)])
                notes.append(f"  frame {n}: plane corner drawn at ({me[0]:.1f},{me[1]:.1f}), AE renders it at ({got[0]:.1f},{got[1]:.1f}) -> {np.linalg.norm(got - me):.2f} px")
    present = [(ti, t["obs"][str(n)]) for ti, t in enumerate(solve["tracks"]) if str(n) in t["obs"]]
    cov = covered_bars([o for _, o in present], W, H)
    covered = {present[i][0] for i in cov}
    for ti, t in enumerate(solve["tracks"]):
        o = t["obs"].get(str(n))
        col = np.array(BAR_PALETTE[ti % len(BAR_PALETTE)], dtype=np.float32)
        m = np.abs(im - col[None, None]).max(2) < 0.2
        if not o:
            if m.sum() > 20: notes.append(f"  frame {n} {t['name']}: bar visible although the track has no data here")
            continue
        if m.sum() < 20:
            notes.append(f"  frame {n} {t['name']}: bar missing in the AE render"); continue
        if o["partial"] or o["extrapolated"] or touches_edge(m):
            continue
        if ti in covered:                                    # a nearer bar overlaps this one: its visible centre is biased
            hidden += 1; continue
        ys, xs = np.nonzero(m); P = np.stack([xs + 0.5, ys + 0.5], 1)
        c = P.mean(0); d = np.linalg.svd(P - c, full_matrices=False)[2][0]
        if d[0] < 0: d = -d
        tt = (P - c) @ d
        pos.append((float(np.hypot(c[0] - o["u"], c[1] - o["v"])), n, t["name"]))
        rel.append(abs((tt.max() - tt.min() + 1) - o["major"]) / o["major"])
        if o["major"] > 60: ang.append(abs((math.degrees(math.atan2(d[1], d[0])) - o["ang"] + 90) % 180 - 90))
dpos, dmiss, gi = [], 0, 0
dots = {n: load("dots", n) for n in range(1, N + 1)} if npts else {}
for t in ae_data["tracks"]:
    for p in t["pts"]:
        col = np.array(dot_palette[gi], dtype=np.float32); gi += 1
        for k, n in enumerate(range(p["first"], p["last"] + 1)):
            m = np.abs(dots[n] - col[None, None]).max(2) < TOL
            if not p["vis"][k]:
                if m.sum() > 6: notes.append(f"  frame {n} {t['name']} {p['name']}: dot visible on a frame without data")
                continue
            if m.sum() < 6:
                dmiss += 1; continue                       # hidden under another dot or outside the frame
            ys, xs = np.nonzero(m)
            dpos.append((float(np.hypot(xs.mean() + 0.5 - p["pos"][k][0], ys.mean() + 0.5 - p["pos"][k][1])), n, t["name"] + " " + p["name"]))
ok = True
if pos:
    pe = np.array([p[0] for p in pos])
    print(f"3D track bars, AE render vs tracked centre: {len(pe)} checks, mean {pe.mean():.2f} px, max {pe.max():.2f} px (frame {max(pos)[1]}, {max(pos)[2]})")
    print(f"  bar length within {max(rel) * 100:.1f} % of the marker length, angle within {max(ang) if ang else 0:.2f} deg"
          f" ; {hidden} bars not measured because a nearer bar covers part of them")
    ok &= pe.mean() < 0.5
if dpos:
    de = np.array([p[0] for p in dpos])
    print(f"2D point dots, AE render vs tracked point: {len(de)} checks, mean {de.mean():.2f} px, max {de.max():.2f} px (frame {max(dpos)[1]}, {max(dpos)[2]}); {dmiss} dots hidden/overlapped")
    ok &= de.mean() < 0.5
if corner:
    print(f"plane corner, AE render vs solve: {len(corner)} frames, max {max(corner):.2f} px")
print("\n".join(notes) if notes else "  no visibility problems")
show = sorted(set(M["measured_camera_frames"] + [1, max(1, N // 3), max(1, 2 * N // 3), N - 1]))[:8]
for n in show:
    Image.open(os.path.join(scratch, f"main_{n - 1:02d}.tif")).convert("RGB").save(os.path.join(out_dir, "check", f"AE_render_frame_{n:02d}.png"))
subprocess.run(["ffmpeg", "-v", "error", "-y", "-framerate", f"{M['fps_num']}/{M['fps_den']}", "-i", os.path.join(scratch, "main_%02d.tif"),
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "14", os.path.join(out_dir, "check", "AE_comp_preview.mp4")], check=False)
print("saved", aep)
print("AE VERIFY:", "PASS" if ok else "FAIL - investigate before delivering")
sys.exit(0 if ok else 2)
