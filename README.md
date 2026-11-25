# autotrack-skill

A [Claude Code](https://claude.com/claude-code) skill that takes a hand-drawn or 2D-animation reference clip and
gives you its camera and character track points as a working **After Effects project** and **Blender scene**, then
proves the result by rendering in both programs.

The skill inside is named `animation-camera-track`.

## What it is for

You have a rough-animation, anime or storyboard clip and want to draw or place your own character over the same
camera move. Ask Claude things like:

- "can you get the camera from this clip? I want the same focal length in After Effects and Blender"
- "track this shot and give me tracking points on the character"

Claude then works through the clip and hands back:

- the lens the drawn perspective implies, with its spread
- a camera (pan / tilt / roll) for After Effects and Blender
- track points on every character copy: a marker centre with scale and rotation, plus extra points
- draft objects so you can see it line up, and CSVs of all the numbers
- accuracy figures measured from After Effects' and Blender's own renders

## What it cannot do

A drawn clip has no physical camera and no rigid 3D scene, so this is not a normal matchmove.

- The camera is only **measured** on frames that show a flat structure with a right-angled corner (a roof, floor,
  wall). Other frames are interpolated, extended or locked, and are labelled that way in every output.
- The lens is a best fit with a range, not an exact value.
- Track points come from flat-coloured shapes (a bow, a scarf, a body fill). A clip with no flat colour needs
  hand-placed points.
- It is rotation-only with a fixed lens. A zoom or dolly in the drawing is reported, not solved.
- It is not for live-action footage. Use Blender's tracker or COLMAP for that.

## Install

Clone into your Claude Code skills folder, keeping the folder name `animation-camera-track`:

```powershell
git clone https://github.com/mussaa3d/autotrack-skill "$env:USERPROFILE\.claude\skills\animation-camera-track"
```

```bash
git clone https://github.com/mussaa3d/autotrack-skill ~/.claude/skills/animation-camera-track
```

Start a new Claude Code session and the skill is available. You can also call it with `/animation-camera-track`.

## Requirements

- Python 3 with `numpy` and `Pillow`
- `ffmpeg` and `ffprobe` on PATH
- After Effects, for the After Effects deliverable and its verification (developed against AE 23.2)
- Blender, for the Blender deliverable and its verification (developed against Blender 5.3)

Developed and tested on Windows. The After Effects automation (`verify_ae.py`, `ae_calibrate.py`) uses Windows
paths and tools; the other scripts are plain Python.

## How it works

Each script takes one config JSON that Claude writes for the clip (`assets/example_config.json` is a worked example).

| Step | Script | What it does |
|---|---|---|
| 1 | `prep_frames.py` | Extracts frames, finds held drawings and blank frames, makes gridded frames and contact sheets |
| 2 | `find_lines.py`, `measure_fov.py` | Finds straight background strokes and estimates the lens from their vanishing points |
| 3 | `track_blobs.py`, `solve.py`, `inspect_offsets.py` | Segments flat-coloured shapes, solves the camera from one plane corner, links character copies through time, lifts everything to 3D |
| 4 | `export.py` | Writes the After Effects `.jsx`, the Blender `.py` and CSVs |
| 5 | `verify_ae.py`, `verify_blender.py` | Runs the deliverables in each program and measures the rendered result against the tracked data |

`SKILL.md` is what Claude reads first. `references/` holds the config reference, the method and its assumptions,
and notes on scripting After Effects and Blender.

## Status

- Built on one 45-frame flying shot, then tested by giving a fresh Claude only this skill and a mirrored,
  recoloured copy of that shot. It reproduced the known solve to under 1 px and passed all 13 checks in
  `evals/mirrored-blue-bow-shot/`.
- That test clip is still the same shot, so the method is **not yet proven on unrelated footage**. Treat the first
  run on a new kind of shot as a test and look at every overlay the solver writes.
- The test clip itself is not included in this repository.

## Licence

MIT. See [LICENSE](LICENSE).
