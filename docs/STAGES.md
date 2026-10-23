# Stages, caching and branching (Foundation phase, Agent 1)

This is the contract Agents 2 and 3 build on. Everything here is implemented in the `stages/` package and
covered by `tests/test_stages.py`, `tests/test_branch_integration.py` and `tests/test_regression.py`.
Nothing that existed before was removed: every file name in a run folder, every route, form field, CLI command
and module function keeps working with the same inputs and outputs. New things are added next to them.

## 1. Stage order

| # | stage | automatic? | tools (first = default, wraps the existing code) | paid |
|---|---|---|---|---|
| 1 | `input_doctor` | yes | `probe` (reads the upload with PyAV, then `pipeline.normalize` → `original.mp4`) | no |
| 2 | `audio` | yes | `original` (source track copied packet for packet at the end), `clean_dialogue` (`audio_workflow.separate`, Demucs on Replicate) | clean_dialogue |
| 3 | `depth` | yes | `depth_anything_replicate` (lucataco), `depth_anything_replicate_chenxwh`, `depth_anything_hf`, `off` | the two Replicate ones |
| 4 | `mask` | yes | `sam3_replicate` (`raw_masks.segment_raw` + `clean_border_fragments`), `off` | yes |
| 5 | `composite` | yes | `depth_cutout` (`pipeline.composite`), `original` | no |
| 6 | `face` | yes | `mediapipe_mesh` (`face_mesh.mesh_worker`, local `.venv-face`), `off` | no |
| 7 | `prompt` | on submit | `identity_only` (`seedance_bridge.DEFAULT_PROMPT`; param `text`) | no |
| 8 | `generate` | on submit | `fal`, `enhancor` (the existing adapters: draft submit + poll + download) | yes |
| 9 | `finish` | on result / approval | `restore_original_audio` (`audio_workflow.finish_preview`), `complete_draft` (HD through the same provider) | complete_draft |

`stages.STAGES` is the order, `stages.PREP_STAGES` = the first six (run by the preparation chain),
`stages.GENERATION_STAGES` = the last three (their reports are written when the user submits a draft, when the
clip arrives and when HD is approved; `seedance_bridge` calls `stages.prompt.record`,
`stages.generate.record_submission/record_result`, `stages.finish.record_restore/record_hd`).

After the `face` stage the runner builds the prepared clip exactly as before: `seedance-input.mp4`
(`audio_workflow.prepare_seedance_video`), `manifest.json` and `workflow-mode.json`.

### Who writes which artifact

| stage | outputs (file names unchanged) |
|---|---|
| input_doctor | `original.mp4` |
| audio (clean_dialogue) | `original-audio.wav`, `vocals.wav`, `music.wav`, `audio-prediction.json`, `audio-manifest.json` |
| depth | `depth-raw.mp4`, `depth.mp4` |
| mask | `raw-masks/`, `raw-masks-<source>-<n>/`, `clean-masks/`, `sam-report.json`, `sam-attempts.json`, `sam-raw-request.json`, `mask-cleanup-report.json` |
| composite (depth_cutout) | `mask.mp4`, `composite.mp4`, `depth-composite-silent.mp4` (the clean cutout, now written in every depth chain, not only depth_mesh) |
| face (mesh or off) | `composite-silent.mp4` (mesh over the base clip, or a copy of the base when off), `face-landmarks.json`, `face-tracking.json`, `preview.jpg`; the runner adds `seedance-input.mp4` to this report |
| prompt | `prompt.txt` (only when the tool is run through the runner) |
| generate | `seedance-request.json`, `seedance-response.json`, `generation.json`, `seedance-result.mp4`, `final-preview.mp4` |
| finish | `hd/request.json`, `hd/response.json`, `hd/final-preview.mp4` |

The one deliberate change in ownership: `composite-silent.mp4` is always the **face** stage's output (the
depth cutout is kept under `depth-composite-silent.mp4`). That is what makes "change only the face tool"
re-link the cutout and never touch the parent's files. The review fingerprint (`mask_review.FILES`) is unchanged.

