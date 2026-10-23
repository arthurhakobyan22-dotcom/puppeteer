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
| Face mesh track: range off, transform, keyframes, expressions, `mesh_edit` face tool, local renderer | `static/track-face.js`, `static/meshedit.js`, `stages/meshedit.py` (tool registered there, see §A3), `static/face-connections.json` | Agent 3 |
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
- `DELETE /jobs/{id}/edits` → discards the session (its files removed; `saved-*/` records of earlier saves stay — changed by Agent 1). The UI asks first ("Discard N pending edits?").
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

## §A1 notes (Agent 1: edit layer, branch `also=`, editor shell)

### What exists now

| piece | file | notes |
|---|---|---|
| Session store, undo/redo, save | `stages/editlayer.py` | `RUNS/_sessions/<id>/` only; `RUNS` is passed in by `app.py` at call time |
| Track hook stubs | `stages/masktrack.py` (Agent 2 replaces), `stages/meshedit.py` (Agent 3), `stages/words.py` (Agent 4 extends) | imported by `stages/__init__.py`; a later `register_track('mask', …)` replaces the stub |
| Multi-stage branch, CARRY | `stages/branch.py` | `branch(..., also=None)`, `also_chain()`, `CARRY` |
| Routes | `app.py` | section "edit layer"; `start_branch()` now calls `run_child()`, which the save shares |
| Client | `static/editlayer.js` | `edits` singleton |
| Timeline + track registry | `static/timeline.js` | `registerTrack`, `tracks()`, `createTimeline()` |
| Editor | `static/editor.js`, `tpl-editor` in `index.html`, CSS block "Timeline editor" in `app.css` | mounted by `review.js` into `[data-editor]` |
| Track list | `static/tracks.js` (one line per track) + `static/track-placeholders.js` | see "Swapping a placeholder" |
| Tests | `tests/test_editlayer.py` (9 tests) | suite: 194 passed |

### Server API as implemented

```python
from stages import editlayer
editlayer.register_track(name, hooks)     # hooks: an instance or a class (instantiated); same name replaces
class editlayer.Track:                    # subclass it; every hook is optional
    label = None        # name in `changed` / `summary` ('face' for the mesh track); defaults to the track name
    empty = {}          # the track's value in an empty layer (words: None)
    def count(self, value) -> int
    def summary(self, value) -> list[str]
    def check(self, value, session_dir) -> None | str | (message, fix)    # refusal → 400 {message, fix, track}
    def change(self, value, parent_folder, session_dir) -> None | (stage, tool, params)
    def materialize(self, value, child_folder, session_dir, parent_folder) -> None
editlayer.note(runs_root, ident, line)    # one line in the session log.txt (previews, applies, hands passes)
editlayer.session_dir(runs_root, ident)   # Path of RUNS/_sessions/<id>/ (put track files under a sub-folder, e.g. mask/)
editlayer.layer_sha(value)                # canonical sha256 of any JSON value (use it in change() params)
editlayer.load / view / put / step / discard / plan / save   # what the routes call
```

- `count`/`summary`/`check`/`change`/`materialize` get `value = layer[track]` (the track's `empty` when the stored
  value is null and `empty` is not None). `materialize` runs **only for tracks with `count > 0`**, after `branch()`
  and before the child runs. Two tracks asking for the same stage is a plain 400; merge such edits in one track.
- Session `calls.jsonl`: write lines yourself in the `stages.calls` format (`{time, provider, endpoint, stage, tool,
  cost_usd, ok}`); they are appended to the child's `calls.jsonl` on save, so the child's `cost_usd_total` includes
  paid applies made while editing. Paid calls made while editing still need their own cost gate at the moment they run.
- The session folder is **moved** to `_sessions/<id>/saved-<child id>/` on save, so the child must never reference
  session files: copy what the tool needs into the child in `materialize()`.

### Endpoints as implemented

`GET /jobs/{id}/edits` (writes nothing; 404 for an unknown run) · `PUT /jobs/{id}/edits` JSON or form
`{rev, label, layer}` or `{rev, label, track, value}` (form values are JSON strings) → the GET shape; missing `rev`
→ 400; stale `rev` → 409 `{message, fix, rev}`; unknown track → 400; a layer over 2 MB of JSON → 413 ·
`POST /jobs/{id}/edits/undo` and `/redo` (optional `rev` → 409 when stale; nothing to undo/redo → 400) ·
`DELETE /jobs/{id}/edits` → the empty GET shape (removes the live session; `saved-*` records stay) ·
`POST /jobs/{id}/edits/save {confirm_cost?}` → `{state, status, id, parent, changed, estimated_cost_usd}`; 400 "There are
no edits to save." / a track's refusal (`track` in the body); 402 with `estimated_cost_usd` through `cost_gate()` when
the re-run includes a paid stage; 409 when the session changed between planning and saving.

Save details: the branch stage is the earliest `change()` stage, the others go in `also`; no change at all (words
only, or tracks without a stage change) → `prompt` (nothing re-runs, the child is `done`, status "Ready · review the
prepared input and create a draft"). The child's `run.json.changed` = the summaries line ("words: 2 words edited",
tracks joined with " · "); `run.json.edits = {summary, layer_sha, stage, chain_changed, session_rev}` where
`chain_changed` is the technical `branch()` line. `edit-layer.json` = `{version, run, child, saved, rev, layer_sha,
summary, changed, stage, chain_changed, layer}`. `GET /jobs` shows `changed` as is for runs with `edits`. A failure
while materializing removes the half-made child and keeps the session.

