# Mask wand

The wand lets the user pause on a frame, click **+** to include a region the text-prompt mask missed (a hand, a prop) or Alt-click **−** to exclude spill, and have a hosted model propagate that point prompt through the whole clip, returning per-frame masks the app can merge with the existing SAM 3 zip (`mask_<frame>.png`, 0/255).

## Model research

Research date: 2026-10-22. Field names below are copied from the live schemas (fal OpenAPI JSON at `https://fal.ai/api/openapi/queue/openapi.json?endpoint_id=<id>`, Replicate `https://replicate.com/<owner>/<model>/llms.txt` and `/api/schema`). Anything not seen in a schema or source file is marked **unverified**.

### 1. Does the current SAM 3 path accept point prompts?

| Model | Point / box prompts for video | Evidence |
|---|---|---|
| Replicate `lucataco/sam3-video` (pinned `408f82fc…`, latest on page) | **Schema yes, implementation no.** Input `visual_prompt` ("Optional: JSON string defining visual prompts (points/labels) or bounding boxes") exists, expected JSON `{"frame_idx": 0, "points": [[x, y], …], "labels": [1, 0], "box": [x1, y1, x2, y2]}` (dict or list of dicts). But `predict.py` only parses it and prints `"Visual prompt received for frame {frame_idx}, but full logic pending implementation."`; tracking runs on the text prompt alone (`propagate_in_video_iterator(..., max_frame_num_to_track=len(frames))` from frame 0). Other inputs: `video`, `prompt`, `negative_prompt`, `mask_only`, `return_zip`, `mask_opacity`, `mask_color`. Output: one URI (mp4, or zip with `mask_%05d.png`, 0/255, all objects OR-merged). | https://replicate.com/lucataco/sam3-video/llms.txt ; https://raw.githubusercontent.com/lucataco/cog-sam3-video/main/predict.py (lines 115–163) |
| Replicate `8digit/gener8-sam3` | **No.** Inputs are only `video`, `prompt`, `preview`. Output: zip with `labels/labels_%05d.png` (16-bit label map, one id per object) + `objects.json`, optional preview mp4. Up to 2000 frames. | https://replicate.com/8digit/gener8-sam3/llms.txt |
| fal `fal-ai/sam-3/video` | **Yes.** `video_url` (required), `prompt`, `text_prompt` (deprecated), `point_prompts[]` of `PointPromptBase {x, y, label (0/1), object_id}`, `box_prompts[]` of `BoxPromptBase {x_min, y_min, x_max, y_max, object_id}`, `detection_threshold` (0.5), `apply_mask` (default true), `video_output_type` (`X264 (.mp4)` / `VP9 (.webm)`). **No `frame_index` on this endpoint** – points are anchored to frame 0 (unverified; the field simply does not exist). Output: `video` (File), optional `boundingbox_frames_zip`. $0.005 per 16 frames. | https://fal.ai/models/fal-ai/sam-3/video/llms.txt ; OpenAPI `endpoint_id=fal-ai/sam-3/video` |
| fal `fal-ai/sam-3/video-rle` | **Yes, with frame index.** `video_url`, `prompt`, `mask_url` + `frame_index` (initial mask), `point_prompts[]` of `PointPrompt {x, y, label (0/1), frame_index, object_id}`, `box_prompts[]` of `BoxPrompt {x_min, y_min, x_max, y_max, frame_index, object_id}`, `detection_threshold`, `apply_mask` (default false), `boundingbox_zip`. "Prompts sharing an object id refine the same object. When a text prompt is also given, the id selects which detected object the point refines." Output per the API page: `rle` (`string | list<string>`, "Run Length Encoding of the mask"), `metadata`, `scores`, `boxes`, optional `boundingbox_frames_zip`; a `…RLEFileOutput` variant returns `rle` as a File. $0.005 per 16 frames. | OpenAPI `endpoint_id=fal-ai/sam-3/video-rle` ; https://fal.ai/models/fal-ai/sam-3/video-rle/api |
| fal `fal-ai/sam-3-1/video` and `/video-rle` (SAM 3.1, "Object Multiplex") | Same fields as the SAM 3 twins plus `max_num_objects` (16) and, on `video-rle`, `return_object_rles` ("Also return every tracked object's own mask in each frame, with an id the object keeps for the whole video. The merged rle is returned as before."); output adds `objects: list<list<ObjectRLE {object_id, rle, box (cxcywh, normalized)}>>`. $0.01 per 16 frames. | OpenAPI `endpoint_id=fal-ai/sam-3-1/video-rle` ; https://fal.ai/models/fal-ai/sam-3-1/video-rle/api |
| fal `fal-ai/sam3/video`, `fal-ai/sam-2/video` | Do not exist (OpenAPI returns `null`). | — |