## 2. Tool interface (`stages/base.py`)

```python
class Tool:
    name: str            # registry key, e.g. "sam3_replicate"
    stage: str           # "mask"
    label: str           # plain words for the UI
    paid: bool
    experimental: bool   # opt-in, labelled in the UI (none of the built-ins are)
    description: str
    params: dict         # name -> {'type': 'bool'|'number'|'string'|'choice', 'default', 'label', 'hint'?, 'choices'?}
    inputs: tuple        # artifact names hashed into the cache key (missing ones are skipped)
    outputs: tuple       # artifact names the tool writes
    def normalize_params(self, params) -> dict      # defaults filled, values coerced
    def estimate_cost(self, inputs, params) -> float | None
    def run(self, inputs, params, folder, status) -> dict   # {'outputs': [...], 'frames', 'gaps', 'warnings', 'health', 'data'?}
    def describe(self) -> dict                      # what GET /stages returns
```

`inputs` passed to `run`: `{'folder', 'chain', 'mode', 'source' (the upload), 'seconds' (clip length)}`.
Registry: `register(tool)`, `get_tool(stage, name)`, `tools_for(stage)`, `registry()` (for the UI), `allow_off(stage)`
registers the `off` tool (depth, mask, face). To add a tool: subclass `Tool`, set the fields, `register(...)` in
`stages/<stage>.py`. Tools call the existing module functions through the module (`pipeline.normalize`,
`raw_masks.segment_raw`, `face_mesh.mesh_worker` …) so the old test patches keep working.

**Before writing an output, call `stages.fresh(path)`**: it unlinks a hard link shared with the parent run (or
removes an old folder) so a branch never writes through into its parent. The built-in tools do this.

### Face tool params

`mediapipe_mesh`: `strict` (bool; `true` in Fast mode, `false` in Advanced + mesh), `pad` (1.8), `max_gap` (6).
`mesh_worker.py` now accepts `--strict` / `--lenient` / `--pad X` / `--max-gap N`; the tool only passes a flag
when the value differs from the worker's own default, so the default invocation is byte-identical to before.

## 3. Reports: `runs/<id>/stages/<stage>/report.json`

Keys (always present): `tool`, `params`, `inputs` (`{name: sha256}`), `outputs` (`{name: sha256}`; a folder's
hash covers every file in it), `frames` (`{covered, filled, missing}`), `gaps` (list of
`{start_frame, end_frame, frames, start_s, end_s}`), `warnings` (plain sentences), `health` (one plain
sentence for the Studio card), `seconds`, `cost_usd`, `cached_from` (run id or null), `started`, `finished`.
Added by the runner: `stage`, `key` (cache key), `state` (`done` | `cached` | `off` | `error` | `missing` for
legacy), `error` (`{message, fix}` or null), `data` (tool-specific extras, e.g. the probe numbers, the SAM
method, `strict`/`ok`/`message` from face tracking). A stage that is off writes `tool: "off"`, `state: "off"`.

Example (face, from the real branching proof):

```json
{"tool":"mediapipe_mesh","params":{"strict":false,"pad":2.0,"max_gap":6},
 "inputs":{"original.mp4":"…","depth-composite-silent.mp4":"…"},
 "outputs":{"composite-silent.mp4":"…","face-landmarks.json":"…","face-tracking.json":"…","preview.jpg":"…","seedance-input.mp4":"…"},
 "frames":{"covered":163,"filled":13,"missing":19},
 "gaps":[{"start_frame":10,"end_frame":16,"frames":7,"start_s":0.42,"end_s":0.71},{"start_frame":50,"end_frame":61,"frames":12,"start_s":2.08,"end_s":2.58}],
 "warnings":["lost face 0.42–0.71 s, 2.08–2.58 s · depth composite only on those frames (no mesh)"],
 "health":"Face tracked on 163 of 195 frames, 13 filled by interpolation; lost 0.42–0.71 s, 2.08–2.58 s (depth composite shown there).",
 "seconds":4.1,"cost_usd":0,"cached_from":null,"started":"…","finished":"…","stage":"face","key":"…","state":"done","error":null}
```

