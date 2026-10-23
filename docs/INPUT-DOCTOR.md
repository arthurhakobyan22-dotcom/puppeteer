# Input doctor (Foundation phase, Agent 3)

The input doctor is the first stage of every run. It reads the upload, writes the 24 fps working copy
(`original.mp4`, exactly as `probe` / `pipeline.normalize` always did), then checks the working copy and fixes
what is safe to fix. It never blocks: a bad clip gets fixes and advice, and only an unreadable upload or a clip
over 30 s stops the run (the same two errors `pipeline.normalize` raised before, with a plain fix).

Tool: `doctor` in `stages/input_doctor.py` (registered after `probe`, which stays available). It is the default
`input_doctor` tool of the four built-in presets and the three legacy modes (`stages.chain_for_mode`); legacy runs
made before the rack keep `probe` in their reconstructed chain. Free, local, no network.

## Checks (one plain sentence each, `report.data.checks` and `input-doctor.json`)

| check | how | sentence |
|---|---|---|
| resolution | PyAV probe of the upload | `Resolution: 3310×1900; working copy 960×550.` |
| frame rate | PyAV probe | `Frame rate: 50.0 fps, normalised to 24 fps for the working copy.` |
| length | PyAV probe + the working copy's frame count | `Length: 8.1 s (195 frames at 24 fps).` |
| audio | PyAV probe (audio stream present) | `Audio: present (…)` / `Audio: none.` |
| brightness | mean luma (Rec. 601) of the picture on 12 sampled frames, leaving out pure-black pixels (luma < 0.02: letterbox bars and padding), plus the share of sampled frames whose mean is below 0.06 | `Brightness: mean luma 0.17 of the picture on 12 sampled frames; fine.` |
| shake | `cv2.phaseCorrelate` (Hanning window) between each sampled frame and the next one, on a 480 px grayscale copy; the mean shift as a fraction of the height | `Shake: average global motion 5.0 px per frame; steady.` |
| face size | MediaPipe face landmarker through `face_probe.py` in `.venv-face` on the sampled frames; when the full frame shows no face, nine overlapping half-frame tiles are searched at 2x (`zoomed`); the median face height as a fraction of the frame height | `Face: about 64% of the frame height on 10 of 12 sampled frames; fine.` |

**Why MediaPipe and not OpenCV's Haar cascade.** The brief suggested `cv2.data.haarcascades +
'haarcascade_frontalface_default.xml'`. The `.venv` has `opencv-python-headless` 5.0.0, which dropped
`cv2.CascadeClassifier` and ships no cascade XML (the `cv2/data` folder is empty); no cascade file exists anywhere
on this machine and fetching one would be a network call. `.venv-face` has the MediaPipe face landmarker the face
stage already tracks with (`models/face_landmarker.task`, downloaded once by `setup-face-mesh.sh`), so the doctor
measures "can the tracker find this face" with the tracker itself. `detect_faces()` falls back to the Haar cascade
when an OpenCV build has it, and returns `None` (advice: "set up the face mesh once") when neither exists.

## Thresholds (tool params, part of the cache key)

| param | default | why this value |
|---|---|---|
| `dark_luma` | 0.12 | The fixture (`runs/85e5…`, a dark-background but correctly exposed interview) measures 0.17 and must not be brightened; a copy darkened to 25 % measures 0.04. 0.12 sits between them. |
| `target_luma` | 0.35 | A normally exposed talking head sits around 0.3–0.45. |
| `max_gain` | 1.8 | The gamma exponent is capped here so the fix stays mild and never turns noise into a grey haze; the brief's bound. |
| `small_face` | 0.12 | Below about an eighth of the frame height the landmarker's full-frame detection starts missing (the fixture face shrunk to 9 % is only found when zoomed in). |
| `shake` | 0.02 | A static camera with a moving subject already measures 0.009 (5 px of 550) because phase correlation picks up subject motion; 2 % leaves room for that and still catches unsteady footage (the test clip jitters by up to 16 px, about 3 %). |
| `fix_brightness`, `fix_face` | true | Switch a fix off and the doctor gives the matching advice instead. |

Changing a threshold changes the stage's cache key (params are hashed), so a re-run from this stage re-checks.

## Fixes (safe, working copy only, each with a before/after note in `report.data.fixes`)

- **fps normalise**: always, by `pipeline.normalize` (24 fps, up to 960 px). Recorded as a fix when the source
  is not 24 fps: `Frame rate: 50.0 fps → 24 fps (working copy only; the original upload is untouched).`
- **brighten** (when mean luma < `dark_luma`): `original.mp4` is rewritten through a gamma curve
  `out = 255·(in/255)^(1/γ)` with `γ = min(max_gain, ln(mean)/ln(target_luma))`, re-measured afterwards:
  `Brightness: mean luma 0.04 → 0.17 (gamma 1.80, capped at 1.8); the original upload is untouched.` If it is still
  dark after the bounded fix, that becomes advice. When the clip is not dark, `original.mp4` is byte-identical to
  what `probe` writes (tested), so the artifact regression on existing runs holds.
- **zoomed tracking copy** (when the face is smaller than `small_face`): `tracking-source.mp4` is written from
  `original.mp4`, a crop around the union of the detected face boxes (same aspect ratio, the face about 30 % of
  the crop height) upscaled 2x (Lanczos, long side ≤ 1920), plus `tracking-source.json` (`crop {x0, y0, w, h}` in
  original pixels, `scale`, `original {width, height}`, `face_fraction`). The face stage tracks on it when both files
  exist (`mesh_worker.py`), maps every landmark back with `mesh_tracking.map_landmarks` and draws on `original.mp4`
  as before; `face-landmarks.json`, `face-tracking.json` (`tracking_source` says which file was used), the mesh
  video and every other artifact stay in the original frame size. Note:
  `Face size: 9% → about 31% of the frame in tracking-source.mp4 (a zoomed copy used for face tracking only …)`.
  `tracking-source.mp4` / `.json` are inputs of the face stage's cache key, so a run with the zoomed copy gets a
  different face key from one without.

## Advice (never blocks)

Short side under 540 px (under 300 px also warns), very short clip, no audio, dark after the bounded brighten,
most frames near black, unsteady camera, no face found, small face ("move closer or crop before uploading"), face
found on fewer than half of the sampled frames, face check unavailable (face mesh not set up).

## Where it shows

- `runs/<id>/input-doctor.json`: `{checks, warnings, advice, fixes, measurements}`.
- `stages/input_doctor/report.json`: `health` ("… → 960×550 at 24 fps, 195 frames; fixes: 24 fps, brightened. 1
  piece of advice."), `warnings`, `data.checks` / `data.fixes` / `data.advice` / `data.measurements`, and the
  `data.source` / `data.normalized` blocks the manifest and the legacy code read.
- The Studio card for "Input check" lists Checks, Fixes applied (the before/after notes) and Advice under the
  health line (`static/stagecard.js` `renderChecklists`, used by any stage that reports those lists).

## Tests

`tests/test_input_doctor.py`: a dark, small-face, shaky clip built from the first 24 frames of the fixture run
(darkened to 25 %, shrunk to a seventh on a black canvas with jitter): dark detected and brightened with the note,
small face found only when zoomed in, advice given, `tracking-source.mp4` written with 24 frames, shake warned,
state done; a bright big-face clip gets no fix and its `original.mp4` equals `probe`'s; an unreadable upload only
warns and leaves the real error to `pipeline.normalize`; `doctor` is the default of every preset and mode with
`probe` still registered first; thresholds change the cache key; the landmark mapping. The face check runs the real
MediaPipe worker when `.venv-face` exists and is injected otherwise.
