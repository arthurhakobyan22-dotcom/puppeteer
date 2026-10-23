# Timeline editor: the shared contract (stage 2, "Review becomes a timeline editor")

Written by the lead before any agent starts. Agents 1–4 build on it in order; the reviewer checks against it and
against the Definition of Done at the end. When you change a contract below, update this file in the same commit
and say so in your hand-off note. Read `AGENTS.md`, `docs/STAGES.md`, `docs/UI.md`, `docs/MASK-WAND.md` first.

## 0. Non-negotiables (all agents)

- **Remove nothing.** Every route, form field, CLI command, file name, module function, preset, the old wand
  (`static/wand.js`, `/mask/preview`, `/mask/frame`, `/mask/apply`), Quick / Studio / Lab / Runs keep working. New
  things are added next to them. The regression suite (`tests/test_regression.py`) and every existing test stay green:
  `.venv/bin/python -m pytest -q` (185 passed at the start of this stage).
- **Never overwrite tool outputs.** Manual edits live in an edit layer; outputs are only ever produced by tools,
  in a new run (branch). The parent run's folder is not written to by editing or saving (sha256 of every file in
  the parent before/after must match — test it).
- **Forgiving by default.** Every error the UI shows is `{message, fix}` in plain words (use `fail()` in `app.py`,
  `showError()` / `notice()` in the UI). No raw exceptions, arrays or tracebacks on screen. Silent retry only for
  free GETs. Nothing paid runs without the estimate on the button and `confirm_cost=true` from that click (402
  otherwise; reuse `cost_gate()`).
