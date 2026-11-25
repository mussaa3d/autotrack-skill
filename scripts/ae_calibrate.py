"""Re-measure After Effects' 3D rotation convention (only needed for an AE version this skill has not been run on,
or if verify_ae.py reports large errors).
usage: python -I ae_calibrate.py <scratch_dir> [<AE 'Support Files' dir>]

Renders known 3D markers through cameras and parent nulls with known Orientation / X-Y-Z Rotation values, then
finds which Euler order and signs reproduce the rendered pixels. export.py assumes the result measured on AE 23.2:
    order=XYZ  signs=(1, 1, 1)  O*R      i.e.  L = Rx(ox) Ry(oy) Rz(oz), Orientation applied before Rotation
If this prints something else, change ae_orient() in export.py to match and re-run verify_ae.py.
"""
import sys, os, math, glob, itertools, subprocess
import numpy as np
from PIL import Image

scratch = os.path.abspath(sys.argv[1]).replace("\\", "/")
os.makedirs(scratch, exist_ok=True)
ae_dir = sys.argv[2] if len(sys.argv) > 2 else sorted(glob.glob("C:/Program Files/Adobe/Adobe After Effects */Support Files"))[-1]

Z = [0, 0, 0]
T = [[Z, Z, Z, Z, [960, 540, 0]], [[8, 0, 0], Z, Z, Z, [960, 540, 0]], [[0, 8, 0], Z, Z, Z, [960, 540, 0]], [[0, 0, 8], Z, Z, Z, [960, 540, 0]],
     [[6, -9, 14], Z, Z, Z, [960, 540, 0]], [Z, [6, -9, 14], Z, Z, [960, 540, 0]], [[4, 7, -11], [-5, 3, 9], Z, Z, [960, 540, 0]],
     [[6, -9, 14], Z, Z, Z, [1100, 400, -300]], [Z, Z, [25, 0, 0], Z, [960, 540, 0]], [Z, Z, [0, 25, 0], Z, [960, 540, 0]],
     [Z, Z, [0, 0, 25], Z, [960, 540, 0]], [Z, Z, [20, -30, 40], Z, [960, 540, 0]], [Z, Z, Z, [20, -30, 40], [960, 540, 0]],
     [Z, Z, [15, 25, -35], [-10, 20, 30], [960, 540, 0]]]
W_PTS = [[960, 540, 3000], [1360, 540, 3000], [960, 840, 3000], [1260, 840, 4200], [660, 340, 2200], [1100, 300, 5000]]
W_COL = [[1, 0, 0], [0, 1, 0], [0, 0, 1], [1, 1, 0], [1, 0, 1], [0, 1, 1]]
C_PTS = [[300, 0, 0], [0, 250, 0], [0, 0, 400]]
C_COL = [[1, 0.5, 0], [0.5, 0, 1], [1, 1, 1]]
NULL_POS, ZOOM, CX, CY = [960, 540, 3000], 2000.0, 960.0, 540.0

JSX = r'''(function () {
    var outDir = "__OUT__";
    var log = new File(outDir + "/log.txt"); log.open("w"); log.close();
    function L(s) { log.open("a"); log.writeln(s); log.close(); }
    try {
        app.beginSuppressDialogs();
        L("AE version " + app.version);
        var T = __T__, pts = __WP__, cols = __WC__, cpts = __CP__, ccols = __CC__, FPS = 24, i, k;
        var comp = app.project.items.addComp("conv_test", 1920, 1080, 1.0, T.length / FPS, FPS);
        comp.bgColor = [0, 0, 0];
        function tg(l) { return l.property("ADBE Transform Group"); }
        for (i = 0; i < pts.length; i++) { var s = comp.layers.addSolid(cols[i], "w" + i, 40, 40, 1.0); s.threeDLayer = true; tg(s).property("ADBE Position").setValue(pts[i]); }
        var nul = comp.layers.addNull(); nul.threeDLayer = true; tg(nul).property("ADBE Position").setValue(__NP__);
        for (i = 0; i < cpts.length; i++) { var c = comp.layers.addSolid(ccols[i], "c" + i, 40, 40, 1.0); c.threeDLayer = true; c.parent = nul; tg(c).property("ADBE Position").setValue(cpts[i]); }
        var cam = comp.layers.addCamera("cam", [960, 540]);
        cam.autoOrient = AutoOrientType.NO_AUTO_ORIENT;
        cam.property("ADBE Camera Options Group").property("ADBE Camera Zoom").setValue(__ZOOM__);
        var ct = tg(cam), nt = tg(nul), names = ["ADBE Orientation", "ADBE Rotate X", "ADBE Rotate Y", "ADBE Rotate Z", "ADBE Position"];
        for (k = 0; k < T.length; k++) {
            var t = k / FPS;
            ct.property(names[0]).setValueAtTime(t, T[k][0]);
            nt.property(names[0]).setValueAtTime(t, T[k][2]);
            for (i = 0; i < 3; i++) { ct.property(names[1 + i]).setValueAtTime(t, T[k][1][i]); nt.property(names[1 + i]).setValueAtTime(t, T[k][3][i]); }
            ct.property(names[4]).setValueAtTime(t, T[k][4]);
        }
        function holdAll(p) { for (var q = 1; q <= p.numKeys; q++) p.setInterpolationTypeAtKey(q, KeyframeInterpolationType.HOLD, KeyframeInterpolationType.HOLD); }
        for (i = 0; i < names.length; i++) { holdAll(ct.property(names[i])); if (i < 4) holdAll(nt.property(names[i])); }
        var rq = app.project.renderQueue.items.add(comp), om = rq.outputModule(1);
        om.applyTemplate("TIFF Sequence with Alpha");
        om.file = new File(outDir + "/r_[##]");
        app.project.save(new File(outDir + "/conv_test.aep"));
        L("project saved");
    } catch (e) { L("ERROR " + e.toString() + " line " + e.line); }
    try { app.project.close(CloseOptions.DO_NOT_SAVE_CHANGES); } catch (e2) {}
    app.quit();
})();
'''
import json
js = (JSX.replace("__OUT__", scratch).replace("__T__", json.dumps(T)).replace("__WP__", json.dumps(W_PTS)).replace("__WC__", json.dumps(W_COL))
      .replace("__CP__", json.dumps(C_PTS)).replace("__CC__", json.dumps(C_COL)).replace("__NP__", json.dumps(NULL_POS)).replace("__ZOOM__", str(ZOOM)))