### 2. Hosted SAM 2 video models with point prompts

| | Replicate `meta/sam-2-video` | fal `fal-ai/sam2/video` |
|---|---|---|
| Version / id | latest `33432afdfc06a10da6b4018932893d39b0159f838b6d11dd1236dff85cc5ec1d` | `fal-ai/sam2/video` |
| Inputs | `input_video` (req), `click_coordinates` (req, `'[x,y],[x,y],...'`, sets the point count), `click_labels` (`'1,0,1'`, 1 fg / 0 bg, last value repeats), `click_frames` (`'0,10,20'`, last value repeats, default all frame 0), `click_object_ids` (`'person,dog'`, same id = same object, auto `object_N`), `mask_type` enum `binary` (default) / `highlighted` / `greenscreen`, `annotation_type` `mask`/`box`/`both` (ignored for binary & greenscreen), `output_video` (bool, default false = image sequence), `video_fps` (30), `output_format` `webp` (default)/`jpg`/`png`, `output_quality` (jpg/webp only), `output_frame_interval` (1) | `video_url` (req), `prompts[]` of `PointPrompt {x, y, label (enum 0/1, default 1), frame_index (default 0)}`, `box_prompts[]` of `BoxPrompt {x_min, y_min, x_max, y_max, frame_index}`, `mask_url` (initial mask), `apply_mask` (false), `boundingbox_zip` (false). **No `object_id`** – all points refine one object (unverified; fal's README does not say how multiple points are grouped). |
| Output | Array of URIs (iterator). `output_video=false` → one image per frame (`png` gives lossless B&W masks when `mask_type=binary`); `output_video=true` → one mp4 at `video_fps`. | `video` (File; mp4 of masks, or overlay when `apply_mask=true`), optional `boundingbox_frames_zip`. No per-frame PNG or RLE option. |
| Multiple prompts on different frames | Yes – README example `click_frames: '0,0,10,20,20'` with mixed labels and ids. | Yes – each `PointPrompt` carries its own `frame_index`. |
| Backward + forward propagation | **Unverified.** README says nothing. Upstream SAM 2 `propagate_in_video(start_frame_idx, max_frame_num_to_track, reverse=False)` only goes one way per call; a wrapper must call it twice to cover both sides of a mid-clip click. Treat as forward-only until tested. | **Unverified** (same caveat). |
| Max length / size | Not stated. Readme: "Higher resolutions … require more processing time." | Not stated; accepts mp4, mov, webm, m4v, gif. |
| Price | Nvidia L40S, $0.000975/s; page: "approximately $0.029 to run … or 34 runs per $1"; "Predictions typically complete within 30 seconds" (varies with input). | Page lists "$0 per compute seconds" (placeholder). fal docs: models without output pricing "fall back to per-second billing based on the GPU machine type". Real rate **unverified**; H100 list price is $0.00125/s. |
| Sources | https://replicate.com/meta/sam-2-video/llms.txt ; https://replicate.com/meta/sam-2-video ; https://replicate.com/pricing | https://fal.ai/models/fal-ai/sam2/video/llms.txt ; OpenAPI `endpoint_id=fal-ai/sam2/video` ; https://fal.ai/docs/documentation/model-apis/pricing |

No other hosted SAM 2 video endpoint with point prompts was found (fal `sam2/image` and `sam2/auto-segment` are image-only).

### 3. Recommendation

**Primary: fal `fal-ai/sam-3/video-rle`** (SAM 3, $0.005 per 16 frames ≈ $0.075 for a 10 s 24 fps clip). It is the only hosted endpoint that has every field the wand needs in one call: `point_prompts[{x, y, label, frame_index, object_id}]` so the + and − clicks can land on the paused frame, a text `prompt` so the existing "person"-style prompt and the clicks refine the *same* object (`object_id` "selects which detected object the point refines"), and a mask-only output (`rle`) that we decode to per-frame 0/255 PNGs without touching a video codec. SAM 3 is also the model already in production, so quality and mask edges stay consistent with the text-only path. Two things to verify on the first paid call and record here: (a) the exact `rle` shape – fal's page says `string | list<string>`; the WaveSpeed mirror of the same model documents COCO-style `{"counts", "size": [h, w]}` decodable with `pycocotools.mask.decode`, so assume one RLE per frame and confirm; (b) propagation direction from a mid-clip `frame_index`. If it only tracks forward, the app can still get both directions with no model change: split the clip at the prompted frame, run the first half reversed (`ffmpeg -vf reverse`) with `frame_index=0`, run the second half forward with `frame_index=0`, and stitch the two mask sequences (the same trick works for every candidate below). Budget cap: pay only for frames that need rework; clips are short.

**Fallback: Replicate `meta/sam-2-video`** (SAM 2, L40S, ≈$0.03 per run). Use `mask_type=binary`, `output_video=false`, `output_format=png`, `output_frame_interval=1` to get one lossless B&W PNG per frame, and `click_coordinates` / `click_labels` / `click_frames` / `click_object_ids` for the clicks. It has no text prompt, so the wand's clicks define the object on their own; keep the same `click_object_ids` for + and − points. It also stays on Replicate, so the existing auth and polling code is reused. fal `fal-ai/sam2/video` is a weaker third choice: it has `frame_index` per point but no `object_id`, outputs only an mp4, and its price is unlisted.

**Not usable today:** `lucataco/sam3-video` `visual_prompt` is a stub (see §1) – do not route clicks to it until the cog source implements it; `8digit/gener8-sam3` is text-only.

**Recovering a binary mask from a video output.** fal `sam-3/video` with `apply_mask=false`, fal `sam2/video` with `apply_mask=false`, and Replicate `mask_type=binary` + `output_video=true` all return a compressed mp4 of the mask: decode with ffmpeg to PNG (`ffmpeg -i masks.mp4 -vsync 0 mask_%05d.png`), convert to grayscale and threshold at 128 (yuv420p chroma subsampling and x264 ringing blur the edge by a pixel or two, so threshold, do not test `== 255`). `highlighted` / overlay outputs (Replicate `mask_type=highlighted`, fal `apply_mask=true`) are the original frame with a tinted overlay and cannot be reliably inverted to a binary mask – avoid them. `greenscreen` (Replicate) replaces the background with flat green: a mask can be recovered by chroma-keying pure green (`G > 200 and R,G,B distance from (0,255,0) small`) but subject pixels that are themselves green will be lost, so prefer `binary`. Prefer RLE or per-frame PNG output wherever the endpoint offers it; mp4 recovery is a last resort.

Frame-index convention: fal and Replicate both count frames from 0 in decode order of the uploaded file. Send the wand the same transcode (same fps, same frame count) the app already uploads for the text pass, so frame `i` in the returned masks is frame `i` in the existing zip.

## Implementation (Foundation phase, Agent 3)

Every mask edit is a **branch at the `mask` stage**: `POST /jobs/{id}/mask/apply` goes through the same machinery
as `POST /jobs/{id}/branch` (`stages.branch` + `run_branch`), so `depth.mp4` and everything before the mask stage
are hard-linked from the parent, nothing is re-billed, the parent folder is never written to (except the preview
PNGs described below), `composite` and `face` re-run unchanged on the new masks, and the child's review is pending
because the fingerprinted files changed. The four tools live in `stages/mask.py` (shared base `WandTool`), the
algorithms, codec and renderers in `stages/wand.py`, the UI in `static/wand.js`.

### Tools (mask stage registry)

| tool | paid | params | what it does |
|---|---|---|---|
| `local_propagate` | no (the default) | `edits`, `max_frames` (120), `depth_tol` (24), `color_tol` (32), `base`, `base_run` | the free local algorithm below; label "Local propagation (free, rougher edges)" |
| `brush` | no | `strokes`, `base`, `base_run` | rasterises strokes with OpenCV on a frame range (the last-1 % fallback) |
| `sam3_points_fal` | yes, $0.005 per 16 frames per call (`costs.PRICES`, verified from the fal page) | `edits`, `prompt`, `source` (auto / depth / rgb), `base`, `base_run` | fal `fal-ai/sam-3/video-rle` point prompts |
| `sam2_points_replicate` | yes, ≈ $0.029 per prediction (Replicate's listed average, unverified) | same | Replicate `meta/sam-2-video`, `mask_type=binary`, `output_video=false`, `output_format=png`, `output_frame_interval=1` |

`edits` is a JSON list of `{frame, x, y, label}`: coordinates normalized 0–1 to the prepared clip (`original.mp4`,
24 fps), `label` 1 = include, 0 = exclude; each edit gets an `object_id` (`add` / `remove`). `strokes` is a JSON list
of `{frame_from, frame_to, mode: paint|erase, points: [[x, y], …], radius}` (radius as a fraction of the height).
`base` = `parent` (start from the base run's `clean-masks`, the default) or `replace` (start from an empty mask);
`base_run` is the run whose masks are edited (`/mask/apply` fills in the run id; without it the run's `parent` from
`run.json`). Because `base_run` and the edits are params, the stage's cache key differs per edit and per base.

**Merge rules** (`wand.merge_frame`, frame by frame, in edit order): include regions are OR-ed into the base mask,
exclude regions are subtracted. All four tools write the same artifact set the composite stage needs: `raw-masks/`
and `clean-masks/` (identical, one 0/255 PNG per frame of the clip, every frame present), `sam-report.json` (a copy
of the base run's report with `method` extended by "+ mask wand (…)" and a `wand` section: tool, base, base run,
`frames_changed`, per-edit notes, provider/endpoint for the hosted tools) and `mask-edits.json` (the click/stroke
history: the base run's history plus this edit). The Replicate tool also writes `sam-attempts.json` /
`sam-raw-request.json` through `raw_masks._predict`; the fal tool writes `wand-hosted.json` (request ids and the
arguments without the upload URL). `manifest.json` picks up the new `method` as before. The report's health line is
plain: "Added a region from frame 52 forward to 5.5 s (the end of the clip) and back to 0.0 s (…) on 133 frames."

### Endpoints (`app.py`)

- `POST /jobs/{id}/mask/preview` — form or JSON `{frame | time, edits}` → the free seed step on that frame only
  (no propagation, no branch): `{url: "/runs/<id>/wand-preview/preview-<frame>-<hash>.png", frame, frames, fps,
  width, height, seconds, selections: [{mode, fraction, already_in_mask}], pending_edits, edits_on_this_frame}`.
  The PNG is the frame with the current mask outline (green), include selections tinted green, exclude tinted
  red. `wand-preview/` is the one thing written into an existing run folder; it is not an artifact of any stage
  (never linked into branches, not in the review fingerprint). 400 with a `fix` for a frame outside the clip, a
  click outside the picture, or a run without `original.mp4`.
- `GET /jobs/{id}/mask/frame?i=N` (or `?t=seconds`) — one JPEG of the prepared clip at that frame with the mask
  outline; headers `X-Frame`, `X-Frames`, `X-Fps`, `X-Width`, `X-Height`, `X-Has-Masks`, `X-Mask-Fraction`.
  Out-of-range indices are clamped.
- `POST /jobs/{id}/mask/apply` — `{tool, edits | strokes, base, max_frames, source, prompt, confirm_cost}` →
  validates (plain 400s with a `fix`: unknown tool, no clicks, no strokes, click outside the clip, no depth video for
  the point tools, no prepared clip), builds the params, runs the cost gate (402 with `estimated_cost_usd` for a
  paid tool without `confirm_cost=true`; `local_propagate` and `brush` are free) and creates the branch exactly like
  `POST /jobs/{id}/branch`: `{state: "running", id: <child>, parent, changed, estimated_cost_usd}`. Poll
  `GET /jobs/{child}`; the UI navigates to the child.
- `POST /jobs/{id}/estimate` with `stage: mask, tool, params: {edits}` gives the estimate the UI shows on the Apply
  button (one hosted call per click type present: include points, exclude points).

### The free local algorithm (`wand.local_propagate`) and its limits

1. The clip is decoded at a working resolution (longest side 480 px) from `original.mp4` and `depth.mp4`.
2. **Seed** on the clicked frame: a fixed-range flood fill from the click on the depth frame (tolerance `depth_tol`)
   AND a fixed-range flood fill on the Gaussian-blurred RGB frame (`color_tol` per channel), bounded by a radius of
   35 % of the frame height; small results fall back to the depth flood alone, then to a 2 % disc. Opened 3×3,
   closed 5×5.
3. **Propagate** forward and backward: the click point is tracked with dense optical flow (OpenCV DIS, medium
   preset; Farneback is the fallback when DIS is missing, but it reports no motion inside flat regions: 0.0 px on a
   uniform square that moves 8 px, where DIS gives 8.0 px — measured on the synthetic test clip) and the region is
   regrown around the tracked point with the same seed rule on every frame. It stops at the clip ends, after
   `max_frames` each way, when the tracked pixel's depth drifts more than 30 levels or its colour more than 60 per
   channel from the clicked pixel ("where the region changed depth or colour"), or when the regrown area falls
   below 30 % or above 300 % of the seed's ("where the region changed size"). The health line names the stop reason
   for each direction.
4. Regions are upscaled to the clip size (linear then threshold) and merged into the base masks.

Limits: edges are rougher than SAM's (work resolution + flood fills); a region whose depth or colour matches the
background leaks up to the radius bound; a fast-moving object the flow cannot follow stops early (then click again
on a later frame; several clicks are merged in order); occlusions stop propagation (click on the other side of the
occlusion). GrabCut was tried and dropped: on the fixture the depth + colour floods alone gave the usable region,
and GrabCut added seconds per frame.

Measured on the fixture (`runs/85e5…`, 195 frames at 480×274 work size): a + click on the unmasked shoulder at
frame 52 propagates to every frame (1.2 s); a − click on the face stops after 13 frames forward where the head
turns (colour drift) and 39 back. On the synthetic clip (a flat square moving 8 px per frame over a textured dark
background, 24 frames) a click on frame 12 masks the square on all 24 frames with IoU > 0.8 (tested).

### Brush

`wand.rasterize_stroke`: a polyline with round joins of thickness `2·radius·height` plus discs at both ends (a
single point is a disc), drawn with OpenCV at full resolution; paint = include, erase = exclude; applied to every
frame in `[frame_from, frame_to]` (clamped to the clip).

### Hosted tools: what is implemented and what is unverified

Both hosted tools send **one call per click type**: the include clicks as one object (`object_id` "include") and
the exclude clicks as another (`object_id` "exclude"), each with `label 1` (the point says what the object *is*);
the returned include mask is OR-ed in and the returned exclude mask subtracted. This is because SAM 3 on fal returns
one merged `rle` per frame for all objects (per-object masks exist only on `sam-3-1/video-rle` with
`return_object_rles`), so include and exclude objects cannot be told apart within one call. A text `prompt` is sent
only with `base = replace` on the include call (the text pass defines the object, the clicks refine it).
`record_call` is made before any I/O for every call (`PUPPETEER_OFFLINE=1` stops it there; tested with `requests` and
`fal_client` mocked to fail on contact). The video uploaded is the one the parent masks came from (`source: auto` →
`sam-report.json.source`, depth by default), the same transcode the text pass used, so frame indices line up.

- fal `sam3_points_fal`: `fal_client.upload_file` → `fal_client.submit('fal-ai/sam-3/video-rle', {video_url,
  apply_mask: false, point_prompts: [{x, y, label, frame_index, object_id}]})` → `handle.get()`. Points are sent in
  **pixels of the uploaded video** (normalized × width/height). `decode_fal_rle` accepts a list of COCO RLEs (one per
  frame), one compressed-counts string per frame (size from `metadata` or the video), a JSON string of either, or a
  File `{url}` (downloaded with `requests`). **Unverified until the first paid call**: (a) the exact `rle` shape
  (fal says `string | list<string>`; the WaveSpeed mirror documents COCO `{counts, size}`); (b) whether points are in
  pixels or normalized; (c) propagation direction from a mid-clip `frame_index` (upstream SAM propagates one way per
  call; if only forward, the documented workaround is TODO: split the clip at the prompted frame, run the first half
  reversed with `frame_index=0`, the second half forward, and stitch the two sequences); (d) how a text prompt and
  `object_id` interact. Record the answers here after the first call.
- Replicate `sam2_points_replicate`: `raw_masks._headers/_upload/_model_version/_predict/_download/_png_mask`
  with `click_coordinates='[x,y],[x,y]'` in pixels (unverified: the README does not say pixels or normalized),
  `click_labels`, `click_frames`, `click_object_ids`; one PNG per frame parsed in output order; missing trailing
  frames stay unchanged. Same direction caveat as above.

The RLE codec (`wand.rle_encode/rle_decode`, pycocotools' column-major counts and its LEB128-style compressed
string with delta coding) is tested round-trip on random masks, both forms, plus the known 2×3 example.

### UI (`static/wand.js`, review panel)

Shown on depth-mode runs (files include `mask.mp4`, mode not `face_mesh`) once the run is done. "Fix the mask"
pauses the video, hides its controls and lays a canvas overlay exactly over the rendered video box (computed from
`videoWidth/videoHeight` against the element's box, so letterboxing does not shift the clicks; repositioned by a
ResizeObserver). The overlay shows `GET /mask/frame` for the current frame; frame stepping (−1 s, ◀ frame, frame ▶,
+1 s) keeps the video's `currentTime` in sync. Click = +, Alt-click, right-click or the "− exclude" toggle = −; each
click adds a marker and a pending edit and the preview (`/mask/preview`) replaces the frame image. Tool select:
Local propagation (free) by default, SAM 3 on fal / SAM 2 on Replicate labelled "· paid" with the estimate on the
Apply button (fetched from `POST /jobs/{id}/estimate`; the click that shows it sends `confirm_cost=true`; a 402
shows "Run anyway · about $x"), and Brush (paint / erase, radius slider, "on N frames from here"). Undo last, Clear
all, "Apply to the whole clip · free" → `POST /mask/apply` → navigate to the child run (review pending). Works at
380 px (the toolbar wraps; the overlay never exceeds the video box).

### Verification artefacts

Made offline on port 8774 (2026-10-23), never touching the fixture runs: `5a8e8a0b…` is a hard-link copy of
`85e5dbe6…` with a reconstructed `run.json`; its wand chain, each a branch at the mask stage with `depth.mp4`
sharing the parent's inode, composite + face re-run, review pending and no `calls.jsonl`:
`76f13faa…` (+ click on the left shoulder at frame 53 → 21 frames changed), `6e4eec6f…` (+ click on the missed right
shoulder at frame 60 → 5–10 % of the frame added on 181 frames), `7a8e463b…` (Alt-click − on the detached
left-shoulder fragment → 6,277 px removed on frame 60, 23 frames), `8f6e9537…` (brush stroke painted on frames
24–28). `431506e4…` is the fixture upload prepared through the Quick route with the Talking head preset (free): its
input-doctor card shows the seven checks and the fps fix; the strict face rule fails it as before.

## The batch wand on the timeline (stage 2, Agent 2)

The editor's **Mask track** (`static/track-mask.js`, server `stages/masktrack.py`) is the wand without a branch per
click. Clicks (+ / Alt-click −) and brush strokes are pending fixes in the edit layer; each previews on its own frame
with the same free seed step (`wand.selections()` → `wand.preview_png(…, strokes, out_dir, base_masks,
transparent=True)`, drawn over the current session mask; ~0.1 s). Nothing propagates until **Apply to clip**
(`POST /jobs/{id}/edits/mask/apply`), which sends every pending click of every frame to **one** `local_propagate`
call (the list was already one pass: the clip is decoded once and each edit propagated in turn) or, for a hosted tool
at full quality, one call per click type as before (`HostedWand.regions` on links in the session's `mask/work/`, so
`record_call` logs to the session's `calls.jsonl`). Quick = working size 240 px, full = 480 px (`work_side`). The
result is a full mask set in `runs/_sessions/<id>/mask/results/<key>/` with a B/W `mask.mp4`; Accept · full quality
re-runs the same fixes and replaces the entry; undo goes back to the previous result (kept by key). **Grab hands**
(`POST …/edits/mask/hands`) runs `hands_worker.py` (MediaPipe Hand Landmarker in `.venv-face`) on the flagged frames
or a range and ORs hull ∩ depth-flood regions into the current mask on those frames only. **Save edits** makes one
child whose mask stage is the free `edit_layer` tool (copies `edit-layer/mask/` into `raw-masks/` + `clean-masks/`,
writes `sam-report.json` + `wand` and `mask-edits.json` like the tools above). The classic wand (this document's
"Implementation" section) is unchanged and still reachable under the editor ("Fix the mask"; the track panel links
to it as "Classic wand (one version per apply)"). Endpoints, layer schema, thresholds and timings:
docs/TIMELINE-SPEC.md §A2.
