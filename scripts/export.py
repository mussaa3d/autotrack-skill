"""Step 4: write the deliverables from solve.json.
usage: python -I export.py <config.json>

Writes into <out_dir>:
  <name>_AE_camera.jsx          After Effects script: adds one comp with camera, 3D + 2D track nulls, draft objects
  <name>_blender_camera.py      Blender script: camera, empties, draft objects, reference clip as camera background
  tracking_data/*.csv, solve.json

After Effects rotation convention (measured by scripts/ae_calibrate.*, AE 23.2, 0.13 px mean error):
  axes x right, y down, z away from the viewer; camera looks along local +z; u = cx + zoom * x / z
  layer local->world rotation  L = Rx(ox) * Ry(oy) * Rz(oz)  for Orientation [ox,oy,oz]  (Orientation acts before X/Y/Z Rotation)
The AE world is the camera's rest frame scaled to pixels, with the camera at z = -zoom, so the z = 0 plane is at 100 %.
"""
import sys, os, json, math, csv
sys.dont_write_bytecode = True          # never leave __pycache__ inside the skill folder
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from common import load_cfg, wdir, el

cfg = load_cfg(sys.argv[1])
out_dir = cfg["out_dir"]
data_dir = os.path.join(out_dir, "tracking_data")
os.makedirs(data_dir, exist_ok=True)
solve = json.load(open(wdir(cfg, "solve", "solve.json")))
M = solve["meta"]
NAME, W, H, N, F = M["name"], M["width"], M["height"], M["frames"], M["focal_px"]
C = np.array(solve["camera"]["center"])
R = {int(k): np.array(v) for k, v in solve["camera"]["R"].items()}
R_rest = np.array(solve["camera"]["R_rest"])
STATUS = {int(k): v for k, v in solve["camera"]["status"].items()}
roof, tracks, bg2d = solve["roof"], solve["tracks"], solve["bg2d"]
S = float(cfg.get("ae", {}).get("px_per_m", 100.0))
AE_CAM = np.array([W / 2.0, H / 2.0, -F])
FLIP = np.diag([1.0, -1.0, -1.0])
MARKER_M = M["marker_real_length_m"]
PALETTE = [[1, 0, 0], [0, 1, 0], [0, 0, 1], [1, 1, 0], [1, 0, 1], [0, 1, 1], [1, 0.5, 0], [0.5, 0, 1]]


def ae_orient(L):
    b = math.asin(max(-1.0, min(1.0, L[0][2])))
    a = math.atan2(-L[1][2], L[2][2])
    c = math.atan2(-L[0][1], L[0][0])
    assert np.abs(el(0, a) @ el(1, b) @ el(2, c) - L).max() < 1e-9, "orientation extraction failed (gimbal)"
    return [round(math.degrees(a), 5), round(math.degrees(b), 5), round(math.degrees(c), 5)]


def ae_pos(Pw):
    return [round(v, 3) for v in (S * (R_rest @ (np.array(Pw, float) - C)) + AE_CAM).tolist()]


def bl_euler_xyz(Rm):
    y = -math.asin(max(-1.0, min(1.0, Rm[2][0])))
    return [math.degrees(math.atan2(Rm[2][1], Rm[2][2])), math.degrees(y), math.degrees(math.atan2(Rm[1][0], Rm[0][0]))]


cam_ae = [ae_orient(R_rest @ R[n].T) for n in range(1, N + 1)]
cam_bl = [(R[n].T @ FLIP).round(9).tolist() for n in range(1, N + 1)]

