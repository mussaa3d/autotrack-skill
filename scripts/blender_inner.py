"""Runs INSIDE Blender (started by verify_blender.py):
  blender -b --factory-startup --python blender_inner.py -- <delivered_script.py> <solve.json> <out.blend> <scratch_dir>
Executes the delivered script unchanged, saves the .blend, then checks with Blender's own camera
(world_to_camera_view on every keyed empty, every frame) and renders the draft bars for a pixel check.
"""
import bpy, sys, os, json, math, runpy
from mathutils import Vector
from bpy_extras.object_utils import world_to_camera_view

args = sys.argv[sys.argv.index("--") + 1:]
script, solve_path, out_blend, scratch = args[:4]
check_frames = args[4] if len(args) > 4 else ""
os.makedirs(scratch, exist_ok=True)
print("BLENDER", bpy.app.version_string)
for ob in list(bpy.data.objects):                 # clean factory scene (cube / light / camera)
    bpy.data.objects.remove(ob, do_unlink=True)
runpy.run_path(script, run_name="__main__")       # exactly what the user will run

scene = bpy.context.scene
cam = scene.camera
solve = json.load(open(solve_path))
W, H, N = solve["meta"]["width"], solve["meta"]["height"], solve["meta"]["frames"]
print("CHECK_INFO: lens %.1f mm, sensor %.1f mm, fps %.4f, frames %d-%d, objects %d, background clips %s" % (
    cam.data.lens, cam.data.sensor_width, scene.render.fps / scene.render.fps_base, scene.frame_start, scene.frame_end,
    len(bpy.data.objects), [c.filepath for c in bpy.data.movieclips]))
for screen in bpy.data.screens:                   # open looking through the camera, showing object colours
    for area in screen.areas:
        if area.type == 'VIEW_3D':
            for space in area.spaces:
                if space.type == 'VIEW_3D':
                    try:
                        space.shading.color_type = 'OBJECT'
                        if space.region_3d is not None:
                            space.region_3d.view_perspective = 'CAMERA'
                    except Exception:
                        pass
scene.frame_set(1)
bpy.ops.wm.save_as_mainfile(filepath=out_blend)
backup = out_blend + "1"
if os.path.exists(backup):
    os.remove(backup)
print("CHECK_INFO: saved", out_blend)

def px(v):
    co = world_to_camera_view(scene, cam, v)
    return co.x * W, (1.0 - co.y) * H

errs, perrs, problems, corner = [], [], [], []
for n in range(1, N + 1):
    scene.frame_set(n)
    bpy.context.view_layer.update()
    for t in solve["tracks"]:
        o = t["obs"].get(str(n))
        emp = bpy.data.objects["TRK_" + t["name"]]
        if (o is not None) != (emp.scale[0] > 0.5):
            problems.append("frame %d %s: visibility mismatch" % (n, t["name"]))
        if o is not None:
            u, v = px(emp.matrix_world.translation)
            errs.append((math.hypot(u - o["u"], v - o["v"]), n, t["name"]))
            u2, v2 = px(emp.matrix_world @ Vector((0.01, 0.0, 0.0)))
            da = abs((math.degrees(math.atan2(v2 - v, u2 - u)) - o["ang"] + 180) % 360 - 180)
            if da > 0.2:
                problems.append("frame %d %s: bar angle off by %.2f deg" % (n, t["name"], da))
        names = set()
        for ob_ in t["obs"].values():
            names.update(ob_["pts"].keys())
        for pn in names:
            pe = bpy.data.objects["PT_%s_%s" % (t["name"], pn)]
            has = o is not None and pn in o["pts"]
            if has != (pe.scale[0] > 0.5):
                problems.append("frame %d %s %s: visibility mismatch" % (n, t["name"], pn))
            if has:
                u, v = px(pe.matrix_world.translation)
                perrs.append((math.hypot(u - o["pts"][pn]["u"], v - o["pts"][pn]["v"]), n, t["name"] + " " + pn))
    if solve["roof"] and str(n) in solve["roof"]["corner_px"]:
        u, v = px(Vector((0.0, 0.0, 0.0)))
        m = solve["roof"]["corner_px"][str(n)]
        corner.append("CHECK_A: frame %d plane corner drawn at (%.1f,%.1f), Blender camera gives (%.1f,%.1f) -> %.3f px" % (n, m[0], m[1], u, v, math.hypot(u - m[0], v - m[1])))