Other per-run files: `run.json` (below), `log.txt` (append-only, timestamped status lines, tracebacks; never a
key value), `calls.jsonl` (one line per external call, see §6).

## 4. `run.json`

```json
{"id":"<32 hex>","parent":"<32 hex>|null","created":"<iso>","preset":"Expressive|null",
 "changed":"face: mediapipe_mesh strict: false → true | null",
 "chain":{"<stage>":{"tool":"…","params":{…},"key":"<sha256>|null","cached_from":"<run id>|null"}, …all nine stages…},
 "cost_usd_total":0.0,"mode":"depth|face_mesh|depth_mesh|original",
 "state":"running|done|error|created","error":{"message":"…","fix":"…"}|null,"started":"…","finished":"…"}
```

`mode` is derived from the chain (`stages.mode_for_chain`): depth on + face on → `depth_mesh`, depth on → `depth`,
face on → `face_mesh`, neither → `original` (new: composite `original` + face `off`; `mask_review.fingerprint`
covers it with `workflow-mode.json`, `original.mp4`, `composite-silent.mp4`, `seedance-input.mp4`).
`workflow-mode.json` is now written for every mode, including `depth`.

## 5. Cache keys and reuse (`stages/cache.py`)

`key = sha256(stage, tool, canonical JSON of params, sorted (input name, sha256) pairs)`. Same inputs + tool +
params give the same key in any run (tested across two folders); any change in any part changes it. Keys are in
every report and in `run.json.chain`.

Reuse: before running a **paid** tool, the runner looks for another run under the same `runs/` whose report for
that stage has the same key, state `done`/`cached`, and whose output files still hash to what that report
recorded. On a hit the outputs are hard-linked in, the report gets `cached_from: <that run>`, `state: "cached"`,
`cost_usd: 0`, and the health line ends with "(reused from run …, nothing re-billed)". Free tools always run
(they are fast and local). Legacy runs have no reports, so they are never reused automatically; branch them.

## 6. Branching (`stages/branch.py`)

`stages.branch(parent, stage, tool=None, params=None, runs_root=None)` →
`(child_folder, chain, changed)`; then `stages.run_branch(child, chain, stage, status)`.

- New 32-hex id under `runs/`; `run.json.parent = <parent id>`; `changed` is one plain line:
  tool change → `face: mediapipe_mesh (strict: false, pad: 1.8, max_gap: 6) → off`;
  param change → `face: mediapipe_mesh strict: false → true`; several → comma-separated.
- `upload.mp4` and every output of every stage **before** `stage` are hard-linked from the parent
  (`os.link`, fallback `shutil.copy2`; folders file by file). `audio-manifest.json` is copied, not linked,
  because the prepare step rewrites it. The earlier stages' reports are copied with `cached_from: <parent>`.
- `mask-review.json` is never carried over: a child run needs its own full-clip review.
- `stage` and everything after it re-run (`run_chain(child, chain, from_stage=stage)`); for a change at
  `prompt` / `generate` / `finish` nothing re-runs: the child is created `done` with every prepared artifact
  linked, ready for review and a draft (nothing is submitted automatically, it is paid and needs references).
- The parent folder is never written to (asserted with sha256 of every file in the tests). For legacy parents
  (no `run.json`) the chain and reports are reconstructed in memory (§9); the parent still gets nothing written.
- Legacy depth runs keep the clean cutout only as `composite-silent.mp4`; `branch` links it into the child as
  `depth-composite-silent.mp4` as well so the face tools find their base.
- `stages.tree(runs_root, summaries)` returns the forest (`children` nested), newest first.
- Branching a branch inherits the branch's params (`pad: 2.0` stays when `strict` is changed next).
- `branch(..., also={later_stage: {tool, params}, …})` changes several stages in **one** child (each `also` stage must
  come after `stage`); `changed` joins the lines with " · ". Without `also` the child is exactly as before.
