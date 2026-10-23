# The UI (Foundation phase, Agent 2)

For Agent 3 (mask wand) and the reviewer. The frontend is plain HTML + CSS + ES modules under `static/`, served by
`app.py` (`GET /` → `static/index.html`, `/static/*`). No build step, no framework. Everything the old single-file
page did still works; it is now split into readable files and has three depths (Quick / Studio / Lab) plus a Runs page.

## 1. Files

| file | what it holds |
|---|---|
| `static/index.html` | Markup only: the shell (header with the view switch, `#notices`, `#job-banner`, `#view`) and one `<template>` per panel: `tpl-quick`, `tpl-studio-new`, `tpl-run-head`, `tpl-stage-card`, `tpl-review`, `tpl-editor`, `tpl-draft`, `tpl-final`, `tpl-lab`, `tpl-lab-tile`, `tpl-runs`, `tpl-run-row`. No inline script or style. |
| `static/app.css` | The light theme (same fonts, colours and card look as before), works from 380 px up. |
| `static/app.js` | Entry: loads the shared data (`/stages`, `/presets`, `/providers`, `/costs`), wires in-app navigation (`a[data-nav]`, `popstate`), renders the view for the URL. Exposes `window.puppeteer = {state, api, navigate, loadJob, registerReviewTool}`. |
| `static/state.js` | The `state` object, URL parsing (`?job=`, `&view=`, `&runs=`, `&stage=`), `navigate()` / `render()`, the token + timer registry (see §3). |
| `static/api.js` | `getJSON` (silent retry, up to 3 times with backoff, on network failures and 5xx), `send` (POST, never retried), `ApiError {message, fix, status, body}`, `plain(error)` → `{message, fix}` for anything thrown. The `api` object lists every endpoint the UI calls. |
| `static/ui.js` | DOM helpers (`tpl`, `el`, `$`), formatting (`usd`, `spent`, `when`, `ranges`), chips, page notices (`notice`, `showError`), file-input wiring, `videoSeconds(file)`. |
| `static/jobdata.js` | Loads and polls the job in the URL (`loadJob`, `poll`, `pollHD`), renders the job banner, `fixActions()` for failed jobs. |
| `static/review.js` | Step 02, the review panel (`mountReview`) and `registerReviewTool` (the mask-wand hook), `trackingLine()`. |
| `static/editor.js` | The timeline editor inside the review panel (`mountEditor`): view switch, stacked synced videos, overlay canvas, transport, keyboard, track panel, Save bar (`tpl-editor`). |
| `static/timeline.js` | Track registry (`registerTrack`, `tracks`) and the timeline component (ruler, playhead, range, zoom, lanes, markers). |
| `static/editlayer.js` | The `edits` client: pending edits (`GET/PUT/DELETE /jobs/{id}/edits`), undo/redo, save as one branch. |
| `static/tracks.js` | One line per editor track (Mask, Face, Words); `static/track-placeholders.js` holds the placeholders until `track-mask.js` / `track-face.js` / `track-words.js` replace them. |
| `static/track-face.js`, `static/meshedit.js` | The face mesh track (mesh off on a range, transform handles + keys, expression sliders, reset, the "Mesh edit" view) and the pure JS port of `stages/meshedit.py` it draws with; `static/face-connections.json` = MediaPipe's connection lists (exported once by `face_connections.py`). |
| `static/track-words.js` | The words track (Agent 4): Transcribe (free local Whisper, or fal with its estimate), word blocks (click, double-click to edit, drag edges), split / merge / add / delete, .srt / words.json / mouth-guidance.json downloads. |
| `static/draft.js` | Steps 03 and 04 (`mountDraft`, `mountFinal`): providers, saved references, the paid buttons with their estimate, manual import; "Insert dialogue beats" (step 03) and the subtitles block (step 04: "Burn subtitles into final", off by default, .srt export). |
| `static/stagecard.js` | One Studio card per stage (`mountStageCard`). |
| `static/export.js` | The export kit under step 04 (`mountExport`, `tpl-export`; World stage Agent 4): tick boxes per item (unavailable ones disabled with the reason), target preset with a "What's in it" line, the alpha format, the pending-edits note, "Export · free, local", progress, README + zip link, earlier exports. `docs/EXPORT.md`. |
| `static/runhead.js` | The run header (`mountRunHead`): name, state chip, spent so far, parent, what changed, Add to Lab, Save as preset. |
| `static/quick.js` | The Quick view (`renderQuick`) and `mountPanels` / `mountFlow` (the step 02–04 panels shared with Studio). |
| `static/studio.js` | The Studio view (`renderStudio`) and the legacy "Preparation method" form (`mountLegacyForm`). |
| `static/lab.js` | The compare view (`renderLab`): picker, synced playback, chain diff, picks. |
| `static/runs.js` | The Runs page (`renderRuns`): tree and flat list. |

