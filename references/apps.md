# After Effects and Blender notes

## After Effects

### Conventions (measured with `ae_calibrate.py` on AE 23.2.1, mean error 0.13 px)

- Comp axes: x right, y down, z away from the viewer. A camera looks along its local +z.
- Projection: `u = cx + zoom * x / z`. Zoom is in pixels and equals the focal length in pixels:
  `zoom = focal_mm / film_size_mm * comp_width`. With AE's default 36 mm film size, 7200 px on a 1920 comp is 135 mm.
  The script API cannot set film size, so quote the zoom / angle of view if the user's default differs.
- A layer's local-to-world rotation for Orientation `[ox, oy, oz]` is `Rx(ox) * Ry(oy) * Rz(oz)` (right-handed in the
  axes above), and Orientation is applied before the X / Y / Z Rotation properties.
- Use a one-node camera: `cam.autoOrient = AutoOrientType.NO_AUTO_ORIENT`.

### How the exported comp is laid out

The AE world is the camera's rest frame scaled to pixels (`ae.px_per_m`, default 100) with the camera at
`[W/2, H/2, -zoom]`. So at rest the camera has zero orientation and the z = 0 plane shows layers at 100 %, like a
default AE camera. Tracks at depth `d` metres sit at `z = d * px_per_m - zoom`.

### Headless scripting (AE 23.2)

- `AfterFX.com -noui -r script.jsx` runs a script without a window and returns when the script calls `app.quit()`.
- `app.newProject()` in `-noui` mode kills AE silently. A fresh launch already has an empty project; do not call it.
- `comp.saveFrameToPng()` in `-noui` mode reports success and writes nothing. Render through the render queue:
  `om.applyTemplate("TIFF Sequence with Alpha"); om.file = new File(dir + "/name_[##]")`, save the project, then
  `aerender.exe -project x.aep -sound OFF`. `[##]` is the 0-based frame index.
- Write logs by open-append-close per line. A buffered log is lost when AE dies, and then there is nothing to debug.
- Scripts can only write files if Preferences > Scripting & Expressions > "Allow Scripts to Write Files and Access
  Network" is on (`"Pref_SCRIPTING_FILE_NETWORK_SECURITY" = "1"` in the prefs file). If it is off, ask the user to
  turn it on; do not change it yourself.
- If AfterFX.exe is already running, a second launch attaches to it. `verify_ae.py` refuses in that case; ask the
  user to save and close.
- After adding a property to a shape layer group, earlier references to sibling properties can go stale. Re-fetch
  from the layer each time (the exported script does).
- Setting `child.parent = nullLayer` compensates the child's transform, so set the child's position / scale /
  orientation after parenting.

## Blender

- Camera looks down local -Z with +Y up. For a world-to-camera rotation `R` in the OpenCV sense used here, the
  camera's world matrix rotation is `R.T @ diag(1, -1, -1)`.
- `sensor_fit = 'HORIZONTAL'`, `sensor_width` = the config sensor, `lens` = focal length in mm.
- 23.976 fps is `fps = 24`, `fps_base = 1.001`.
- The exported script only uses `bpy.data` (no operators), keys every frame, and hides objects by scale 0, so it does
  not depend on context, interpolation defaults or the action/slot API. Verified on Blender 5.3.0.
- `blender -b --factory-startup --python script.py -- args` runs headless, including Workbench renders.
- `bpy_extras.object_utils.world_to_camera_view(scene, cam, point)` returns normalised frame coordinates with y up:
  `u = x * W`, `v = (1 - y) * H`. This is the quickest exact check of a camera.
- No Blender on the machine: get the portable zip and the matching `.sha256` from
  `https://download.blender.org/release/BlenderX.Y/`, verify the hash, extract into its own folder. Ask first; it is
  a ~400 MB download.