- `CARRY` (`words.json`, `mouth-guidance.json`, `subtitles.json`): non-stage artifacts hard-linked from the parent when
  present; call `fresh()` before rewriting one in the child.
- **Edit sessions** (`stages/editlayer.py`, timeline editor): pending manual edits of run `<id>` live in
  `runs/_sessions/<id>/` (never in the run folder; `GET /jobs` and `tree` skip the folder). `POST /jobs/{id}/edits/save`
  turns the whole session into exactly one branch at the earliest stage a track changes (a words-only session at
  `prompt`), writes `edit-layer.json` and `run.json.edits` into the child, appends the session `log.txt` /
  `calls.jsonl` to the child's, then runs the child like `/branch` (shared `run_child()` in `app.py`). Details:
  `docs/TIMELINE-SPEC.md` §2 and §A1.

## 7. Offline switch and the calls log (`stages/calls.py`)

`PUPPETEER_OFFLINE=1` (also `true`/`yes`/`on`): every paid or network code path calls
`stages.calls.record_call(folder, provider, endpoint, stage=None, tool=None, cost_usd=None)` **before any I/O**;
in offline mode it raises `stages.OfflineError("<provider endpoint> is switched off in offline mode
(PUPPETEER_OFFLINE=1); nothing was sent.")` (with a `.fix` attribute). Wired into: `pipeline.depth_replicate`,
`pipeline.depth_hf`, `raw_masks._upload` and `_predict`, `audio_workflow.separate`, `providers/fal.py`
`submit_draft` and `finalize`, `providers/enhancor.py` `submit_draft` and `finalize`, `media_host.upload`, and
`seedance_bridge.wait_and_finish` (polling). On startup in offline mode saved requests are not resumed and the
run's `status.json` is not touched. Free tools (probe, original audio, composite, MediaPipe face mesh) run
normally, so Fast-mode runs and face branches work fully offline. `tests/conftest.py` clears the variable for
the test run and redirects the global log and `presets.json` to a temp dir.

Otherwise `record_call` appends `{time, provider, endpoint, stage, tool, cost_usd, ok}` to
`runs/<id>/calls.jsonl` and the same line plus `run` to `runs/calls.log` (global). `stage`/`tool` come from the
runner's context when the caller does not pass them; `cost_usd` from `stages/costs.py` (clip length from
`upload.mp4`). `ok: true` means the request was sent; a failure afterwards is in `log.txt`. The run's
`cost_usd_total` and each report's `cost_usd` are sums of these lines. "Zero Replicate calls" = no
`calls.jsonl` in the child (the integration test asserts exactly that on the real run).

## 8. Costs and the cost gate (`stages/costs.py`, `app.py`)

`GET /costs` returns the table: per tool `provider`, `endpoint`, the pricing model (`usd_flat` = Replicate's
listed average per run, `usd_per_clip_second`, or `gpu` + `usd_per_gpu_second` + `gpu_seconds_per_frame`),
`source`, `date`, `verified`, and `estimate_usd_per_10s_clip`. Numbers follow `docs/COSTS-RESEARCH.md`
(2026-10-22): depth-anything-video ≈ $0.04 per run (T4, listed average), chenxwh ≈ $0.14, sam3-video on an
L40S at $0.000975/s × 0.35 s per frame **per comma-separated term** (unverified runtime constant
`SAM3_SECONDS_PER_FRAME`), demucs ≈ $0.015, fal Seedance 2.5 480p draft $0.2646 per clip second (480p
$0.2205/s × 0.6 for a video input × input + output seconds; verified), fal 1080p completion $1.3968 per clip
second (verified), Enhancor $0.30 per second placeholder (no public price list; `verified: false`), HF depth $0.
For the 8.1 s fixture: depth ≈ $0.04, SAM with two terms ≈ $0.13, fal draft ≈ $2.15, fal 1080p ≈ $11.34.

