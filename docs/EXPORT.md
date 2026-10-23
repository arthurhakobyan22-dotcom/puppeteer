# Export kit (stage 3, Agent 4)

One zip per export with everything a downstream tool needs, made locally and free, always including the timeline
edits. Code: `stages/export.py` (the engine), `stages/export_presets.py` (items and presets as data), the routes in
`app.py` (section "export kit"), the panel `static/export.js` (`mountExport`, `tpl-export`, mounted under step 04 and
reached from the Studio run head "Export…"). Contract: `docs/WORLD-LOOK-EXPORT-SPEC.md` §6, §6.1, §W4.

## 1. Where an export lands

`runs/<id>/export/<preset>-<yyyymmdd>-<hhmmss>-<xxxx>/` (unzipped) and `runs/<id>/export/<same name>.zip` next to it,
plus `runs/<id>/export/<same name>.json` (the record the listing, the poll and the download read). When pending edits
were saved first, `<id>` is the **new child run**; the run the export was asked on gets the `.json` record only, so
both runs list the export and both can download it. Nothing else is written into any run.

## 2. Items (tick boxes)

| key | file(s) | made from | when it is missing (the tick box is disabled with this reason) |
|---|---|---|---|
| `composite_audio` | `composite.mp4` H.264 + AAC, ≤1080p, source fps | `seedance-input.mp4` (the prepared clip: the picture copied byte for byte, the audio copied when it is AAC, else encoded to AAC 192k) | no prepared clip yet |
| `composite_silent` | `composite-silent.mp4` (copy) · `composite-silent.mov` (ProRes 422 HQ) · `composite-silent/frame_%05d.png` | `composite-silent.mp4` | no silent composite |
| `depth` | `depth.mp4` · `depth.mov` · `depth/frame_%05d.png` | `depth.mp4` | Fast · Face mesh runs have no depth |
| `mesh_alpha` | `face-mesh-alpha.mov` (ProRes 4444) **or** `face-mesh/frame_%05d.png` (RGBA) | `face-landmarks.json` drawn with `stages.meshedit.draw_face` on a transparent canvas: alpha 255 on the lines, 0 everywhere else; frames with `status: off` or no face are fully transparent | no face mesh |
| `mask` | `mask.mp4` · `mask.mov` · `mask/frame_%05d.png` | `mask.mp4`, else the `clean-masks/` / `raw-masks/` PNGs encoded | Fast · Face mesh runs have no mask |
| `alpha` | `person-alpha.mov` (ProRes 4444) **or** `person-alpha/frame_%05d.png` | `composite-silent.mp4` RGB + the mask as alpha (straight alpha) | needs the composite and a mask |
| `audio_original` | `audio-original.wav` 48 kHz 16-bit PCM · `audio-original.m4a` (AAC copy, Seedance web) | `upload.mp4` | the source has no audio track |
| `audio_vocals` / `audio_music` | `vocals.wav` / `music.wav` | the Clean dialogue step | not separated |
| `landmarks` | `face-landmarks.json` | the run's file (a `mesh_edit` child already holds the edited points) | no face mesh |
| `words` | `words.srt` (phrases ≤42 chars / ≤5 s, `stages.subtitles.cues`), `words.json` | pending word edits first, else `words.json` | no transcript |
| `prompt` | `prompt.txt` | `stages.promptkit.assemble` when that module exists (Agent 2), else today's text (`generation.json` prompt → `run.json.chain.prompt.params.text` → the default) + the `Dialogue beats` block (`stages.words.beats_text`) + the reference list in attachment order | always |
| `refs` | `ref-01-char1.png`, `ref-02-char2.jpg`, then the set image (`slots.set.mode == set_ref`) and the look image (`slots.look.mode == style_ref`) | `char1-reference.*`, `char2-reference.*`, `runs/_assets/<name>` | no reference saved |
| `run` | `run.json`, `slots.json` (when present), `edit-layer.json` (when the run was saved from edits) | copies (a legacy run gets a reconstructed `run.json`) | always |