## 2. URLs, views and state

- `/?job=<32 hex>` opens a run (the old deep link; unchanged). `&view=quick|studio|lab` picks the depth; no
  `view` means `quick`. `/?view=runs` is the Runs page (`&flat=1` for the old flat list). The Lab keeps its selection
  in `&runs=<id>,<id>&stage=<file>` (and in `sessionStorage` as a fallback).
- Navigation is in-app: `a[data-nav]` links and `navigate(params)` call `history.pushState` then `render()`. A render
  clears the notices, the job listeners and the job data, and mounts the view into `#view`.
- `state` (in `state.js`): `jobId`, `view`, the shared data (`registry` = `GET /stages`, `presets`, `providers`,
  `providerDefault`, `costs`), the job data (`job` = status dict, `run` = `GET /jobs/{id}/run`, `files` = Set of
  `GET /jobs/{id}/files`, `review`, `tracking` = `face-tracking.json`, `generation` = `generation.json`, `hd`),
  `selectedPreview` (the review tab, kept stable across refreshes), `labRuns`, `labStage`.
- Views that show a job call `onJobData(fn)` once and then `loadJob()`; `fn` is called after every load and every
  poll. Panels are mounted once and have an `update()` that re-reads `state`, so videos are not reset while polling.

## 3. The job banner vs page notices (the stale banner fix)

- `#job-banner` is written only by `jobdata.renderBanner()` and shows only `state.job` of `state.jobId`. Every
  async load and every timer carries the token that was current when it started (`state.token`); `render()` bumps
  the token and clears every timer (`stopTimers()`), and a response is dropped when `current(token, jobId)` is false.
  So a poll started for one run can never write into the page after the user moved to another run, and a
  `loadRuns`-style failure never touches the banner.
- `#notices` is for everything else: upload failures, saved presets, 402 cost refusals, network trouble. Use
  `notice(message, {fix, kind, actions, key})` or `showError(error, {actions, key})`; `key` replaces an earlier
  notice with the same key. Actions are `[{label, run, secondary?}]` and render as fix buttons.
- `#notices` is a **fixed toast stack** at the bottom of the viewport (bottom-right, 460 px wide from 720 px up;
  full width minus 12 px gutters below), so a notice raised from the editor's Save bar, a track tool or a Studio
  card is visible wherever the page is scrolled (review fix 1). Newest at the bottom, at most 4 (the oldest goes),
  scrolls inside itself above 60 vh. Errors (`role="alert"`) and notices with actions stay until × / Esc / an
  action; `ok` notices fade after 10 s and plain warnings after 16 s, paused while hovered or focused. While an
  action runs its buttons are disabled and the label gets "…"; the notice closes when it resolves. The job banner is
  unchanged (in the page flow, bound to the job in the URL).
- Every error on screen is `message` + `fix`: the server's `{detail|message, fix}` body, or a mapped sentence
  (network: "The app could not be reached. Is it still running? Restart it and reload."). `plain()` in `api.js`
  never lets an array, object or `Error:` prefix through.

## 4. The review panel (where the mask wand goes)

`review.js` mounts `tpl-review` and updates it from `state`:

