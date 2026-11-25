# Method, assumptions, and how to adapt

## Contents
1. Lens from vanishing points
2. Camera from one plane corner
3. Filling the unmeasured frames
4. Tracks, depth and extra points
5. When the clip does not fit
6. Things that went wrong before

## 1. Lens from vanishing points

Two families of strokes, A and B, are assumed perpendicular in the scene and coplanar. Each family's strokes meet at
a vanishing point; with the principal point at the frame centre `c` and square pixels,
`f^2 = -(vpA - c) . (vpB - c)`. `measure_fov.py` perturbs every stroke by 1 degree (about what hand-drawn lines
wobble) 4000 times and reports the percentiles of `f`.

Interpretation:
- "valid %" is the share of perturbations that gave a real focal length. Low values mean the lines carry almost no
  convergence.
- Nearly parallel families -> thousands of pixels of focal length -> long lens. That is a real finding ("the
  background is drawn flat / telephoto"), not a failure.
- A plane seen exactly face-on has no convergence for any lens. If the corner looks like a clean 90 degrees on
  screen, the lens cannot be measured from that plane at all; say so and choose.
- Curvilinear ("fisheye") drawn perspective breaks the model. Use short, central strokes or give up on a number.

## 2. Camera from one plane corner

On each measured frame the corner `p_n` and the on-screen angles of its two edges are fitted. A right angle seen at
on-screen angle `D` under near-orthographic projection has a one-parameter family of plane orientations; the solver
takes the minimum-tilt member (both edges equally foreshortened, `k^2 = 1 / (1 + |cos D|)`), built once from the
shape shared by all measured frames (least squares: one pair of edge angles plus a roll per frame).

The camera centre is fixed at `distance_m` along the reference frame's corner ray. Each measured frame then gets a
rotation (3 unknowns) by Gauss-Newton on: corner position (weight 0.5 px) and the two corner-edge angles. The corner
is matched to ~0.01 px; the two edges split whatever the drawing's shape disagrees by.

Why not match each frame exactly: it needs the camera to orbit the plane by 10-20 degrees from one frame to the next
purely because two rough drawings differ. The result reprojects perfectly and is useless as a camera move. A shared
shape with honest residuals is what a matchmove artist would hand over.

The plane tilt sign (`near_sign`) and `distance_m` are conventions. With a flat draft plane nothing visible depends
on them; they only matter if the user adds geometry with height. By default the solver tries both signs and keeps
the one with the lower all-stroke residual.

### Which corner is "the same corner"?

This is the biggest judgment call and the scripts cannot make it. A rough layout can draw the same building as a
double line with a node at each end on one frame and as a bold scribbled edge plus a thin inner line on the next.
Work through it like this:

1. On each candidate frame, list every corner that has two clear edges (use `find_lines.py`).
2. Build the possible chains across frames and run `solve.py` for each. Compare the printed corner steps: one real
   corner under a pan moves in a nearly straight line with steadily changing speed (for example 410 px then 200 px
   in almost the same direction). A chain that zig-zags or reverses is two different corners.
3. Compare the corner-edge residuals and how the draft outline sits on the drawing in the overlays.
4. Report the choice and the runner-up. In one tested clip the two candidates were about 170 px apart on the middle
   frame.

If the structure also changes size between measured frames (measure the same edge on both), the drawing implies a
zoom or pull-back that this rotation-only solve does not carry. Say so in the report; section 5 has the options.

## 3. Filling the unmeasured frames

- Between measured frames: rotation interpolated along the shortest arc.
- Before the first: `constant_pan` repeats the first measured step without its roll component (no evidence for roll);
  `hold` freezes.
- After the last: `decay` multiplies the last step by the ratio of the last two measured pan steps (clamped to
  0.3-0.7) each frame until it is under `lock_deg`, then locks. This reproduces an eased whip pan.
- Held drawings copy their source frame's camera, because the whole picture is held.

These frames are guesses shaped by the measured ones. Label them in the report and never quote accuracy for them.

## 4. Tracks, depth and extra points

`track_blobs.py` labels connected regions of the marker colour (row-run union-find, fast in pure Python) and stores
centre, principal axis, extents and bounding box. `solve.py` then:

1. Picks the main marker of each copy. In an afterimage chain the copies shrink toward `far_end`; walking from the far
   end, a blob is a main marker only if it is longer than the one before. Shapes cut by the frame edge are kept only
   if they continue a track from the previous frame, and their length is frozen at the last full value.
2. Links copies across frames in near-to-far order with an order-preserving alignment. The cost of linking an old
   observation to a new blob is `distance / mean(length_old, length_new) + |ln(length_new / length_old)|` (the size
   term is dropped when either shape is cut by the frame edge); starting or ending a track costs `gap_cost`. So a
   link survives only if it is cheaper than two gaps. Order-preserving matters: nearest-neighbour matching swaps
   identities when a whole chain shifts. `debug_links` prints every link and its cost; `forced_rank_until` /
   `forced_rank_frames` bypass the matcher and link by order where sizes jump (bursts).
3. Lifts each observation to 3D: `depth = F * real_length / length_px`, position = ray through the pixel at that
   depth, rotated into the world with that frame's camera. Extra points of a copy use the copy's depth.

Marker length is the only depth cue, so depth follows how big the artist drew the marker. That is exactly right for
reprojection (every point lands on its pixel) and only approximately meaningful as a 3D path.

A second point per copy is worth the trouble: one small marker gives a noisy scale and rotation; marker + body centre
give a long baseline.

## 5. When the clip does not fit

- **No rigid structure anywhere**: drop `plane`. Deliver tracks, a locked camera, and say the camera could not be
  measured. Offer the 2D tracks as the main result.
- **Structure visible on one frame only**: one measured frame; use `hold` on both sides.
- **Corner off-screen but both families visible**: the solver needs a point. Use the intersection of two clear
  strokes as the "corner" even if it is not a real corner, by naming those strokes in `cornerA` / `cornerB`.
- **Obvious zoom or dolly** (the structure changes size between measured frames): this solver has no zoom. Either
  report it as a limitation or add a per-frame focal scale: fit the size ratio of a known edge between frames and
  scale `focal_px` per frame in `solve.py` and both exporters.
- **No flat-coloured shape to track**: use `manual` observations placed by eye from the gridded frames, and say they
  are hand-placed (expect several pixels of error).
- **Several different characters**: run the marker tracker per colour and merge, or give each its own config.
- **Live action or 3D-rendered footage**: do not use this skill; use a real matchmove.

## 6. Things that went wrong before

- Pixel centres: blob and stroke coordinates are stored at `index + 0.5` so that `(W/2, H/2)` is the true optical
  centre. Forgetting this is a constant half-pixel error in both apps.
- Thick scribbled strokes and solid fills are removed by `find_lines.py`'s fill filter; fit them with a wide corridor
  in the config instead.
- A "secondary" blob can belong to the next copy, not the nearest marker (the far-side bow of the copy behind sat next
  to the front copy's marker). Decide ownership by offset in units of the candidate owner's length, not by distance.
- Body fills of overlapping copies merge into one component; `max_size` rejects those, so the point is simply absent
  on such frames rather than wrong.
- Centres of shapes cut by the frame edge are biased; they are flagged `partial` and excluded from accuracy checks.
- The "solid fill" filter once padded the image with zeros, which shaved 3 px off every fill at the frame border, so
  no body fill ever counted as cut and off-frame bodies got a point. It now pads with the edge value. If you write
  another neighbourhood filter, pad the same way and test a shape that touches the border.
- Draft bars overlap in afterimage chains; the visible part of a covered bar has a biased centre and used to show up
  as a "1 px worst case". The verify scripts now skip bars that a nearer bar overlaps and say how many they skipped.
- An independent test (a fresh agent on a mirrored, recoloured copy of the example clip) matched the reference solve
  to under 1 px. That clip is still the same shot, so it does not prove the method on unrelated footage; treat the
  first run on a new kind of shot as a test and read the overlays closely.