Every export also has `README.txt` and, whenever a PNG sequence is in it (always for ComfyUI), `frames.json`
`{fps, fps_text, frames, width, height}`. Numbering of the refs equals the `@ImageN` numbering in the prompt (char1,
char2, set, look: the same order `stages/promptkit.py` attaches them; `@Video1` is the clip).

## 3. Presets and why

| preset | items on by default | formats | why |
|---|---|---|---|
| `seedance_web` | composite_audio, prompt, refs | H.264 mp4 ≤1080p at the source fps with AAC; prompt.txt; refs numbered | The Dreamina / fal upload box takes one H.264 + AAC mp4 up to 1080p, which the prepared clip already is, so the picture is copied without a re-encode; the prompt names references by position, so the files carry that number. `audio_original` here would be an `.m4a` (the box takes no wav). |
| `kling` | composite_audio, mask, prompt | both videos H.264 at the source fps | Kling wants a control video and a mask video of the same length; same fps and frame count keeps them one-to-one. A hard black / white matte survives H.264 at crf 18; PNGs are not accepted there. |
| `comfyui` | depth, mask, composite_silent (PNG sequences), landmarks, words, run | `frame_%05d.png`, `frames.json` | Load-image-sequence and ControlNet nodes read numbered PNGs with no codec step and want exact frames. A PNG has no frame rate, so `frames.json` and the README carry it: set the same fps on the combine node. |
| `after_effects` | mesh_alpha, alpha (ProRes 4444), composite_silent (ProRes 422 HQ), audio_original (wav), words | `.mov`, source fps, 48 kHz wav, `.srt` | ProRes 4444 is the alpha codec every NLE / compositor imports natively (straight alpha; H.264 cannot carry alpha). 422 HQ keeps 10-bit 4:2:2 for grading. 48 kHz PCM is the timeline default, so no resampling on import. |
| `custom` | nothing (tick what you need) | mp4 for video, the chosen alpha format, wav | For any other tool. |

The alpha format (ProRes 4444 `.mov` or RGBA PNG sequence) applies to both alpha items; the presets set it, `custom`
and the picker override it (`mesh_format` / `alpha_format` on the request). Frame rate is never changed: every video
and sequence has the clip's frames and fps (24 for runs prepared by Puppeteer; imported controls keep theirs).

**ffmpeg.** `shutil.which('ffmpeg')`, then `/opt/homebrew/bin/ffmpeg`; missing → `{message: 'ffmpeg is not installed…',
fix: 'Install ffmpeg: brew install ffmpeg…'}` before anything is written. ProRes 4444 is written with
`-c:v prores_ks -profile:v 4444 -pix_fmt yuva444p10le` from raw RGBA frames on a pipe; ProRes 422 HQ with
`-profile:v 3 -pix_fmt yuv422p10le`. Note for the reviewer: ffmpeg 9's ProRes *decoder* reports a 4444 stream as
`yuva444p12le` in `ffprobe` (the encoder was fed `yuva444p10le`); `profile=4444` and the decoded alpha pixels are the
proof (`tests/test_export.py::Alpha`).

## 4. Edits are always included

`POST /jobs/{id}/export` looks at the run's edit session (`runs/_sessions/<id>/`). When `pending.total > 0` it calls the
same `stages.editlayer.plan()` the save route calls: a track that cannot save yet (mask clicks not applied) refuses the
export with that track's own message; a save that would re-run a paid stage is refused with a 402-style message
("Saving these edits first would re-run a paid stage (about $x)… Save the edits from the editor…") so no paid call ever
starts from an export. Otherwise the export thread runs `stages.editlayer.save()` and `run_child()` exactly like
`POST /jobs/{id}/edits/save` (one free branch, the session closed), waits for the child, and exports the **child**:
the response, the poll and the README carry `exported_run` (≠ the id the export was asked on) and the edits line
("1 pending edit of <parent> saved first as the new version <child> (face: mesh off on frames 3–5)"). A run with no
pending edits exports itself. The panel says it before the click: "3 pending edits will be saved first (free) and the
export made from the new run."

