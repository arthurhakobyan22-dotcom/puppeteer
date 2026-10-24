# Prompt builder with fences, and the Claude vision fill (World stage, Agent 2)

The draft step (03) builds the creative prompt from what the run already knows: the saved character references, the Set / Look /
Light slots (`slots.json`, `docs/STAGES.md` §18) and the dialogue beats from the Words track. Every attached reference gets **one
job and one fence sentence**, numbered in the order the adapters upload it, so the `@ImageN` in the text is the `@ImageN` Seedance
sees. Nothing here is paid or networked except the optional Claude vision fill, which costs about a cent and asks first.

Code: `stages/promptkit.py` (assembly, fences, checks), `stages/vision.py` (Claude vision), `providers/base.py: build_prompt`
(the adapter-appended rules), `static/promptkit.js` (the panel), routes in `app.py` section "Prompt builder with fences + Claude
vision fill". Tests: `tests/test_promptkit.py`.

## 1. Numbering rule

References are attached, uploaded and numbered **in this order**; a slot that is empty is skipped and the numbers close up:

| order | slot | file | token |
|---|---|---|---|
| 1 | `char1` | `runs/<id>/char1-reference.<png|jpg|jpeg|webp>` (or an identity video `.mp4|.mov|.webm`) | `@Image1`, or **`@Video2`** for an identity video (it takes no image number) |
| 2 | `char2` | `runs/<id>/char2-reference.<ext>` | `@Image2` (`@Image1` when char1 is a video) |
| 3 | set image | `runs/_assets/<slots.set.image>` when `slots.set.mode == 'set_ref'` | next `@ImageN` |
| 4 | look image | `runs/_assets/<slots.look.image>` when `slots.look.mode == 'style_ref'` | next `@ImageN` |

`@Video1` is always the prepared clip (`seedance-input.mp4`). `true_swap` attaches nothing: the plate is already composited
behind the person (`set-plate.<ext>` in the run) and the prompt says so. The adapters upload in exactly this order
(`providers/fal.py` `image_urls`, `providers/enhancor.py` `images`; the identity video goes to `video_urls` / `videos`).

## 2. Fences (one per reference, restated at every mention)

- character (`char1`): `@ImageN defines the character's identity only (face, hair, outfit, proportions); do not copy its pose, expression, props, background or lighting.`
  (`char2`: `… defines the second character's identity only …`; an identity video: `@Video2 defines the character's identity only …`)
- set: `@ImageN defines the set only (walls, floor, furniture, depth of the room); do not use its people or lighting.`
- look: `@ImageN defines the rendering style only (palette, grain, contrast, brushwork); do not copy its content, people or layout.`

At submit `providers.base.build_prompt` appends its usual `@Video1` / `@Image2` rules and, new, one short sentence per extra
reference: `@Image3 is the set reference only.` / `@Image4 is the style reference only.` (numbers consistent with the upload
order). For a run with only character references the appended text is byte-identical to before (the regression suite pins it).

## 3. Sections of the assembled text (`promptkit.assemble`)

In order, each present only when its slot says so, separated by blank lines:

1. `CHARACTER: ` the character fences + `Pose, motion, timing and lip-sync come from @Video1.`
2. `SET: ` the set fence (`set_ref`), or `The depth of @Video1 defines the layout of the room only (walls, floor, furniture, distances); regenerate its look and materials.` (`original_depth`), or `The set behind the person in @Video1 is the real set: keep its walls, floor, furniture and depth exactly as they are.` (`true_swap`); plus `slots.set.prompt` whenever it is filled. Nothing for `original` with no description.
3. `LOOK: ` the style fence (`style_ref`) and / or `slots.look.prompt`. Nothing for `follow` with no description.
4. the dialogue-beats block **exactly** as `GET /jobs/{id}/words/beats` renders it (`Dialogue beats (timing from the original audio; keep the lip-sync on these):` + one `a–b s says: "…"` line per beat), from pending word edits first, else `words.json`; absent when the run has no words.
5. `LIGHT: ` `slots.light`.
6. exactly one closing constraints line: `Keep the camera, crop, timing and every word of the embedded dialogue; replace the whole identity including hair; remove any mesh lines or depth colours from the output.` — the `replace the whole identity including hair` and `mesh lines` clauses only when the run has a face mesh (`face_mesh` / `depth_mesh`, or `face-landmarks.json`), `depth colours` only when it has depth (`depth` / `depth_mesh`, or `depth.mp4` on a legacy run). A plain depth run ends `…embedded dialogue; remove any depth colours from the output.`

`assemble(folder, slots=None, refs=None, words=None, runs_root=None)` returns `{'text', 'refs', 'beats', 'sections', 'warnings',
'closing', 'has'}`. `refs` is `[{'n', 'token', 'slot', 'kind': 'image'|'video', 'file', 'path', 'job', 'job_line', 'fence'}, …]`.
`slots` None → `stages.slots.read(folder)`; `refs` None → the run's saved references + the slots' assets (a numbered list or the
provider dict `{'char1','char2','set','look'}` is also accepted; `stages/export.py` passes its own list). `words` None → the
run's current words.

