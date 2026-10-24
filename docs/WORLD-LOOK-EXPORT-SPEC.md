# World, Look and Export: the shared contract (stage 3)

Written by the lead before any agent starts. Agents 1–4 build on it; a fresh reviewer checks the Definition of Done
at the end. Read `AGENTS.md`, `docs/STAGES.md`, `docs/UI.md`, `docs/TIMELINE-SPEC.md` (§0 non-negotiables, §2 edit
layer) first. When you change a contract below, update this file in the same commit and say so in your notes section.

## 0. Non-negotiables (all agents)

- **Prep studio first, generator second.** Generation is one possible exit. Everything you build for prep, edit and
  export must work with no `FAL_KEY` / `ENHANCOR_API_KEY` (verify by starting your server with `FAL_KEY= ENHANCOR_API_KEY=`
  set to empty in the environment; `config.setting` then sees them as unset. Never edit the user's `.env`).
- **Remove nothing.** Every route, form field, CLI command, file name, module function, preset, Quick / Studio / Lab /
  Runs, the timeline editor, words, import and download keep working. New things go next to them. The regression suite
  and every existing test stay green: `.venv/bin/python -m pytest -q` (255 passed at the start of this stage).
- **Never overwrite tool outputs; never write into a parent run.** A changed Background is a new composite run (a
  branch). Slots, set plates and exports are *not* tool outputs and may be written into the run folder (like
  `status.json`, `char1-reference.png`), but never into another run.
- **Forgiving by default.** Every error the UI shows is `{message, fix}` in plain words (`fail()` in `app.py`,
  `showError()` / `notice()` in the UI). No raw exceptions on screen, no console errors. Nothing paid runs without the
  estimate on the button and `confirm_cost=true` from that click (402 via `cost_gate()` otherwise). When a provider
  cannot do what was asked, say so in one plain sentence and name the nearest option that works.
- **Offline + ports.** Verify with `PUPPETEER_OFFLINE=1 ENHANCOR_WEBHOOK_URL=http://localhost/dummy PORT=<port> .venv/bin/python launch.py`
  (the dummy webhook stops launch.py from starting a cloudflared tunnel that would delete `.runtime-webhook.json`,
  which the user's own instance uses). Ports: Agent 1 → 8781, Agent 2 → 8782, Agent 3 → 8783, Agent 4 → 8784,
  reviewer → 8785. **Never touch 8770/8771** (the user's instances), never `pkill -f launch.py` / `pkill -f uvicorn`;
  stop only the PID you started.
- **Fixtures.** `runs/` folders are real paid fixtures; never write into them. Test on a hard-link copy:
  `cp -al runs/0be4cf2cadd945008a9c9131b6c75f12 runs/<new 32 hex>`, then replace (copy, not link) `status.json`,
  `run.json`, `mask-review.json` if present, and remove `stages/` reports' hard links the same way (copy the folder).
  `0be4…` is Advanced + mesh with `run.json` (depth_mesh, 195 frames at 24 fps, 960×550, SAM clean-masks, face
  landmarks, `words.json`, `mouth-guidance.json`). `85e5dbe64df1464fa63825319ebfa104` is the legacy mesh fixture
  without `run.json`. List the ids you create in your notes section; unit tests use `tmp_path` and synthetic clips.
- **Shared files.** `app.py`, `static/index.html`, `static/draft.js`, `static/stagecard.js`, `static/app.css`,
  `stages/generate.py`, `providers/*.py` are edited by more than one agent. Make targeted edits (never rewrite a shared
  file wholesale), add new routes in your own clearly commented block, and re-read a shared file before editing it.
  Put most of your work in your own new files (listed in §1).
- **Commits.** Work on branch `world-look-export`. At the end commit your work in one or a few logical commits
  (message body ends with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`). Do not push; the lead pushes.
  Never commit `runs/`, `.venv*`, `models/`, `.env`.
- **Style.** Match the surrounding code: dense one-line Python in `app.py` / `stages/`, plain ES modules with small
  helpers in `static/`, no build step, no framework, no new CDN dependencies, no new pip dependencies without saying
  so (the Anthropic call uses `requests`; `anthropic` is not installed). Usable at 380 px.

## 1. Where things live

| piece | file(s) | owner |
|---|---|---|
| Background on the composite stage (params, renderer, set-plate fit) | `stages/composite.py`, `pipeline.py` (additive helper), `stages/plates.py` (new: asset store + fit) | Agent 1 |
| Set / Look / Light slots, `slots.json`, run.json mirror, task switching | `stages/slots.py` (new), `stages/prompt.py` (params), `stages/generate.py` (`task` param), routes in `app.py` | Agent 1 |
| Slot UI: Background on the composite card, Set / Look panel in the draft step | `static/stagecard.js`, `static/slots.js` (new), `static/draft.js` (mount point only), `tpl-slots` in `index.html`, CSS | Agent 1 |
| Prompt builder with fences, timed beats, preview with refs side by side | `stages/promptkit.py` (new), `providers/base.py` (additive), `providers/fal.py` + `enhancor.py` (extra refs), `static/promptkit.js` (new), `static/draft.js` | Agent 2 |
| Claude vision fill (SET / LIGHT) | `stages/vision.py` (new), `POST /jobs/{id}/describe` in `app.py`, button in `static/promptkit.js` | Agent 2 |
| Generator capabilities + Wan/VACE adapter | `providers/capabilities.py` (new), `providers/wan.py` (new, if an endpoint fits), `providers/__init__.py`, `stages/generate.py`, `stages/costs.py`, `static/generator.js` (new), `docs/GENERATORS.md` (new) | Agent 3 |
| Export kit, target presets, README, start.command | `stages/export.py` (new), `stages/export_presets.py` (new), routes in `app.py`, `static/export.js` (new), `tpl-export` in `index.html`, `docs/EXPORT.md` (new), `start.command` | Agent 4 |

Each agent appends a "§W1 notes" … "§W4 notes" section to this file: what was built, endpoints, verification run
ids, anything the next agent must know. Update `docs/UI.md`, `docs/STAGES.md`, `docs/PROVIDERS.md` where your work
changes what they describe.

## 2. Background (Agent 1)

A `background` param on the composite stage's `depth_cutout` tool (the only tool that produces a depth person;
`original` has none, and the UI says so in one line when the composite tool is `original`):

| `background` | result behind / around the depth person |
|---|---|
| `original` (default) | today's behaviour: depth person over the real frames (byte-identical output for the default params) |
| `full_depth` | the whole frame is the depth video (`depth.mp4` as is) |
| `plain` | a flat colour (`plain_color`: `black` default, or `gray`) |
| `set_image` | a set plate (`set_image`: an asset name, see §2.1) fitted to the frame, person over it |

Params on `depth_cutout`: `background` (choice), `plain_color` (choice: `black` | `gray`, default `black`),
`set_image` (string, default `''`), `set_fit` (string JSON `{"x":0,"y":0,"scale":1}` in frame fractions / scale
factor around the fitted plate, default `{}`). Default params must produce exactly today's files, so existing
cache keys and the regression suite stay as they are; add the new keys with defaults such that
`normalize_params({})` of a legacy chain hashes the same (keep the param order and defaults stable).

The face stage draws on whatever composite is chosen (it already reads `depth-composite-silent.mp4`), so the mesh
and hands land on top of every background. The composite tool also keeps writing `mask.mp4`, `composite.mp4`
(with audio) and `depth-composite-silent.mp4`.

Implementation: add an optional `background=` argument to a new helper next to `pipeline.composite` (do not change
`pipeline.composite`'s signature or behaviour; the regression suite patches it by name) — e.g.
`pipeline.composite_bg(original, depth, seg, directory, audio_source=None, background='original', plate=None, plain=(0,0,0), fit=None)`
that `DepthCutout.run` calls when `background != 'original'`, and `pipeline.composite` otherwise. The plate is
auto-fitted: cover the frame (scale to fill, centred), then `set_fit` moves/scales it; export the fit maths in a tiny
pure function so the UI (`static/slots.js`) can draw the same preview on a canvas.

### 2.1 Assets (set plates, style images)

`stages/plates.py`: `store_asset(upload_bytes, filename, runs_root) -> name` saves to `runs/_assets/<sha256[:16]>.<ext>`
(png / jpg / jpeg / webp, ≤30 MB, decoded with PIL to be sure it is an image) and returns `name` (`<sha>.<ext>`).
`asset_path(name, runs_root)`, `asset_info(name)` (width, height). Routes: `POST /jobs/{id}/assets` (multipart
`file`, `kind` = `set` | `look`) → `{name, width, height, url}`; `GET /assets/{name}` serves it (static mount of
`runs/_assets`). When a composite run uses a plate, `DepthCutout.run` copies it into the child run as
`set-plate.<ext>` (after `fresh()`) so the run folder is self-contained; `set-plate.*` is listed in the tool's outputs.

### 2.2 Choosing a background in the UI

On the composite stage card (Studio): a "Background" row with the four choices, the plain colour, a set-plate
upload/picker with a small position/scale control (drag to move, slider for scale, drawn on a canvas over the first
frame of `original.mp4` with the mask preview if available), and the normal "Re-run from here" (free: composite
and face are local) which creates the branch. In Quick, the review panel shows the current background in one
chip ("Background · Set image") that deep-links to the Studio card.

## 3. Set, Look and Light slots (Agent 1 stores, Agent 2 reads)

Slots describe the *generation*; they live in `runs/<id>/slots.json` and are mirrored into `run.json` as `slots`
(and into `chain.prompt.params` as flat keys so they travel with branches: `set_mode`, `set_image`, `set_prompt`,
`look_mode`, `look_image`, `look_prompt`, `light`). Writing a slot does **not** create a branch (nothing re-runs);
`fresh()` the two files first so a hard-linked copy never writes through.

```json
{"version":1,
 "set":{"mode":"original|original_depth|set_ref|prompt|true_swap","image":"<asset name>|null","prompt":"","fit":{}},
 "look":{"mode":"follow|style_ref|prompt","image":"<asset name>|null","prompt":""},
 "light":"",
 "generator":{"name":"fal|enhancor|<agent 3 adds>","task":"auto|reference|editing","resolution":null},
 "updated":"<iso>"}
```

Meaning of `set.mode`: `original` keep the room (prepared clip as is); `original_depth` the room geometry is kept
as depth and the look regenerated (= Background `full_depth` composite; the prompt says the depth defines layout only);
`set_ref` a set image is attached as a reference (@ImageN, set fence); `prompt` the set is described in words
(typed, or filled by Claude vision); `true_swap` = Background `set_image` (the plate is composited behind the person
and the prompt says the plate is the real set). `true_swap` and `original_depth` need a composite branch: the UI offers
"Apply as background (new run)" which calls `/branch` at composite with the right `background`; the slot is then saved
on the child.

**Automatic task switching.** `generator.task` is derived whenever `set.mode` changes: `original` → `editing`,
anything else → `reference`. The user may override it; the derived value is re-applied when the set mode changes
again. `stages/slots.py: task_for(slots) -> 'editing'|'reference'`. `stages/generate.py` tools gain a `task`
param (choice `auto|reference|editing`, default `auto` = follow `FAL_TASK` as today) and `providers/fal.py`
`_task()` takes the explicit task from the request when given. At submit, `seedance_bridge.submit(..., task=None)`
passes it through; `generation.json` gets `task`, and `run.json.chain.generate.params.task` is set. The draft panel
shows "Task · reference (set changed)" / "Task · editing (original set)". A provider that does not support the
derived task (Agent 3's capabilities say which) shows a plain sentence and the nearest option.

Endpoints: `GET /jobs/{id}/slots` (defaults when the file is missing), `PUT /jobs/{id}/slots` (JSON or form;
partial updates merge; validates modes and asset names; returns the whole slots object plus `task`).

## 4. Prompt builder with fences (Agent 2)

`stages/promptkit.py`: `assemble(folder, slots, refs, words=None) -> {'text', 'refs', 'beats', 'sections', 'warnings'}`

- `refs` are attached **in this order** and numbered in that order: `char1` (image → `@Image1`; identity video →
  `@Video2`), `char2` (`@Image2` when char1 is an image, else `@Image1`), set image (`set.mode == 'set_ref'`), look
  image (`look.mode == 'style_ref'`). `@Video1` is always the prepared clip. The returned `refs` list is
  `[{'n':1,'token':'@Image1','slot':'char1','file':'char1-reference.png','job':'identity','fence':'…'}, …]`.
- **One job, one fence, per ref**, written automatically and restated at every mention:
  - character: `@ImageN defines the character's identity only (face, hair, outfit, proportions); do not copy its pose, expression, props, background or lighting.`
  - set: `@ImageN defines the set only (walls, floor, furniture, depth of the room); do not use its people or lighting.`
  - look: `@ImageN defines the rendering style only (palette, grain, contrast, brushwork); do not copy its content, people or layout.`
- Sections in order, each on its own line(s), each present only when its slot says so: CHARACTER (fences), SET
  (`set.prompt` or the depth / plate sentence for `original_depth` / `true_swap`), LOOK (`look.prompt` or the style
  fence), DIALOGUE BEATS (`Dialogue beats` block exactly as `GET /jobs/{id}/words/beats` renders it, from pending
  word edits first, else `words.json`), LIGHT (`light`), then **one** closing constraints line: `Keep the camera,
  crop, timing and every word of the embedded dialogue; replace the whole identity including hair; remove any mesh
  lines or depth colours from the output.` (mesh / depth clauses only when the run has them).
- The provider's `build_prompt` keeps its old behaviour for old callers. New: `build_prompt(prompt, folder, refs)`
  accepts `refs` with optional `set` / `look` paths; the sentence it appends mentions each extra ref with its slot
  (`@Image3 is the set reference only.`) and the adapters upload them in the same order (`image_urls` / `images`),
  so numbering matches attachment order. Save the ref list into `generation.json` as `refs`.
- `POST /jobs/{id}/prompt/assemble` `{slots?}` → the assembled result (free, no network). The draft panel shows the
  final prompt (editable textarea, what is in the box is what is sent) next to a strip of the attached refs with
  their number, slot and one-line job, before the paid button. `seedance-request.json` stays the exact payload.

### 4.1 Claude vision fill (Agent 2)

`stages/vision.py: describe_frame(folder, t=None, runs_root=None) -> {'set': str, 'light': str, 'model', 'usd'}`:
one frame (the middle frame, or `t` seconds) of `original.mp4`; when `clean-masks/` (or `raw-masks/`) exists the
person's mask region is filled with neutral gray before encoding, and the instruction says to describe only the set
(architecture, furniture, materials, depth) and the light (direction, quality, colour temperature, practicals), never
people, clothing or faces, in two short lines labelled `SET:` and `LIGHT:`. Call the Anthropic Messages API with
`requests` (no new dependency), model `claude-sonnet-5-5`, key from `config.setting('ANTHROPIC_API_KEY')`. Load the
`claude-api` skill before writing this code and record the call in `calls.jsonl` with its estimated cost (a cent or
two; put the price in `stages/costs.py` as `claude_vision` with the source). It is paid, so the route
`POST /jobs/{id}/describe` `{t?, confirm_cost?}` goes through `cost_gate()`. Missing key → 400
`{message: 'No Anthropic key yet.', fix: 'Add a line ANTHROPIC_API_KEY=sk-ant-… to the .env file in the project folder (console.anthropic.com → API keys), then restart the app.'}`;
`PUPPETEER_OFFLINE=1` → the usual offline refusal. The button "Describe set & light from this frame · $0.01" fills
the SET and LIGHT fields of the slots (the user edits them before submit) and writes nothing else.

## 5. Generator slot and capabilities (Agent 3)

Every generator declares capabilities (`providers/capabilities.py` defines the keys; the two existing adapters
fill them in; `GET /providers` returns them): `resolutions` (list, e.g. `['480p','720p','1080p']`), `draft`
(bool), `finalize` (existing), `max_seconds`, `audio` (bool: generates audio), `tasks` (list of supported task
names, e.g. `['auto','reference','editing']`), `ref_images_max` (int), `slots` (`{'set_ref': bool, 'look_ref':
bool, 'char2': bool, 'identity_video': bool}`), `control` (`'video'` for Seedance edit, `'pose'` for a pose-native
model), `fps`. The UI (`static/generator.js`) offers only what the chosen generator supports: unsupported slot
choices are shown disabled with one plain sentence and the nearest option ("Wan takes one reference image: the set
image is ignored here. Use Seedance via fal for a set reference."). Existing fields (`draft_resolution`, …) stay.

**Pose-native option.** Research fal's current (October 2026) Wan endpoints that take a control video plus a
reference image (candidates: `fal-ai/wan/v2.2-14b/animate/replace` and `/move`, `fal-ai/wan-vace-14b/*`,
`fal-ai/wan/v2.2-a14b/video-to-video`, Wan 2.5/2.6 if any). Read each endpoint's OpenAPI JSON
(`https://fal.ai/api/openapi/queue/openapi.json?endpoint_id=<id>`) and pricing page; pick the one that best matches
"control video (our prepared clip) + reference image → the character replaced, pose kept", document why in
`docs/GENERATORS.md` (table of candidates, schema facts, price, date read). Implement it as `providers/wan.py`
(`Provider` subclass: `submit_draft`, `poll`, `finalize` → "not available: Wan has no draft/complete; the draft is
the final" or a higher-resolution re-run if the endpoint offers one) and a `generate` tool `wan_fal`, tested with
mocked `fal_client`. If nothing fits, say so in the doc with the reason and skip the adapter (the UI then lists only
the two Seedance generators). Price goes into `stages/costs.py` with its source.

## 6. Export kit (Agent 4)

`stages/export.py: build_export(folder, items, preset, runs_root, status) -> {'folder': Path, 'zip': Path, 'files': [...], 'readme': str, 'fps', 'frames'}`
writes `runs/<id>/export/<preset>-<yyyymmdd-hhmmss>/` (unzipped) and `runs/<id>/export/<same name>.zip`.

**Items** (tick boxes; each present only when the run has the source):

| key | file in the export | made from |
|---|---|---|
| `composite_audio` | `composite.mp4` (H.264 + original audio) | `seedance-input.mp4` (the prepared clip, with the edits) |
| `composite_silent` | `composite-silent.mp4` | `composite-silent.mp4` |
| `depth` | `depth.mp4` | `depth.mp4` |
| `mesh_alpha` | `face-mesh-alpha.mov` (ProRes 4444, `yuva444p10le`) **or** `face-mesh/frame_%05d.png` (RGBA) | `face-landmarks.json` drawn with `stages.meshedit.draw_face` on a transparent canvas, mesh edits applied |
| `mask` | `mask.mp4` (black / white) | `mask.mp4` (or `clean-masks/` when a run has only the PNGs) |
| `alpha` | `person-alpha.mov` (ProRes 4444) **or** `person-alpha/frame_%05d.png` | `composite-silent.mp4` RGB with `mask.mp4` as alpha |
| `audio_original` | `audio-original.wav` (or `.m4a` copy for Seedance web) | `upload.mp4` |
| `audio_vocals` / `audio_music` | `vocals.wav` / `music.wav` | when the run has them |
| `landmarks` | `face-landmarks.json` | with mesh edits applied |
| `words` | `words.srt`, `words.json` | pending word edits first, else `words.json` |
| `prompt` | `prompt.txt` (final assembled prompt with the timed beats + the ref list) | `stages.promptkit.assemble` (Agent 2) when available, else today's prompt text |
| `run` | `run.json`, `slots.json` | copies |

Always: `README.txt` (what each file is, fps, frame count, resolution, which run and edits it came from, the preset's
reasoning in two lines). ffmpeg is at `/opt/homebrew/bin/ffmpeg` with `prores_ks`, `png`, `libvpx-vp9`;
`shutil.which('ffmpeg')` first and a plain fix when missing ("Install ffmpeg: brew install ffmpeg").

**Edits always included.** When `runs/_sessions/<id>/` has pending edits (`stages.editlayer` reports `pending.total > 0`),
the export first saves them exactly like `POST /jobs/{id}/edits/save` (one free branch; refuse with the same plain
message when the session cannot be saved yet), then exports the **child** and says so in the response and README
(`exported_run`). A run without pending edits exports itself. This is what makes "exports always include my timeline
edits" true without rendering the layer twice.

**Target presets** (`stages/export_presets.py`, documented in `docs/EXPORT.md` with the reasoning per choice):

| preset | items on by default | formats / naming |
|---|---|---|
| `seedance_web` | composite_audio, prompt, refs copied (`ref-01-char1.png` …) | H.264 mp4 ≤1080p, source fps, AAC; prompt.txt; refs numbered in attachment order |
| `kling` | composite_audio, mask, prompt | H.264 mp4, mask as mp4, source fps |
| `comfyui` | depth, mask, composite_silent as PNG sequences, landmarks, words.json, run | `depth/frame_%05d.png` etc., fps in README and `frames.json` `{fps, frames, width, height}` |
| `after_effects` | mesh_alpha (ProRes 4444), alpha (ProRes 4444), composite_silent (ProRes 422), audio_original wav, words.srt | `.mov`, source fps, 48 kHz wav |
| `custom` | whatever is ticked | mp4 / mov / png as per the item |

Routes: `GET /jobs/{id}/export` → presets, available items for this run (with the reason an item is missing),
pending-edit note, earlier exports; `POST /jobs/{id}/export` `{preset, items?, mesh_format?: 'prores'|'png', alpha_format?}`
→ runs in a thread, returns `{state, name, ...}`, polled by `GET /jobs/{id}/export/{name}`; `GET /jobs/{id}/export/{name}.zip`
downloads. Free, local; no cost gate needed but the UI shows "free, local" on the button. The UI panel
(`static/export.js`, mounted under step 04 and on the Studio run head "Export…") lists the items with tick boxes,
the preset picker and a "What's in it" line, and shows the README after the export.

Tests: each preset on a synthetic run (`tmp_path`, 12 frames, 24 fps) → the zip opens, frame counts and fps match
(`ffprobe`), README present; `mesh_alpha` ProRes has `pix_fmt yuva444p10le` and a decoded frame has alpha 0 away
from the face and >0 on a mesh line; the export of a run with pending edits exports the child (`exported_run != id`).

### 6.1 start.command (Agent 4)

`start.command` must start the full app from a double-click: `cd` to its own folder, create `.venv` and install
`requirements.txt` when `.venv/bin/python` is missing (print what it is doing), then `exec .venv/bin/python launch.py`
with any `PORT` it was given, and on failure keep the Terminal window readable (`read -r` on error). `.venv/bin/python
launch.py`, `setup.sh`, `workflow.py` and `doctor.py` keep working unchanged.

## 7. Definition of Done (reviewer checks line by line)

- [ ] Regression suite and all tests pass; Quick / Studio / Lab, timeline editor, words, import / download still work in the browser
- [ ] Background: Original, Full depth, Plain and Set image each produce the expected composite on the same run, with the face mesh drawn on top in all four
- [ ] Set: choosing anything other than Original switches the Seedance task to reference mode, shown in the UI and run.json
- [ ] Look: a style image is attached with its fence; prompt-only style lands in the prompt
- [ ] Prompt builder: with character + set + style refs, every ref has exactly one job + fence, numbering matches attachment order, dialogue beats come from words.json
- [ ] Claude vision fills SET / LIGHT from a frame without describing people; missing key shows a plain how-to
- [ ] Generator slot lists only supported options per generator; the Wan/VACE adapter is either working (mocked HTTP) or documented as not available with the reason
- [ ] Export: each preset produces a zip that opens, with correct fps / frame count, a README.txt, and includes timeline edits
- [ ] The transparent face-mesh export has a real alpha channel (verified)
- [ ] Prep → edit → export works end to end with fal and Enhancor keys removed
- [ ] start.command launches the full app
- [ ] No paid call without confirmation; no raw errors; no console errors; usable at 380 px

## §W3 notes (Agent 3, generator capabilities + Wan adapter) — draft after Phase A

**Research (fal, 2026-10-24, OpenAPI + model pages; full table in `docs/GENERATORS.md`).** Endpoints that take a
control video plus a reference image: `fal-ai/wan/v2.2-14b/animate/replace` and `/move` (video_url + image_url, no
prompt, 480p/580p/720p, $0.04/0.06/0.08 per 16 frames), `fal-ai/wan-motion` (video + image, 720p, $0.06 per 24-fps s,
character placed in the image's setting), `fal-ai/wan-vace-14b` (+ `/inpainting`, `/outpainting`: prompt required,
optional video + `ref_image_urls` list + masks, `task` depth/pose/…, ≤ 241 frames, ≤ 720p), `fal-ai/wan/v2.7/edit-video`
(prompt + 2–10 s video + one `reference_image_url`, 720p/1080p, `audio_setting: origin`, $0.10/$0.15 per s).
No image input: `fal-ai/wan/v2.2-a14b/video-to-video`. Loose references only: `fal-ai/wan/v2.7/reference-to-video`.
404: `wan-vace-14b/reference-to-video`, `wan-vace-14b/video-to-video`, Wan 2.5/2.6, `wan-animate`, `animate-v2`.

**Chosen: `fal-ai/wan/v2.2-14b/animate/replace`** — purpose-built "keep the clip's pose, expression, background and
lighting, swap the person for the image"; pose-native; same FAL_KEY and upload path as the Seedance adapter; $0.60 per
10 s at 480p, $1.20 at 720p. Cannot: a prompt, a second image, set/look refs, an identity video, a draft/complete, audio.

**Capability shape** (`providers/capabilities.py`: `GENERATOR_KEYS`, `normalize`, `supports`, `summary`;
`providers.normalized_capabilities(name)`):

```json
{"fal":      {"resolutions":["480p","720p","1080p"],"draft":true,"finalize":"complete_draft","max_seconds":30,"audio":true,"tasks":["auto","reference","editing","extension"],"ref_images_max":30,"slots":{"set_ref":true,"look_ref":true,"char2":true,"identity_video":true},"control":"video","fps":24,"prompt":true},
 "enhancor": {"resolutions":["1080p"],"draft":true,"finalize":"complete_draft","max_seconds":30,"audio":true,"tasks":[],"ref_images_max":30,"slots":{"set_ref":true,"look_ref":true,"char2":true,"identity_video":true},"control":"video","fps":24,"prompt":true},
 "wan":      {"resolutions":["480p","580p","720p"],"draft":false,"finalize":null,"max_seconds":30,"audio":false,"tasks":[],"ref_images_max":1,"slots":{"set_ref":false,"look_ref":false,"char2":false,"identity_video":false},"control":"pose","fps":16,"prompt":false}}
```

`supports(caps, slots, others)` → `[{slot, message, fix}]`, e.g. set → "Wan 2.2 Animate · replace (fal) takes one
reference image: the set image is ignored here." / "Use Enhancor for a set reference, or describe the set in the prompt."

**Registry.** `providers.PROVIDERS` stays `('enhancor','fal')` (default-provider rule, `GET /providers`, the regression
assertion `set(providers) == {'enhancor','fal'}` and `test_providers.EndpointTests` all depend on it);
`providers.GENERATORS = ('enhancor','fal','wan')`, `KEYS['wan']='FAL_KEY'`, `get_provider('wan')` → `providers.wan.Wan`.
`Wan.submit_draft(..., task=None, resolution=None)` accepts the orchestrator's `task` kwarg and ignores it (no `task` in
`seedance-request.json`, so `task_sent()` reports 'not applicable'). Resolution: argument > `<run>/wan-options.json` >
`WAN_RESOLUTION` > 480p. Files: `wan-request.json` (= `seedance-request.json`), `wan-result.json`.

**Costs.** `stages/costs.py` `wan` ($0.06 per clip second at 24 fps, 480p), `wan_580p` ($0.09), `wan_720p` ($0.12),
provider `fal`, endpoint `fal-ai/wan/v2.2-14b/animate/replace`, source + date 2026-10-24; `estimate_tool('wan'|'wan_fal',
s, {'resolution'})`; no `wan_complete` (there is no completion).

**Tests.** `tests/test_generators.py` (20 tests: normalize/supports/summary, adapter payload + upload order, resolution
sources, refusals before upload, missing key, offline, redaction, poll states, finalize refusal, costs, `GET /providers`
unchanged with the new keys). `tests/test_generators.py tests/test_providers.py tests/test_regression.py`: 84 passed.

**Phase B (done).** `providers.GENERATORS` drives `seedance_bridge.submit` / `provider_for`, the `provider` field of
`POST /jobs/{id}/seedance` and `GET /providers` (now `{default, generators, providers}` with normalized capabilities + `configured` +
`summary`; `default` stays enhancor | fal; the two set assertions were widened to include `wan`). New: `GET /jobs/{id}/generators`
(capabilities, configured + `key`, summary, estimate at this run's length, `limits` from `supports()` with the nearest *configured*
generator; `?char1_video=1&char2=1` for unsaved form picks), `stages/generate.py` `WanTool` (`wan_fal`: params `char1`,
`resolution`; writes `wan-options.json`; report tool `wan_fal`), `write_wan_options()`, the wan estimate on the seedance cost gate and
in `GET /jobs/{id}/run` (`estimates.draft.wan`, `estimates.complete.wan: null`), a plain 400 from `POST /jobs/{id}/hd` for a run
with `finalize: null`. UI: `static/generator.js` (`mountGenerator`, mounted by `draft.js` into `[data-slot=generator]`): picker,
summary, limits, resolution select (wan only), draft/final line, saves `slots.generator.{name,resolution}`, keeps the legacy
`select[name=provider]` in sync (row hidden), disables `set_ref` / `style_ref` options, the Character 2 upload and video Character 1
where unsupported; `slots.js` task line now reads `tasks: []` from the capabilities; step 04 hides the HD button for `finalize: null`.
Docs: `docs/GENERATORS.md`, `docs/UI.md` §13, `docs/PROVIDERS.md`. Tests: `tests/test_generators.py` (27), full suite 310 passed.

**Verification (2026-10-24, port 8783, offline).** Hard-link copy of `0be4cf2cadd945008a9c9131b6c75f12` →
`ec49f86d3330400c913db6965ef1e842` (own status.json / run.json / stages/). With FAL_KEY set (offline): the generator slot lists
Enhancor (not configured · ENHANCOR_API_KEY), fal ($2.15 draft) and Wan ($0.49 · one render); choosing Wan disables `set_ref`,
`style_ref` and Character 2, restricts Character 1 to images, shows the task sentence and the resolution select (480p · about $0.49),
the button reads the wan price, the legacy select says `wan`; back on fal everything is enabled again and the limits list is empty.
380 px: `scrollWidth` 380, no console errors. With `FAL_KEY= ENHANCOR_API_KEY=`: all three unconfigured with their key names;
`/run`, `/slots`, `/export`, `/edits` answer 200; `POST /hd` on the (never generated) copy answers 400. The fixture's `run.json` /
`status.json` are sha256-identical before and after; the copy has no `calls.jsonl`.


## §W4 notes (Agent 4: export kit, start.command)

### What exists now

| piece | file | notes |
|---|---|---|
| Export engine | `stages/export.py` | `build_export(folder, items, preset, runs_root, status, *, mesh_format, alpha_format, name, requested_run, edits_line, record_in)`, `availability()`, `describe()`, `prompt_text()`, `refs_list()`, `list_exports()`, `zip_for()`, `ExportError(message, fix, status)` |
| Items + presets as data | `stages/export_presets.py` | `ITEMS`, `PRESETS` (`seedance_web`, `kling`, `comfyui`, `after_effects`, `custom`), `formats_for()`, `listing()` |
| Routes | `app.py` section "export kit" (before `/health`) | below |
| Panel | `static/export.js` (`mountExport`), `tpl-export` in `index.html`, CSS block "Export kit" in `app.css` | mounted by `mountFinal` (`draft.js`, two lines) inside the step 04 panel; "Export…" link on the Studio run head (`runhead.js`, one line) scrolls to `#export` |
| Launcher | `start.command` | venv + requirements on first start, `exec`-style run of `launch.py` with `PORT`, `read -r` on error |
| Docs | `docs/EXPORT.md` (new), `docs/UI.md` (file table, "Export kit" section, endpoints row) | |
| Tests | `tests/test_export.py` (13) | synthetic 12-frame 24 fps run with real clips; ffmpeg-dependent tests skip when it is missing (it is present here, so they ran) |

### Endpoints as implemented

- `GET /jobs/{id}/export` → `{id, presets: [{name, label, items, formats, what, why[2]}], items: [{key, label, what, available, reason, …}]
  (every item of the table, `reason` a plain sentence when missing; `words.source`, `refs.files`), clip: {frames, fps, width, height,
  seconds, source}, formats: {rgba: ['prores','png']}, ffmpeg: bool, ffmpeg_problem, pending: {total, summary, note, problem,
  estimated_cost_usd}, exports: [{name, preset, preset_label, state, created, files, zip_url, zip_exists, exported_run, …}], running}`.
  `pending.note` = "N pending edits will be saved first (free) and the export made from the new run."; `pending.problem` = the
  track's own refusal (`{message, fix, track}`) or the paid refusal (`status: 402`, `estimated_cost_usd`). Writes nothing.
- `POST /jobs/{id}/export` `{preset, items?, mesh_format?, alpha_format?}` (JSON or form; `items` list or "a, b", empty → the preset's
  defaults; `custom` must tick something) → `{state: 'running', name, run, requested_run, exported_run: null, preset, items, formats,
  status, started, pending_edits, zip_url}`. 400 plain + `fix` for a bad preset / item / format, nothing ticked, an item the run lacks
  (`item`), ffmpeg missing ("Install ffmpeg: brew install ffmpeg"), a track that cannot save; **402** when saving the pending edits
  would re-run a paid stage ("…Save the edits from the editor…", `estimated_cost_usd`; nothing is branched); 409 while the run prepares.
- `GET /jobs/{id}/export/{name}` → running `{state, status, …}`, done = the record (`files [{file, what, item}]`, `readme`, `fps`,
  `frames`, `width`, `height`, `seconds`, `zip`, `zip_url`, `zip_bytes`, `folder`, `exported_run`, `requested_run`, `edits`,
  `warnings`, `created`), error `{state: 'error', status, fix}`; 400 for a name not matching `<preset>-<8 digits>-<6 digits>[-xxxx]`, 404 unknown.
- `GET /jobs/{id}/export/{name}.zip` → the zip (`attachment; filename="<id8>-<name>.zip"`), from this run or the exported child (via
  the record); 400 bad name, 404 missing. A decoded `..%2F` never reaches the route (404, like the folder download).

### Spec notes and small decisions

- Export names carry a 4-hex suffix (`after_effects-20261024-024653-3cd9`) so two exports in one second never collide.
- The export of a run with pending edits lives in the **child's** `export/` folder (it is that run's export); the parent gets
  `export/<name>.json` (the record) so its listing and download answer too. Both are "not tool outputs"; nothing else is written
  into either run. `edit-layer.json` is copied with the `run` item when the run was saved from edits.
- `frames.json` is written whenever a PNG sequence is in the export (not only for `comfyui`).
- `refs`: char1, char2, then the set image (`slots.set.mode == 'set_ref'`, `runs/_assets/<name>` or the run's `set-plate.*`) and the
  look image (`slots.look.mode == 'style_ref'`), numbered as the prompt numbers `@ImageN`. `prompt.txt` uses `stages.promptkit.assemble`
  when the module exists (wrapped in try/except: a signature change there can never block an export), else today's text + beats + refs.
- **ffprobe reports `yuva444p12le`** for the ProRes 4444 files on this machine (ffmpeg 9.0.2's ProRes decoder), although the encoder is
  fed `-pix_fmt yuva444p10le` exactly as §6 says. The tests therefore assert `profile=4444` + `pix_fmt` starting with `yuva444p` and
  check real decoded alpha pixels; the README states "yuva444p10le" (the encoding format). Reviewer: `ffprobe -show_entries
  stream=profile,pix_fmt face-mesh-alpha.mov` → `profile=4444`, `pix_fmt=yuva444p12le`.

### Verification (2026-10-24, port 8784, `PUPPETEER_OFFLINE=1 FAL_KEY= ENHANCOR_API_KEY=`)

`b8fb8944adc24eeeb49a4fc3ae7d7d9d` = hard-link copy of `0be4cf2cadd945008a9c9131b6c75f12` (status.json, run.json, stages/ copied).
API: `GET /export` listed 14 items (vocals / music / refs unavailable with their reasons), custom export of the 11 available items
→ 12 files in 6.7 s (192 MB zip); ffprobe: every video `r_frame_rate=24/1`, `nb_read_frames=195`, `composite.mp4` h264 + aac 48 kHz,
`audio-original.wav` pcm_s16le 48 kHz, both `.mov` `prores` `profile=4444`. Alpha pixels (PyAV, `rgba`, frame 40): corner (0,0) alpha 0,
the first lips connection point alpha 255 with colour (255,135,100), 21 127 opaque pixels of 528 000; `person-alpha.mov` alpha ∈ {0, 255}.
Browser (built-in, no console messages on Studio, Quick, Runs; 380 px: `scrollWidth` 375 = `innerWidth`, panel 305 px): the panel
under step 04 with all 14 tick boxes (3 disabled with reasons), the Studio run head "Export…" link, preset switch to After Effects
re-ticked its 5 items and set ProRes 4444; after `PUT /edits` (mesh off 100–102) the line read "1 pending edit will be saved first
(free) and the export made from the new run. (face: mesh off on frames 100–102)"; **Export · free, local** → progress lines → exactly
one child `79465ec947f1409a8715a18ba07a74bf` (`changed` "face: mesh off on frames 100–102", session moved to `saved-79465ec9…`), export
`after_effects-20261024-024653-3cd9` in the child (6 files, 228.6 MB), the panel showed the README, the zip link and "Open the new
version →"; its `face-mesh-alpha.mov` has 0 opaque pixels on exactly frames 100–102 (19 911 on 99, 16 316 on 103). The parent's listing
shows both exports (one `exported_run` = the child); the child's shows its own. `0be4…` has no file newer than this work.
Reviewer: open `/?job=b8fb8944adc24eeeb49a4fc3ae7d7d9d&view=studio`, click "Export…" in the run head, pick a target, click
"Export · free, local", download the zip, open the README; make a mesh-off edit on the Face lane first to see the pending note and
the new version. Suite at the time of writing: 303 passed (255 at the start of the stage + 13 here + the other agents' new tests), no failures.
`start.command`: `PORT=8784 PUPPETEER_OFFLINE=1 ENHANCOR_WEBHOOK_URL=http://localhost/dummy bash start.command` served `/health` and was stopped by its PID only.

## §W1 notes (Agent 1: Background, assets, Set / Look / Light slots, task)

### What exists now

| piece | file | notes |
|---|---|---|
| Background on `depth_cutout` | `stages/composite.py`, `pipeline.py` (`composite_bg`, `PLAIN_COLORS`, shared `_cutout`) | `pipeline.composite` keeps its signature and body behaviour (byte-identical output, regression fakes patch it by name); `normalize_params` drops defaults so legacy `{}` params and keys are unchanged |
| Asset store + fit maths | `stages/plates.py` | `runs/_assets/<sha16>.<ext>` + `<sha16>.json`; `fit_rect`, `parse_fit`, `fit_text`, `render_plate` |
| Slots | `stages/slots.py` | read / write / validate / `task_for` / `effective_task` / `view` / `mirror` / `unflat` |
| Task plumbing | `stages/prompt.py` (flat slot params), `stages/generate.py` (`task` param, `record_submission(task=)`), `providers/base.py` + `fal.py` (`submit_draft(..., task=None)`, `_task(explicit=None)`), `providers/enhancor.py` (accepts and ignores `task`), `seedance_bridge.py` (`submit(..., task=None)`, `task_sent`, `record_task`) | |
| Routes | `app.py` block "World stage (Agent 1)" + `task` on `POST /jobs/{id}/seedance` + the slots re-mirror in `run_child` | |
| UI | `static/slots.js` (new), `tpl-slots` in `index.html`, targeted edits in `stagecard.js`, `draft.js`, `review.js`, CSS block in `app.css` | |
| Tests | `tests/test_world.py` (14) | suite: 302 passed + Agent 4's export test in flux at the time of my run |
| Docs | `docs/STAGES.md` §18, `docs/UI.md` §12, `docs/PROVIDERS.md` (task, generation.json) | |

### Endpoints as implemented

- `POST /jobs/{id}/assets` — multipart `file` (png / jpg / jpeg / webp, ≤ 30 MB, PIL-decoded), `kind` = `set` | `look` →
  `{"name":"f7f1c8783ca9d58e.png","filename":"plate.png","kind":"set","size":8022,"width":1600,"height":900,"url":"/assets/f7f1c8783ca9d58e.png"}`.
  Plain 400 `{message, fix}` for a non-image / wrong extension / wrong kind / empty file, 413 over 30 MB. The store is
  shared by every run (content-addressed, so the same file uploads once).
- `GET /assets?kind=set|look` → `{"assets":[{name, filename, kind, size, width, height, url}, …]}` newest first (the picker).
- `GET /assets/{name}` → the image (400 for a name that is not `<16 hex>.<ext>`, 404 when missing).
- `GET /jobs/{id}/slots` → the slots object (below) plus `id`, `task` (what will be sent), `derived_task`, `task_source`
  (`set` | `user`), `file` (slots.json exists), `background` (the composite stage's: `original | full_depth | plain |
  set_image | none`), `background_label`, `background_needed` (`full_depth` for `original_depth`, `set_image` for
  `true_swap`, else null), `background_applied` (true when the composite already has it, with the same plate).
- `PUT /jobs/{id}/slots` — JSON or form; keys `set`, `look`, `light`, `generator` (form fields may carry JSON); partial
  updates merge; validates modes, asset names and text length (plain 400); returns the same shape as GET. Allowed while
  the run prepares (slots are not tool outputs; `run_child` mirrors them again when it finishes).
- `POST /jobs/{id}/seedance` gained `task` (`auto | reference | editing`; a bad value is a plain 400). No field →
  `slots.json`'s effective task; no `slots.json` either → `FAL_TASK` as before.

### Slots JSON as stored (`runs/<id>/slots.json`)

```json
{"version":1,
 "set":{"mode":"true_swap","image":"f7f1c8783ca9d58e.png","prompt":"","fit":{}},
 "look":{"mode":"follow","image":null,"prompt":""},
 "light":"soft window light",
 "generator":{"name":null,"task":"auto","resolution":null},
 "updated":"2026-10-24T02:44:10+00:00"}
```

`set.fit` is `{}` when it is the default, else `{x, y, scale}` (clamped: x, y in −1…1, scale 0.2…5). `generator.task`
`auto` means "derived from the set mode" (`task_for`: `original` → `editing`, else `reference`); `reference` / `editing`
are user overrides, reset to `auto` by `write()` when the set mode changes (unless the same patch sets the task). The
mirror: `run.json.slots` = the object above, `run.json.chain.prompt.params` gets `set_mode`, `set_image`, `set_prompt`,
`look_mode`, `look_image`, `look_prompt`, `light` (strings; empty string for no image). A branch inherits the flat keys
through its chain, and `slots.read()` rebuilds the slots from them when the child has no `slots.json`.

### Composite params and `changed` lines

`{"background":"plain","plain_color":"gray"}`, `{"background":"full_depth"}`,
`{"background":"set_image","set_image":"f7f1c8783ca9d58e.png","set_fit":"{\"scale\":1.0,\"x\":0.2,\"y\":0.116}"}`; `{}` for
original (also when the request said `background: original`). `changed`: "composite: depth_cutout background: original →
set_image, set_image: → f7f1…png, set_fit: → moved 20% / 12%, scale ×1.00".

### Verification (2026-10-24, port 8781, `PUPPETEER_OFFLINE=1 ENHANCOR_WEBHOOK_URL=http://localhost/dummy`)

Hard-link copy of `0be4cf2cadd945008a9c9131b6c75f12` → `46bb5dfeb55a40d681177a95ba1fcd57` (own `status.json`, `run.json`,
`stages/`; ids patched). Children made at the composite stage, all `done`, mesh drawn on top in every one (checked on a
contact sheet of frame 40: `depth-composite-silent.mp4` over `composite-silent.mp4`), no `calls.jsonl` anywhere, fixture
and copy sha256-identical before and after:

| background | run id | outside-mask mean RGB (frame 40) |
|---|---|---|
| original | `459087f59c1748b989b96d3ed8e69b86` | 39/31/19 (= the original frame) |
| full_depth | `503a4e8b8a494c8d9a4a29308cc78271` | 24/14/28 (= the depth frame) |
| plain gray | `9f3aabb359014a34a47bfa0d846b9c95` | 126/126/126 |
| set_image (API, x 0.05, scale 1.2) | `08a838f2fadd4eba99572082764a9fb9` | 97/81/84 (plate), `set-plate.png` in the run |
| set_image (placed by dragging on the Studio card) | `721368c2cd2b4bdd8b48408a2710266d` | fit `{x:0.2, y:0.116}` from the drag |
| full_depth from "Apply as background" (draft step, set mode Depth only) | `cdc475cc4b594ff6b738aad8a61a3496` | slots saved on the child, mirrored after the run |
| missing plate (plain error with fix) | `03b6e51064584dff86a147db7ea254d0` | report `state: error`, nothing composited |

Browser: Studio and Quick of the copy and the children, no console errors, 375 px: `scrollWidth` 375, the canvas
271 px wide. The browser pane is shared with the other agents: use your own `tabId` (`preview_start` with the URL).

### What Agents 2 and 3 must know

- Read the slots with `stages.slots.read(folder)` (never the file directly: a branch may only have the flat keys) or
  `GET /jobs/{id}/slots`; write with `stages.slots.write(folder, patch)` / `PUT`. Keys: `set.mode` ∈ `original |
  original_depth | set_ref | prompt | true_swap`, `set.image` (asset name or null), `set.prompt`, `set.fit`; `look.mode`
  ∈ `follow | style_ref | prompt`, `look.image`, `look.prompt`; `light`; `generator.name`, `generator.task`,
  `generator.resolution`. Asset files: `stages.plates.asset_path(name, runs_root)`.
- The set image to attach as a reference (`set_ref`) is `slots.set.image`; for `true_swap` the plate is already in the
  composite (`runs/<id>/set-plate.<ext>`; the prompt should say the plate is the real set) and for `original_depth` the
  depth defines layout only. `GET /jobs/{id}/slots` tells you whether the matching background is applied
  (`background_applied`).
- Mount points inside `tpl-slots` (draft step, above the prompt textarea): `[data-slot=prompt-builder]` (Agent 2) and
  `[data-slot=generator]` (Agent 3), empty divs under the task line. `mountSlots()` is called once per draft panel; the
  node is `.slots`. To react to a slot change, listen for `PUT` responses yourself or re-read on `update()`; the panel
  re-renders its own fields only.
- `generate` tools accept `params.task` (`auto | reference | editing`); `seedance_bridge.submit(..., task=)` and
  `Provider.submit_draft(..., task=None)` are the hooks; Enhancor ignores it and `generation.json.task` says
  `"not applicable"` (plus `task_note`). Agent 3's capabilities (`tasks: []`) should drive the UI sentence; today the
  slots panel says it in one sentence when the provider is Enhancor.
- Choice I made where the spec left one: `normalize_params` drops the new params at their defaults (instead of adding
  them with defaults) so `normalize_params({})` stays `{}` and the legacy cache keys are literally the same; the same for
  the generate tools' `task` (`auto` dropped) and the prompt tool's slot keys (`defaults()` answers only `text`).
- Known: Starlette answers 404 (not 400) for a percent-encoded `/` in a path segment (`/assets/..%2Fx`); the test accepts both.

## §W2 notes (Agent 2: prompt builder with fences, Claude vision fill)

### What exists now

| piece | file | notes |
|---|---|---|
| Prompt assembly + fences | `stages/promptkit.py` | `assemble(folder, slots=None, refs=None, words=None, runs_root=None)` → `{text, refs, beats, sections, warnings, closing, has}`; `fences_ok(text, refs)`; `number_refs`, `collect_refs`, `extra_refs(slots, runs_root)`, `saved_reference`, `closing_line`, `beats_block` |
| Adapter rules for extra refs | `providers/base.py` (`extra_ref_sentences`, `extra_ref_paths`, `build_prompt` additive), `providers/fal.py`, `providers/enhancor.py` (upload set then look after the characters, `check_image_constraints` on them) | two-ref output byte-identical (regression suite) |
| Orchestrator | `seedance_bridge.submit(..., set_image=None, look_image=None)` (keyword-only additions), `ref_record()` → `generation.json` gets `refs` + `slots` | adapters get the paths as `refs['set']` / `refs['look']`, so Agent 3's Wan adapter and the test fakes keep their signature |
| Claude vision | `stages/vision.py` | `describe_frame(folder, t=None, runs_root=None)`; `frame_image` (mask → gray, ≤1024 px, JPEG), `parse`, `strip_people`, `VisionError(message, fix, status)`, `NO_KEY_MESSAGE` / `NO_KEY_FIX` (the spec's exact text) |
| Price | `stages/costs.py` `claude_vision` | $0.0062 = 1,600 input + 300 output tokens at Sonnet 5.5 $2 / $10 per MTok (pricing page via the claude-api skill, 2026-10-24); `usd_per_million_input/output` for the real spend from `usage` |
| Routes | `app.py` block "Prompt builder with fences + Claude vision fill (Agent 2)" + two lines in `POST /jobs/{id}/seedance` | below |
| Panel | `static/promptkit.js` (`mountPromptBuilder`), two lines + `promptBuilder.update()` in `static/draft.js`, CSS block "Prompt builder (Agent 2)" in `app.css` | mounted into `[data-slot=prompt-builder]` |
| Tests | `tests/test_promptkit.py` (15) | suite: 325 passed at the time of writing |
| Docs | `docs/PROMPT-BUILDER.md` (new), `docs/PROVIDERS.md` (build_prompt extra refs, generation.json `refs` / `slots`), `docs/UI.md` §14 + endpoints row | |

### Endpoints as implemented

- `POST /jobs/{id}/prompt/assemble` `{slots?, text?, provider?}` (JSON or form) → `{id, text, refs: [{n, token, slot, kind, file, path, job, job_line, fence}], beats, sections: [{name, text}], warnings, closing, has: {mesh, depth}, full_prompt, mode, provider, provider_note, edited}`. Free, nothing written, no network. `text` = a hand-edited box whose `full_prompt` and `fences_ok` warnings are wanted; `slots` = a preview of unsaved slots; a generator with `prompt: false` gets `full_prompt: null` + `provider_note`. 400 for a non-object `slots`, 404 unknown run.
- `POST /jobs/{id}/describe` `{t?, confirm_cost?, estimate_only?, apply?}` → `{id, set, light, model, usd, estimated_usd, frame_s, frame, fps, masked, warnings, raw, applied, estimated_cost_usd}`. Order of refusals: bad `t` → 400; no key → 400 `No Anthropic key yet.` + the how-to; `estimate_only` → the price (free); no `confirm_cost` → 402 via `cost_gate()`; offline → 400 plain (`record_call` raises before the request); Anthropic 401 / 429 / other → 502 plain with a fix; `refusal` stop reason → 502 plain. `apply=true` writes only `set.prompt` and `light` through `stages.slots.write`.
- `POST /jobs/{id}/seedance`: the slots' set / look images (`set_ref` / `style_ref`, `stages.promptkit.extra_refs`) go to `submit(..., set_image=, look_image=)` and are uploaded after the character references. `seedance-request.json` stays the exact payload.

### The fence sentences (exact)

- char1: `@ImageN defines the character's identity only (face, hair, outfit, proportions); do not copy its pose, expression, props, background or lighting.` (identity video: the same with `@Video2`; char2: `…defines the second character's identity only…`)
- set: `@ImageN defines the set only (walls, floor, furniture, depth of the room); do not use its people or lighting.`
- look: `@ImageN defines the rendering style only (palette, grain, contrast, brushwork); do not copy its content, people or layout.`
- appended by `build_prompt`: `@ImageN is the set reference only.` / `@ImageN is the style reference only.`
- closing line: `Keep the camera, crop, timing and every word of the embedded dialogue; replace the whole identity including hair; remove any mesh lines or depth colours from the output.` — `replace … hair` and `mesh lines` only with a mesh, `depth colours` only with depth.

### Choices where the spec left one

- Sections are rendered as `CHARACTER: …`, `SET: …`, `LOOK: …`, `LIGHT: …` paragraphs separated by blank lines; the beats block and the closing line have no label (the beats block must stay byte-identical to the route's text).
- `set.prompt` / `look.prompt` are included whenever they are filled, not only in `prompt` mode, so a Claude description of the real room still goes out with an `original` set (the vision fill is for exactly that). `true_swap` attaches no ref (the plate is in the composite).
- `fences_ok` is run on the assembled text and on the hand-edited box text, not on `full_prompt`: `build_prompt`'s pinned `@Image2 defines … under the same rules.` sentence would count as a second job sentence there.
- The vision request is minimal on purpose (no `fallbacks`, no betas): a `refusal` is a plain 502 "Claude declined to describe this frame" rather than a silent switch to another model with another price. `output_config.effort: low` and adaptive thinking by default (Sonnet 5.5 cannot disable thinking).
- The Describe button uses `apply=true` and reloads the slots panel instead of typing into the (possibly hidden) Set description field; the two lines are also shown under the button with the frame time and the real cost.

### Verification (2026-10-24, port 8782, `PUPPETEER_OFFLINE=1 ENHANCOR_WEBHOOK_URL=http://localhost/dummy FAL_KEY= ENHANCOR_API_KEY=`)

`be6eb3fc0fdb4e49a7da2ef134fdca05` = hard-link copy of `0be4cf2cadd945008a9c9131b6c75f12` (status.json, run.json, stages/ copied; ids patched; `char1-reference.jpg` = its preview.jpg). New asset `runs/_assets/489b0de59abadc0b.png` (a 640×360 style image, kind look). Browser (built-in, own tab): Set reference + `f7f1c878…png`, Style image + `489b0de5…png`, Build prompt → 3 fences + beats from words.json (`2.2–6.4 s says: "And I need you, and I miss you,"`) + closing line, strip @Image1 / @Image2 / @Image3 / @Video1 with thumbnails, final prompt ends with `@Image2 is the set reference only. @Image3 is the style reference only.`, no warnings; Describe with no key → the how-to notice; 375 px `scrollWidth` = `innerWidth`; no script errors (Chrome logs the expected 400 as a resource error). No `calls.jsonl` in the fixture or the copy; `0be4…` has no file newer than this work.