## 5. Routes

- `GET /jobs/{id}/export` → `{id, presets: [{name, label, items, formats, what, why}], items: [{key, label, what, available,
  reason, …}], clip: {frames, fps, width, height, seconds, source}, formats: {rgba: [prores, png]}, ffmpeg, ffmpeg_problem,
  pending: {total, summary, note, problem, estimated_cost_usd}, exports: [records newest first, each with zip_url, zip_exists],
  running}`. Writes nothing.
- `POST /jobs/{id}/export` `{preset, items?, mesh_format?, alpha_format?}` (JSON or form; `items` a list or "a, b") →
  `{state: running, name, run, requested_run, exported_run: null, preset, items, formats, status, started, pending_edits,
  zip_url}`; 400 plain for a bad preset / item / format, an unticked export, an item the run lacks (`item`), ffmpeg
  missing, a track refusal; 402 when the pending edits would cost money; 409 while the run prepares.
- `GET /jobs/{id}/export/{name}` → the state: running (`status` line), done (the record: `files [{file, what, item}]`,
  `readme`, `fps`, `frames`, `width`, `height`, `zip`, `zip_url`, `zip_bytes`, `exported_run`, `requested_run`,
  `warnings`, `edits`, `created`), error (`status` + `fix`); 400 for a name that is not `<preset>-<8 digits>-<6 digits>[-xxxx]`;
  404 for an unknown export.
- `GET /jobs/{id}/export/{name}.zip` → the zip (`Content-Disposition: attachment; filename="<id8>-<name>.zip"`), from
  this run's folder or the exported child's (through the record); same name rules, 404 when missing.

## 6. README template

```
Puppeteer export · <preset label>
Made <iso> · export name <name>
Run: <exported run>[ · exported from the new version <child> saved first from <parent>]
Clip: <frames> frames at <fps> fps · <w>×<h> · <seconds> s (from composite-silent.mp4)
Mode: <mode>[ · preset <name>]

Edits: <no pending timeline edits; the run exported as it is. | N pending edits of <parent> saved first as the new version <child> (<changed>); this export is of that version. | this version was saved from timeline edits: <changed>>

Why this preset:
  <line 1>
  <line 2>

Files:
  <file>   <what it is, format, frame count, source>
  …
  README.txt   This file.

[Notes:  <warnings, e.g. a mask shorter than the composite>]

Frame rate and count are the same in every video and sequence here; … Alpha files are straight (unpremultiplied) alpha.
Made by Puppeteer, locally and free; nothing was sent anywhere.
```

## 7. start.command

Double-click → `cd` to its folder → when `.venv/bin/python` is missing: check Python ≥ 3.12, `python3 -m venv .venv`,
`pip install -r requirements.txt`, make `.env` from `.env.example` (all printed) → `.venv/bin/python launch.py` with the
`PORT` it was given (default 8770). On any failure the Terminal stays open (`read -r`). `setup.sh`, `launch.py`,
`workflow.py` and `doctor.py` are unchanged.

## 8. Tests

`tests/test_export.py` (13, all run here since ffmpeg is installed): a synthetic 12-frame 24 fps 320×192 Advanced + mesh run with sound (real clips, the
fixture face from `tests/fixtures/mesh-edit-cases.json`, a mesh drawn with `meshedit.render`, the prepared clip from
`audio_workflow.prepare_seedance_video`). Every preset → the zip opens, ffprobe fps / frame counts / sizes match, the
README names every file; ProRes 4444 mesh (`profile 4444`, `yuva444p*`, alpha 0 at the corners and >0 on a lips line,
empty on the missing frame); RGBA PNG sequences; the person alpha; mask from the PNG folder; ffmpeg missing; the routes
(items with reasons, POST → poll → zip, bad names → 400, unknown → 404, 409 while preparing); pending mesh edits saved
first (exactly one child, `exported_run != id`, frames 3–5 fully transparent, the parent unchanged but for its record);
a refusing track → 400 and a paid track → 402 with nothing branched. ffmpeg-dependent tests skip when it is missing.