ae_tracks, bl_tracks = [], []
for ti, t in enumerate(tracks):
    fr = sorted(int(k) for k in t["obs"])
    obs = [t["obs"][str(n)] for n in fr]
    ref = next(o["major"] for o in obs if not o["partial"])
    col = PALETTE[ti % len(PALETTE)]
    names = sorted({k for o in obs for k in o["pts"]})
    a_pts, b_pts = [], []
    for pn in names:
        have = [n for n, o in zip(fr, obs) if pn in o["pts"]]
        first, last = have[0], have[-1]
        pos, vis, lastp = [], [], None
        for n in range(first, last + 1):
            o = t["obs"].get(str(n))
            if o and pn in o["pts"]:
                lastp = [round(o["pts"][pn]["u"], 2), round(o["pts"][pn]["v"], 2)]
                vis.append(100)
            else:
                vis.append(0)
            pos.append(lastp)
        a_pts.append(dict(name=pn, first=first, last=last, pos=pos, vis=vis))
        b_pts.append(dict(name=pn, obs=[dict(frame=n, loc=[round(v, 5) for v in t["obs"][str(n)]["pts"][pn]["world"]]) for n in have]))
    ae_tracks.append(dict(
        name=t["name"], color=col, first=fr[0], last=fr[-1], f=fr,
        p3=[ae_pos(o["world"]) for o in obs],
        o3=[ae_orient(R_rest @ R[n].T @ el(2, math.radians(o["ang"]))) for n, o in zip(fr, obs)],
        p2=[[round(o["u"], 2), round(o["v"], 2)] for o in obs],
        s2=[round(o["major"] / ref * 100.0, 3) for o in obs], r2=[round(o["ang"], 3) for o in obs], pts=a_pts))
    bl_tracks.append(dict(
        name=t["name"], color=col + [1.0],
        obs=[dict(frame=n, loc=[round(v, 5) for v in o["world"]], rot=(R[n].T @ FLIP @ el(2, math.radians(-o["ang"]))).round(9).tolist())
             for n, o in zip(fr, obs)], pts=b_pts))

plane_ae, plane_bl = None, None
if roof:
    g = roof["grid"]
    def loc(x, y):
        return [round(S * x, 2), round(-S * y, 2)]          # plane-local coords: x = world X, y = -world Y
    lines = []
    x = g["x0"]
    while x <= g["x1"] + 1e-6:
        lines.append([loc(x, g["y0"]), loc(x, g["y1"])]); x += g["step"]
    y = g["y0"]
    while y <= g["y1"] + 1e-6:
        lines.append([loc(g["x0"], y), loc(g["x1"], y)]); y += g["step"]
    corners = [[0, 0, 0], [roof["lenX"], 0, 0], [roof["lenX"], roof["lenY"], 0], [0, roof["lenY"], 0]]
    plane_ae = dict(pos=ae_pos([0, 0, 0]), orient=ae_orient(R_rest @ FLIP), gridStep=g["step"],
                    roofPoly=[loc(c[0], c[1]) for c in corners], gridLines=lines, corners3d=[ae_pos(c) for c in corners],
                    bg2d=dict(p=[[round(bg2d[str(n)]["u"], 2), round(bg2d[str(n)]["v"], 2)] for n in range(1, N + 1)],
                              r=[round(bg2d[str(n)]["rot"], 4) for n in range(1, N + 1)]))
    plane_bl = dict(roof=corners, grid=g)

fps = M["fps_num"] / M["fps_den"]
video = cfg["video"].replace("\\", "/")
ae_data = dict(compName=NAME + " CAMERA TRACK", videoName=os.path.basename(video), videoPath=video, width=W, height=H, frames=N,
               fps=round(fps, 3), zoom=F, focal_mm=M["focal_mm"], camPos=AE_CAM.tolist(), camOrient=cam_ae,
               measured=M["measured_camera_frames"], lockFrame=M["lock_frame"], plane=plane_ae, markerPx=MARKER_M * S, tracks=ae_tracks)
bl_fps = round(fps)
bl_data = dict(name=NAME, video_name=os.path.basename(video), video_path=video, width=W, height=H, frames=N, fps=bl_fps, fps_base=bl_fps / fps,
               focal_mm=M["focal_mm"], sensor_mm=M["sensor_mm"], cam_loc=[round(v, 5) for v in C.tolist()], cam_rot=cam_bl,
               plane=plane_bl, marker_m=MARKER_M, clip_end=max(1000.0, 10.0 * float(np.linalg.norm(C))), tracks=bl_tracks)

