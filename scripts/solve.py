"""Step 3b: solve the camera and lift the tracked shapes to 3D.
usage: python -I solve.py <config.json>

CAMERA  (config "plane", optional)
  A drawn clip has no rigid 3D scene, so a normal matchmove cannot work. What usually does exist for a few frames
  is one flat structure with a right-angled corner (roof, floor tile, wall, table). For those frames:
    - the corner position and its two edges are fitted from the ink
    - one shared corner shape + a roll per frame is fitted (least squares over the frames)
    - the camera is a fixed-position (nodal) pan / tilt / roll: corner exact, both edges split the residual
  Frames without that structure are filled in: interpolated between measured frames, extended before the first
  ("constant_pan" or "hold") and after the last ("decay" = ease-out measured from the last steps, or "hold").
  Held drawings reuse their source frame's camera. Without a "plane" section the camera is simply locked.

TRACKS  (config "marker")
  Each marker blob becomes one copy of the subject: centre, length (-> depth = F * real_length / length) and angle.
  Copies are linked through time in near-to-far order (order-preserving matching, so afterimage chains stay
  consistent). Extra points per copy: both ends of the marker, "secondary" marker pieces, "attached" shapes.

Writes <work_dir>/solve/solve.json, overlay/ov_XXXX.png for every frame and overlay contact sheets.
ALWAYS look at the overlays: they are the only proof that the solve sits on the drawing.
"""
import sys, os, json, math
sys.dont_write_bytecode = True          # never leave __pycache__ inside the skill folder
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from PIL import Image, ImageDraw
from common import (load_cfg, wdir, meta, load_rgb, fit_frame_edges, isect, expm, logm, wrap180, Camera, font, contact_sheet)

cfg = load_cfg(sys.argv[1])
m = meta(cfg)
W, H, N, HOLDS, BLANK = m["width"], m["height"], m["frames"], m["holds"], set(m["blank"])
cam = Camera(W, H, cfg["lens"]["focal_mm"], cfg["lens"]["sensor_mm"])
F = cam.F
os.makedirs(wdir(cfg, "solve", "overlay"), exist_ok=True)
plane = cfg.get("plane") or {}
AX = [np.array([1.0, 0.0, 0.0]), np.array([0.0, 1.0, 0.0])]