- While the job runs: the progress line says "Preparing… <status>" and the review line says the review opens when
  it finishes. After a failure: "Preparation failed: <reason>" + the fix + fix buttons (`fixActions()`: "Re-run with
  lenient gaps · free" for a strict face-tracking failure, "Open the failed stage in Studio"). Only when the files
  exist does the real review state show (`GET /jobs/{id}/mask-review` → `preparing | failed | unavailable | pending |
  approved | rejected`; the backend got the first two additively, `mask_review.state(folder, job)`).
- Tabs come from the files present (`TABS` in `review.js`: Prepared input, Original, Depth, Mask, Composite). The
  `<video data-video>` keeps its `src` unless the selected file changes.
- The face-tracking line (`trackingLine(t, jobState, depth)`): red only when `ok` is false **and** the job is in
  error (strict rule blocked the run); yellow for any warning with `ok` true (lost ranges in lenient mode, many
  interpolated frames); green otherwise. Wording: "Face lost 0.42–0.71 s and 2.08–2.58 s; the depth composite
  stands in there. Tracked 163 of 195 frames, …".
- The checkbox + Approve / Needs fixing post to `POST /jobs/{id}/mask-review` with the fingerprint; a 409 (the
  files changed) shows a notice with a "Reload the latest preview" action.

**Adding controls (Agent 3).** In your module:

```js
import { registerReviewTool } from './review.js';   // or window.puppeteer.registerReviewTool
registerReviewTool((box, ctx) => {
  // box: the [data-review-tools] element inside the panel (between the video and the review box). Empty it and draw.
  // ctx: {jobId, files (Set), review, video (the <video>), selected (file name of the tab), mode, refresh()}
  // Pause ctx.video, read ctx.video.currentTime for the frame, send your request, then ctx.refresh() to reload the
  // job data: the fingerprint changes after a mask edit, so the approval clears by itself and the panel re-renders.
});
```

The callback runs after every `update()` (every poll and every reload), so keep your own state outside the DOM you
redraw, or only redraw when `ctx.jobId` / `ctx.selected` changed. Import your module from `app.js` (one line) or add a
second `<script type="module">` to `index.html`. For a hosted (paid) wand tool, follow the cost-meter rule: show the
estimate on the button first and send `confirm_cost=true` from that click; on a 402, `showError(e, {actions: [...]})`
with a "Run anyway · about $x" action (see `costActions` in `draft.js`). A mask edit should be a branch at `mask`
(`api.branch(id, {stage: 'mask', tool, params, confirm_cost})` then `navigate({job: child, view})`).

### The timeline editor (stage 2, Agent 1)

The viewer of the review panel is now the timeline editor (`static/editor.js`, mounted once into `[data-editor]`;
contract and APIs in `docs/TIMELINE-SPEC.md` §3 and §A1). The view switch shows the `TABS` present (plus views added by
tracks with `editor.addView`); every view keeps its `<video>` alive, so switching is instant and keeps the frame. Under
the picture: the transport (−1 s, ◀ frame, play/pause, frame ▶, +1 s, "frame 52 / 195 · 2.17 s", zoom − + fit), the
caption and the Download link of the current view, then the timeline (one playhead over the Mask / Face / Words lanes;
drag = range, click = playhead, click a track name = its tools in the panel below), then the Save bar ("N pending
edits · Undo · Redo · Discard · Save edits"). Keys: ← → frame, Shift+← → second, Space, Home/End, `[` `]` markers, Esc,
Cmd/Ctrl+Z, Shift+Cmd/Ctrl+Z, Ctrl+Y. The review box, approval, audio downloads and `[data-review-tools]` are
unchanged; `registerReviewTool` callbacks get `ctx.video` = the editor's base video (and `ctx.editor`). New endpoints
used: `GET/PUT/DELETE /jobs/{id}/edits`, `POST /jobs/{id}/edits/undo|redo|save`, and `GET /jobs/{id}/mask/frame?i=0`
(frame count / fps headers).

**Mask track (Agent 2, `static/track-mask.js`).** Select the Mask lane: a click on the picture adds a pending + fix
(Alt-click, right-click or "− exclude" = −; "Brush" paints / erases with a radius and "on N frames from here"), shown
at once on that frame (tint + outline; markers on the lane, `[` `]` jump). The panel lists the pending fixes (frame,
type, ✕, click to jump; Undo last, Clear all), "Apply to clip · quick preview · free" and "Apply at full quality"
(paid tools show "Apply with SAM 3 on fal · about $x" and send `confirm_cost=true` from that click), then "Accept ·
full quality" after a quick Apply; problem ticks (red bars + shaded spans over the area sparkline, which turns green
once the session mask differs), Prev / Next tick, "Grab hands on flagged frames · free" / "on <range>"; view buttons
B/W · Composite · Tint (Tint = original + the mask video with `mix-blend-mode: screen` and an SVG colour-matrix
filter `#mask-tint`; the Mask tab follows the session mask). A pending fix blocks "Save edits" with "Apply now" /
"Save without them". New calls: `POST /jobs/{id}/edits/mask/preview|apply|hands`, `GET /jobs/{id}/mask/problems`.

**Face track (Agent 3, `static/track-face.js`).** Select the Face lane: the view switches to **Mesh edit** (the depth
composite, or the original in Fast mode, *without* the baked mesh; leaving the track switches back) and the edited mesh
is drawn live on the overlay with the same colours as `mesh_worker.py` (dimmer on filled frames). A dashed box around
the mesh: drag inside = move, the corner square = scale, the top circle = rotate; each drag is one undoable commit
(a key on that frame). Panel: "Applies to frame N / frames a–b" (the selected range), "Mesh off on this frame / on
range" and "Mesh on", dx / dy / scale / rot fields (the frame's effective correction; editing one sets a key), six
expression sliders (jaw open, mouth smile, mouth pucker, blink left / right = the person's eyes, brow up; commit on
release, applied to the frame or the range), ◀ Prev key / Next key ▶, Reset frame, Reset range, view buttons Mesh edit
· Prepared input. Lane: tracked / filled / missing / off colours, mesh-off ranges hatched, keys ◆, the blended span as
a bar, expression frames ●; `[` `]` jump between them. No server calls beyond the edit-layer PUTs and two static GETs
(`/runs/<id>/face-landmarks.json`, `/static/face-connections.json`).

**Words track (Agent 4, `static/track-words.js`).** Select the Words lane: "Transcribe · free, runs locally" (or the fal
engine "· about $0.03", confirm on that click) with a Singing mode checkbox; each word is a block (click = select and
jump, double-click = edit its text, drag an edge = timing, snapped to frames, never over a neighbour, one undoable
commit per drag); panel: the selected word's text and times, Split at playhead, Merge with next, Add word at playhead /
in range, Delete, Prev / Next, Export subtitles (.srt), words.json, mouth-guidance.json. The current word is drawn as a
caption on the picture while the track is selected. Step 03 has "Insert dialogue beats" (timed lines appended to the
prompt textarea, editable; enabled when the run has words); step 04 has "Burn subtitles into final" (off by default,
free, local; preview + download of the subtitled copy) and the .srt export. New calls: `GET /jobs/{id}/words`,
`POST /jobs/{id}/words/transcribe`, `GET /jobs/{id}/words/beats`, `GET /jobs/{id}/subtitles.srt`, `GET/POST
/jobs/{id}/subtitles`. Details: `docs/WORDS.md`.

## 5. Stage cards (Studio)

`stagecard.js` → `mountStageCard(rack, stageDef, index)` where `stageDef` is one entry of `GET /stages` (`name`,
`label`, `automatic`, `tools[]` with `params` schema). `update({active})` reads `state.run.run.chain[stage]` and
`state.run.reports[stage]`:

- Tool dropdown: every tool with `· paid` / `· experimental` suffixes, `off` where the registry has it; the on/off
  toggle flips between `off` and the last on-tool. Params come from the selected tool's schema (`bool` → checkbox,
  `number` → number input, `choice` → select, `string` → text; the prompt `text` → textarea).