### `branch(also=)` and CARRY

`stages.branch(parent, stage, tool, params, runs_root=…, also={'face': {'tool': 'off', 'params': {}}})`: each `also`
stage must come **after** `stage` (else ValueError); `changed` = the lines joined with " · " (e.g. `composite:
depth_cutout → original · face: mediapipe_mesh (strict: false, pad: 1.8, max_gap: 6) → off`). Without `also` the
child is the same as before (tested against the `8f6a192` version of `branch()` for four kinds of change). `CARRY =
['words.json', 'mouth-guidance.json', 'subtitles.json']` are hard-linked from the parent when present; a writer calls
`stages.fresh(path)` first (the words stub does).

### Client API as implemented (`static/editlayer.js`)

As in §2.4, plus: `fn(draft)` may **return** a new value (needed when the track's value is null); commits are queued
in order, and a failed commit rolls back, drops the commits queued after it and reloads; `edits.saveActions[track] =
problem => [{label, run}]` adds buttons to the notice when that track's `check()` refuses a save (Agent 2: "Apply
now" / "Save without them"); `edits.discard()`; `edits.busy`; `edits.on('change', fn)` returns an unsubscribe function.

### Editor and timeline as implemented

- `registerTrack(def)` exactly as §3 plus optional `height` (px, default 40) and `markerColor`. `draw(lane, view)`:
  `view = {pxPerFrame, frames, fps, scrollLeft, width, height, frame, range, dpr, ctx2d, x(frame), frameAt(x)}`;
  `lane.canvas` is the lane's canvas, already sized to the **visible** width and cleared, `ctx2d` pre-scaled by `dpr`
  (draw in CSS px; `x(f)` is the left edge of frame `f` in the visible box). The shell then draws the markers
  (`markers(ctx)`) as small triangles. DOM children you add to a lane must carry `data-tl-item` if they handle their
  own pointer events (otherwise a drag on them selects a range); position them in `draw()` with `view.x()` (it is
  called on every scroll / zoom / frame change). `draw` gets no ctx: keep the last ctx from `mount`/`update`.
- `canvas(ctx2d, box, frame)`: `box = {width, height, dpr}` in **device** pixels of the picture (normalized × width).
  Called for every visible track, in order, inside `save()/restore()`.
- `pointer`: the overlay only takes pointer events while a track with `pointer` is selected (otherwise the video's
  native controls stay clickable); `pt = {x, y, frame}`, x/y 0–1 of the picture.
- Editor API (`ctx.editor`, also `window.puppeteer.editor`): see the header of `static/editor.js` — `frame`, `frames`,
  `fps`, `range`, `selected`, `seek`, `step`, `play`, `pause`, `toggle`, `setRange`, `select`, `redraw`, `addView`,
  `setView`, `view`, `video` (base video of the current view), `layers`, `on(event)` (`frame`, `range`, `select`,
  `view`, `zoom`, `update`), `pictureBox()`, `overlay`, `timeline`. `addView({id, label, layers: [{file}|{src}, {file,
  style: {mixBlendMode: 'screen', opacity: '0.6'}}], caption?, download?, available?(ctx), order?})` — layers after the
  first are stacked above the base, muted, pointer-events none, kept on the same time (also when loading late).
- Frames and fps come from the prepared clip (`GET /jobs/{id}/mask/frame?i=0` headers), first guessed from the
  input-doctor report or `face-tracking.json`, last resort the video duration × 24.
- The base video keeps its native `controls` (volume, fullscreen, scrubbing; the editor follows `seeked`/`play`/`pause`
  on it). Only the current view's base is audible.

### Swapping a placeholder

`static/tracks.js` has one line per track: replace `registerTrack(maskPlaceholder);` with `import './track-mask.js';`
(Agent 2), the face line with `import './track-face.js';` (Agent 3), the words line with `import './track-words.js';`
(Agent 4); the new file calls `registerTrack({id: 'mask', …})`. Keep the ids `mask`, `face`, `words` (the layer keys
are `mask`, `mesh`, `words`: the face track commits to `'mesh'`). Server side, register your hooks in your own module
(`stages/masktrack.py`, `stages/meshedit.py`, `stages/words.py`; keep the `register_track` call at import).

### Gotchas for Agents 2–4

- The placeholder mask/mesh hooks **refuse to save** pending edits ("… the mask track is not installed in this
  version") so nothing is dropped silently; your hooks replace that.
- The old wand (`static/wand.js`) appends its `.wand-overlay` to `editor.video.parentElement` (`.stage-view`) and
  lines up exactly with the editor overlay (checked: both 838×480 at the same position). Its frame rounding now uses
  the editor's convention (`floor(t·fps + 1e-3)`, seeks to the frame centre); nothing else in it changed.
- Keys are handled on `document` in the capture phase and stop propagation (so a focused `<video>` does not also act
  on Space/arrows); they are ignored in inputs, textareas, selects and contenteditable; Space on a button outside the
  editor clicks that button.
- `requestVideoFrameCallback` and `timeupdate` do not fire while the page is hidden; pausing re-syncs the frame.
- The browser pane's screenshots sometimes show `seedance-input.mp4` as black although it renders (canvas readback
  had content); not an app bug.
- `review.js` still calls every `registerReviewTool` callback after each update with `ctx.video = editor.video`
  (plus `ctx.editor`).

### Verification (2026-10-23, port 8775, `PUPPETEER_OFFLINE=1`)

`3d2b448ade9e42e8b7083ee35d31242b` = hard-link copy of `85e5…` (status/run.json copied, reconstructed). In Studio and
Quick: video + Mask (area sparkline, red jump ticks), Face (tracked/filled/missing; 50–61 red) and Words lanes with one
playhead; ← / → exactly one frame (counter and `video.currentTime` agree), Shift+→ 24 frames, "frame 52 / 195 · 2.17 s";
zoom −/+ and Ctrl/Cmd+wheel from fit (4.3 px/frame) to 24; drag on the words lane → range 95–136, Esc clears; click on
the ruler moves the playhead; view switch keeps the frame (also while playing); `[`/`]` on Face jump 10 → 50 → 10;
Home/End; the old "Fix the mask" wand opens on the editor's frame, follows arrow steps and closes with controls back;
a word added at the playhead, Cmd+Z / Shift+Cmd+Z undo and redo it; Discard asks first; **Save edits** created exactly
one child `d8c05b5f888a4a07a129d80ff1aef98e` (runs 49 → 50; words-only → branch at prompt, done, `words.json` in the
child, review pending) and the page navigated to it; every file of `3d2b…` and of `85e5…` sha256-identical before and
after. At 380 px: `document.documentElement.scrollWidth` 380, the timeline scrolls inside its box (scrollWidth 1639 in
a 250 px box). `/?view=runs` (child shows "What changed: words: 1 word edited"), `/?view=lab`, the Quick form and a
Fast-mode run (`f5a3f11d…`, Face + Words lanes only) render; zero console messages. Session record left under
`runs/_sessions/3d2b…/saved-d8c05b5f…/`.

## §A2 notes (Agent 2: mask track)

### What exists now

| piece | file | notes |
|---|---|---|
| Track hooks, Apply, Grab hands, problem ticks, previews | `stages/masktrack.py` | replaces the stub; `register_track('mask', MaskTrack)` at import |
| `edit_layer` mask tool | `stages/mask.py` (`EditLayerMask`, a `WandTool`) | free; registered after the other wand tools, so `sam3_replicate` stays first/default |
| Hands worker | `hands_worker.py` (runs in `.venv-face`) | MediaPipe Hand Landmarker, IMAGE mode, ≤ 2 hands, confidences 0.3; model `models/hand_landmarker.task` fetched on first use (7.8 MB, done once on 2026-10-23) |
| Wand additions (additive keywords) | `stages/wand.py` | `local_propagate(…, work_side=None, fast_decode=False)`, `work_scale(h, w, side=None)`, `decode_video(…, fast=False)`, `selections()`, `preview_png(…, strokes=(), out_dir=None, base_masks=None, transparent=False)`; defaults behave exactly as before |
| Session call log | `stages/calls.py` | `session_folder_of(path)`; `record_call` on a path under `_sessions/<id>/` writes that session's `calls.jsonl` (offline still raises first) |
| Routes | `app.py` section "mask track of the edit layer" | below |
| Client | `static/track-mask.js` (swapped in `static/tracks.js`), CSS block "Mask track panel" in `app.css` | `maskPlaceholder` stays exported, unused |
| Edit-layer client addition | `static/editlayer.js` | `edits.saveChecks[track] = () => null | {message, fix}`: a known refusal is shown with the track's `saveActions` without a 400 round trip (no console error); the server still checks |
| Tests | `tests/test_mask_track.py` (16) | suite: 210 passed (`test_editlayer` now expects the real track's refusal wording) |

### Endpoints as implemented

- `POST /jobs/{id}/edits/mask/preview` `{frame | time, points?, strokes?}` → `{url: /runs/_sessions/<id>/mask/previews/preview-<frame>-<hash>.png, frame, frames, fps, width, height, selections: [{mode, fraction, already_in_mask}], points_on_frame, strokes_on_frame, server_seconds}`. Transparent RGBA: tints (include green, exclude red) + the outline of the **current session mask**. Without `points`/`strokes` the session's pending ones are used (the client sends its optimistic ones so a preview never waits for the PUT). One `mask preview: …` line in the session log. The old `/mask/preview` is unchanged (still `wand-preview/` in the run).
- `POST /jobs/{id}/edits/mask/apply` `{quality: quick|full, tool: local_propagate|sam3_points_fal|sam2_points_replicate, replace?: <applied id>, rev?, confirm_cost?, estimate_only?}` → the GET `/edits` shape + `apply: {entry, result, video, frames_changed, quality, tool, seconds, reused, estimated_cost_usd, intended_tool}`. Plain 400s (nothing pending, unknown tool, not the latest entry, no depth), 409 stale `rev`, 402 for a paid full Apply without `confirm_cost`, 400 with `OfflineError.fix` when offline. `estimate_only` answers `{tool, estimated_cost_usd, free}` and runs nothing (the client shows it on the button).
- `POST /jobs/{id}/edits/mask/hands` `{source: problems | range, from?, to?, rev?}` → GET shape + `hands: {entry, result, video, frames, hands_on, frames_changed, changed, seconds}`.
- `GET /jobs/{id}/mask/problems` → `{id, frames: [{frame, kind: jump|limb, note, span: [a, b]}], areas, flagged, median, source: session|report|masks, result, thresholds}`. Session-aware; writes nothing in the run (session results cache `problems.json` in their own folder; run masks are cached in memory).

### Layer schema as implemented (`layer.mask`)

```json
{"points":  [{"id":"p…","frame":40,"x":0.55,"y":0.45,"label":1,"t":1792781691626}],
 "strokes": [{"id":"s…","frame_from":100,"frame_to":104,"mode":"paint","points":[[0.7,0.4],…],"radius":0.03,"t":…}],
 "applied": [{"id":"a…","kind":"fix","tool":"local_propagate","quality":"quick","points":[…],"strokes":[…],"base":null,
              "result":"<24 hex>","frames_changed":95,"notes":[…],"intended_tool":"sam3_points_fal"?},
             {"id":"h…","kind":"hands","tool":"mediapipe_hands","quality":"full","frames":[…],"hands_on":[…],"base":"<prev>","result":"<24 hex>","frames_changed":3,"source":"problems"}]}
```

`applied` is one chronological chain; each entry's `result` is a full mask set built on `base` (the previous entry's
result, or the run's masks when null). Current mask = `applied[-1].result`. Undo/redo just move along the layer
history; results stay on disk under `runs/_sessions/<id>/mask/results/<key>/` (`mask_00000.png …`, `mask.mp4` B/W,
`areas.json`, `problems.json`), `key` = sha256 of (run, base, kind, fixes, quality, tool)[:24], so the same Apply on
the same base is never computed twice (`reused: true`). **Spec change:** the B/W session video is
`mask/results/<key>/mask.mp4` (one per result, so undo swaps back to an already loaded `<video>` instantly) instead
of a single `mask/session-mask.mp4`. Hosted tools and the hands worker run in `mask/work/` (symlinks to the run's
clips), so their records and call lines land in the session.

Grab hands ordering: a hands pass is applied at once to the current mask; pending clicks stay pending and are applied
on top at the next Apply ("hands before manual clicks", and a − click can still remove a wrong hand region). Accept ·
full quality works on the latest applied fix only (else a plain 400: undo the later steps first); it reuses that
entry's own points/strokes and base and replaces it (one undo step back to the quick one). A quick Apply with a paid
tool runs the free local algorithm and records `intended_tool`; Accept then carries that tool's estimate + `confirm_cost`.

Save hook: `count` = pending points + strokes + applied entries; `summary` = "5 clicks on frames 40–60 applied, 1
brush stroke, hands added on 3 frames[, quick quality]" (pending: "N clicks on frames a–b not applied"); `check` refuses
pending points/strokes ("1 brush stroke is not applied yet. Apply them to the clip first, or remove them." + fix);
`change` → `('mask', 'edit_layer', {layer_sha, base_run, result})` only when something is applied; `materialize`
copies the result PNGs to `child/edit-layer/mask/` + `child/edit-layer/mask.json` (`{result, base_run, summary,
fixes}`). The tool's inputs include `edit-layer/mask`, so its cache key covers the pixels.

### Thresholds (problem ticks, Grab hands)

- **jump**: |area[i] − area[i−1]| > 12 % of the median area (areas = `mask_pixels` of `mask-cleanup-report.json` when
  it matches the run's masks, else counted from the PNGs; session results from `areas.json`). A drop paired with the
  next rise within 24 frames flags the frames in between; an unpaired rise flags the 8 frames before it (the part was
  probably missing just before it appears), an unpaired drop the 8 frames after it.
- **limb**: connected components (8-connected) on masks downscaled 4×, parts ≥ 0.2 % of the frame, every part but the
  largest; it "vanished" at frame i when < 20 % of it is still covered by frame i's mask dilated 2 px (at ¼ size);
  parts touching the picture edge are skipped (they may have left the frame); the span runs to its return within 24
  frames (else 3 frames).
- `flagged` = the union of the spans = what "Grab hands on flagged frames" looks at.
- Hand region: convex hull of the 21 landmarks at work size (480 px), grown by 35 % of the hand size, cut by a depth
  flood (tolerance 20) from every landmark; the plain hull is added back when the depth rule keeps < 50 % of it;
  closed 5×5; OR-ed into the current mask on flagged frames only.

### Measured (fixture copy, 960×550, 195 frames, offline, port 8776)

- Preview per click (browser, click → overlay drawn): 0.08–0.17 s; server 0.03–0.07 s. Synthetic test: < 2 s asserted.
- Apply 5 points on 3 frames: quick 2.0–2.2 s (95–109 frames changed), Accept · full 2.9–3.2 s. Most of it is writing
  195 PNGs + encoding the B/W video (~1 s); decoding uses FFmpeg's scaler (`fast_decode`, 0.15 s vs 0.56 s with
  OpenCV INTER_AREA).
- Grab hands on 18 flagged frames: 2.9–3.3 s (worker start included); hands found on 168–170, exactly those frames changed.
- View switch B/W ↔ Composite ↔ Tint: 1.7–5.8 ms synchronous `setView`, base `readyState` 4, frame kept, no new
  request after the first load of each file (the pane was hidden, so rAF-based timing is not meaningful there).
- Problems: 0.45 s first call on the fixture, then cached (2 ms).

### Verification (2026-10-23, port 8776, `PUPPETEER_OFFLINE=1`)

`7d0a5cb914b4452aa3830458eebb0bbf` = hard-link copy of `85e5…` (status/run.json copied, reconstructed). In Studio:
5 real clicks on frames 40, 40, 52, 52 (Alt-click −), 60 → each previewed on its frame (0.08–0.17 s), session log had 5
`mask preview` lines and no propagation line, run count unchanged; "Apply to clip · quick preview" → exactly one line
`mask propagation: 5 points on 3 frames, quick, local_propagate → 95 frames changed`, the page switched to Tint with
the session mask (sparkline turns green); Accept · full quality replaced the entry; Prev/Next tick and `[`/`]` jump
48 ↔ 176; Grab hands on flagged frames changed exactly frames 168–170; a brush drag added a pending stroke; Cmd+Z ×2
/ Shift+Cmd+Z ×2 undid/redid the stroke and the hands pass (the Tint layer swapped back to the previous result's
video instantly); Save edits → page-side "not applied yet" notice with Apply now / Save without them → "Apply now"
created exactly one child `499413329e1142d394713256823db33a` (mask `edit_layer`, composite + face re-run, its 195
clean-masks byte-identical to the session result, its `mask.mp4` agrees with them, no `calls.jsonl`); a second
flow in Quick made `c3f93cf88d99496593f05563d1a94b55`. `85e5…` and `7d0a…` sha256-identical before/after. A paid
Apply ("Apply with SAM 3 on fal · about $0.06") offline → plain notice, nothing logged. At 380 px
`scrollWidth` 380. Old "Fix the mask" wand opened, previewed a click and closed with controls back. Session records:
`runs/_sessions/7d0a…/saved-4994…/`, `saved-c3f9…/`. Console: only the expected 4xx of deliberate refusals (offline paid
Apply, and two from the pre-fix run of the save race described below).

### Gotchas for Agents 3–4

- **Save right after a server-side commit**: the session folder is moved on save, so anything the page loads from
  `/runs/_sessions/<id>/…` after that 404s. The mask track pauses its view/problem loads during "Apply now" / "Save
  without them" (`quietSave`); do the same if your track serves session files.
- Use `edits.saveChecks[track]` for refusals the page can predict; a 400 from fetch is a console error.
- A server-side commit (`editlayer.put` from a route) changes the layer under the client: call `edits.load()` after it
  (the mask track does after Apply / Grab hands). Pass `rev` from `edits.rev` (after `await edits.queue`).
- `editor.addView({id: 'mask.mp4', …, order: 30})` overrides the built-in Mask tab (same id) — that is how the B/W view
  follows the session; a `download` of `'../_sessions/…'` resolves to the session file under `/runs/`.
- The browser serves `static/*.js` from memory cache across reloads; after editing a module, `fetch(url, {cache:
  'reload'})` it once before `location.reload()` or you test a mix of old and new modules.
- `replaceChildren(...)` prints `null` as text; filter children first (the `el()` helper skips nulls, the DOM API does not).
- The track uses `onFrame` only while paused (no DOM work per frame during playback).

## §A3 notes (Agent 3: face mesh track)

### What exists now

| piece | file | notes |
|---|---|---|
| Pure edit, track hooks, local renderer, `mesh_edit` face tool | `stages/meshedit.py` | replaces the stub; `register_track('mesh', MeshTrack)` and `register(MeshEdit)` at import (**spec change:** the tool registers in `meshedit.py`, after face.py's tools, not in `face.py`, so the TRACKS order stays mask, mesh, words and `mediapipe_mesh` stays first) |
| Connection lists | `static/face-connections.json` (+ `face_connections.py`, run once in `.venv-face`) | MediaPipe 1.1.0 `FaceLandmarksConnections` in MediaPipe order: tessellation (2556), lips (40), left/right eye (16), brows, face oval, irises |
| JS port of the formulas | `static/meshedit.js` | pure ES module, no DOM; checked against the same fixture under node |
| Track | `static/track-face.js` (swapped in `static/tracks.js`), CSS block "Face track panel" in `app.css` | `facePlaceholder` stays exported, unused |
| Shared fixture | `tests/fixtures/mesh-edit-cases.json` | a synthetic 478-point face, 8 expression/transform cases, the eased blend, normalize; regenerate only when the formulas change on purpose |
| Tests | `tests/test_mesh_edit.py` (17) | suite: 227 passed |
| Small fixes elsewhere | `stages/branch.py`, `stages/base.py` (`unshare`), `stages/editlayer.py`, `static/editlayer.js` | see "Changes to shared code" |

### Layer schema as implemented (`layer.mesh`)

```json
{"off":  [[100, 102]],                                        // inclusive frame ranges, merged; drawn without a mesh
 "keys": {"70": {"dx": 0.0549, "dy": -0.02083, "scale": 1, "rot": 0}},   // dx/dy in frame widths/heights, rot ° clockwise
 "expr": {"40": {"jaw": 1}}}                                  // per frame; zero values dropped
```

`normalize()` (Python and JS identical) drops junk: frames must be whole numbers (int, integral float or digit string;
booleans refused), keys clamp to |dx|,|dy| ≤ 2, scale 0.2–5, |rot| ≤ 180, expressions to their ranges (jaw, pucker,
blink 0…1; smile, brow −1…1). `count` = off ranges + keys + expression runs (consecutive frames with equal values =
one edit, so a slider on a 30-frame range counts once); `summary` e.g. "mesh off on frames 100–102, 2 transform keys
(frames 70, 82), jaw on frame 40"; `check` never refuses; `change` → `('face', 'mesh_edit', {layer_sha, base_run})`
(400 "This run has no face mesh…" when the parent has no `face-landmarks.json`); `materialize` writes
`edit-layer/mesh.json` `{version, base_run, layer_sha, summary, layer}` and **copies** (spec said links) the parent's
`face-landmarks.json` → `edit-layer/face-landmarks-base.json` and `face-tracking.json` → `edit-layer/face-tracking-base.json`.

### Formulas (pixel-aspect space: x · width/height, y; all from the frame's own unedited points)

- H = |p152 − p10| (face height), d = unit(p152 − p10) (face "down"), r = (d.y, −d.x) (face right on screen),
  m = mean of 61, 291, 13, 14 (mouth centre). Expressions first (all offsets from the unedited points, summed), then
  the transform about the centroid of the unedited points 0–467 (irises 468–477 move with it).
- **jaw 0…1**: every point not in UPPER_LIP (61 185 40 39 37 0 267 269 270 409 291 78 191 80 81 82 13 312 311 310 415
  308) moves jaw · 0.10 · H · wv · wl along d; wv = clamp((v − v_c)/(v_14 − v_c), 0, 1), v = (p − m)·d, v_c = mean
  of the corners 61/291 (denominator ≥ 0.02 H); wl = clamp(2 − |(p − m)·r| / M, 0, 1), M = half the mouth width.
  So the inner lower lip 14, the outer lower lip 17, the chin 152 and everything below the lip under the mouth drop by
  exactly jaw · 10 % of H; the jaw angles near the ears barely move (hinge). Tested to 1e-12.
- **smile −1…1**: points within 0.18 H of the nearer corner move smile · H · (1 − dist/0.18H)² · (0.06 · side · r −
  0.04 · d); the corners themselves go out 6 % and up 4 % of H at 1 (−1 = frown).
- **pucker 0…1**: the 40 lip points move pucker · (−0.4 ((p − m)·r) r + 0.15 ((p − m)·d) d): 40 % narrower, a bit rounder.
- **blink_l / blink_r 0…1**: upper-lid contour points move onto their lower partners, u + blink · (l − u).
  blink_l = MediaPipe LEFT_EYE = the person's left eye (right of the picture): (466,249) (388,390) (387,373) (386,374)
  (385,380) (384,381) (398,382); blink_r = RIGHT_EYE: (246,7) (161,163) (160,144) (159,145) (158,153) (157,154) (173,155).
- **brow −1…1**: the 20 brow points (46 53 52 65 55 70 63 105 66 107 / 276 283 282 295 285 300 293 334 296 336) move
  brow · 0.06 · H against d.
- **Transform**: p' = c + scale · R(rot) (p − c) + (dx · aspect, dy). Points no edit touches keep their exact input
  values (no float round trip), and an identity key changes nothing.

**Easing rule:** a key's frame uses that key; a frame strictly between consecutive keys a < f < b uses
A + (B − A) · e(t), e(t) = t²(3 − 2t), t = (f − a)/(b − a), per value (dx, dy, scale, rot, linear in each); endpoints
exact, e(½) = ½ (frame 46 between 40 and 52 is exactly half way); one key affects only its frame; before the first and
after the last key there is no correction. A drag on a frame between keys starts from the blended value and adds a key
there. Frames without a face (missing) stay faceless whatever the keys say; off frames get `faces: []`, `status:
"off"`, `edited: "off"`; changed frames `edited: true`.

### Renderer and tool

`meshedit.render(folder, landmarks, base_clip, status=…, out_name='composite-silent.mp4', preview_name='preview.jpg')`
draws any face-landmarks.json-shaped dict over every frame of `base_clip` exactly like `mesh_worker.py` pass 2
(checked: byte-identical drawing on the same decoded frame; tessellation 1 px (50,170,205), lips 2 px (255,135,100),
eyes 2 px (130,255,150), ×0.45 when status ≠ tracked; libx264 crf 18 yuv420p, 24 fps; preview = first tracked frame
from 30 on), writing under temporary names then `os.replace` (never through a hard link). Pixel differences against
`.venv-face` outputs (~1–2 levels) come from the different PyAV/FFmpeg builds of the two venvs, not the drawing.
`mesh_edit`: base = `composite.base_clip(chain)` (refuses a legacy `composite-silent.mp4` base); writes edited
`face-landmarks.json`, `face-tracking.json` = the base tracking numbers unchanged + `edited: {off_frames, off_ranges,
keyed_frames, transformed_frames, expression_frames, changed_frames, tool, base_run, layer_sha, summary, note}`,
`composite-silent.mp4`, `preview.jpg`; report health "Face mesh from the timeline edits (…) drawn locally on N
frames. …". The runner builds `seedance-input.mp4` after it as usual. ~1.7 s for 195 frames at 960×550.

### Changes to shared code (additive)

- `branch()` (stages/branch.py): for every prep stage the child re-runs, a tool input under `edit-layer/` that the
  parent has is hard-linked into the child. So `POST /jobs/{mesh child}/branch {stage: face|composite|mask}` re-runs
  `mesh_edit` on the same saved edits (same inputs → same cache key; tested), and the same holds for the mask `edit_layer`.
- `editlayer.save()` calls `stages.base.unshare(child/'edit-layer')` before the tracks' `materialize()`: linked files
  are replaced by private copies, so a track writing its files (Agent 2's `copyfile` into `edit-layer/mask/`) can
  never write through into the parent (tested: re-saving from an edited child leaves that child sha256-identical).
- `edits.step()` (static/editlayer.js) is queued like commits: a fast Cmd+Z Cmd+Z used to send the second undo with
  a stale rev (409 + console error); now each undo/redo uses the rev the previous one returned.

### Verification (2026-10-23, port 8777, `PUPPETEER_OFFLINE=1`)

`b03ff4240ede4cdb96489a911a2c47e2` = hard-link copy of `85e5…` (status/run.json copied, reconstructed). Studio:
selecting Face switched to **Mesh edit** (depth composite, no baked mesh) with the live mesh + handles; leaving it
switched back. Jaw-open slider dragged to 1 on frame 40 → one commit, the overlay's mouth/chin visibly opened
(screenshots before/after). A real drag inside the mesh on frame 70 (move) and on the top circle (rotate) and the
corner (scale) on frame 82 → one commit per drag (rev +1 each); frames 71–81 showed the blended correction (nose tip
x shift 0.0549 → 0.0539 → 0.0511 → … 0.0050, eased). Keys on 40 and 52 (52 has no face in this clip) gave nose shifts
0.0200, 0.0212, 0.0244, 0.0294, 0.0356, 0.0426, **0.0500** (46), 0.0574, 0.0644, 0.0706 on 40–49 (identical to the
Python test values), then undone. Mask click + "Mesh off on range" 100–102, Cmd+Z ×2 / Shift+Cmd+Z ×2 undid and redid
both across tracks. Network panel: only `localhost:8777` (static files, `/runs/<id>/face-landmarks.json`, `PUT
/edits`, undo/redo, the mask preview); zero external requests. Save edits → exactly one child
`ff22c0b5627a4be88717786696b26568` (runs 68 → 69; face `mesh_edit`, `changed` "face: mesh off on frames 100–102, 2
transform keys (frames 70, 82), jaw on frame 40", no `calls.jsonl`); its `composite-silent.mp4` has zero mesh-coloured
pixels on exactly frames 100–102 (1277–2095 on 96–99 / 103–105), and differs from the parent's (mean 8.3–9.6 vs ~2
codec noise) on exactly 40 and 70–82. `b03f…` and `85e5…` sha256-identical before/after. 380 px:
`scrollWidth` 380, a real rotate-handle drag worked (handles now clamped onto the picture), panel 284 px without
overflow; that test edit was discarded. Fast-mode run `f5a3f11d…`: Mesh edit view = `original.mp4` with the live mesh.
Console: one 409 from the double Cmd+Z before the `edits.step` fix, none after. Session record:
`runs/_sessions/b03f…/saved-ff22c0b5…/`.

### Notes for Agent 4

- **Face import**: build a landmarks dict in the face-landmarks.json schema (`{fps, frames: [{frame, status, faces:
  [[{x, y} × 468|478]]}]}`), then `meshedit.render(folder, landmarks, composite.base_clip(folder, chain))` writes
  `composite-silent.mp4` + `preview.jpg` (refuse or warn when the point count is not 468/478; `draw_face` skips
  connections whose indices are missing). `meshedit.apply(landmarks, layer, aspect)` and `edited_section()` are pure.
- Mouth guidance: frames with no mesh drawn = `face-tracking.json` `missing_frames` ∪ `edited.off_frames` (the base
  numbers are kept unchanged on purpose); `face-landmarks.json` frames with `status: "off"` have no face.
- `editor.addView({id: 'mesh-edit'})` exists (order 15); the face track switches to it on select and back on leave
  (`setView(…, {chosen: true})`, so the review panel's preferred view follows).
- The face track's `markers()` = keys, off-range starts, expression-run starts; it only re-renders its panel on
  `onFrame` while paused.

## §A4 notes (Agent 4: words track, beats, mouth guidance, subtitles, Import my own, Download)

### What exists now

| piece | file | notes |
|---|---|---|
| Transcription, track hooks, beats, mouth guidance | `stages/words.py` | replaces Agent 1's stub (same `register_track('words', WordsTrack)`; the stub's count/summary wording is kept) |
| Local worker | `words_worker.py` (runs in `.venv-words`), `setup-words.sh` | mlx-whisper 0.4.3 + `models/whisper/whisper-large-v3-turbo` (1.6 GB); engine comparison in `docs/WORDS.md` |
| Subtitles (SRT, burn-in, toggle state) | `stages/subtitles.py` | PIL text over PyAV frames, audio packets copied |
| Import tools, upload store, branch plan | `stages/imports.py` | `import_depth`, `import_mask`, `keep_parent` (mask), `import_face`, `import_control`; registered last in each stage |
| Routes | `app.py` sections "words track" / "downloads" / "Import my own" | below |
| Track | `static/track-words.js` (swapped in `static/tracks.js`), CSS "Words track" + "Subtitles, downloads and imports" in `app.css` | `wordsPlaceholder` stays exported, unused |
| UI additions | `static/draft.js` (Insert dialogue beats; subtitles block in `mountFinal`), `static/stagecard.js` (Download links, Import my own…, imported chip), `static/runhead.js` + `static/runs.js` (imported chips), `static/editor.js` (mask.zip link) | |
| Small shared changes | `stages/base.py` (`Tool.imported`, in `describe()`), `stages/presets.py` (`describe_chain` labels imports, `mode_for_chain`: `import_control` → `original`), `stages/costs.py` (`words_fal`, pricing model `usd_per_started_minute`), `app.py` (`run_summary.imported`, `run_child` refreshes mouth guidance) | all additive |
| Tests | `tests/test_words.py` (14, one real local run skipped without `.venv-words`), `tests/test_imports.py` (9) | suite: 250 passed (one `test_editlayer` line changed, see below) |

### Endpoints as implemented

`GET /jobs/{id}/words` · `POST /jobs/{id}/words/transcribe {engine?, singing?, language?, confirm_cost?, estimate_only?}`
(synchronous, ~4 s locally; 402 for fal without `confirm_cost`; 400 + `bash setup-words.sh` fix when the venv or model is
missing; offline: local works, fal refused before any I/O) · `GET /jobs/{id}/words/beats` · `GET /jobs/{id}/subtitles.srt`
· `GET/POST /jobs/{id}/subtitles {burn}` · `GET /jobs/{id}/download/<folder>.zip` · `POST /jobs/{id}/import` (multipart
`stage`, `file`, `confirm_cost?`). Shapes in `docs/WORDS.md` §2/§6 and `docs/IMPORTS.md`.

### Layer schema (`layer.words`)

`{words: [{id, text, start, end}], singing, edited: [ids], replaced?: {engine, language}}`. Ids of words that came from
`words.json` are `f<index>` until edited; new words get `w<time><rand>`. The client keeps blocks frame-snapped; the save
hook normalizes anyway (`normalize_words`: sorted, trimmed text, ≥ 1 frame, an overlapping earlier word is trimmed to the
next start, inside the clip). `count` = edited ids (+1 for a re-transcription), `summary` "3 words edited" / "transcribed
again (10 words, singing mode)". `materialize` writes the child's `words.json` (`edited: true`, engine/language from the
parent or the re-transcription) **and `mouth-guidance.json`** (fresh() first).

### Spec changes (and why)

- **Paid fallback = ElevenLabs speech-to-text on fal**, not `fal-ai/whisper`: the Whisper page lists "$0 per compute
  second", so no honest estimate is possible; ElevenLabs lists $0.03/min and returns word timings natively. Estimate
  counts started minutes ($0.03 for the fixture).
- **`mouth-guidance.json` is rewritten in the child on save** (it was only CARRY-linked by Agent 1's stub);
  `tests/test_editlayer.py::test_words_only_save_is_one_done_child_at_prompt` now asserts a fresh file with the edited
  words and the parent's copy untouched, instead of the shared inode. It is also refreshed after every branch run
  (`app.run_child` → `words.refresh_guidance`), because a face re-run (mesh off) changes `mouth_hidden`.
- **SRT / beats / burn-in read the pending edits first**, then `words.json` (what you see on the lane is what you export).
- **Depth import** re-runs the mask stage, so it brings `mask: keep_parent` (new free tool: the parent's masks unchanged)
  in the same branch; otherwise SAM would be re-billed. **Control import** sets `face: off` via `also`, and
  `mode_for_chain` answers `original` for `import_control` so the review fingerprint covers the files that exist.
- Words in the last 0.15 s shorter than 20 ms are dropped at transcription (Whisper's tail artifact; large-v3 produced a
  170-word loop there).

### Gotchas for the reviewer

- The Browser pane was hidden for most checks: `requestAnimationFrame` does not run then, so the word blocks (drawn in
  the timeline's rAF `draw`) appear after the next frame (a screenshot triggers one). Not an app bug (Agent 1 note too).
- The draft step's "Insert dialogue beats" button is enabled only when the run has `words.json` or pending word edits
  (no 404 in the console). The words panel's .srt link likewise.
- `runs/_cache/words/` holds transcriptions (also the ones made by the browser checks); `runs/_imports/` the uploads.
- A transcription writes `words.json` + `mouth-guidance.json` into the run being viewed when it has none (allowed:
  additive analysis output, like the face report); burning subtitles writes `subtitles.json` + `*-subtitled.mp4` next
  to the untouched finals. Nothing else of mine writes into a run that is not a new child.

### Verification (2026-10-24, port 8778, `PUPPETEER_OFFLINE=1`)

`0be4cf2cadd945008a9c9131b6c75f12` = hard-link copy of `85e5…`. Words lane → Transcribe (free, local): 10 blocks in
4.1 s ("And I need you, and I miss you, and I'm"), `words.json` + `mouth-guidance.json` written; double-click "And" →
"Oh and" (rev 1); a real drag of its left edge to frame 18 = 0.75 s (one commit, rev 2); Split at playhead (frame 110)
→ "a" / "nd" (rev 3); select "a" + Merge with next (rev 4); reload → the same 10 words and rev 4. A mask click (frame
40) and "Mesh off on range" 100–102 → Cmd+Z ×3 / redo ×3 walked mesh → mask → words and back. Save edits → "Apply now"
→ exactly one child `b96aaa69bf334ac69da65d68a69d53df` (runs 71 → 72; changed "mask: 1 click on frame 40 applied ·
face: mesh off on frames 100–102 · words: 3 words edited"; its `words.json` has the edits, its `mouth-guidance.json`
marks 100–102 hidden; no `calls.jsonl`). In that child "Insert dialogue beats" put
`0.8–6.4 s says: "Oh and I need you, a nd I miss you,"` / `7.9–8.1 s says: "and I'm"` under the prompt (not
submitted). `GET …/subtitles.srt` → `attachment; filename="b96aaa69-subtitles.srt"`, three valid cues ending at
00:00:08,125. `5af8e90d1bf34849b7e768935da65cf2` = hard-link copy of `3c54f295…` (has a draft final): the burn toggle
was off by default ("No transcript yet…"); after Transcribe (vocals.wav: "And I need you, and I miss you, and I") it
turned on → `final-preview-subtitled.mp4` in 1.5 s, previewed with "And I need you, and I miss you," at 3.2 s, audio
packets identical (381), `final-preview.mp4` sha256 unchanged. Studio cards show Download links (folders as zip, mask.zip)
and "Import my own…" on depth / mask / face / composite. Mask round trip and mismatched import: `docs/IMPORTS.md`
(children `6f20c4d1543a468485988b4ba7894a1d`, `36536b28c76044c79109adf3f7e02896`; "imported" chips on card, header and
Runs list). 380 px: `scrollWidth` 380 (words panel 284 px, Studio cards with imports open, finish step). Console: no
messages. `85e5…` and `3c54…` sha256-identical before/after; the two copies only gained the additive files named above.