# ================================================================= camera
status = {}
roof = None
bg2d = None
if plane.get("frames"):
    mf = sorted(int(k) for k in plane["frames"])
    ref = int(plane.get("reference_frame", mf[-1]))
    DIST = float(plane.get("distance_m", 200.0))
    meas = {n: fit_frame_edges(cfg, n, plane["frames"][str(n)]) for n in mf}
    for n in mf:
        e = meas[n]
        # which way each corner edge leaves the corner (+1 along the fitted direction, -1 against it)
        e["sA"] = 1.0 if (e["cA"]["c"] - e["corner"]) @ e["cA"]["d"] > 0 else -1.0
        e["sB"] = 1.0 if (e["cB"]["c"] - e["corner"]) @ e["cB"]["d"] > 0 else -1.0
        print(f"f{n}: corner=({e['corner'][0]:.1f},{e['corner'][1]:.1f})  corner edges A {e['cA']['ang']:.2f} deg, B {e['cB']['ang']:.2f} deg")
    # ---- one shared corner shape + a roll per frame
    others = [n for n in mf if n != ref]
    rows, rhs = [], []
    for n in mf:
        for key, col in (("cA", 0), ("cB", 1)):
            r = [0.0] * (2 + len(others))
            r[col] = 1.0
            if n != ref:
                r[2 + others.index(n)] = 1.0
            rows.append(r)
            rhs.append(meas[n][key]["ang"])
    sol = np.linalg.lstsq(np.array(rows), np.array(rhs), rcond=None)[0]
    a0, b0 = sol[0], sol[1]
    roll0 = {n: (sol[2 + others.index(n)] if n != ref else 0.0) for n in mf}
    for a, b in zip(mf[:-1], mf[1:]):                # the corner's path is the quickest sanity check of "same corner?"
        st = meas[b]["corner"] - meas[a]["corner"]
        print(f"corner step f{a}->f{b}: ({st[0]:+.0f},{st[1]:+.0f}) px, {np.linalg.norm(st) / (b - a):.0f} px/frame"
              "   (a straight, steadily slowing or speeding path is what one real corner looks like)")

    def camera_for(sign):
        """reference orientation (minimum-tilt solution for a right angle seen as aA - aB) + per-frame rotations"""
        aA = math.radians(a0 + (180.0 if meas[ref]["sA"] < 0 else 0.0))
        aB = math.radians(b0 + (180.0 if meas[ref]["sB"] < 0 else 0.0))
        cosD = math.cos(aA - aB)
        k = math.sqrt(1.0 / (1.0 + abs(cosD)))
        z = sign * math.sqrt(max(0.0, 1.0 - k * k))
        eA = np.array([k * math.cos(aA), k * math.sin(aA), z])
        eB = np.array([k * math.cos(aB), k * math.sin(aB), z if cosD <= 0 else -z])
        fam_axis = {"B": 0, "A": 1}                  # world X runs along B, world Y along A ...
        eN = np.cross(eB, eA)
        if eN[2] > 0:                                # ... unless that would make the plane face away from the camera
            fam_axis = {"A": 0, "B": 1}
            eN = np.cross(eA, eB)
        eN /= np.linalg.norm(eN)
        eX = eB if fam_axis["B"] == 0 else eA
        eX = eX / np.linalg.norm(eX)
        R_ref = np.column_stack([eX, np.cross(eN, eX), eN])
        ray = cam.ray(meas[ref]["corner"])
        C = -R_ref.T @ (ray / np.linalg.norm(ray) * DIST)

        def pred_angle(R, fam, at_px):
            Xw = cam.backproject_plane(R, C, at_px)
            p, _ = cam.project(R, C, np.stack([Xw - AX[fam_axis[fam]] * 2.0, Xw + AX[fam_axis[fam]] * 2.0]))
            return math.degrees(math.atan2(p[1, 1] - p[0, 1], p[1, 0] - p[0, 0]))

        def residuals(delta, n):
            R = expm(delta) @ R_ref
            e = meas[n]
            uv, _ = cam.project(R, C, np.zeros(3))
            res = list((uv[0] - e["corner"]) / 0.5)
            for fam, l in (("A", e["cA"]), ("B", e["cB"])):
                res.append(wrap180(l["ang"] - pred_angle(R, fam, l["c"])))
            return np.array(res)

        Rm, report, hero_res, cerr, sq, wsum = {}, {}, {}, {}, 0.0, 0.0
        for n in mf:
            d = np.array([0.0, 0.0, math.radians(roll0[n])])
            for _ in range(40):
                r = residuals(d, n)
                J = np.zeros((len(r), 3))
                for i in range(3):
                    e3 = np.zeros(3)
                    e3[i] = 1e-6
                    J[:, i] = (residuals(d + e3, n) - r) / 1e-6
                step = np.linalg.lstsq(J, -r, rcond=None)[0]
                d = d + step
                if np.linalg.norm(step) < 1e-11:
                    break
            Rm[n] = expm(d) @ R_ref
            e = meas[n]
            uv, _ = cam.project(Rm[n], C, np.zeros(3))
            cerr[n] = float(np.linalg.norm(uv[0] - e["corner"]))
            hero_res[n] = [wrap180(e["cA"]["ang"] - pred_angle(Rm[n], "A", e["cA"]["c"])), wrap180(e["cB"]["ang"] - pred_angle(Rm[n], "B", e["cB"]["c"]))]
            report[n] = [dict(name=nm, family=fam, measured_deg=l["ang"], residual_deg=wrap180(l["ang"] - pred_angle(Rm[n], fam, l["c"])), length_px=l["span"])
                         for fam in ("A", "B") for nm, l in zip(e["names"][fam], e[fam])]
            for r_ in report[n]:
                sq += r_["length_px"] * r_["residual_deg"] ** 2
                wsum += r_["length_px"]
        return dict(R_ref=R_ref, C=C, Rm=Rm, report=report, hero_res=hero_res, cerr=cerr, fam_axis=fam_axis,
                    tilt=math.degrees(math.acos(-eN[2])), interior=math.degrees(math.acos(cosD)), rms=math.sqrt(sq / wsum))

    # which side of the plane leans toward the camera cannot be seen in line art; try both and keep the one whose
    # perspective agrees better with every stroke (config near_sign -1 / 1 forces a choice)
    forced = plane.get("near_sign", "auto")
    cands = {s: camera_for(s) for s in ((-1.0, 1.0) if forced in ("auto", None) else (float(forced),))}
    best_sign = min(cands, key=lambda s: cands[s]["rms"])
    if len(cands) > 1:
        print("near_sign: all-stroke residual " + ", ".join(f"{cands[s]['rms']:.2f} deg rms for {s:+.0f}" for s in cands) + f" -> using {best_sign:+.0f}")
    sel = cands[best_sign]
    R_ref, C, Rm, report, hero_res, fam_axis, tilt, interior = (sel[k_] for k_ in ("R_ref", "C", "Rm", "report", "hero_res", "fam_axis", "tilt", "interior"))
    print(f"shared corner: A {a0:.2f} deg, B {b0:.2f} deg, apparent interior angle {interior:.1f} deg -> plane tilt {tilt:.1f} deg ; roll vs f{ref}: "
          + ", ".join(f"f{n} {roll0[n]:+.2f}" for n in mf))
    for n in mf:
        print(f"f{n}: corner error {sel['cerr'][n]:.3f} px ; corner edges off by A {hero_res[n][0]:+.2f} deg, B {hero_res[n][1]:+.2f} deg ; all strokes: "
              + "  ".join(f"{r_['name']}:{r_['residual_deg']:+.1f}" for r_ in report[n]))
    # ---- fill every frame
    R = {}
    for i, n in enumerate(mf):
        R[n] = Rm[n]
        status[n] = "measured"
        if i + 1 < len(mf):
            n2 = mf[i + 1]
            w = logm(Rm[n2] @ Rm[n].T)
            for q in range(n + 1, n2):
                R[q] = expm(w * (q - n) / (n2 - n)) @ Rm[n]
                status[q] = "interpolated"
    lock_deg = float(plane.get("lock_deg", 0.02))
    before, after = plane.get("before_first", "constant_pan"), plane.get("after_last", "decay")
    v_first = logm(Rm[mf[1]] @ Rm[mf[0]].T) / (mf[1] - mf[0]) if len(mf) > 1 else np.zeros(3)
    v_first[2] = 0.0                                 # keep the pan speed, add no roll that was never observed
    for n in range(mf[0] - 1, 0, -1):
        R[n] = (expm(-v_first) @ R[n + 1]) if (before == "constant_pan" and len(mf) > 1) else R[n + 1]
        status[n] = "extrapolated" if (before == "constant_pan" and len(mf) > 1) else "held"
    decay = 0.5
    v = np.zeros(3)
    if len(mf) > 1 and after == "decay":
        v = logm(Rm[mf[-1]] @ Rm[mf[-2]].T) / (mf[-1] - mf[-2])
        if len(mf) > 2:
            vp = logm(Rm[mf[-2]] @ Rm[mf[-3]].T) / (mf[-2] - mf[-3])
            decay = float(np.clip(np.linalg.norm(v[:2]) / max(np.linalg.norm(vp[:2]), 1e-9), 0.3, 0.7))
        print(f"last measured steps: pan {math.degrees(np.linalg.norm(v[:2])):.2f} deg/frame, roll {math.degrees(v[2]):+.2f} deg/frame, ease-out factor {decay:.3f} per frame")
    for n in range(mf[-1] + 1, N + 1):
        v = v * decay
        if np.linalg.norm(v) > math.radians(lock_deg):
            R[n] = expm(v) @ R[n - 1]
            status[n] = "extrapolated"
        else:
            R[n] = R[n - 1]
            v = np.zeros(3)
            status[n] = "locked"
    for dst, src in HOLDS.items():
        if status[dst] != "measured":
            R[dst] = R[src]
    # ---- structure size (optional): a named line intersection gives the length of each corner edge
    lengths = {"A": 0.15 * DIST, "B": 0.15 * DIST}
    for fam, spec in (plane.get("edge_lengths") or {}).items():
        e = meas[int(spec["frame"])]
        ls = [e["cA"] if nm == "@cornerA" else e["cB"] if nm == "@cornerB" else e["fits"][nm] for nm in spec["lines"]]
        Xp = cam.backproject_plane(R[int(spec["frame"])], C, isect(ls[0], ls[1]))
        lengths[fam] = float(abs(Xp[fam_axis[fam]]))
        print(f"edge {fam}: far end at world ({Xp[0]:.2f},{Xp[1]:.2f}) -> length {lengths[fam]:.1f} m")
    lenX, lenY = (lengths["B"], lengths["A"]) if fam_axis["B"] == 0 else (lengths["A"], lengths["B"])
    xs, ys = [], []
    for n in range(1, N + 1):
        for uv in ((0, 0), (W, 0), (W, H), (0, H)):
            X = cam.backproject_plane(R[n], C, uv)
            if np.linalg.norm(X - C) < 6 * DIST:
                xs.append(X[0]); ys.append(X[1])
    step = float(plane.get("grid_step_m", 0)) or float(min([1, 2, 5, 10, 20, 50, 100], key=lambda s: abs((max(xs) - min(xs)) / s - 22)))
    grid = dict(step=step, x0=math.floor(min(xs) / step) * step, x1=math.ceil(max(xs) / step) * step,
                y0=math.floor(min(ys) / step) * step, y1=math.ceil(max(ys) / step) * step)
    roof = dict(lenX=lenX, lenY=lenY, grid=grid, tilt_deg=tilt, interior_deg=interior,
                corner_px={str(n): meas[n]["corner"].tolist() for n in mf},
                corner_edge_residual_deg={str(n): hero_res[n] for n in mf}, strokes={str(n): report[n] for n in mf})
    R_rest = R[N]
    # 2D background track: where the corner lands on screen + how much the plane has rolled, per frame
    def edge_dir(Rn):
        p, _ = cam.project(Rn, C, np.stack([np.zeros(3), AX[0] * 2.0]))
        return math.degrees(math.atan2(p[1, 1] - p[0, 1], p[1, 0] - p[0, 0]))
    bg2d = {}
    for n in range(1, N + 1):
        p, _ = cam.project(R[n], C, np.zeros(3))
        bg2d[str(n)] = dict(u=float(p[0, 0]), v=float(p[0, 1]), rot=float((edge_dir(R[n]) - edge_dir(R_rest) + 180) % 360 - 180))
    print(f"camera centre (world m): {np.round(C, 2).tolist()} ; structure {lenX:.1f} x {lenY:.1f} m ; grid step {step:g} m")