**Gate rule.** The paid endpoints (`POST /jobs`, `POST /jobs/{id}/seedance`, `POST /jobs/{id}/hd`,
`POST /jobs/{id}/branch`) compute the estimate first. If it is above zero and the request does not carry
`confirm_cost=true` (form or JSON; `1`/`on`/`yes` also count) they answer **402**:

```json
{"detail":"Preparing this video costs about $0.18. Confirm the cost to run it.","message":"…same…",
 "fix":"Send confirm_cost=true with the same request to run it (the UI shows the estimate on the button).","estimated_cost_usd":0.1832}
```

and nothing runs (for `POST /jobs` the uploaded file is discarded again). Free chains (Talking head, face
branches) need no confirmation.

**No legacy exception.** Every paid request on every route — `POST /jobs` (old `mode` field, `preset` or
`chain`), `POST /jobs/{id}/seedance`, `POST /jobs/{id}/hd`, `POST /jobs/{id}/branch`, `POST /jobs/{id}/mask/apply`
— is refused with 402 unless it carries `confirm_cost=true`; a missing field counts as no confirmation, and a
refusal writes nothing anywhere (the 402 body is the record; a parent run is never touched). The UI sends
`confirm_cost=true` from every paying button, which shows the estimate first, so one click is both the look and
the confirmation. Free chains (Talking head, face branches, the free wand tools) need nothing. (An earlier
version let a request without the field run "as the old UI did"; that hole was closed on 2026-10-23 because the
Definition of Done says no paid call fires without confirmation, and the old tests now send the field.)

## 9. Legacy runs (`stages/migrate.py`)

`stages.reconstruct(folder, with_keys=False, write=False)` → `(run, reports)` built from `workflow-mode.json`
(or inferred from the files), `manifest.json`, `audio-manifest.json`, `sam-report.json`, `face-tracking.json`,
`generation.json`, `status.json` and the artifacts present. `run['migrated'] = True`. `with_keys=True` hashes
the artifacts and fills `key` and output hashes (needed to branch; done automatically by `branch`). `write=True`
writes `run.json` and the reports into the folder (used on copies, never on the original runs by the app).
`stages.run_info(folder)` is what `GET /jobs/{id}/run` uses: `run.json` + reports when present, otherwise the
in-memory reconstruction with `migrated: true`. A failed legacy run gets `state: "error"` on its best-guess
failing stage with the saved status text as `error.message`.

## 10. Presets (`stages/presets.py`, `presets.json`)

Built-ins (always listed first, defined in code): **Talking head** (Fast = `face_mesh`), **Full body**
(Advanced = `depth`), **Expressive** (Advanced + mesh = `depth_mesh`), **Profile-heavy** (Advanced with the mesh
off = `depth`). `presets.json` at the project root lists them for reference and holds the user-saved ones
(`builtin: false`, with `chain`, `source_run`, `created`). A preset = name + one-line description + chain.
`stages.chain_for_mode(mode, prompt, provider, clean_dialogue)` / `mode_for_chain` / `normalize_chain`
(every stage present, params defaulted) / `describe_chain` (one line per stage for the UI).

When `POST /jobs` uses a preset, the form's `prompt` (mask subject), `provider` (depth model) and
`clean_dialogue` are applied on top of the preset's chain. An explicit `chain` is used as sent.

## 11. Endpoints

All existing routes are unchanged. New or extended (every error body: `{detail, message, fix}`, plus
`estimated_cost_usd` on 402; `detail` is the sentence so the old UI helper still shows it):

- `POST /jobs` — form: `video` (file) plus either the legacy `mode` (`depth|face_mesh|depth_mesh`) or `preset`
  (name, case-insensitive) or `chain` (JSON `{stage: {tool, params}}`), and `prompt`, `provider`,
  `clean_dialogue`, `confirm_cost`. Response as before plus `estimated_cost_usd` and `preset`:
  `{"state":"running","status":"Starting","id":"…","estimated_cost_usd":0.0,"preset":"Talking head"}`.
  On error the job status gets `fix` as well: `{"state":"error","status":"<sentence>","fix":"<suggestion>"}`.