- **Offline + ports.** Verify with `PUPPETEER_OFFLINE=1 PORT=<your port> .venv/bin/python launch.py`. Ports:
  Agent 1 → 8775, Agent 2 → 8776, Agent 3 → 8777, Agent 4 → 8778, reviewer → 8779. **Never kill anything on
  8770/8771** (the user's own instances) and never `pkill -f launch.py`; stop only the PID you started.
- **Fixtures.** Existing `runs/` folders are real paid fixtures. Never write into them. To test on real data, make a
  hard-link copy: `cp -al runs/85e5dbe64df1464fa63825319ebfa104 runs/<new 32 hex>`, then **replace** (copy, not
  link) `status.json`, `run.json`, `mask-review.json` if present, and `python -c "import stages;stages.reconstruct(Path('runs/<new>'),with_keys=True,write=True)"`
  so it has a `run.json` (see how `tests/test_branch_integration.py` does it). `85e5…` is Advanced + mesh (depth,
  SAM masks, face mesh, 195 frames, 24 fps, 8.12 s, AAC audio). Note its face is lost on frames 10–16 and 50–61.
  List the ids you create in your doc section.
- **Commits.** Work on branch `timeline-editor`. At the end, commit your work in one or a few logical commits
  (message body ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`). Do not push; the lead pushes.
  `runs/` is git-ignored; never commit it, `.venv*` or `models/`.
- **Style.** Match the surrounding code: dense one-line Python in `app.py`/`stages/`, plain ES modules with small
  helpers in `static/`, no build step, no framework, no new CDN dependencies. Docstrings/comments in the same terse
  plain-English voice.

## 1. Where things live

| piece | file(s) | owner |
|---|---|---|
| Edit-layer store, undo/redo, save → one branch | `stages/editlayer.py`, routes in `app.py` | Agent 1 |
| Multi-stage branch (`also=`) | `stages/branch.py` (additive) | Agent 1 |
| Editor shell: viewer, playhead, timeline, tracks API, keyboard, Save bar | `static/editor.js`, `static/timeline.js`, `static/editlayer.js`, `tpl-editor` in `index.html`, CSS | Agent 1 |
| Mask track: batch wand, pending list, ticks, tint, Grab hands, quick preview, `edit_layer` mask tool | `static/track-mask.js`, `stages/masktrack.py` (+ `stages/mask.py` tool registration), `hands_worker.py` | Agent 2 |
| Face mesh track: range off, transform, keyframes, expressions, `mesh_edit` face tool, local renderer | `static/track-face.js`, `stages/meshedit.py` (+ `stages/face.py` registration), `static/face-connections.json` | Agent 3 |
| Words track, transcription, prompt beats, mouth guidance, subtitles, Import my own, Download | `static/track-words.js`, `stages/words.py`, `words_worker.py`, `setup-words.sh`, `stages/imports.py`, `static/draft.js`/`stagecard.js` additions | Agent 4 |

New docs: each agent appends its own section to this file ("§A1 notes" … "§A4 notes") with what it built, the
endpoints, verification artefacts (run ids) and anything the next agent must know. Also update `docs/UI.md`
and `docs/STAGES.md` where your work changes what they describe.

## 2. The edit layer (Agent 1 builds, everyone uses)

### 2.1 Storage

Pending edits for run `<id>` live **outside the run folder** in `RUNS/_sessions/<id>/` (resolve `RUNS` at call time:
tests patch `app.RUNS`). `GET /jobs` and `stages.tree` already ignore non-hex folder names (like `runs/_compare`).

```
runs/_sessions/<id>/
  session.json        # the layer + history (below)
  log.txt             # session log: every preview / apply / hands pass, one line each (copied into the child's log.txt on save)
  calls.jsonl         # external calls made while editing (paid Apply / Grab hands); appended to the child's calls.jsonl on save
  mask/…              # Agent 2: applied mask results, session mask video, previews
  …                   # other tracks may add sub-folders
```

`session.json`:

```json
{"version":1,"run":"<id>","rev":7,"created":"<iso>","updated":"<iso>",
 "base_fingerprint":"<mask_review.fingerprint(run) when the session started>",
 "layer":{"mask":{…},"mesh":{…},"words":null},
 "undo":[{"label":"Add + point on frame 40","layer":{…}}, …],   // newest last, capped at 200
 "redo":[…]}
```

The `layer` is plain JSON owned per track (`mask` → Agent 2, `mesh` → Agent 3, `words` → Agent 4); the store never
interprets a track's content except through the track hooks (2.3). Empty layer = `{"mask":{},"mesh":{},"words":null}`.
Each track key must be JSON-serialisable and small (no pixel data; pixel results are files referenced by hash).

### 2.2 Endpoints (form or JSON, plain errors)

- `GET /jobs/{id}/edits` → `{run, rev, layer, can_undo, can_redo, undo_label, redo_label, pending: {mask: n, mesh: n, words: n, total}, summary: ["3 mask fixes on frames 12–40", …], stale: bool}`.
  No session yet → an empty layer, `rev: 0` (nothing is written by a GET). `stale` is true when the run's current
  review fingerprint differs from `base_fingerprint` (the run changed under the session).
- `PUT /jobs/{id}/edits` `{rev, label, layer}` → replaces the whole layer, pushes the old one onto `undo` with `label`,
  clears `redo`, `rev += 1`. 409 `{message, fix, rev}` when `rev` does not match (another tab edited); the UI reloads.
  Optionally `{rev, label, track, value}` replaces only `layer[track]`.
- `POST /jobs/{id}/edits/undo` / `.../redo` → the new state (same shape as GET). Undo/redo across all tracks share
  one stack (Cmd+Z undoes the last edit whatever track it was on).
- `DELETE /jobs/{id}/edits` → discards the session (folder removed). The UI asks first ("Discard N pending edits?").
- `POST /jobs/{id}/edits/save` `{confirm_cost?}` → **exactly one branch** for the whole session (2.3), then the session
  is closed (moved to `runs/_sessions/<id>/saved-<child id>/` for the record, or removed) and the response is the child
  job like `POST /jobs/{id}/branch`: `{state, id, parent, changed, estimated_cost_usd}`. Nothing pending → 400
  "There are no edits to save." 402 when the re-run would include a paid stage without `confirm_cost`
  (normally saving is free: edit tools are local). Refuses with a plain 400 + fix when a track's hook says it cannot
  save yet (e.g. mask points not applied: "3 mask clicks are not applied yet. Apply them to the clip first, or remove
  them." — the UI shows "Apply now" / "Save without them" actions).

### 2.3 Track hooks (server)

`stages/editlayer.py` exposes `register_track(name, hooks)`; hooks is an object with:

- `count(layer_value) -> int` — pending edits for the badge and `pending`.
- `summary(layer_value) -> list[str]` — plain lines for the Save bar and `changed`.
- `check(layer_value, session_dir) -> str | None` — a plain reason the session cannot be saved yet, or None.
- `change(layer_value, parent_folder, session_dir) -> None | (stage, tool, params)` — the stage change this
  track contributes to the save branch (e.g. `('mask', 'edit_layer', {...})`, `('face', 'mesh_edit', {...})`).
  Params must make the cache key differ per edit (include a hash of the layer value and `base_run`).
- `materialize(layer_value, child_folder, session_dir, parent_folder) -> None` — writes the files the tool will read
  into the **child** before it runs (e.g. `edit-layer/mask/*.png`, `edit-layer/mesh.json`, `words.json`).

Save algorithm: collect `change()` from every track with `count > 0`; the branch stage is the earliest stage among
them in `stages.STAGES` (mask < composite < face < prompt); a words-only session branches at `prompt` (nothing
re-runs; the child is `done`, all prepared artifacts linked). Call `stages.branch(parent, stage, tool, params,
runs_root=RUNS, also={other_stage: {tool, params}, …})` once, then every track's `materialize()`, write the whole
layer to the child as `edit-layer.json` (the record; included in the child's `run.json` as `edits: {summary, layer_sha}`),
append session `log.txt` / `calls.jsonl` into the child's, then run the child exactly like `start_branch()` does.
`changed` = the summaries joined ("mask: 5 clicks on frames 12–40 applied, 1 brush stroke · face: mesh off 50–52,
2 transform keys · words: 3 words edited"). The child has no `mask-review.json`, so its approval is pending
("Approval clears on save"). The parent is never written.

`stages.branch(..., also=None)`: additive keyword. Each entry is applied to the chain with the same
`changed_chain` rules; `changed` lists every change. Without `also` behaviour is byte-identical to today.
Non-stage artifacts that a child should inherit from its parent (`words.json`, `mouth-guidance.json`,
`subtitles.json`) are linked by `branch()` when present (list `CARRY` in `branch.py`, extended by Agent 4); a
materialize hook may replace them in the child (call `stages.fresh(path)` first).

### 2.4 Client (`static/editlayer.js`)

```js
import { edits } from './editlayer.js';
edits.load(jobId)                  // GET; called by the editor on mount and on job change
edits.layer                        // current layer (treat as read-only)
edits.commit(label, track, fn)     // fn(draft) mutates a structuredClone of layer[track]; PUTs {rev,label,track,value}; optimistic, rolls back + notice on error
edits.undo(); edits.redo()         // POST; Cmd+Z / Shift+Cmd+Z (Ctrl on others) wired by the editor
edits.on('change', fn)             // after every load/commit/undo/redo; tracks redraw from here
edits.pending                      // {mask, mesh, words, total}
edits.save()                       // POST save → navigate({job: child, view}); 400 hooks → notice with actions; 402 → "Run anyway · about $x"
```

The Save bar (part of the editor): "N pending edits · Undo · Redo · Discard · **Save edits** (free, creates one
new version)". Disabled when nothing is pending. A `beforeunload` guard is not required (edits persist server-side).

## 3. The editor shell (Agent 1)

`tpl-review` keeps its review box, approval checkbox, Approve / Needs fixing, audio downloads and the
`[data-review-tools]` hook (the old wand registers there and must still work). The viewer area becomes the editor:

```
┌ view switch: Prepared input · Original · Depth · Mask · Composite · (+ Tint, added by Agent 2) ┐
│ <div class="stage-view">  <video base>  <video overlay?>  <canvas overlay>  </div>            │
│ transport: ◀◀1s ◀frame ▶/❚❚ frame▶ 1s▶▶   frame 52 / 195 · 2.17 s   zoom − +   Download ↓   │
├ timeline (scrolls horizontally inside its own box) ────────────────────────────────────────────┤
│ ruler (seconds + frame ticks)   ▼ playhead spans every row                                      │
│ MASK   ▁▂▃▅▃▂ area sparkline · red ticks · pending markers                                      │
│ FACE   tracked/filled/missing · off ranges · keyframe ◆ · edited ●                              │
│ WORDS  [hello][there]  [my][friend]                                                           │
├ track panel: the selected track's tools (pending list, sliders, word editor…) ─────────────────┤
└ Save bar: 5 pending · Undo · Redo · Discard · Save edits                                        ┘
```

- **One playhead** = one integer frame. `editor.frame`, `editor.frames`, `editor.fps` (from `GET /jobs/{id}/mask/frame`
  headers or the run's `original.mp4`; prepared clips are 24 fps). Seeking: `video.currentTime = (frame + 0.5) / fps`;
  the frame shown: `Math.floor(currentTime * fps + 1e-3)`; during playback follow `requestVideoFrameCallback` (fallback
  `timeupdate`). Every stacked video is kept on the same time.
- **Keys** (ignored while focus is in an input/textarea/select/contenteditable): ←/→ one frame, Shift+←/→ one second,
  Space play/pause, Home/End first/last frame, Cmd/Ctrl+Z undo, Shift+Cmd/Ctrl+Z (and Ctrl+Y) redo, `[`/`]` previous /
  next marker on the selected track (tracks provide markers), Esc clears the range.
- **Zoom**: −/+ buttons and Ctrl/Cmd+wheel over the timeline; `pxPerFrame` from "fit" (whole clip in view) up to 24 px
  per frame. The timeline box has `overflow-x: auto`; the **page** never scrolls horizontally (`scrollWidth <= 380` at
  380 px).
- **Range selection**: drag across the ruler or an empty part of any track → `editor.range = {from, to}` (inclusive
  frames), shown as a band across all rows; click without dragging = move the playhead; Esc / click elsewhere clears.
  Tracks read `editor.range` for range tools (mesh off, expression on range, …).
- **Views**: the view switch picks the base video (existing `TABS` files). A track may add views (`editor.addView({id,
  label, layers: [...]})`, e.g. Tint = original + mask video with CSS blend). Switching views keeps the frame and must be
  instant (keep elements alive, swap visibility; no re-download of an already loaded file).
- **Tracks API** (`static/timeline.js`):

```js
import { registerTrack } from './timeline.js';
registerTrack({
  id: 'mask', label: 'Mask', order: 10,
  available(ctx) { return ctx.files.has('mask.mp4'); },     // ctx = {jobId, files, run, mode, editor, edits}
  mount(row, panel, ctx) {},      // once per job: row = the track's lane element, panel = its tools box (shown when the track is selected)
  update(ctx) {},                 // after every job poll and edits change
  draw(lane, view) {},            // view = {pxPerFrame, frames, fps, scrollLeft, width}; redraw on zoom/scroll/frame
  markers(ctx) { return [12, 40]; },   // for [ / ] and click-to-jump
  onFrame(frame, ctx) {},         // playhead moved
  canvas(ctx2d, box, frame) {},   // draw on the overlay canvas over the video (markers, mesh preview)
  pointer: { down(e, pt), move(e, pt), up(e, pt) } // optional: pointer events on the overlay canvas (pt = normalized 0–1 to the video picture, letterbox-safe)
});
```

  The shell owns: the lanes' common ruler/playhead/range band, track selection (click the label), the overlay canvas
  sized exactly to the rendered video box (reuse `videoBox()` logic from `wand.js`; ResizeObserver), and routing pointer
  events on the canvas to the selected track. Agent 1 ships the shell with **placeholder tracks** for Mask, Face and
  Words that draw what already exists (mask area from `mask-cleanup-report.json`; face status from
  `face-tracking.json`; words lane empty with "No transcript yet") so the shell is testable on its own.
- **Old review tools**: `registerReviewTool` callbacks still run after each update with the same `ctx` (`video` = the
  editor's base video element), so the old "Fix the mask" wand still works.
- **380 px**: transport wraps, the timeline scrolls inside its box, track panel stacks.
- **No console errors**; every network failure shows a plain notice.

## 4. Mask track (Agent 2)

- **Pending fixes, no propagation.** Click on the overlay = + include, Alt-click (or the "− exclude" toggle) = −;
  brush strokes (paint/erase, radius, "on N frames from here") also only add pending fixes. Each point → layer commit
  (`mask.points[]`, `{id, frame, x, y, label}` normalized 0–1) + an instant preview on **that frame only** using the
  existing free seed step (`wand.preview_png`; extend it to include strokes) shown on the overlay within ~2 s. No
  propagation, no hosted call, no branch until **Apply to clip**.
- **Apply to clip** `POST /jobs/{id}/edits/mask/apply {quality: "quick"|"full", tool, confirm_cost?}` sends **all**
  pending points from all frames in **one** propagation call (one `wand.local_propagate` call over the list; for a
  hosted tool one call per click type, as today) and builds on the **current mask** = base run masks → Grab-hands
  result → previous applied results. Writes `mask/results/<sha>/` (one PNG per frame) + `mask/session-mask.mp4` (B/W)
  in the session, appends exactly one line to the session `log.txt` ("mask propagation: 5 points on 3 frames, quick,
  local_propagate → 181 frames changed"), and commits the layer: pending points/strokes move into
  `mask.applied[] = {id, tool, quality, points, strokes, result: <sha>}`. Undo reverts to the previous result (results
  are kept by hash). **Quick preview:** `quality=quick` runs at a low working size (longest side ~240 px) and shows
  the result; "Accept · full quality" re-runs the same points at full quality (`quality=full`, longest side 480 or
  native) and replaces that applied entry. Paid tools: quick preview uses the free local algorithm; the accept click
  carries the estimate and `confirm_cost=true`.
- **Pending-fixes list** in the track panel (frame, type +/−/brush, delete per item, Undo last, Clear all); markers on
  the lane at frames with pending fixes; click a marker/list row to jump.
- **Problem ticks**: red ticks where the mask area jumps (reuse per-frame `mask_pixels` from `mask-cleanup-report.json`,
  computed from the masks when absent; thresholds documented, e.g. |Δarea| > 12 % of the median area frame-to-frame)
  or a connected component (likely hand/limb) disappears for a few frames. Endpoint `GET /jobs/{id}/mask/problems`
  → `{frames: [{frame, kind: "jump"|"limb", note}], areas: [..]}` (session-aware: after Apply the ticks come from the
  current session mask). Prev/next tick buttons and `[`/`]`.
- **Views**: B/W (`mask.mp4` or the session mask video), Composite (`composite.mp4`), **Tint** = original video with
  the mask video stacked on top (CSS `mix-blend-mode: screen` + tint filter/opacity, or a canvas), all synced to the
  playhead; switching is instant.
- **Grab hands**: runs a hands-only pass on just the flagged frames (the problem ticks, or the selected range) and
  merges the hand regions into the current mask **before** manual clicks. Default: free local MediaPipe Hand Landmarker
  in `.venv-face` (`hands_worker.py`, model `models/hand_landmarker.task` downloaded on first use from Google's
  mediapipe-models bucket like the face model) → hand landmarks → region grown with the depth/colour seed rule.
  Optional paid hosted pass (SAM 3 "hands" on fal) only with the estimate + confirmation. Only flagged frames change
  (test it).
- **Save hook**: `change()` → `('mask', 'edit_layer', {layer_sha, base_run})`; `materialize()` copies the final mask
  set into `child/edit-layer/mask/`; the `edit_layer` mask tool (free, registered in `stages/mask.py`, not first, so the
  default stays `sam3_replicate`) copies them to `raw-masks/` + `clean-masks/`, writes `sam-report.json` (+ `wand`
  section) and `mask-edits.json` like `WandTool`. `check()` refuses while unapplied points/strokes exist.

## 5. Face mesh track (Agent 3)

Landmarks: `face-landmarks.json` (`frames[i].faces[0]` = 468/478 `{x, y}` normalized; `status` tracked|filled|missing).

- **Layer** `mesh = {off: [[a,b],…], keys: {"<frame>": {dx, dy, scale, rot}}, expr: {"<frame>": {jaw, smile, pucker,
  blink_l, blink_r, brow}}}` (dx/dy in normalized frame units, scale factor, rot degrees about the face centroid;
  expression values −1…1 or 0…1 as documented).
- **Range on/off**: with a range selected, "Mesh off on range" / "Mesh on" edit `off`; those frames fall back to the
  depth composite only (no mesh drawn).
- **Transform**: on-canvas handles (move = drag inside, scale = corner handle, rotate = top handle) on the current
  frame; each change sets a key on that frame.
- **Keyframes**: two or more keys are blended across the frames between them with an ease-in-out curve; a single key
  affects only its frame; frames outside the first…last key get no correction (document this). Keys are ◆ on the lane.
- **Expressions**: sliders jaw open, mouth smile, mouth pucker, blink left, blink right, brow up on the current frame or
  the selected range; applied as landmark offsets on named MediaPipe index groups (document the indices) to the saved
  face data.
- **Rendering**: the overlay re-renders **locally and free**: instantly on the browser canvas (tessellation +
  lips/eyes from `static/face-connections.json`, exported once from `.venv-face` mediapipe, same colours as
  `mesh_worker.py`), and on save by the `mesh_edit` face tool (main venv, PIL/OpenCV, no mediapipe needed) over the
  depth composite (or original in Fast mode). Zero external calls (no `record_call`, no network; test with network
  mocked to fail).
- **Edited frames** marked on the lane; "Reset frame" / "Reset range".
- **Save hook**: `('face', 'mesh_edit', {layer_sha, base_run})`; `materialize()` writes `child/edit-layer/mesh.json`
  and links the base `face-landmarks.json` as `edit-layer/face-landmarks-base.json`; the tool writes the edited
  `face-landmarks.json`, `face-tracking.json` (with an `edited` note), `composite-silent.mp4`, `preview.jpg`.
  A shared pure function `meshedit.apply(landmarks, mesh_layer) -> landmarks` is used by the tool, the tests and (via
  the same formulas in JS) the canvas preview; keep both in step (a test compares Python output with fixed expectations).

## 6. Words track, prompt beats, subtitles (Agent 4)

- **Transcription**: free local Whisper on Apple Silicon preferred (e.g. `mlx-whisper` with
  `mlx-community/whisper-large-v3-turbo` and `word_timestamps=True`, in an isolated `.venv-words` on Python 3.12 via
  `setup-words.sh`, like `.venv-face`), fal as the paid fallback (check fal's live OpenAPI for a word-level Whisper
  endpoint; cost gate). Pick the most accurate option that actually works here and document the comparison and choice
  in `docs/WORDS.md`. `POST /jobs/{id}/words/transcribe {engine?, singing?, confirm_cost?}`; cached by audio sha256
  (`runs/_cache/words/<sha>-<engine>-<singing>.json`) so a re-transcribe is free and instant.
- **words.json** (text, start, end) on the run: `{"version":1,"engine":"…","language":"…","singing":false,
  "words":[{"text":"hello","start":0.0,"end":0.42}, …]}`. Transcription of a run with no transcript writes `words.json`
  into that run (an additive analysis output, like the face report; never overwriting an existing one); edits go to the
  layer (`words = {words: [{id, text, start, end}], singing}`) and land in the child's `words.json` on save.
- **Lane**: each word a block; edit text (double-click), drag edges to fix timing (snap to frames, no overlap), split
  (at the playhead), merge (with next), add a missing word (at the playhead / in the selected range), delete.
  Singing mode = looser auto-timing (e.g. no punctuation splitting, longer minimum durations) with the expectation of
  manual drags.
- **Uses**: (a) the draft step's prompt gets "Insert dialogue beats" → lines like `0.0–1.8 s says: "…"` grouped by
  pauses, editable in the textarea before submit (what is in the textarea is what is sent); (b) `mouth-guidance.json`
  per word `{text, start, end, start_frame, end_frame}` plus per-frame word index and `mouth_hidden` (face missing/filled
  from `face-tracking.json`) for a later stage — data only, no generation; (c) "Export subtitles (.srt)"
  (`GET /jobs/{id}/subtitles.srt`, valid SRT, phrases ≤ ~42 chars / ≤ ~5 s) and a "Burn subtitles into final" toggle
  on the finish step, **off by default**; when on, a local free burn-in writes `final-preview-subtitled.mp4` (and
  `hd/…` when present) next to the untouched final. This ffmpeg build has **no `subtitles`/`drawtext` filter (no
  libass/freetype)**: render text with PIL onto frames via PyAV and copy the audio packets.

## 7. Import my own / Download (Agent 4)

- **Download**: every stage output gets a Download button (Studio stage cards: one link per output file in the
  report; the editor's views; masks also as a PNG zip `GET /jobs/{id}/download/mask.zip`; landmarks JSON).
- **Import my own** tools: `depth: import_depth` (grayscale or coloured video), `mask: import_mask` (B/W video, PNG
  sequence zip, or alpha video), `face: import_face` (overlay video or landmarks JSON in our schema),
  `composite: import_control` (a finished control video: face off, goes straight to review). Upload:
  `POST /jobs/{id}/import` (multipart `stage`, `file`) → stored content-addressed as `runs/_imports/<sha256>.<ext>`
  → a branch at that stage with params `{file: <sha>, name: <original name>}` (cache key covers the sha) → the UI
  navigates to the child. Auto-conform to the run's fps, frame count and size (trim / pad by holding the last frame /
  resize) and say so in plain words in the report's `warnings` ("Your mask had 200 frames; the clip has 195, so the
  last 5 were dropped."). Mismatches are warnings, never errors; unreadable files are a plain 400 with a fix.
- **Labelled "imported"**: report `data.imported = true` + tool flag `imported: true` in `describe()`; the stage card
  chip, the run chain (`describe_chain`), the run header's "what changed" and the Runs list (`imported: [stages]` on the
  summaries) show "imported".

## 8. Definition of Done (copied from the brief; the reviewer checks each line)

- [ ] Regression suite + all existing tests pass; Quick/Studio/Lab, presets, branching and the cost gate still work in the browser
- [ ] Timeline shows video + mask, face and word tracks with one playhead; arrow keys step frames; range selection works
- [ ] Mask: 5 points across 3 frames cause zero propagation until Apply; one Apply = one propagation (check logs); each point previews on its frame within ~2 s
- [ ] Problem ticks appear where the mask area jumps; next/previous tick jumps work
- [ ] Tint overlay, B/W and composite views switch instantly
- [ ] Grab hands adds missing hands on flagged frames only
- [ ] Face: switching the mesh off for a 3-frame range leaves depth-only on exactly those frames
- [ ] Face: moving the mesh on frames 40 and 52 blends the correction smoothly across 41–51
- [ ] Face: the jaw-open slider visibly changes the overlay; all mesh edits make zero external calls
- [ ] Words: transcription produces word blocks with timing; editing text, dragging edges, split/merge all persist after reload
- [ ] The prompt shows timed dialogue beats from words.json, editable before submit
- [ ] .srt export opens correctly; burn-in toggle works and is off by default
- [ ] Import: a mask exported, edited externally and re-imported is used in the composite; a mismatched one conforms with a warning, not an error
- [ ] Undo/redo works across mask, mesh and word edits; "Save edits" creates exactly one branch; the parent is unchanged
- [ ] No raw errors in the UI; no console errors; usable at 380px (timeline scrolls horizontally inside its panel, page itself doesn't)
- [ ] Commit in logical commits on a new branch and push; tell me the restart command and the link to open the editor