- Preview: the first existing file of `PREVIEW[stage]` then the report's `outputs` (video, image or audio); the
  prompt card shows the text.
- Health line (`report.health`), numbers (`frames` covered / filled / missing, `gaps` in seconds, `seconds`,
  `cost_usd`, `cached_from`), warnings, `error.message + fix`, state chip (`done | cached | off | error | missing`,
  plus `running` / `waiting` while the job runs: the first stage without a report is the active one).
- "Re-run from here": first click → `POST /jobs/{id}/estimate`; free → `POST /jobs/{id}/branch` at once (no
  confirmation needed); paid → the button becomes "Run now · about $x · click to confirm" and the second click sends
  `confirm_cost=true`. Any param change resets the estimate. A 402 shows a notice with "Run anyway · about $x". After
  the branch the page navigates to the child (`?job=<child>&view=studio`) and polls it.
- Fix button on a failed strict face stage: "Re-run with lenient gaps · free".
- Download (Agent 4): one link per output of the report (`/runs/<id>/<file>`), folders as `GET /jobs/{id}/download/<folder>.zip`,
  plus "Masks as PNGs (mask.zip)" on the mask card. "Import my own…" (depth, mask, face, composite): a file input with the
  accepted formats and "Import · free" → `POST /jobs/{id}/import` → the page opens the new child; an "imported" chip marks a
  stage whose tool is an import (the card then shows "Imported file: <name>" instead of the raw params). The run header
  and the Runs rows show "imported · <stage>" chips. Details: `docs/IMPORTS.md`.