else:
    print("no plane measurements in the config: camera is locked for the whole clip (tracks only)")
    R0 = np.array([[1.0, 0.0, 0.0], [0.0, 0.0, -1.0], [0.0, 1.0, 0.0]])    # looks along world +Y, Z up
    C = np.zeros(3)
    R = {n: R0 for n in range(1, N + 1)}
    R_rest = R0
    mf = []
    for n in range(1, N + 1):
        status[n] = "locked"
lock_frame = N
while lock_frame > 1 and np.allclose(R[lock_frame - 1], R_rest, atol=1e-12):
    lock_frame -= 1
for n in range(lock_frame, N + 1):
    if status[n] != "measured":
        status[n] = "locked"
runs, start = [], 1
for n in range(2, N + 2):
    if n == N + 1 or status[n] != status[start]:
        runs.append(f"{start}-{n - 1} {status[start]}" if n - 1 > start else f"{start} {status[start]}")
        start = n
print("camera status by frame:", ", ".join(runs))

# ================================================================= tracks
tracks = []
mk = cfg.get("marker")
if mk and os.path.exists(wdir(cfg, "blobs", "blobs.json")):
    allb = json.load(open(wdir(cfg, "blobs", "blobs.json")))
    mblobs = {int(k): v for k, v in allb["marker"].items()}
    RIBBON = float(mk.get("real_length_m", 0.30))
    single = set(mk.get("single_subject_frames", []))
    override = {int(k): v for k, v in (mk.get("chain_override") or {}).items()}
    manual = {}
    for o in mk.get("manual", []):
        manual.setdefault(int(o["frame"]), []).append(o)
    far_end = mk.get("far_end", "bottom")            # where the far (small) end of an afterimage chain sits on screen
    far_key = {"bottom": lambda b: -b["cy"], "top": lambda b: b["cy"], "left": lambda b: b["cx"], "right": lambda b: -b["cx"]}[far_end]
    GAP = float(mk.get("gap_cost", 1.5))
    forced_until = int(mk.get("forced_rank_until", 0))
    forced_frames = set(int(x) for x in mk.get("forced_rank_frames", []))
    DEBUG_LINKS = bool(mk.get("debug_links", False))
    uniq = [n for n in range(1, N + 1) if n not in HOLDS]

    def link_cost(o, b):
        """distance in marker lengths + |log size ratio| (size is ignored when either shape is cut by the frame edge)"""
        c = math.hypot(b["cx"] - o["u"], b["cy"] - o["v"]) / (0.5 * (o["major"] + b["major"]))
        if not (b["cut"] or o["partial"]):
            c += abs(math.log(b["major"] / o["major"]))
        return c

    def prep(n):
        bl = []
        for b in mblobs.get(n, []):
            if b["minor"] < mk.get("min_minor", 5):
                continue
            b = dict(b)
            b["cut"] = b["x0"] <= 1 or b["y0"] <= 1 or b["x1"] >= W - 2 or b["y1"] >= H - 2
            b["cx"] += 0.5; b["cy"] += 0.5
            b["e0"] = [b["e0"][0] + 0.5, b["e0"][1] + 0.5]; b["e1"] = [b["e1"][0] + 0.5, b["e1"][1] + 0.5]
            bl.append(b)
        return bl

    def chain(n, bl, prev):
        """main markers of this frame, ordered near -> far; everything else is left over for 'secondary'"""
        if n in override:
            out = []
            for px, py in override[n]:
                b = min(bl, key=lambda q: math.hypot(q["cx"] - px, q["cy"] - py))
                if b not in out:
                    out.append(b)
            return out
        if n in single:
            return sorted(bl, key=lambda b: -b["area"])[:1]
        out, last = [], 0.0
        for b in sorted([b for b in bl if not b["cut"]], key=far_key):      # far end first: sizes must grow towards the camera
            if b["major"] > last:
                out.append(b)
                last = b["major"]
        out.reverse()
        cuts = []
        for b in bl:
            if not b["cut"]:
                continue
            for _, o in prev:                                               # a shape leaving the frame must continue a known track
                dist = math.hypot(b["cx"] - o["u"], b["cy"] - o["v"])
                if dist < 1.2 * o["major"] or (dist < 2.5 * o["major"] and b["area"] >= 0.3 * o.get("area", 1e18)):
                    cuts.append(b)
                    break
        if cuts:
            out.insert(0, max(cuts, key=lambda b: b["area"]))
        return out

    raw = []
    active = []
    for n in uniq:
        bl = prep(n)
        prev = [(t, raw[t][max(raw[t])]) for t in active]
        ch = chain(n, bl, prev)
        for o in reversed(manual.get(n, [])):
            ch.insert(0, dict(cx=o["u"], cy=o["v"], major=o["major"], ang=o.get("ang", 0.0), area=o["major"] ** 2 / 3.0, cut=False, manual=True,
                              e0=None, e1=None))
        if n <= forced_until or n in forced_frames or not prev:
            pairs = [(i, i) for i in range(min(len(prev), len(ch)))]
        else:
            ni, nj = len(prev), len(ch)
            D = np.full((ni + 1, nj + 1), 1e9)
            D[0, :] = np.arange(nj + 1) * GAP
            D[:, 0] = np.arange(ni + 1) * GAP
            bt = {}
            for i in range(1, ni + 1):
                for j in range(1, nj + 1):
                    c = link_cost(prev[i - 1][1], ch[j - 1])
                    D[i, j], bt[i, j] = min((D[i - 1, j - 1] + c, "m"), (D[i - 1, j] + GAP, "u"), (D[i, j - 1] + GAP, "l"))
            pairs, i, j = [], ni, nj
            while i > 0 and j > 0:
                mv = bt[i, j]
                if mv == "m":
                    pairs.append((i - 1, j - 1)); i -= 1; j -= 1
                elif mv == "u":
                    i -= 1
                else:
                    j -= 1
            pairs.reverse()
        if DEBUG_LINKS and prev:
            print(f"links f{n} ({'by rank' if (n <= forced_until or n in forced_frames) else 'matched'}, gap cost {GAP}): " + "  ".join(
                f"({prev[i][1]['u']:.0f},{prev[i][1]['v']:.0f})->({ch[j]['cx']:.0f},{ch[j]['cy']:.0f}) cost {link_cost(prev[i][1], ch[j]):.2f}" for i, j in pairs)
                + f"  | ended {len(prev) - len(pairs)}, started {len(ch) - len(pairs)}")
        matched = {j: prev[i][0] for i, j in pairs}
        new_active = []
        for j, b in enumerate(ch):
            t = matched.get(j)
            if t is None:
                raw.append({})
                t = len(raw) - 1
            last = raw[t][max(raw[t])] if raw[t] else None
            major = max(b["major"], last["major"]) if (b["cut"] and last) else b["major"]
            pts = {}
            if not b["cut"] and b.get("e0"):
                e0, e1 = (b["e0"], b["e1"]) if b["e0"][0] <= b["e1"][0] else (b["e1"], b["e0"])
                pts[mk.get("end_names", ["endL", "endR"])[0]] = e0
                pts[mk.get("end_names", ["endL", "endR"])[1]] = e1
            raw[t][n] = dict(u=b["cx"], v=b["cy"], major=major, ang=b["ang"], area=b["area"], partial=bool(b["cut"]),
                             extrapolated=bool(b.get("manual", False)), pts=pts)
            new_active.append(t)
        # ---- secondary marker pieces: leftovers that sit at a known offset from a main marker (offsets in marker lengths)
        left = [b for b in bl if not b["cut"] and all(b is not c for c in ch)]
        for pat in mk.get("secondary", []):
            for t in new_active:
                o = raw[t][n]
                if o["extrapolated"]:
                    continue
                cand = [b for b in left if pat["dx"][0] <= (b["cx"] - o["u"]) / o["major"] <= pat["dx"][1]
                        and pat["dy"][0] <= (b["cy"] - o["v"]) / o["major"] <= pat["dy"][1]]
                if cand:
                    if "expect" in pat:                      # best-placed candidate when the usual offset is known
                        b = min(cand, key=lambda q: math.hypot((q["cx"] - o["u"]) / o["major"] - pat["expect"][0],
                                                               (q["cy"] - o["v"]) / o["major"] - pat["expect"][1]))
                    else:
                        b = max(cand, key=lambda q: q["area"])
                    o["pts"][pat["name"]] = [b["cx"], b["cy"]]
                    left = [q for q in left if q is not b]
        # ---- attached shapes (e.g. body fill): every component goes to the copy whose expected spot is nearest
        for att in mk.get("attached", []):
            owners = [(t, raw[t][n]) for t in new_active if not (raw[t][n]["partial"] or raw[t][n]["extrapolated"])]
            acc = {t: [0.0, 0.0, 0.0, 0.0] for t, _ in owners}          # area, sum x, sum y, area cut by the frame edge
            for b in allb.get(att["name"], {}).get(str(n), []):
                cut = b["x0"] <= 1 or b["y0"] <= 1 or b["x1"] >= W - 2 or b["y1"] >= H - 2
                best, bd = None, 1e9
                for t, o in owners:
                    ex, ey = o["u"] + att["expect"][0] * o["major"], o["v"] + att["expect"][1] * o["major"]
                    dn = math.hypot(b["cx"] + 0.5 - ex, b["cy"] + 0.5 - ey) / o["major"]
                    if dn < bd and (cut or b["major"] / o["major"] <= att.get("max_size", 4.2)):
                        best, bd = t, dn
                if best is None or bd > att.get("max_dist", 1.2):
                    continue
                if cut:
                    acc[best][3] += b["area"]
                else:
                    acc[best][0] += b["area"]; acc[best][1] += b["area"] * (b["cx"] + 0.5); acc[best][2] += b["area"] * (b["cy"] + 0.5)
            for t, o in owners:
                a, sx, sy, a_cut = acc[t]
                # a shape that runs off the frame has no meaningful centre, so the point is left out for that frame
                if a >= att.get("min_mass", 0.6) * o["major"] ** 2 and a_cut <= 0.3 * a:
                    o["pts"][att["name"]] = [sx / a, sy / a]
        active = new_active

    raw = [t for t in raw if any(not o["partial"] for o in t.values())]
    raw.sort(key=lambda t: min(t))
    first_name, prefix = mk.get("first_track_name", "SUBJECT"), mk.get("other_track_prefix", "COPY")
    for i, t in enumerate(raw):
        for dst, src in HOLDS.items():
            if src in t:
                t[dst] = json.loads(json.dumps(t[src]))
        obs = {}
        for n in sorted(t):
            o = t[n]
            depth = F * RIBBON / o["major"]
            def lift(u, v):
                return (R[n].T @ (cam.ray((u, v)) * depth) + C).tolist()
            o["depth"] = float(depth)
            o["world"] = lift(o["u"], o["v"])
            o["pts"] = {k: dict(u=float(p[0]), v=float(p[1]), world=lift(p[0], p[1])) for k, p in o["pts"].items()}
            obs[str(n)] = o
        tracks.append(dict(name=first_name if i == 0 else f"{prefix}_{i:02d}", obs=obs))
    print("\ntracks  (frame:u,v,length  * = cut by the frame edge, ~ = placed by hand)   extra points in brackets")
    for t in tracks:
        fr = sorted(int(k) for k in t["obs"])
        pc = {}
        for o in t["obs"].values():
            for k in o["pts"]:
                pc[k] = pc.get(k, 0) + 1
        print(f" {t['name']:9s} frames {fr[0]}-{fr[-1]}: " + " ".join(
            f"{n}:{t['obs'][str(n)]['u']:.0f},{t['obs'][str(n)]['v']:.0f},{t['obs'][str(n)]['major']:.0f}"
            + ("*" if t['obs'][str(n)]['partial'] else "") + ("~" if t['obs'][str(n)]['extrapolated'] else "") for n in fr if n not in HOLDS)
            + f"   [{', '.join(f'{k} x{v}' for k, v in sorted(pc.items()))}]")
