# Config reference

One JSON file per clip. `assets/example_config.json` is a complete, working example - copy it and edit.
All pixel coordinates are in the frame as extracted (x right, y down, origin top-left). Read them off the gridded
frames in `<work_dir>/grid/`. Frame numbers are 1-based.

## Top level

| Key | Meaning |
|---|---|
| `name` | Base name for every output file and the After Effects comp. Default: the video's file name. |
| `video` | Full path to the clip. |
| `work_dir` | Scratch folder (frames, overlays, intermediate JSON). Safe to delete afterwards. |
| `out_dir` | Where the deliverables go. |
| `lens.focal_mm`, `lens.sensor_mm` | The lens you decided on after `measure_fov.py`. Sensor is horizontal, default 36. |
| `ae.px_per_m` | After Effects pixels per world metre. Default 100. |
| `ae_dir` | After Effects "Support Files" folder. Default: newest install under Program Files. |
| `blender_exe` | Path to `blender.exe`. Default: PATH, standard install, or `~/Downloads/blender_portable`. |

## `plane` - the flat structure the camera is solved from (optional)

Leave the whole section out when no frame shows a usable structure; the camera is then locked.

| Key | Meaning |
|---|---|
| `frames` | Object keyed by frame number. Only frames where the corner and both edges are drawn. |
| `frames[n].A`, `.B` | The two edge families. Each stroke: `[name, [x1,y1], [x2,y2], half_width]`. Half-width 8-12 for a thin line, 25-30 for a thick scribbled one. Include every clear stroke of the family; they are all used for the lens. |
| `frames[n].cornerA`, `.cornerB` | Names of the stroke(s) that form the actual tracked corner. Two names = a double line, averaged. |
| `reference_frame` | The cleanest measured frame. The world is built from it. Default: last measured. |
| `distance_m` | Camera-to-corner distance. Pure convention (sets world scale). Default 200. |
| `near_sign` | `"auto"` (default), `-1` or `1`: which side of the plane tilts toward the camera. Auto solves both ways and keeps the one whose perspective agrees better with every stroke; `solve.py` prints both residuals. With a long lens the choice is nearly invisible. |
| `edge_lengths.A`, `.B` | Optional `{"frame": n, "lines": [name1, name2]}`: the intersection of two named strokes marks the far end of that corner edge. `"@cornerA"` / `"@cornerB"` refer to the averaged corner edges. Without it the draft outline gets a default size. |
| `before_first` | Frames before the first measured one: `"constant_pan"` (continue the first measured pan speed, no extra roll) or `"hold"`. |
| `after_last` | Frames after the last measured one: `"decay"` (ease out, ratio taken from the last two measured steps) or `"hold"`. |
| `lock_deg` | Rotation step (degrees per frame) below which the camera is treated as locked. Default 0.02. |
| `grid_step_m` | Draft grid spacing. Default: chosen automatically. |

## `marker` - the flat-coloured shape that is tracked (optional)

| Key | Meaning |
|---|---|
| `color` | `{"expr": "(R>150)&(R-G>70)&(R-B>45)"}` (numpy expression on R, G, B in 0-255; `np` is available) or `{"rgb": [r,g,b], "tol": 60}`. Check `blobs/contact_*.png` after `track_blobs.py`. |
| `min_area`, `min_minor` | Ignore specks (area in px) and hairline streaks (short axis in px). Defaults 150 and 5. |
| `real_length_m` | Real length assigned to the marker. Sets every depth. Convention; default 0.30. |
| `first_track_name`, `other_track_prefix` | Names, e.g. `"HERO"` and `"GHOST"` -> HERO, GHOST_01, ... |
| `end_names` | Names for the two ends of the marker (left end first), e.g. `["ribbonL", "ribbonR"]`. |
| `single_subject_frames` | Frames where only one subject exists: the largest blob is the marker, the rest are secondary pieces. Also the honest choice for a smear frame of one character: track the one subject and let the copies start on the next frame. |
| `far_end` | Where the far (small) end of an afterimage chain sits on screen: `"bottom"` (default), `"top"`, `"left"`, `"right"`. Main markers must grow from that end toward the camera; anything smaller than the copy behind it is treated as a secondary piece. |
| `forced_rank_until` | Up to this frame, copies are linked purely by near-to-far order (use through bursts where sizes jump). After it, linking is an order-preserving match on position and size. |
| `forced_rank_frames` | A list of individual frames to link purely by near-to-far order (finer than `forced_rank_until`). |
| `chain_override` | `{"frame": [[x,y], ...]}`: the main markers of an odd frame, listed near to far by approximate centre. The order you list them in is the order the next frame is matched against. Use for smear / burst frames. |
| `manual` | `[{"frame", "u", "v", "major", "ang"}]`: a hand-placed observation where the subject is there but the marker is hidden. Flagged in every output. Do not use it when the marker is simply out of frame. |
| `gap_cost` | Cost of starting / ending a track in the matcher. Default 1.5. Lower it if tracks swap, raise it if they fragment. |
| `debug_links` | `true` prints, per frame, which copy was linked to which and the cost of each link. Use it instead of doing the arithmetic by hand. |
| `secondary` | `[{"name", "dx": [min,max], "dy": [min,max], "expect": [dx,dy]}]`: leftover marker-coloured blobs whose offset from a main marker, in units of that marker's length, falls in the window. With `expect` the candidate nearest that offset wins; without it the largest does. |
| `attached` | `[{"name", "mask", "solid", "min_area", "expect": [dx,dy], "max_dist", "max_size", "min_mass"}]`: another class of fill (e.g. the body). Each component goes to the copy whose expected spot (`centre + expect * length`) is nearest; the point is the area-weighted centre of what was assigned. Left out on frames where the fill runs off the frame. |

`attached` thresholds, all relative to the owning marker's length `L`:

- `max_dist` - how far a component's centre may be from the expected spot, in units of `L`.
- `max_size` - component length / `L`. Set it between the size of one body and the size of two merged bodies, so
  overlapping copies give no point rather than a wrong one.
- `min_mass` - total assigned area / `L^2`. Below it the fill is too fragmentary to have a meaningful centre.

Tracks are named in order of their first frame, then by creation order: the first is `first_track_name`, the rest
`<other_track_prefix>_01`, `_02`, ...

To find the windows, run `solve.py` once without `secondary` / `attached`, then `inspect_offsets.py <config> [frames]`.
It prints every non-marker shape with `dx`, `dy`, `size` and `mass` relative to the two nearest markers; bracket the
values of the shapes you want. A dark-fill mask also catches thick scribbled background strokes; they show up boxed
in `blobs/contact_*.png` but `max_dist` keeps them from being attached.