# ------------------------------------------------------------------ After Effects script
JSX = r'''/*
  __NAME__ - camera + tracking data for After Effects   (generated by the animation-camera-track skill)

  HOW TO USE
    File > Scripts > Run Script File...  and pick this file. It adds ONE new comp, "__NAME__ CAMERA TRACK",
    to whatever project is open. Nothing else is changed; one Undo removes it.

  WHAT IS IN THE COMP (top to bottom)
    CAM ...                 one-node camera, fixed position, Orientation keyed on every frame. Zoom is in pixels:
                            zoom / comp width * 36 = focal length in mm for AE's default 36 mm film size.
    TRK3D <copy>            3D null on each tracked marker (hold keys = the drawing timing), facing the camera
    DRAFT <copy>            coloured bar parented to that null: same place, length and angle as the marker
    BG3D corner n           3D nulls fixed on the solved plane (they do not move; the camera does)
    TRK2D <copy>            2D null: marker centre (Position px), Scale (% of its first drawing), Rotation
    PT2D <copy> <point>     2D nulls for the extra points of that copy (marker ends, second marker piece, body ...)
    TRK2D BACKGROUND        2D null that follows the background: parent a flat background layer to it
    DRAFT 2D POINTS         one shape layer with a dot on every 2D point (a dot disappears on frames where its point has no data)
    DRAFT ROOF / GROUND GRID  the flat structure the camera was solved from, and a grid on the same plane
    REFERENCE               the original clip

  To pin your own drawing to a character copy: parent it to that copy's TRK2D null (2D layer) or TRK3D null (3D layer).
*/
(function () {
    var D = __DATA__;
    var HEADLESS = (typeof ACT_HEADLESS !== "undefined") && ACT_HEADLESS;

    function findVideo() {
        var here = (new File($.fileName)).parent;
        var c = [here.fsName + "/" + D.videoName, D.videoPath];
        if (here.parent) c.push(here.parent.fsName + "/" + D.videoName);
        for (var i = 0; i < c.length; i++) { var f = new File(c[i]); if (f.exists) return f; }
        if (!HEADLESS) return File.openDialog("Locate " + D.videoName + "   (Cancel = build without the reference clip)");
        return null;
    }
    function tp(layer, name) { return layer.property("ADBE Transform Group").property(name); }
    function hold(prop) {
        for (var k = 1; k <= prop.numKeys; k++) prop.setInterpolationTypeAtKey(k, KeyframeInterpolationType.HOLD, KeyframeInterpolationType.HOLD);
    }
    function vectors(layer, gi) { return layer.property("ADBE Root Vectors Group").property(gi).property("ADBE Vectors Group"); }
    function addPath(layer, gi, pts, closed) {
        var pg = vectors(layer, gi).addProperty("ADBE Vector Shape - Group");
        var s = new Shape(); s.vertices = pts; s.closed = closed;
        pg.property("ADBE Vector Shape").setValue(s);
    }
    function addStroke(layer, gi, rgb, width) {
        var st = vectors(layer, gi).addProperty("ADBE Vector Graphic - Stroke");
        st.property("ADBE Vector Stroke Color").setValue([rgb[0], rgb[1], rgb[2], 1]);
        st.property("ADBE Vector Stroke Width").setValue(width);
    }
    function addFill(layer, gi, rgb, opacity) {
        var fl = vectors(layer, gi).addProperty("ADBE Vector Graphic - Fill");
        fl.property("ADBE Vector Fill Color").setValue([rgb[0], rgb[1], rgb[2], 1]);
        fl.property("ADBE Vector Fill Opacity").setValue(opacity);
    }
    function planeLayer(comp, name) {
        var sl = comp.layers.addShape(); sl.name = name; sl.threeDLayer = true;
        tp(sl, "ADBE Anchor Point").setValue([0, 0, 0]);
        tp(sl, "ADBE Position").setValue(D.plane.pos);
        tp(sl, "ADBE Orientation").setValue(D.plane.orient);
        sl.property("ADBE Root Vectors Group").addProperty("ADBE Vector Group");
        return sl;
    }

    if (!HEADLESS) app.beginUndoGroup(D.compName);
    try {
        var comp = app.project.items.addComp(D.compName, D.width, D.height, 1.0, D.frames / D.fps, D.fps);
        var fd = comp.frameDuration, i, k, j, t, times;
        function T(n) { return (n - 1) * fd; }
        function span(layer, first, last) { layer.inPoint = T(first); layer.outPoint = T(last) + fd; }

        // ---- reference clip (bottom layer)
        var vf = findVideo();
        if (vf) {
            var item = app.project.importFile(new ImportOptions(vf));
            var ref = comp.layers.add(item); ref.name = "REFERENCE " + D.videoName;
            try { ref.audioEnabled = false; } catch (e0) {}
        }

        // ---- plane: grid + structure outline (3D shape layers lying on the solved plane)
        if (D.plane) {
            var grid = planeLayer(comp, "GROUND GRID (" + D.plane.gridStep + " m)");
            for (i = 0; i < D.plane.gridLines.length; i++) addPath(grid, 1, D.plane.gridLines[i], false);
            addStroke(grid, 1, [0.35, 0.65, 1.0], 4);
            tp(grid, "ADBE Opacity").setValue(60);
            var roof = planeLayer(comp, "DRAFT ROOF");
            addPath(roof, 1, D.plane.roofPoly, true);
            addStroke(roof, 1, [1, 0, 0], 12);
            addFill(roof, 1, [1, 0, 0], 8);
        }

        // ---- one shape layer with a dot per 2D point
        var dots = comp.layers.addShape(); dots.name = "DRAFT 2D POINTS";
        tp(dots, "ADBE Anchor Point").setValue([0, 0]);
        tp(dots, "ADBE Position").setValue([0, 0]);
        var gi = 0;
        for (i = 0; i < D.tracks.length; i++) {
            t = D.tracks[i];
            for (j = 0; j < t.pts.length; j++) {
                var pt = t.pts[j];
                var g = dots.property("ADBE Root Vectors Group").addProperty("ADBE Vector Group");
                g.name = t.name + " " + pt.name; gi++;
                vectors(dots, gi).addProperty("ADBE Vector Shape - Ellipse").property("ADBE Vector Ellipse Size").setValue([16, 16]);
                addStroke(dots, gi, [1, 1, 1], 2);
                addFill(dots, gi, t.color, 100);
                var tr = dots.property("ADBE Root Vectors Group").property(gi).property("ADBE Vector Transform Group");
                times = []; var vis = [];
                for (k = pt.first; k <= pt.last; k++) times.push(T(k));
                tr.property("ADBE Vector Position").setValuesAtTimes(times, pt.pos); hold(tr.property("ADBE Vector Position"));
                var vt = times.slice(0), vv = pt.vis.slice(0);
                if (pt.first > 1) { vt.unshift(0); vv.unshift(0); }
                if (pt.last < D.frames) { vt.push(T(pt.last + 1)); vv.push(0); }
                tr.property("ADBE Vector Group Opacity").setValuesAtTimes(vt, vv); hold(tr.property("ADBE Vector Group Opacity"));
            }
        }

        // ---- 2D background track
        if (D.plane) {
            var bg = comp.layers.addNull(); bg.name = "TRK2D BACKGROUND (plane corner)"; bg.label = 2;
            times = [];
            for (k = 1; k <= D.frames; k++) times.push(T(k));
            tp(bg, "ADBE Position").setValuesAtTimes(times, D.plane.bg2d.p); hold(tp(bg, "ADBE Position"));
            tp(bg, "ADBE Rotate Z").setValuesAtTimes(times, D.plane.bg2d.r); hold(tp(bg, "ADBE Rotate Z"));
        }

        // ---- 2D tracks and extra 2D points
        for (i = D.tracks.length - 1; i >= 0; i--) {
            t = D.tracks[i];
            for (j = t.pts.length - 1; j >= 0; j--) {
                var q = t.pts[j], pn = comp.layers.addNull();
                pn.name = "PT2D " + t.name + " " + q.name; pn.label = 10;
                times = [];
                for (k = q.first; k <= q.last; k++) times.push(T(k));
                tp(pn, "ADBE Position").setValuesAtTimes(times, q.pos); hold(tp(pn, "ADBE Position"));
                span(pn, q.first, q.last);
            }
            times = []; var s2 = [];
            for (k = 0; k < t.f.length; k++) { times.push(T(t.f[k])); s2.push([t.s2[k], t.s2[k], 100]); }
            var n2 = comp.layers.addNull(); n2.name = "TRK2D " + t.name; n2.label = 9;
            tp(n2, "ADBE Position").setValuesAtTimes(times, t.p2); hold(tp(n2, "ADBE Position"));
            tp(n2, "ADBE Scale").setValuesAtTimes(times, s2); hold(tp(n2, "ADBE Scale"));
            tp(n2, "ADBE Rotate Z").setValuesAtTimes(times, t.r2); hold(tp(n2, "ADBE Rotate Z"));
            span(n2, t.first, t.last);
        }

        // ---- fixed 3D background nulls on the plane
        if (D.plane) {
            for (i = D.plane.corners3d.length - 1; i >= 0; i--) {
                var cn = comp.layers.addNull(); cn.name = "BG3D corner " + (i + 1) + (i === 0 ? " (tracked)" : ""); cn.threeDLayer = true; cn.label = 2;
                tp(cn, "ADBE Position").setValue(D.plane.corners3d[i]);
                tp(cn, "ADBE Orientation").setValue(D.plane.orient);
            }
        }

        // ---- 3D tracks + draft bars
        for (i = D.tracks.length - 1; i >= 0; i--) {
            t = D.tracks[i]; times = [];
            for (k = 0; k < t.f.length; k++) times.push(T(t.f[k]));
            var n3 = comp.layers.addNull(); n3.name = "TRK3D " + t.name; n3.threeDLayer = true; n3.label = 11;
            var bar = comp.layers.addSolid(t.color, "DRAFT " + t.name, 600, 200, 1.0);
            bar.threeDLayer = true;
            bar.parent = n3;
            tp(bar, "ADBE Position").setValue([0, 0, 0]);
            tp(bar, "ADBE Orientation").setValue([0, 0, 0]);
            var sc = D.markerPx / 600 * 100;
            tp(bar, "ADBE Scale").setValue([sc, sc, sc]);
            tp(bar, "ADBE Opacity").setValue(70);
            tp(n3, "ADBE Position").setValuesAtTimes(times, t.p3); hold(tp(n3, "ADBE Position"));
            tp(n3, "ADBE Orientation").setValuesAtTimes(times, t.o3); hold(tp(n3, "ADBE Orientation"));
            span(n3, t.first, t.last); span(bar, t.first, t.last);
            n3.moveBefore(bar);
        }

        // ---- camera (top layer)
        var cam = comp.layers.addCamera("CAM " + D.focal_mm + "mm", [D.width / 2, D.height / 2]);
        cam.autoOrient = AutoOrientType.NO_AUTO_ORIENT;
        tp(cam, "ADBE Position").setValue(D.camPos);
        cam.property("ADBE Camera Options Group").property("ADBE Camera Zoom").setValue(D.zoom);
        times = [];
        for (k = 1; k <= D.frames; k++) times.push(T(k));
        tp(cam, "ADBE Orientation").setValuesAtTimes(times, D.camOrient); hold(tp(cam, "ADBE Orientation"));

        try {
            for (i = 0; i < D.measured.length; i++) comp.markerProperty.setValueAtTime(T(D.measured[i]), new MarkerValue("camera measured"));
            if (D.measured.length) comp.markerProperty.setValueAtTime(T(D.lockFrame), new MarkerValue("camera locked off"));
        } catch (e1) {}
        if (!HEADLESS) comp.openInViewer();
    } finally {
        if (!HEADLESS) app.endUndoGroup();
    }
})();
'''
jsx_path = os.path.join(out_dir, NAME + "_AE_camera.jsx")
open(jsx_path, "w", encoding="utf-8").write(JSX.replace("__NAME__", NAME).replace("__DATA__", json.dumps(ae_data, separators=(",", ":"))))