`fences_ok(text, refs)` → a list of plain problems, `[]` when the text is right: a ref that is attached but never mentioned, a
ref mentioned without its job sentence (`@ImageN defines … only`), a ref with two job sentences, an `@ImageN` / `@VideoN` that is
not attached. The assembled text always passes; the panel runs it on the hand-edited text and shows the problems as warnings.

## 4. Routes

- `POST /jobs/{id}/prompt/assemble` `{slots?, text?, provider?}` (JSON or form) → `{id, text, refs, beats, sections, warnings,
  closing, has, full_prompt, mode, provider, provider_note, edited}`. Free, writes nothing, no network. `slots` previews other
  slots without saving them; `text` is a hand-edited prompt whose `full_prompt` (the adapter's appended rules included, through
  `build_prompt`) and fence warnings are wanted; `provider` picks whose rules (default: the run's generator, else the default
  provider). A generator without a prompt (capabilities `prompt: false`, Agent 3's Wan) gets `full_prompt: null` and a one-line
  `provider_note`.
- `POST /jobs/{id}/seedance` now reads the set / look images from the run's slots (`set_ref` / `style_ref`) and passes them to
  `seedance_bridge.submit(..., set_image=, look_image=)`; the adapter receives them in `refs['set']` / `refs['look']`.
  `generation.json` gets `refs` (the numbered list, no paths) and `slots` next to `prompt`, `mode`, `task`.
- `POST /jobs/{id}/describe` — see §6.

## 5. The panel (`static/promptkit.js`, mounted into `[data-slot=prompt-builder]` by `draft.js`)

- **Build prompt from slots** fills the prompt textarea with `text` (what is in the box is what is sent; "Insert dialogue beats"
  still works on the box). A notice says how many references and whether beats were included.
- **Final prompt** (a `<details>`): the refs strip (thumbnail or a ▶ tile for an identity video, `@ImageN` / `@VideoN`, slot,
  one-line job; the prepared clip as `@Video1` last) beside the exact text the adapter will send (`full_prompt`) and the line
  "Sent through fal · Seedance 2.5 · edit mode". It refreshes when the box changes (600 ms debounce), when a slot is saved, when
  a reference is chosen, when the provider changes and when the job changes.
- **Warnings** from `fences_ok` on the current box text, as a list under the preview.
- **Describe set & light from this frame · about $0.01** (§6).

## 6. Claude vision fill of SET and LIGHT (`stages/vision.py`)

One frame of `original.mp4` — the middle one, or the frame at `t` seconds (index `round(t × fps)`; the panel uses the time the
viewer is paused on when the timeline editor is open, else the middle) — with the person's mask region (`clean-masks/`, else
`raw-masks/`) filled neutral gray, scaled to ≤ 1024 px, sent as a base64 JPEG to the Anthropic Messages API
(`POST https://api.anthropic.com/v1/messages`, `anthropic-version: 2023-06-01`) with `requests` (no SDK dependency), model
`claude-sonnet-5-5`, `max_tokens` 300, `output_config.effort` `low`. The system instruction asks for the set (architecture,
furniture, materials, depth) and the light (direction, quality, colour temperature, practicals) only, never people, clothing or
faces, as two lines `SET:` and `LIGHT:`. The two lines are parsed; a sentence that still names a person is stripped and reported in
`warnings`; a `refusal` stop reason is a plain error.

- Key: `ANTHROPIC_API_KEY` from `.env` via `config.setting`. Never logged, never written to a run folder, never in a URL. Missing →
  400 `{message: 'No Anthropic key yet.', fix: 'Add a line ANTHROPIC_API_KEY=sk-ant-… to the .env file in the project folder (console.anthropic.com → API keys), then restart the app.'}`.
  **How to add the key:** create an API key at console.anthropic.com → API keys, add `ANTHROPIC_API_KEY=sk-ant-…` as a line in
  `.env` in the project folder, restart the app (`.venv/bin/python launch.py` or `start.command`).
- Cost: `stages/costs.py` `claude_vision` = 1,600 input + 300 output tokens at Sonnet 5.5 list prices ($2 / $10 per million,
  platform.claude.com/docs/en/about-claude/pricing, read 2026-10-24) = **$0.0062**, shown as "about $0.01". An image costs about
  width × height / 750 tokens, so a 1024 × 576 frame is ~790 tokens; the estimate leaves headroom. The call is logged with
  `record_call(folder, 'anthropic', 'messages', cost_usd=0.0062)` before the request (so `PUPPETEER_OFFLINE=1` refuses first, and
  it appears in `calls.jsonl` and the run's spend); the response's `usage` gives the real `usd`.
- Route `POST /jobs/{id}/describe` `{t?, confirm_cost?, estimate_only?, apply?}` → `{id, set, light, model, usd, estimated_usd,
  frame_s, frame, fps, masked, warnings, raw, applied, estimated_cost_usd}`. Through `cost_gate()`: **402** with the estimate
  without `confirm_cost=true`; `estimate_only=true` answers the price for free. With `apply=true` the two lines are written into
  the slots (`set.prompt`, `light`) and nothing else; without it the text is only returned. Offline → the usual 400 plain refusal.
- The button "Describe set & light from this frame · about $0.01" sends `confirm_cost=true` and `apply=true` from that click, shows
  the two lines with the frame time and the real cost, reloads the slots panel so the fields show them (edit them before you
  create the draft), and shows the plain how-to notice when there is no key.
