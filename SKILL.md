---
name: animation-camera-track
description: Recover the camera (lens, pan/tilt/roll) and character tracking points from a hand-drawn or 2D-animation reference clip and deliver them as a working After Effects project and Blender scene, verified by rendering in both apps. Use this whenever the user gives an anime / sakuga / rough-animation / storyboard / line-art clip and asks for "the same camera", the camera movement, the focal length or FOV, tracking data, a matchmove, tracking points, or wants to draw or place their own character over a reference shot's camera move in After Effects or Blender, even if they just say "track this" or "what lens is this". Also use it for driving After Effects headlessly from scripts. Not for live-action footage (use a real matchmover such as Blender's tracker or COLMAP there).
---

# Animation camera track

Turn a hand-drawn reference clip into a camera + track points that line up with the drawing in After Effects and
Blender, and prove it by rendering in both.

## The one thing to understand first

A drawn clip has **no physical camera and no rigid 3D scene**. The animator redraws the background every frame, mixes
perspectives, and holds drawings. So an ordinary matchmove (feature tracks + bundle adjustment) has nothing to solve.
What can be recovered honestly:

- the **lens the drawn perspective implies**, with a spread, from vanishing points of straight background lines
- the **camera rotation on the few frames that show a rigid flat structure** (a roof, floor, wall with a right-angled
  corner); everything else is interpolated / extended and must be labelled as such
- exact **2D positions of flat-coloured shapes** (a bow, scarf, hair clip, body fill). Flat fills are the only thing in
  line art that segments to sub-pixel accuracy, so they are the track points; outlines are not

Say this to the user up front, in plain words. People ask for "100% right"; what you can deliver is "sits on the
drawing to a fraction of a pixel where the drawing gives something to measure, and is clearly labelled where it
does not". Never present an extrapolated frame as measured.

## Workflow

All scripts live in `scripts/` next to this file, need only Python 3 + numpy + Pillow and `ffmpeg`/`ffprobe` on PATH,
and take one argument: a config JSON you write for the clip. Run them as `python -I <script> <config.json>` (`-I` keeps
stray modules next to downloaded media from being imported; the scripts add their own folder to the path).

Start the config from `assets/example_config.json` (a complete worked example) and read `references/config.md` for
every key. Put `work_dir` in a scratch folder and `out_dir` somewhere the user will find it (next to the clip is good).

| Step | Command | What you do with the output |
|---|---|---|
| 1 | `prep_frames.py` | Look at `contact_*.png`. Note held drawings, blank frames, which frames show straight background lines, and which flat colour could be a marker. Read coordinates off `grid/grid_f_XXXX.png`. |
| 2 | `find_lines.py <cfg> <frame>` then `measure_fov.py` | Pick the two edge families of one flat structure and write their corridors into `plane.frames`. Set `lens.focal_mm` from the result. |
| 3 | `track_blobs.py` then `solve.py` (and `inspect_offsets.py` to set extra-point windows) | Look at `blobs/contact_*.png`, then at **every** `solve/overlay_contact_*.png`. Fix the config until the overlay sits on the drawing. |
| 4 | `export.py` | Writes the After Effects `.jsx`, the Blender `.py` and CSVs into `out_dir`. |
| 5 | `verify_ae.py` and `verify_blender.py` | Both must print PASS. They also save the `.aep`, the `.blend` and check images. |
| 6 | Report | See "What to tell the user". |

### Step 2 - the lens

`find_lines.py` lists every long straight stroke with its angle. Group strokes into two families that are perpendicular
in the scene and lie on one plane; nearby strokes of the same family should have nearly the same angle. Give each
stroke to the config as a corridor `[name, [x1,y1], [x2,y2], half_width]` - approximate endpoints are fine, the ink
inside the corridor is fitted by least squares. `measure_fov.py` then reports a focal length per frame with a
Monte-Carlo spread.

Read it with judgment: if the lines of a family are parallel within a degree or two there is almost no convergence,
which means a long lens (or a flat drawing) and a wide uncertainty - report the range and pick a standard focal length
inside it. Background and character often disagree (flat background, wide-angle character); follow the background,
because the draft geometry has to match the background lines, and mention the disagreement.

### Step 3 - camera and tracks

`solve.py` fits, on each frame listed in `plane.frames`, the corner where the two families meet and both corner edges,
then finds one shared corner shape plus a roll per frame and a fixed-position (nodal) camera that puts the corner
exactly on the drawing. Why nodal with a shared shape rather than an exact per-frame fit: the animator's drawings of
the same structure differ by a few degrees; matching each one exactly would turn drawing noise into violent camera
jumps. The solver prints how far each corner edge is off per frame - quote those numbers.