# ------------------------------------------------------------------ Blender script
BPY = r'''# __NAME__ - camera + tracking data for Blender   (generated by the animation-camera-track skill)
#
# HOW TO USE
#   Scripting workspace > Text > Open > this file > Run Script (Alt+P). Works in a new or an existing scene.
#   It adds a collection "__NAME___track" and sets the scene resolution, frame rate and frame range.
#
# WHAT IT MAKES
#   CAM_...                camera with the solved lens, fixed position, rotation keyed on every frame, and the
#                          reference clip as its background (look through it with Numpad 0)
#   TRK_<copy>             empty on each tracked marker;  DRAFT_<copy>: a bar with the marker's length and angle
#   PT_<copy>_<point>      empties for the extra points of that copy (marker ends, second marker piece, body ...)
#   BG_corner_n, DRAFT_ROOF, GROUND_GRID   the flat structure the camera was solved from, on z = 0
#   Anything that has no data on a frame is scaled to 0 on that frame.
# World units are metres, Z is up.
import bpy, os, json
from mathutils import Matrix

VIDEO_PATH = ""      # optional: full path to the reference clip if it is not found automatically
D = json.loads(r"""__DATA__""")

scene = bpy.context.scene
scene.render.resolution_x = D["width"]
scene.render.resolution_y = D["height"]
scene.render.resolution_percentage = 100
scene.render.pixel_aspect_x = 1.0
scene.render.pixel_aspect_y = 1.0
scene.render.fps = D["fps"]
scene.render.fps_base = D["fps_base"]
scene.frame_start = 1
scene.frame_end = D["frames"]
NF = D["frames"]

col = bpy.data.collections.new(D["name"] + "_track")
scene.collection.children.link(col)


def add_mesh(name, verts, edges, faces):
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, edges, faces)
    me.update()
    ob = bpy.data.objects.new(name, me)
    col.objects.link(ob)
    return ob


def add_empty(name, kind, size):
    ob = bpy.data.objects.new(name, None)
    ob.empty_display_type = kind
    ob.empty_display_size = size
    ob.rotation_mode = 'XYZ'
    col.objects.link(ob)
    return ob


def key_rotation(ob, rot3, frame, prev):
    m = Matrix(rot3)
    e = m.to_euler('XYZ', prev) if prev is not None else m.to_euler('XYZ')
    ob.rotation_euler = e
    ob.keyframe_insert(data_path="rotation_euler", frame=frame)
    return e.copy()


def key_sparse(ob, obs, with_rotation):
    """key location (+rotation) on every frame; scale 0 where there is no data so stale positions never show"""
    by = dict((o["frame"], o) for o in obs)
    first = obs[0]
    prev = None
    for n in range(1, NF + 1):
        o = by.get(n)
        if o is not None:
            ob.location = o["loc"]
            ob.scale = (1.0, 1.0, 1.0)
            if with_rotation:
                prev = key_rotation(ob, o["rot"], n, prev)
        else:
            if n < first["frame"]:
                ob.location = first["loc"]
            ob.scale = (0.0, 0.0, 0.0)
            if with_rotation:
                ob.keyframe_insert(data_path="rotation_euler", frame=n)
        ob.keyframe_insert(data_path="location", frame=n)
        ob.keyframe_insert(data_path="scale", frame=n)


# ---- camera
cam_data = bpy.data.cameras.new("CAM_%dmm" % round(D["focal_mm"]))
cam_data.lens = D["focal_mm"]
cam_data.sensor_width = D["sensor_mm"]
cam_data.sensor_fit = 'HORIZONTAL'
cam_data.clip_start = 0.1
cam_data.clip_end = D["clip_end"]
cam = bpy.data.objects.new(cam_data.name, cam_data)
col.objects.link(cam)
cam.rotation_mode = 'XYZ'
prev = None
for n in range(1, NF + 1):
    cam.location = D["cam_loc"]
    cam.keyframe_insert(data_path="location", frame=n)
    prev = key_rotation(cam, D["cam_rot"][n - 1], n, prev)
scene.camera = cam

# ---- reference clip as camera background
candidates = [VIDEO_PATH, D["video_path"]]
if bpy.data.filepath:
    candidates.append(os.path.join(os.path.dirname(bpy.data.filepath), D["video_name"]))
video = next((p for p in candidates if p and os.path.isfile(p)), None)
if video:
    try:
        clip = bpy.data.movieclips.load(video)
        cam_data.show_background_images = True
        bg = cam_data.background_images.new()
        bg.source = 'MOVIE_CLIP'
        bg.clip = clip
        bg.alpha = 0.6
    except Exception as ex:
        print("could not attach the reference clip:", ex)
else:
    print("reference clip not found - set VIDEO_PATH at the top of this script")

# ---- solved plane: structure outline, grid, corner empties (all static)
if D["plane"]:
    roof = add_mesh("DRAFT_ROOF", [tuple(v) for v in D["plane"]["roof"]], [], [(0, 1, 2, 3)])
    roof.display_type = 'WIRE'
    roof.color = (1.0, 0.0, 0.0, 1.0)
    g = D["plane"]["grid"]
    verts, edges = [], []
    x = g["x0"]
    while x <= g["x1"] + 1e-6:
        verts += [(x, g["y0"], 0.0), (x, g["y1"], 0.0)]
        edges.append((len(verts) - 2, len(verts) - 1))
        x += g["step"]
    y = g["y0"]
    while y <= g["y1"] + 1e-6:
        verts += [(g["x0"], y, 0.0), (g["x1"], y, 0.0)]
        edges.append((len(verts) - 2, len(verts) - 1))
        y += g["step"]
    grid = add_mesh("GROUND_GRID", verts, edges, [])
    grid.color = (0.35, 0.65, 1.0, 1.0)
    for i, c in enumerate(D["plane"]["roof"]):
        e = add_empty("BG_corner_%d" % (i + 1), 'PLAIN_AXES', g["step"] * 0.4)
        e.location = c

# ---- tracks: one empty + draft bar per copy, plus its extra points
L = D["marker_m"]
for t in D["tracks"]:
    emp = add_empty("TRK_" + t["name"], 'ARROWS', L * 0.5)
    bar = add_mesh("DRAFT_" + t["name"],
                   [(-L / 2, -L / 6, 0.0), (L / 2, -L / 6, 0.0), (L / 2, L / 6, 0.0), (-L / 2, L / 6, 0.0)], [], [(0, 1, 2, 3)])
    bar.color = tuple(t["color"])
    bar.parent = emp
    key_sparse(emp, t["obs"], True)
    for p in t["pts"]:
        pe = add_empty("PT_%s_%s" % (t["name"], p["name"]), 'SPHERE', L * 0.12)
        pe.color = tuple(t["color"])
        key_sparse(pe, p["obs"], False)

scene.frame_set(1)
print("%s: camera, %d tracks, %d extra point empties created. Numpad 0 looks through the camera."
      % (D["name"], len(D["tracks"]), sum(len(t["pts"]) for t in D["tracks"])))
'''
bpy_path = os.path.join(out_dir, NAME + "_blender_camera.py")
open(bpy_path, "w", encoding="utf-8").write(BPY.replace("__NAME__", NAME).replace("__DATA__", json.dumps(bl_data, separators=(",", ":"))))