### Export kit (stage 3, Agent 4)

Under step 04 (`mountFinal` mounts `mountExport(node)`; works with no draft and no generator keys) and from the Studio
run head's "Export…" link (scrolls to `#export`). Target picker (Seedance web, Kling, ComfyUI, After Effects / Nuke,
Custom) re-ticks the preset's default items and shows "What's in it: …"; one tick box per item, disabled with the plain
reason when the run lacks the source; the alpha format (ProRes 4444 .mov or RGBA PNG sequence) appears when a
transparent item is ticked; the pending-edits line says "N pending edits will be saved first (free) and the export made
from the new run" (or the track's refusal / the paid refusal, with the button disabled); "Export · free, local" →
`POST /jobs/{id}/export`, polled with `GET /jobs/{id}/export/{name}` every 0.7 s (progress line), then the README in a
`<pre>`, the "Download <name>.zip ↓" link (`GET /jobs/{id}/export/{name}.zip`), "Open the new version →" when the edits
were saved first, and "Earlier exports" with a zip link each. Details and the reasoning per preset: `docs/EXPORT.md`.

## 6. Endpoints per view

| view | calls |
|---|---|
| all | `GET /stages`, `GET /presets`, `GET /providers`, `GET /costs` once at boot |
| Quick (form) | `POST /estimate` (preset + seconds + prompt/provider/clean_dialogue) for the button label and the per-preset cost lines; `POST /jobs` (multipart: `video`, `preset`, `prompt`, `provider`, `clean_dialogue`, `char1`, `char2`, `confirm_cost=true`) |
| job panels (Quick + Studio) | `GET /jobs/{id}/run`, `GET /jobs/{id}/files`, `GET /jobs/{id}/mask-review`, `GET /jobs/{id}` (poll every 2.5 s while running), `GET /runs/{id}/face-tracking.json`, `GET /runs/{id}/generation.json`, `GET /jobs/{id}/hd`; `POST /jobs/{id}/mask-review`; `POST /jobs/{id}/seedance` (`confirm_cost=true`); `POST /jobs/{id}/hd` (`confirm_cost=true`); `POST /jobs/{id}/finish`; `POST /presets` |
| Studio cards | `POST /jobs/{id}/estimate`, `POST /jobs/{id}/branch`; legacy form: `POST /estimate` with `mode`, `POST /jobs` with `mode` |
| export kit (step 04) | `GET /jobs/{id}/export`, `POST /jobs/{id}/export`, `GET /jobs/{id}/export/{name}` (poll), `GET /jobs/{id}/export/{name}.zip` |
| Lab | `GET /jobs/tree` (picker), `GET /jobs/{id}/run` + `GET /jobs/{id}/files` per tile, `GET /compare/picks`, `POST /compare/picks` (`runs`, `stage`, `picked`, `note`) |
| Runs | `GET /jobs/tree` (tree) or `GET /jobs` (flat) |