**Choosing the corner is the judgment call that matters most.** Rough layouts often show two or three candidate
corners per frame (a bold roof edge and a thin inner line, say), and nothing labels which one is "the same corner"
in the next frame. List the candidates per frame, then prefer the chain whose path across the measured frames is
straight and steadily slowing or speeding (`solve.py` prints the corner step between measured frames for exactly
this) and whose edge residuals are smaller. A different reasonable choice can move a frame's corner by a hundred
pixels or more, so tell the user which corner you used and what the alternative was. If the structure also changes
size between measured frames, say so: this solve is rotation-only with a fixed lens (see `references/method.md`).

Frames without the structure get filled in (`before_first`: `constant_pan` or `hold`; `after_last`: `decay` or `hold`)
and are labelled `extrapolated` / `locked` in every output. If the clip has no usable structure at all, leave out the
`plane` section: the camera is locked and you deliver tracks only - say so.

Tracks come from `marker` in the config: one flat-coloured shape per character copy. Its centre, length and angle are
the track; its length sets depth (`depth = focal_px * real_length / length_px`), so afterimage copies of different
size land at different depths automatically. Add more points per copy with `end_names` (both ends of the marker),
`secondary` (other pieces of the same colour at a known offset) and `attached` (other fills such as the body). More
points matter to the user: they pin scale and rotation far better than one point. Be clear about which points are
exact (flat-colour centroids) and which are approximate (the centre of a body fill moves with the pose).

To set the `secondary` / `attached` windows, run `solve.py` once without them and then `inspect_offsets.py`: it
prints every non-marker shape as an offset, size and mass relative to the nearest markers, which is all the windows
need. Only hand-place a point (`manual`) when the subject is really there but the marker is hidden; if the marker
is simply out of frame, leaving that frame without a track is more honest than inventing one.

The overlays are the only proof the solve is right. Check them all, especially the first and last frame of every
track, frames where shapes touch the frame edge, and burst / smear frames where the ordering rules break. For a
smear frame, `single_subject_frames` (track one subject, let the copies start a frame later) is often more honest
than forcing a chain with `chain_override`; `forced_rank_frames` and `debug_links` help when tracks swap or break
there. `references/method.md` explains the assumptions and what to change when they do not fit.

### Step 5 - verification is part of the job

`verify_ae.py` runs the delivered `.jsx` unchanged in a window-less After Effects, renders with AE's own renderer and
measures the rendered bars and dots against the tracked data. `verify_blender.py` does the same in Blender using
`world_to_camera_view` on every keyed object plus a render. Expect means well under 0.2 px. This matters because
rotation conventions and frame timing are easy to get subtly wrong and impossible to see by reading the script.

- After Effects must not be open with the user's work when you run `verify_ae.py`; the script refuses if it is.
- If Blender is not installed, the Blender script is untested: say so plainly and ask before downloading Blender
  (portable zip plus its `.sha256` from `download.blender.org/release/`, checksum verified, in its own folder).
- On an After Effects version this skill has not met, run `ae_calibrate.py` first. `references/apps.md` has the
  measured conventions and the headless quirks.

## What to tell the user

Lead with what they can use, then the limits. Keep it short and concrete:

1. The lens, as a best fit with its spread, and that After Effects (zoom in px) and Blender (mm) carry the same lens.
2. Which frames the camera is measured on, and that the rest is extended or locked. Which corner you tracked, and
   the alternative if there was one.
3. Accuracy from the verification runs (corner px, edge degrees, track px in each app).
4. What each track point is and which ones are approximate; frames where a shape is cut by the frame edge.
5. Anything not tested (for example Blender not installed).
6. Where the files are and how to use them: open the `.aep` / `.blend`, or run the `.jsx` / `.py`. To pin their own
   drawing to a character, parent it to that copy's `TRK2D` null (2D layer) or `TRK3D` null (3D layer). Both projects
   link to the clip by its full path, so moving the clip means relinking the footage.

World scale is a convention (marker length and plane distance are assumed), so only ratios are meaningful - mention
it once so nobody treats the metres as real.

## Files

- `scripts/common.py` - shared math and image helpers
- `scripts/prep_frames.py`, `find_lines.py`, `measure_fov.py`, `track_blobs.py`, `solve.py`, `export.py` - the pipeline
- `scripts/inspect_offsets.py` - prints where every other shape sits relative to each marker (for the extra points)
- `scripts/verify_ae.py`, `verify_blender.py`, `blender_inner.py` - build and prove the deliverables
- `scripts/ae_calibrate.py` - re-measure After Effects' rotation convention
- `references/config.md` - every config key
- `references/method.md` - the math, the assumptions, and how to adapt when a clip does not fit them
- `references/apps.md` - After Effects headless quirks and conventions, Blender notes
- `assets/example_config.json` - the worked example (a 45-frame flying shot: roof corner on 3 frames, red bow marker)
- `evals/` - a test case (a mirrored, recoloured copy of the example clip with pass/fail statements)