# ------------------------------------------------------------------ CSV + json
with open(os.path.join(data_dir, "camera_per_frame.csv"), "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["frame", "camera_status", "focal_mm", "ae_zoom_px", "ae_pos_x", "ae_pos_y", "ae_pos_z", "ae_orient_x", "ae_orient_y", "ae_orient_z",
                "blender_loc_x", "blender_loc_y", "blender_loc_z", "blender_rot_x_deg", "blender_rot_y_deg", "blender_rot_z_deg",
                "background_2d_x", "background_2d_y", "background_2d_rotation_deg"])
    for n in range(1, N + 1):
        b = bg2d[str(n)] if bg2d else dict(u="", v="", rot="")
        w.writerow([n, STATUS[n], M["focal_mm"], F] + [round(v, 4) for v in AE_CAM.tolist()] + cam_ae[n - 1] + [round(v, 5) for v in C.tolist()]
                   + [round(v, 5) for v in bl_euler_xyz(np.array(cam_bl[n - 1]))] + [b["u"], b["v"], b["rot"]])
with open(os.path.join(data_dir, "tracks_per_frame.csv"), "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["frame", "track", "point", "screen_x_px", "screen_y_px", "marker_length_px", "marker_angle_deg", "cut_by_frame_edge", "placed_by_hand",
                "depth_from_camera_m", "blender_x", "blender_y", "blender_z", "ae_x", "ae_y", "ae_z"])
    for t in tracks:
        for k in sorted(t["obs"], key=int):
            o = t["obs"][k]
            w.writerow([int(k), t["name"], "centre", round(o["u"], 2), round(o["v"], 2), round(o["major"], 2), round(o["ang"], 2), int(o["partial"]),
                        int(o["extrapolated"]), round(o["depth"], 4)] + [round(v, 5) for v in o["world"]] + ae_pos(o["world"]))
            for pn in sorted(o["pts"]):
                p = o["pts"][pn]
                w.writerow([int(k), t["name"], pn, round(p["u"], 2), round(p["v"], 2), "", "", "", "", round(o["depth"], 4)]
                           + [round(v, 5) for v in p["world"]] + ae_pos(p["world"]))
json.dump(solve, open(os.path.join(data_dir, "solve.json"), "w"), indent=1)
json.dump(ae_data, open(wdir(cfg, "solve", "ae_data.json"), "w"))
npts = sum(len(t["pts"]) for t in ae_tracks)
print(f"wrote {jsx_path} ({os.path.getsize(jsx_path)} bytes)")
print(f"wrote {bpy_path} ({os.path.getsize(bpy_path)} bytes)")
print(f"{len(ae_tracks)} tracks, {npts} extra point tracks, camera lens {M['focal_mm']:g} mm = After Effects zoom {F:g} px")