else:
    print("no marker section / blobs.json: no tracks")

# ================================================================= write
out = dict(
    meta=dict(name=cfg["name"], width=W, height=H, frames=N, fps_num=m["fps_num"], fps_den=m["fps_den"],
              focal_mm=cfg["lens"]["focal_mm"], sensor_mm=cfg["lens"]["sensor_mm"], focal_px=F,
              hfov_deg=math.degrees(2 * math.atan(W / 2 / F)), marker_real_length_m=(mk or {}).get("real_length_m", 0.30),
              plane_distance_m=plane.get("distance_m", 200.0) if roof else None, measured_camera_frames=mf, lock_frame=lock_frame,
              holds={str(k): v for k, v in HOLDS.items()}, blank=sorted(BLANK)),
    camera=dict(center=C.tolist(), R={str(n): R[n].tolist() for n in range(1, N + 1)}, R_rest=R_rest.tolist(),
                status={str(n): status[n] for n in range(1, N + 1)}),
    roof=roof, bg2d=bg2d, tracks=tracks)
json.dump(out, open(wdir(cfg, "solve", "solve.json"), "w"), indent=1)

# ================================================================= overlays
f22, f16 = font(22), font(16)
cols = [(0, 170, 0), (0, 90, 255), (230, 120, 0), (170, 0, 200), (0, 160, 170), (200, 0, 60), (110, 80, 0), (60, 60, 60)]