- `GET /jobs` — each run adds `parent`, `changed`, `preset`, `cost_usd_total`, `fix`.
- `GET /jobs/tree` — `{"runs":[{…summary…,"children":[{…,"children":[]}]}]}`, roots newest first.
- `GET /jobs/{id}/run` — `{"run": run.json, "reports": {stage: report}, "migrated": bool, "status": {…}, "calls": [...]}`.
- `GET /jobs/{id}/calls` — `{"id","calls":[{time,provider,endpoint,stage,tool,cost_usd,ok}],"cost_usd_total","note"}`.
- `POST /jobs/{id}/estimate` — form or JSON `{stage, tool?, params?}` →
  `{"id","stage","changed":"face: mediapipe_mesh strict: false → true","stages_to_run":["face"],"estimated_cost_usd":0,"paid":[],"free":true,"note"}`.
  For `mask`: `stages_to_run` = `["mask","composite","face"]`, `paid` = `[{"stage":"mask","tool":"sam3_replicate","label":"SAM 3 on Replicate","estimated_cost_usd":0.123}]`.
- `POST /jobs/{id}/branch` — form or JSON `{stage, tool?, params? (JSON object or string), confirm_cost?}`.
  402 when the re-run includes a paid stage and `confirm_cost` is not true. Otherwise creates the child and runs
  it in a background thread like `POST /jobs`:
  `{"state":"running","status":"Branched from <parent> · face: mediapipe_mesh → off","id":"<child>","parent":"<parent>","changed":"…","estimated_cost_usd":0}`.
  Poll `GET /jobs/{child}`; final status `Preparation complete · input review required` (or `Ready · review the
  prepared input and create a draft` for a change at prompt/generate/finish).
- `GET /costs` — the price table (§8).
- `GET /presets` — `{"presets":[{name, description, mode, builtin, chain, summary:[…], source_run?, created?}]}`.
- `POST /presets` — form or JSON `{name, description, job}` → `{"preset": {…}}`; 400 for a built-in name or
  a missing name, 404 for an unknown job.
- `GET /stages` — `{"stages":[{"name","label","automatic","tools":[{name,stage,label,paid,experimental,description,params:{name:{type,default,label,hint}},outputs,inputs}]}]}`.

## 12. Entry points kept as functions

`pipeline.run(src, directory, prompt, provider, status, clean_dialogue)`, `face_mesh.run(src, folder, status,
clean_dialogue)` and `face_mesh.run_depth(src, folder, prompt, provider, status, clean_dialogue)` are thin
wrappers over `stages.runner.run_mode(mode, …)`; they produce the same artifacts and status lines as before plus
`run.json`, the reports and `log.txt`. `workflow.py prepare` therefore writes them too. `pipeline.normalize`,
`pipeline.depth_replicate`, `pipeline.depth_hf`, `pipeline.composite`, `raw_masks.segment_raw`,
`raw_masks.clean_border_fragments`, `audio_workflow.separate`, `audio_workflow.prepare_seedance_video`,
`face_mesh.mesh_worker` are called by the tools through their modules, so patching them still works.

## 13. Verification done (Agent 1)

- `tests/test_regression.py` (37 tests, written first and green against the untouched code, still green).
- `tests/test_stages.py` (30 tests): registry, cache keys, reuse, reports, branching, offline switch for every
  paid path with `requests`/`fal_client` mocked to fail on contact, calls log, cost gate, presets, migration,
  tree and the new endpoints.