open(os.path.join(scratch, "calibrate.jsx"), "w", encoding="utf-8").write(js)
subprocess.run([os.path.join(ae_dir, "AfterFX.com"), "-noui", "-r", os.path.join(scratch, "calibrate.jsx")], capture_output=True, text=True, timeout=600)
print(open(os.path.join(scratch, "log.txt")).read().strip())
subprocess.run([os.path.join(ae_dir, "aerender.exe"), "-project", os.path.join(scratch, "conv_test.aep"), "-sound", "OFF"], capture_output=True, text=True, timeout=900, check=True)

WP, CP, NP = np.array(W_PTS, float), np.array(C_PTS, float), np.array(NULL_POS, float)
ALLC = np.array(W_COL + C_COL, float)
def centroids(k):
    im = np.asarray(Image.open(os.path.join(scratch, f"r_{k:02d}.tif")).convert("RGB"), dtype=np.float32) / 255.0
    out = {}
    for i, c in enumerate(ALLC):
        m = np.abs(im - c[None, None]).max(2) < 0.2
        if m.sum() >= 60:
            ys, xs = np.nonzero(m); out[i] = (xs.mean() + 0.5, ys.mean() + 0.5)
    return out
obs = [centroids(k) for k in range(len(T))]

def el(axis, a):
    c, s = math.cos(math.radians(a)), math.sin(math.radians(a))
    return [np.array([[1, 0, 0], [0, c, -s], [0, s, c]]), np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]]), np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])][axis]
def euler(v, order, signs):
    Mx = np.eye(3)
    for ax in order: Mx = Mx @ el(ax, signs[ax] * v[ax])
    return Mx
def proj(P, cp, Lc):
    Xc = (P - np.array(cp, float)) @ Lc
    return np.stack([CX + ZOOM * Xc[:, 0] / Xc[:, 2], CY + ZOOM * Xc[:, 1] / Xc[:, 2]], 1)
res = []
for order in itertools.permutations(range(3)):
    for signs in itertools.product((1, -1), repeat=3):
        for combo in ("O*R", "R*O"):
            e = []
            for k, (co, cr, no, nr, cp) in enumerate(T):
                O, Rr, NO, NR = euler(co, order, signs), euler(cr, order, signs), euler(no, order, signs), euler(nr, order, signs)
                Lc, Ln = (O @ Rr, NO @ NR) if combo == "O*R" else (Rr @ O, NR @ NO)
                pw, pc = proj(WP, cp, Lc), proj(NP + CP @ Ln.T, cp, Lc)
                e += [math.hypot(pw[i, 0] - obs[k][i][0], pw[i, 1] - obs[k][i][1]) for i in range(6) if i in obs[k]]
                e += [math.hypot(pc[i, 0] - obs[k][6 + i][0], pc[i, 1] - obs[k][6 + i][1]) for i in range(3) if 6 + i in obs[k]]
            res.append((float(np.mean(e)), float(np.max(e)), order, signs, combo))
res.sort(key=lambda r: r[0])
print("best conventions (mean px error, max px error, euler order as a left-to-right matrix product, signs, orientation/rotation order):")
for r in res[:4]:
    print(f"  {r[0]:8.3f} {r[1]:8.3f}  order={''.join('XYZ'[a] for a in r[2])}  signs={r[3]}  {r[4]}")
print("export.py expects: order=XYZ  signs=(1, 1, 1)  O*R  with a mean error well under 1 px")