def seg(dr, Rn, a, b, fill, width):
    p, zc = cam.project(Rn, C, np.stack([a, b]))
    if (zc > 1).all() and np.abs(p).max() < 30000:
        dr.line([tuple(p[0]), tuple(p[1])], fill=fill, width=width)

ov_paths, ov_labels = [], []
for n in range(1, N + 1):
    im = Image.fromarray((255 - (255 - load_rgb(cfg, n)) * 0.55).astype(np.uint8))
    dr = ImageDraw.Draw(im)
    if roof:
        g = roof["grid"]
        x = g["x0"]
        while x <= g["x1"] + 1e-6:
            seg(dr, R[n], np.array([x, g["y0"], 0]), np.array([x, g["y1"], 0]), (150, 200, 255), 1); x += g["step"]
        y = g["y0"]
        while y <= g["y1"] + 1e-6:
            seg(dr, R[n], np.array([g["x0"], y, 0]), np.array([g["x1"], y, 0]), (150, 200, 255), 1); y += g["step"]
        rc = [np.array(p, float) for p in ((0, 0, 0), (roof["lenX"], 0, 0), (roof["lenX"], roof["lenY"], 0), (0, roof["lenY"], 0))]
        for i in range(4):
            seg(dr, R[n], rc[i], rc[(i + 1) % 4], (255, 0, 0), 4)
    for ti, t in enumerate(tracks):
        o = t["obs"].get(str(n))
        if not o:
            continue
        col = cols[ti % len(cols)]
        p, _ = cam.project(R[n], C, np.array(o["world"]))
        u, v = p[0]
        a = math.radians(o["ang"]); h = o["major"] / 2
        dr.line([(u - h * math.cos(a), v - h * math.sin(a)), (u + h * math.cos(a), v + h * math.sin(a))], fill=col, width=3)
        dr.ellipse([u - 9, v - 9, u + 9, v + 9], outline=col, width=4)
        dr.text((u + 12, v + 8), t["name"] + ("*" if o["partial"] else ""), fill=col, font=f22)
        for kname, pt in o["pts"].items():
            q, _ = cam.project(R[n], C, np.array(pt["world"]))
            dr.ellipse([q[0, 0] - 7, q[0, 1] - 7, q[0, 0] + 7, q[0, 1] + 7], fill=col, outline=(255, 255, 255))
            dr.text((q[0, 0] + 9, q[0, 1] - 9), kname, fill=col, font=f16)
    dr.rectangle([0, 0, 380, 34], fill=(255, 255, 255))
    dr.text((8, 4), f"frame {n:02d}  camera: {status[n]}", fill=(0, 0, 0), font=f22)
    p = wdir(cfg, "solve", "overlay", f"ov_{n:04d}.png")
    im.save(p)
    if n not in HOLDS and n not in BLANK:
        ov_paths.append(p); ov_labels.append(str(n))
for k in range(0, len(ov_paths), 9):
    contact_sheet(ov_paths[k:k + 9], ov_labels[k:k + 9], wdir(cfg, "solve", f"overlay_contact_{k // 9 + 1:02d}.png"), thumb_w=800, cols=3)
print("\nsolve.json, per-frame overlays and overlay contact sheets written to", wdir(cfg, "solve"))