- `tests/test_branch_integration.py`: hard-links `runs/85e5dbe64df1464fa63825319ebfa104` to a new id, migrates
  it, branches it three times through `POST /jobs/{id}/branch` with `PUPPETEER_OFFLINE=1` (pad 2.0 → done with a
  new `composite-silent.mp4`, `seedance-input.mp4`, `face-tracking.json`; `strict: true` → plain error "lost
  face …" with a fix, numbers still written; `off` → the cutout becomes the composite). Earlier artifacts share
  the parent's inode, every parent and fixture file is sha256-identical before and after, no `calls.jsonl`
  anywhere. Runs in ~9 s, cleans up its folders, skipped without `.venv-face`.
- Browser on port 8772 (offline): `/` and `/?job=85e5…` load, the Runs list renders 17 runs, the review panel
  shows the tracking line, `/jobs/tree`, `/jobs/{id}/run`, `/stages` return JSON, no console errors, no
  horizontal scroll at 380 px.

## 14. Open points for Agents 2 and 3

- Agent 2: the old UI never sends `confirm_cost`; add it (true) to Prepare / Create draft / Approve HD / Re-run
  buttons and show `estimated_cost_usd` from `POST /jobs/{id}/estimate` or the 402 body. Use
  `GET /jobs/{id}/run` for Studio cards (`reports[stage].health`, `warnings`, `frames`, `state`, `error.fix`)
  and `GET /jobs/tree` for the Runs page. `jobs[...]['fix']` / `status.json.fix` carries the suggestion for
  the banner. Mode `original` (composite original + face off) has no label in the old `MODES` map.
- Agent 3: register new tools with `register(...)` in `stages/input_doctor.py` (`doctor`) and `stages/mask.py`
  (wand/brush); set `inputs`/`outputs`, call `fresh()` before writing, and mark hosted ones `paid=True` with a
  `costs.PRICES` entry. A mask edit should be a branch at `mask` (depth is linked, nothing re-billed); the
  approval clears by itself because the fingerprint files change. `providers.base.build_prompt` still says
  "colored-depth composite" for mode `original`; adjust when that mode gets a UI.
- Cache reuse currently covers paid tools only; free tools always re-run.

## 15. UI (Agent 2): what later agents must know

The frontend is `static/index.html` (markup + `<template>`s), `static/app.css` and ES modules `static/*.js`; the
full map, the view/state model, the review-panel hook for the mask wand and the endpoint list per view are in
`docs/UI.md`. Backend additions made for it (all additive, tested in `tests/test_ui_routes.py`):

- `POST /jobs` accepts optional `char1` / `char2` files (saved as `char1-reference.<ext>` / `char2-reference.<ext>`,
  the same rules as the seedance route) so Quick mode uploads the character with the job.
- `POST /estimate` (form or JSON: `preset` | `mode` | `chain`, `seconds`, `prompt`, `provider`, `clean_dialogue`) →
  `{estimated_cost_usd, paid, free, mode, seconds}` for the button labels before anything is uploaded.
- `GET/POST /compare/picks` → `runs/_compare/picks.json` (one pick per `sorted run ids + ':' + stage`; `GET /jobs`
  ignores the folder because its name is not 32 hex).
- `GET /jobs/{id}/run` also returns `seconds` and `estimates {draft: {fal, enhancor}, complete: {fal, enhancor}}`.
- `mask_review.state(folder, job=None)`: with the job's status dict it answers `status: "preparing"` while the run
  is still going and `status: "failed"` (+ `fix`) after an error, instead of `unavailable`; `unavailable` now carries
  a `fix` too. `approved` / `status` / `note` / `fingerprint` are unchanged; `workflow.py` keeps calling it with one
  argument.
- The UI sends `confirm_cost=true` from every paid button (Prepare with a paid preset or mode, Create draft, Approve
  & complete, Re-run from here when the branch includes a paid stage) and shows the estimate on the button first.

## 16. Input doctor and mask wand (Agent 3): what later agents must know

Details in `docs/INPUT-DOCTOR.md` and the "Implementation" section of `docs/MASK-WAND.md`. In short:

- **`input_doctor` has two tools**: `probe` (unchanged, registered first) and `doctor` (checks + safe fixes), and
  `doctor` is now the default of the four built-in presets and the three legacy modes (`chain_for_mode`). Legacy runs
  still reconstruct with `probe`. The doctor's outputs are `original.mp4`, `input-doctor.json` and, for a small
  face, `tracking-source.mp4` + `tracking-source.json`; its report `data` keeps `source` and `normalized` (the
  manifest reads them) and adds `checks`, `fixes` (with before/after notes), `advice`, `measurements`. Its params are
  the thresholds, so they are part of the cache key. With an unreadable upload it warns and lets
  `pipeline.normalize` raise the real error, exactly like `probe` (the regression fakes still pass).
- **The face stage** lists `tracking-source.mp4` and `tracking-source.json` among its inputs (missing ones are
  skipped, so existing keys are unchanged); `mesh_worker.py` tracks on the zoomed copy when both exist and maps
  landmarks back with `mesh_tracking.map_landmarks`. `face-tracking.json` says which file was tracked
  (`tracking_source`).
- **Mask stage tools**: `sam3_replicate` (default, unchanged), `local_propagate` (free), `brush` (free),
  `sam3_points_fal` (paid), `sam2_points_replicate` (paid), `off`. The wand tools edit an existing mask and are
  meant to run as a branch at `mask`; they read the base masks from `params.base_run` (else `run.json.parent`),
  so the base run id is part of the cache key. They write `raw-masks/`, `clean-masks/`, `sam-report.json` (+ `wand`
  section), `mask-edits.json`; the Replicate one also `sam-attempts.json` / `sam-raw-request.json`, the fal one
  `wand-hosted.json`. `stages/wand.py` holds the algorithms, the COCO RLE codec and the preview renderers.
- **Costs**: `costs.PRICES['sam3_points_fal']` ($0.005 per 16 frames, a new `usd_per_frame` pricing model in
  `price_for`) and `['sam2_points_replicate']` ($0.029 listed average); `estimate_tool` multiplies by the number of
  click types in `params.edits` (one hosted call each). The registry test's paid set includes the two new tools.
- **Endpoints**: `POST /jobs/{id}/mask/preview`, `GET /jobs/{id}/mask/frame`, `POST /jobs/{id}/mask/apply` (the
  latter shares `start_branch()` with `POST /jobs/{id}/branch`, which is otherwise unchanged). `/mask/preview`
  writes PNGs under `runs/<id>/wand-preview/` of the run being edited; nothing else writes into a parent.
- **Tests**: `tests/test_input_doctor.py` (11) and `tests/test_mask_wand.py` (10); the whole suite is green.

## 16. Review fix pass (2026-10-23, lead)

The independent reviewer's findings and what changed:

- `status.json` and `mask-review.json` are written through `fresh()`-style unlinking, so a hard-linked copy of a run
  never writes into the run it was linked from (the 85e5 fixture's `status.json` had been overwritten that way; it is
  restored). The integration test copies those files instead of linking them.
- A non-video upload fails with "This file could not be read as a video … nothing was prepared." plus a fix
  (`stages.input_doctor.normalize_or_explain`; PyAV's `InvalidDataError` is also a `ValueError`, so decoder errors are
  caught first).
- A source without an audio track no longer stops the run: the prepared clip and the final export are silent, the
  audio manifest carries a warning, and `audio-note.json` records it. Clean dialogue still needs `vocals.wav`.
- A face found only when zoomed in counts as small, so the zoomed tracking copy is written.
- `run.json.changed` summarises list params in words ("2 clicks on frame 24 (1 include, 1 exclude)", "1 brush stroke
  on frames 24–28") and hides `base_run`; older branches are re-described from their chains by `GET /jobs` and
  `GET /jobs/tree`. Legacy status strings with raw arrays are reworded in the Runs list.
- Branch children show their own `run.json.created` date. The wand's backward propagation says "the start of the
  clip". The review tab follows the best available preview unless the user chose one.
- The cost gate has no legacy exception any more (§8).
