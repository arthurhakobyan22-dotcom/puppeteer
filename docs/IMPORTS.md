# Import my own, and Download (Agent 4)

Any stage output can be downloaded, edited elsewhere and brought back. An import never overwrites anything: it makes a
**new branch** at that stage whose tool is an "Import my own" tool, so the rest of the chain re-runs on your file and
the run you imported into stays exactly as it was. Contract: `docs/TIMELINE-SPEC.md` §7, §A4. Code: `stages/imports.py`,
routes in `app.py` (section "Import my own"), UI in `static/stagecard.js`.

## Download

- Studio stage cards: "Download" lists one link per output in the stage's report (`/runs/<id>/<file>` with `download`);
  a folder output (e.g. `raw-masks/`, `clean-masks/`) is a zip from `GET /jobs/{id}/download/<folder>.zip`. The mask card
  adds "Masks as PNGs (mask.zip)", the face card `face-landmarks.json`.
- The editor: "Download <view> ↓" under the picture (as before) plus "Masks as PNGs (.zip) ↓" while a mask view is on.
- Words panel: `Export subtitles (.srt)`, `words.json`, `mouth-guidance.json`; finish step: `.srt` and the subtitled finals.
- `GET /jobs/{id}/download/<name>.zip`: `name` must match `[A-Za-z0-9][A-Za-z0-9_-]*` (no dots, slashes or `..`); it is
  `mask`/`masks` (= `clean-masks/`, else `raw-masks/`), or a top-level folder that one of the run's reports lists as an
  output, or `clean-masks`, `raw-masks`, `edit-layer`, `stages`. The folder must be a real directory inside the run (no
  symlink); files are zipped under `<name>/…`, symlinks skipped. Anything else is a plain 400/404. Writes nothing.

## Import

`POST /jobs/{id}/import` (multipart: `stage`, `file`, `confirm_cost?`) → the child job like `/branch`
(`{state, id, parent, changed, estimated_cost_usd}`); the UI navigates to it (Studio). The file is stored
content-addressed as `runs/_imports/<sha256>.<ext>` (+ `<sha256>.json` = `{sha256, ext, name, size, stage}`); an
unreadable file is removed again. Size limit 1 GB (413 "This file is larger than 1000 MB…"). Branch params:
`{file: <sha256>, ext, name}` (the cache key covers the file; the Studio card shows only "Imported file: <name>").
A copy is hard-linked into the child as `imported-<stage><ext>`. Imports are free, so no confirmation is needed; the
route still goes through `cost_gate()` for the stages that re-run (402 if a paid one would).

| stage | tool | accepts | what it writes | extra changes in the same branch |
|---|---|---|---|---|
| depth | `import_depth` | grayscale or coloured video | `depth-raw.mp4`, `depth.mp4` (libx264 crf 12) | `mask: keep_parent` (the parent's masks, free, never re-billed); composite → `depth_cutout` if it was not |
| mask | `import_mask` | B/W video, `.zip` of PNG frames (natural name order), video with alpha (ProRes 4444 / PNG / QuickTime RLE in `.mov`, VP9 `.webm` with alpha via libvpx) | `raw-masks/`, `clean-masks/` (white = subject; the alpha channel when it has real transparency, else brightness > 127), `sam-report.json` (`method: imported mask …`, `source: imported`) | composite → `depth_cutout` if it was not (needs the run's `depth.mp4`) |
| face | `import_face` | overlay video (its non-black pixels, max channel > 24, or its alpha, drawn over the base clip) **or** landmarks `.json` in the `face-landmarks.json` schema (`{fps?, frames: [{faces: [[{x, y} × 468 or 478]], status?}]}`) | `composite-silent.mp4`, `preview.jpg`; for JSON also `face-landmarks.json`, `face-tracking.json` (lenient evaluation, `imported: true`), drawn with `meshedit.render` | — |
| composite | `import_control` | a finished control video | `imported-control.mp4` (the base the face stage passes on) | `face: off`, so the control video becomes `composite-silent.mp4` / `seedance-input.mp4` (original audio added as always); the chain's mode is `original` (review = the prepared clip itself) |

**Conform** (never an error; each change is a plain sentence in the report's `warnings`, shown on the card):
frame rate resampled by time (each output frame takes the last source frame starting before its middle) —
"Your mask was 30 fps; it was resampled to the clip's 24 fps."; frame count trimmed or padded by holding the last frame —
"Your mask had 200 frames; the clip has 195, so the last 5 were dropped." / "…so the last frame was held for 4 more
frames."; size resized (bilinear; masks thresholded after) — "Your mask was 480×276; it was resized to the clip's
960×550." (+ "(stretched: the shapes differ)" when the aspect differs). Landmarks are used frame by frame; frames whose
face has another point count are treated as missing (warning). Unreadable files are a 400 with the accepted formats as
the fix; a wrong extension, a missing file, an empty zip, a landmarks file without a 468/478-point face likewise.

**"imported" label**: `imported: true` in `Tool.describe()` (`GET /stages`), `report.data.imported = true` (+ `file`,
`name`, `source` = frames / fps / size / alpha / codec of the upload), `run.json.imported = [stages]` and
`run.json.changed` = `mask: imported "my mask.zip" (was sam3_replicate)` (+ `· composite: depth_cutout` etc.), `describe_chain`
→ `mask: import_mask (name: my mask.zip) · imported`, `imported: [stages]` on every summary of `GET /jobs` and
`GET /jobs/tree`. UI: an orange "imported" chip on the stage card, "imported · mask" chips in the run header next to
"What changed" and on the Runs list rows.

## Verification (2026-10-24, port 8778, offline)

On `0be4cf2cadd945008a9c9131b6c75f12` (hard-link copy of `85e5…`): mask.zip downloaded (195 PNGs), a white box painted
on every frame with PIL, imported through the Mask card → child `6f20c4d1543a468485988b4ba7894a1d` (done; its
`mask.mp4` is white in the box — mean difference 249 there, 0 elsewhere — so the composite used the import; chips on
card, header and Runs list). A mismatched mask (480×276, 200 frames, H.264) → child
`36536b28c76044c79109adf3f7e02896`, done, with the two warnings above, no error. Tests: `tests/test_imports.py`.