Backend additions made for the UI (all in `app.py`, tested in `tests/test_ui_routes.py`): `char1` / `char2` on
`POST /jobs` (saved as `char1-reference.<ext>` / `char2-reference.<ext>`, same rules as the seedance route);
`POST /estimate`; `GET/POST /compare/picks` (`runs/_compare/picks.json`, one pick per sorted-ids + stage);
`seconds` and `estimates {draft, complete}` on `GET /jobs/{id}/run`; `mask_review.state(folder, job)` with the
`preparing` / `failed` states and a `fix` on `unavailable`.

## 7. Cost meter rules (keep them when adding buttons)

Every paid button shows the estimate in its label before anything runs ("Prepare · about $0.40", "Create draft ·
about $2.15", "Approve & complete at 1080p · about $11.34", "Run now · about $0.13 · click to confirm") and sends
`confirm_cost=true` only from that click. Free actions say so ("free, runs locally"). A 402 answer is shown with its
`message` and `fix` plus a button that re-sends with the confirmation. Paid requests are never retried by the page;
only GET polling retries (3 times, backoff). "Spent so far: $x.xx" comes from `run.json.cost_usd_total` and is shown
in the run header and on every Runs row.

## 8. Checking it

`PUPPETEER_OFFLINE=1 PORT=8773 .venv/bin/python launch.py`, then `/?view=runs`, `/?job=<id>&view=studio`,
`/?view=lab&runs=<a>,<b>,<c>`, at desktop width and at 380 px (`document.documentElement.scrollWidth <= 380`, no
console errors). Free things that really run offline: the Talking head preset (strict; the fixture clip fails it on
purpose), a saved lenient face preset, any branch at the face stage, "Re-run with lenient gaps".

## 9. Verification artefacts left under `runs/` (Agent 2, 2026-10-22)

All made offline and free, never touching the fixture runs: `9e44f470…` (hard-link copy of `85e5dbe6…` with a
reconstructed `run.json`), its children `464c5006…` (face pad 1.8 → 1.82) and `1a62b8d2…` (pad → 2.0, made through
the Studio card), `f5a3f11d…` (branch of the failed Fast run `0b6ee85c…` via the "Re-run with lenient gaps" fix
button, then approved in the UI), `17b938cf…` (Quick one-click run with a saved lenient preset and a `char1`
reference). `runs/_compare/picks.json` holds one Lab pick. The saved preset was removed again; `presets.json` is as
before. No `calls.jsonl` exists in any of them. Note for Lab checks: a browser pauses muted media started without a
user gesture when it is off screen, so drive the Play button with a real click.

## 10. Mask wand and input doctor in the UI (Agent 3)

- `static/wand.js` registers itself through `registerReviewTool` (imported from `app.js`). On a depth-mode run
  that is done (files include `mask.mp4`, mode not `face_mesh`) it adds a "Fix the mask" button under the video.
  Open: the video pauses, its controls hide, and a `.wand-overlay` (an `<img>` of `GET /jobs/{id}/mask/frame` plus a
  `<canvas>` for markers and strokes) is placed over the rendered video box inside `.viewer` (now
  `position: relative`), sized from `videoWidth/videoHeight` against the element's box so letterboxing does not
  shift the clicks, and repositioned by a ResizeObserver. Frame steps (−1 s, ◀ frame, frame ▶, +1 s) reload the frame
  and keep the video's `currentTime` in sync. Click = include, Alt-click / right-click / the "− exclude" toggle =
  exclude; every click adds a marker and a pending edit and the preview from `POST /jobs/{id}/mask/preview`
  replaces the frame image. Tools: Local propagation (free, default), SAM 3 on fal · paid, SAM 2 on Replicate · paid
  (the estimate from `POST /jobs/{id}/estimate` is on the Apply button; that click sends `confirm_cost=true`; a 402
  shows "Run anyway · about $x"), Brush (paint / erase, radius slider, "on N frames from here"; strokes are drawn on
  the canvas and sent as `strokes`). Undo last, Clear all, "Apply to the whole clip · free" → `POST
  /jobs/{id}/mask/apply` → `navigate({job: child, view})`; the child opens with its review pending. Closing restores
  the video controls. Keep the wand's state outside the DOM it redraws: the review panel calls every tool after
  each poll, and the module keeps one state object per job id.
- Stage cards: `renderChecklists(report)` in `static/stagecard.js` lists `data.checks`, `data.fixes` (their
  `note`) and `data.advice` under the health line for any stage that reports them (today: the input doctor).
  CSS: `.checklist`, `.checklist-title`, `.wand*` in `app.css`.
- New API calls used by the UI: `GET /jobs/{id}/mask/frame?i=N` (read with `fetch` for the `X-Frames` / `X-Fps` /
  `X-Width` / `X-Height` headers), `POST /jobs/{id}/mask/preview`, `POST /jobs/{id}/mask/apply`,
  `POST /jobs/{id}/estimate` with `{stage: 'mask', tool, params: {edits}}`.

## 11. Verification artefacts left under `runs/` (Agent 3, 2026-10-23)

`5a8e8a0b…` (hard-link copy of `85e5dbe6…`) and its mask-wand children `76f13faa…`, `6e4eec6f…`, `7a8e463b…`,
`8f6e9537…` (see docs/MASK-WAND.md "Verification artefacts"), plus `431506e4…` (Talking head preset on the fixture
upload, input-doctor card checked in Studio). No `calls.jsonl` exists in any of them. At 380 px with the wand open
`document.documentElement.scrollWidth` is 380 and the overlay box equals the rendered video box.

## 12. Background row, Background chip and the Set / Look / Light panel (Agent 1, World stage)

- `static/slots.js` holds it all: `fitRect` / `parseFit` (the plate maths, same as `stages/plates.py`), `assetPicker({kind,
  value, onChange})` (thumbnails from `GET /assets?kind=` plus an "Upload image…" input → `POST /jobs/{id}/assets`),
  `backgroundControls(box, {tool, params, set, jobId})`, `backgroundChip(chain, jobId)` and `mountSlots(before)`.
- **Composite card (Studio).** `stagecard.js` skips the four background params in its generic loop for `depth_cutout`
  and calls `backgroundControls`: a Background select (Original frames / Full depth / Plain colour / Set image with one
  line each), the plain colour when `plain`, and for `set_image` the set-plate picker plus a canvas: the plate drawn
  with `fitRect`, the first frame (`GET /jobs/{id}/mask/frame?i=0`, with the mask outline) half transparent over it;
  drag = move (frame fractions), the slider = scale, "Centre & cover" resets. Every change goes through the card's
  `set()` so "Re-run from here" (free: composite + face are local) branches with `{background, set_image, set_fit}`.
  The `original` composite tool shows one line: no depth person, so no background to choose.
- **Review panel.** A chip row (`.slot-chips`, before `[data-review-tools]`) shows "Background · Set image" when the
  composite tool is `depth_cutout`; it links to `/?job=<id>&view=studio#stage-composite` (Studio scrolls to the card).
- **Draft step.** `mountSlots` mounts `tpl-slots` above the prompt textarea (`draft.js` calls `slots.update()` in its
  `update()`). Set (five modes with one line each; the picker for `set_ref` / `true_swap`, a textarea for `prompt`),
  Look (three modes; the picker for `style_ref`, a textarea for `prompt`), Light (one line), the task line
  "Task · reference (set changed)" / "Task · editing (original set)" / "(chosen by you)" (plus one sentence when the
  generator is Enhancor: no task setting, recorded as not applicable), and "Saved with this run (slots.json)". Changes
  are saved at once (`PUT /jobs/{id}/slots`, text fields debounced 500 ms). `original_depth` and `true_swap` show
  "Apply as background (new run) · free": `POST /jobs/{id}/branch` at `composite` with `background: full_depth` or
  `set_image` (+ the plate and fit), then `PUT /jobs/<child>/slots` with the same slots and `navigate` to the child;
  when the run already has that background the note says "Applied in this run". Picking `true_swap` on a run whose
  composite already has a plate adopts that plate. Mount points for Agents 2 and 3 inside `tpl-slots`:
  `[data-slot=prompt-builder]` and `[data-slot=generator]` (empty divs under the task line).
- New calls: `GET/PUT /jobs/{id}/slots`, `POST /jobs/{id}/assets`, `GET /assets`, `GET /assets/{name}`,
  `GET /jobs/{id}/mask/frame?i=0` (the canvas frame). CSS: `.slots*`, `.asset*`, `.bg-plate`, `.bg-canvas`, `.slot-chips`.
- Verification artefacts (2026-10-24, port 8781, offline): `46bb5dfe…` (hard-link copy of `0be4cf2c…`, own
  status / run.json / stages/), its composite children `459087f5…` (original), `503a4e8b…` (full depth), `9f3aabb3…`
  (plain gray), `08a838f2…` (set image via the API), `721368c2…` (set image placed by dragging on the card),
  `cdc475cc…` (full depth from "Apply as background" in the draft step, slots saved on it), and `03b6e510…` (the plain
  error for a missing plate). The plate is `runs/_assets/f7f1c8783ca9d58e.png`. No `calls.jsonl` anywhere; the fixture
  and the copy are sha256-identical before and after; 375 px wide: no horizontal scroll, no console errors.

## 13. Generator slot (Agent 3, World stage)

- `static/generator.js` `mountGenerator(host, {select, facts, onChange})`, mounted by `draft.js` into `[data-slot=generator]` inside
  `tpl-slots` (under the task line, after the prompt builder). Data: `GET /jobs/{id}/generators` (normalized capabilities,
  `configured` + `key`, `summary`, `estimate_usd` / `estimates` per resolution, `limits` = `supports(caps, slots)`), reloaded when the
  slots panel reports a save (`[data-saved]` text) and on every `update()`.
- One radio button per generator in `providers.GENERATORS` order (Enhancor, fal · Seedance 2.5, Wan 2.2 Animate · replace (fal)):
  configured ones show the estimate ("about $2.15 draft" / "about $0.49 · one render"); unconfigured ones are disabled and say
  "not configured · FAL_KEY" (tooltip: the `.env` line). Then the summary line, the limits list ("Set · … takes one reference image:
  the set image is ignored here." + the nearest configured generator), a Resolution select only for a generator that renders once at a
  chosen resolution (wan: 480p/580p/720p with the price per option), and the draft line ("Draft 480p → 1080p on approval (the same
  draft completed)" or "One render at 480p. Wan Animate has no draft to complete …"). Once a draft exists the picker is locked to
  the generator that made it.
- Side effects of a choice: `PUT /jobs/{id}/slots {generator: {name, resolution}}`; the legacy `select[name=provider]` gets the same
  value and its row is hidden (the form still submits it); the Create-draft button shows the chosen generator's estimate; the Set
  select's `set_ref` / Look select's `style_ref` options are disabled (tooltip = the sentence, label "· not with Wan …") when the
  generator has no such slot; the Character 2 upload is disabled with the sentence; Character 1 accepts images only when the
  generator takes no identity video; the slots task line adds "… has no task setting …" when `tasks` is empty.
- Step 04: a run whose generator has `finalize: null` hides the HD button and shows `finalize_hint` under "This render is the final".
- Checked 2026-10-24 on port 8783 (offline) with the copy `ec49f86d…`: 380 px without horizontal scroll, no console errors, and
  with `FAL_KEY= ENHANCOR_API_KEY=` every generator unconfigured with its key name while prep / edit / export routes keep working.