if errs:
    w = max(errs)
    print("CHECK_A: %d track centres through Blender's camera: mean %.4f px, max %.4f px (frame %d %s)" % (len(errs), sum(e[0] for e in errs) / len(errs), w[0], w[1], w[2]))
if perrs:
    w = max(perrs)
    print("CHECK_A: %d extra points through Blender's camera: mean %.4f px, max %.4f px (frame %d %s)" % (len(perrs), sum(e[0] for e in perrs) / len(perrs), w[0], w[1], w[2]))
for c in corner:
    print(c)
print("CHECK_A: problems:", problems if problems else "none")

try:                                              # draft bars only, flat colours, transparent film (not saved in the .blend)
    for ob in bpy.data.objects:
        if ob.name in ("DRAFT_ROOF", "GROUND_GRID"):
            ob.hide_render = True
    scene.render.engine = 'BLENDER_WORKBENCH'
    scene.display.shading.light = 'FLAT'
    scene.display.shading.color_type = 'OBJECT'
    scene.render.film_transparent = True
    scene.view_settings.view_transform = 'Standard'
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGBA'
    scene.render.filepath = os.path.join(scratch, "bl_")
    bpy.ops.render.render(animation=True)
    print("CHECK_B: rendered", len([f for f in os.listdir(scratch) if f.startswith("bl_")]), "frames")
except Exception as ex:
    print("CHECK_B: render failed:", ex)

# ---- a few frames with the plane outline and grid visible too, so the check images show the whole line-up.
# Wire objects do not render, so thin strips are built just for these pictures (nothing here is saved).
try:
    frames = [int(x) for x in check_frames.split(",") if x]
    if solve["roof"] and frames:
        Fpx = cam.data.lens / cam.data.sensor_width * W
        px_m = cam.location.length / Fpx                      # metres that cover one pixel at the plane's distance

        def strips(name, segs, width, color, lift):
            verts, faces = [], []
            for a, b in segs:
                a, b = Vector(a), Vector(b)
                d = b - a
                nrm = Vector((-d.y, d.x, 0.0)).normalized() * (width / 2.0)
                i = len(verts)
                verts += [tuple(a - nrm + lift), tuple(b - nrm + lift), tuple(b + nrm + lift), tuple(a + nrm + lift)]
                faces.append((i, i + 1, i + 2, i + 3))
            me = bpy.data.meshes.new(name)
            me.from_pydata(verts, [], faces)
            me.update()
            ob = bpy.data.objects.new(name, me)
            scene.collection.objects.link(ob)
            ob.color = color
        g, lx, ly = solve["roof"]["grid"], solve["roof"]["lenX"], solve["roof"]["lenY"]
        segs, x, y = [], g["x0"], g["y0"]
        while x <= g["x1"] + 1e-6:
            segs.append(((x, g["y0"], 0.0), (x, g["y1"], 0.0))); x += g["step"]
        while y <= g["y1"] + 1e-6:
            segs.append(((g["x0"], y, 0.0), (g["x1"], y, 0.0))); y += g["step"]
        strips("CHECK_grid", segs, 1.5 * px_m, (0.35, 0.65, 1.0, 1.0), Vector((0.0, 0.0, 0.0)))
        strips("CHECK_roof", [((0, 0, 0), (lx, 0, 0)), ((lx, 0, 0), (lx, ly, 0)), ((lx, ly, 0), (0, ly, 0)), ((0, ly, 0), (0, 0, 0))],
               4.0 * px_m, (1.0, 0.0, 0.0, 1.0), Vector((0.0, 0.0, 0.5 * px_m)))     # half a pixel above the grid, so it wins
        depths = [o["depth"] for t in solve["tracks"] for o in t["obs"].values()]
        cam.data.clip_start = min(1.0, 0.5 * min(depths)) if depths else 1.0         # depth precision for coplanar strips
        for n in frames:
            scene.frame_set(n)
            scene.render.filepath = os.path.join(scratch, "full_%04d.png" % n)
            bpy.ops.render.render(write_still=True)
        print("CHECK_B: rendered", len(frames), "check frames with the plane visible")
except Exception as ex:
    print("CHECK_B: plane check render skipped:", ex)
