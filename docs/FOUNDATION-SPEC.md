# Puppeteer Foundation phase: shared spec for all agents

This file is the single brief for the Foundation phase. Every agent reads it fully before touching code.
The user's original request is reproduced in section A verbatim; sections B onward are the lead's decisions
that make the agents' work fit together. When B conflicts with A, A wins and you flag it in your report.

## A. The user's request (verbatim)

Puppeteer, Foundation phase: turn the app into a stage rack for experimenting. Improve and level up; DO NOT remove any existing function.

MUST KEEP WORKING (regression list)
- All three prep modes: Advanced (depth+SAM), Fast (face mesh), Advanced + Face mesh (lenient gaps)
- Providers fal + Enhancor, draft → finalize, original-audio restore, clean_dialogue
- Review gate with artifact fingerprint (any change clears approval)
- SAM multi-term prompts ("person, hands"), RGB retry, fallback model, sam-attempts/sam-report
- Face tracking: face-first crop, gap fill ≤6 frames, strict in Fast / lenient in Advanced+mesh
- Runs list, ?job= links, /jobs/{id}/files, doctor.py, all existing tests
Before changing anything, write tests/test_regression.py covering this list. It must pass at the end.

GUIDING PRINCIPLE: FORGIVING BY DEFAULT
- No hard stops on partial data: fallback chain per slot, fill and flag, warn and continue. Error only when every option failed.
- Every message in plain language with a suggested fix and, where possible, a fix button. No raw tracebacks or arrays in the UI (log them to the run folder instead).
- Silent retry for network/server glitches. Paid generations never retry automatically and always show the estimated cost and ask first.
- Robust tools are the defaults. Experimental or non-commercial tools are opt-in and labelled.

1. STAGE RACK ARCHITECTURE
- A stages/ package. Stages: input_doctor, audio, mask, depth, face, composite, prompt, generate, finish. Each has a registry of interchangeable tools with one interface: run(inputs, params) -> outputs + report.json (frames covered/filled/missing, gap ranges in seconds, warnings, time, cost).
- Wrap the existing code as the first tool in each registry. No behaviour change unless stated.
- Per-stage caching keyed on inputs + tool + params: changing one stage re-runs only it and what follows. Never re-bill an earlier paid step.
- run.json records the full chain (tool + params per stage).

2. BRANCHING, NEVER OVERWRITING
- Changing any stage on a run creates a new branch run (child), reusing cached stage outputs. The original stays intact.
- Runs list shows the branch tree (parent → children) with a one-line "what changed" per branch.

3. THREE DEPTHS IN ONE UI
- Quick: upload, pick a preset and a character, go. Presets: "Talking head" (Fast), "Full body" (Advanced), "Expressive" (Advanced + mesh), "Profile-heavy" (Advanced, mesh off).
- Studio: the run as stage cards: tool dropdown, on/off, key params, output preview, health line in plain words ("hands lost 2.1–2.4 s, filled"), Re-run from here.
- Lab: the compare view (section 6).
- Save as preset: any run's chain becomes a named preset.

4. INPUT DOCTOR (new first stage)
- Checks resolution, fps, duration, brightness, face size, shake, audio present.
- Auto-fixes where safe (fps normalise, mild brighten, upscale small faces for tracking only, never altering the original), with a before/after note.
- Anything it can't fix becomes advice ("Face is small: move closer"). Never blocks; only warns.

5. MASK WAND (click to fix)
- In review, pause on any frame and click: + to include (a missed finger), Alt-click − to exclude (spill). SAM propagates the fix forward and backward through the clip.
- Find which hosted SAM model on Replicate/fal accepts point prompts for video (SAM 2 video likely; check if our SAM 3 model does). Use the best available; document the choice.
- Simple brush/eraser fallback for the last 1%.
- Re-running masks reuses the cached depth (no depth re-bill). Approval clears automatically after any mask change.

6. A/B COMPARE (Lab)
- Pick 2–4 runs or branches and play any stage output side by side, synced, with play at 1x and 0.25x.
- Each tile shows its chain differences and report numbers.
- An "A or B?" pick button that records your choice per comparison (stored, for the scoring phase later).

7. COST METER
- Every paid step shows the estimated cost before running; each run shows its total spent.

8. BUGS TO FIX
- The stale red banner that shows another job's error.
- The review panel saying "Prepare the video first" on prepared jobs.
- The face-tracking line showing red when it should be a yellow warning.

AGENTS
- Agent 1: regression tests + stage architecture + caching + branching.
- Agent 2: UI (Quick/Studio/Lab, presets, banner bugs, cost meter).
- Agent 3: input doctor + mask wand.
Run them sequentially where they touch the same files. Then a fresh reviewer agent that hasn't seen the work checks the Definition of Done line by line and reports pass/fail.

DEFINITION OF DONE
- [ ] test_regression.py passes; every function on the MUST KEEP list still works end to end (verified in the browser, no paid jobs)
- [ ] All tests pass, plus new tests for the stage registry, cache keys and branching
- [ ] Changing only the face tool on an existing run creates a branch, re-runs only face + later stages, and makes zero Replicate calls (checked in logs)
- [ ] The parent run is unchanged after branching; the Runs list shows the tree with "what changed"
- [ ] Quick mode: one upload + preset + character reaches the review step with no other clicks
- [ ] Studio cards show tool, preview and a plain-language health line for every stage
- [ ] Input doctor runs on a dark, small-face clip, auto-fixes what it can, and shows advice without blocking
- [ ] Mask wand: a + click on a missed hand on one frame fixes it across the clip; Alt-click removes spill; approval clears after
- [ ] Compare view plays 3 runs synced at 1x and 0.25x; A/B picks are saved and survive reload
- [ ] Every paid step shows its cost first; no paid call fires without confirmation
- [ ] All three banner/review bugs are fixed
- [ ] No raw errors in the UI; every failure shows plain words + a suggestion
- [ ] No console errors; works at 380px with no horizontal scroll
- [ ] README updated in plain language: the three depths, the presets, how branching works
- [ ] End by telling me to restart the app and giving me the link to the Runs page

## B. Hard rules for every agent

1. **Never make a paid or live network call.** `.env` in this project holds REAL keys for fal, Enhancor, Replicate
   and Hugging Face. Tests mock every HTTP and `fal_client` call (see `tests/test_raw_masks.py`,
   `tests/test_providers.py` for the patterns). Never run `workflow.py prepare` in `depth` or `depth_mesh` mode, never
   call `segment_raw`, `depth_replicate`, `depth_hf`, `separate`, `submit`, `submit_hd`, `media_host.upload` or any
   `fal_client` function for real. The local MediaPipe face mesh (`.venv-face`, `mesh_worker.py`) is free and may be
   run for real. Set `PUPPETEER_OFFLINE=1` (Agent 1 implements it) whenever you start a server for verification.
2. **Do not touch the user's running servers.** Ports 8770 and 8771 are the user's own instances; never kill them.
   Start your own verification server on port 8772 (Agent 1), 8773 (Agent 2), 8774 (Agent 3), 8775 (reviewer):
   `PUPPETEER_OFFLINE=1 PORT=8772 .venv/bin/python launch.py` from the project folder, in the background, and stop it
   when you finish.
3. **Do not delete or modify anything under `runs/` that already exists** except by creating new run folders. The
   existing runs are real paid outputs and are the fixtures for offline browser verification. Useful ones:
   - `85e5dbe64df1464fa63825319ebfa104`: Advanced + Face mesh, done, has `sam-report.json` (terms person + hands),
     tracked 163 / filled 13 / missing 19, two lost ranges shown as a warning. Best fixture for branching
     (change the face tool/params, re-run only face and later, zero Replicate calls).
   - `5031246f08be4951b3abb2716f168158`: Advanced + Face mesh, done, prepared and awaiting review.
   - `ecadf68ef7a44b22b2ca9860f5e4afde`: Advanced (depth), done, reviewed (`mask-review.json`).
   - `571e5a15b3784fee991d2ae6292b4745`: Advanced, fal draft finished (`final-preview.mp4`, `generation.json`).
   - `3c54f2952b494f62810dfac35a4d738b`: Advanced + mesh, fal draft finished, clean dialogue stems present.
   - `0b6ee85cc2464b6e9dd7d4e8605b6703`: Fast mode run that failed the strict gap rule (error state).
   - `f0c90ff4548e43b984b444baafbe63d6`: depth run that failed frame alignment (SAM found 0 frames).
   Make test copies under `runs/` (new 32-hex ids) or in a temp dir when you need to mutate.
4. **Keep every existing file name and content in a run folder as it is today** (`original.mp4`, `depth.mp4`,
   `mask.mp4`, `composite-silent.mp4`, `depth-composite-silent.mp4`, `seedance-input.mp4`, `face-landmarks.json`,
   `face-tracking.json`, `sam-report.json`, `sam-attempts.json`, `clean-masks/`, `manifest.json`,
   `audio-manifest.json`, `workflow-mode.json`, `status.json`, `mask-review.json`, `generation.json`,
   `seedance-request.json`, `seedance-response.json`, `final-preview.mp4`, `hd/…`). The review fingerprint
   (`mask_review.FILES`), the CLI and old runs depend on them. New files are added next to them.
5. **Every existing HTTP route, form field, CLI command and module function keeps working with the same
   inputs and outputs.** Add, never remove. The old `mode` form field (`depth` / `face_mesh` / `depth_mesh`) keeps
   working on `POST /jobs`.
6. **Never print, log, or write a key value anywhere.** Logs go to the run folder, never credential values.
7. **Plain-language errors.** Anything that reaches the UI is a sentence a non-engineer understands plus a
   suggested fix. Raw exceptions, arrays and tracebacks go to `runs/<id>/log.txt` (append-only) instead.
8. **Tests:** `.venv/bin/python -m pytest -q` must be green when you hand over. Add tests for everything you build.
   Python is 3.14 in `.venv`; the mesh worker runs in `.venv-face` (3.12).
9. **Do not commit.** The user has not asked for commits. Leave the working tree with your changes.
10. **Browser checks** use the built-in browser tools (`mcp__Claude_Browser__*`) against your own server on your
    port. Check at desktop width and at 380 px (`resize_window` width 380): no horizontal scroll, no console errors.
11. **Report** at the end: what you built, what you verified (how), what you could not verify and why, and anything
    you changed that later agents must know. Write the "must know" part into `docs/STAGES.md` (Agent 1) or
    append to it (Agents 2 and 3), so the next agent reads one file.

## C. Architecture decisions (Agent 1 implements; everyone relies on them)

### Stage order and tool mapping of the existing code

Pipeline order is the real data flow (the user's list had mask before depth, but SAM runs on the depth video):

| # | stage | first tool (wraps existing code) | other tools | paid? |
|---|---|---|---|---|
| 1 | `input_doctor` | `probe`: resolution, fps, duration, audio present (from `upload.mp4`, pure PyAV) | Agent 3 adds `doctor` (brightness, face size, shake, safe auto-fixes) | no |
| 2 | `audio` | `original` (packet-copy of the source track, today's default) | `clean_dialogue` (Demucs on Replicate: `audio_workflow.separate`) | clean_dialogue yes |
| 3 | `depth` | `depth_anything_replicate` (`pipeline.depth_replicate`, lucataco) | `depth_anything_replicate_chenxwh`, `depth_anything_hf`, `off` | yes (hf: free quota) |
| 4 | `mask` | `sam3_replicate` (`raw_masks.segment_raw` + `clean_border_fragments`: multi-term, RGB retry, fallback model, sam-attempts/sam-report) | `off`; Agent 3 adds wand/brush edit tools | yes |
| 5 | `composite` | `depth_cutout` (`pipeline.composite`: depth subject over original background) | `original` (passthrough: `composite-silent.mp4` = original frames, used by Fast mode) | no |
| 6 | `face` | `mediapipe_mesh` (`face_mesh.mesh_worker`; params `strict` true in Fast, false in Advanced + mesh; `pad`, `max_gap`) | `off` | no |
| 7 | `prompt` | `identity_only` (`seedance_bridge.DEFAULT_PROMPT` + `providers.base.build_prompt`) | user text as a param | no |
| 8 | `generate` | `fal` and `enhancor` (the two existing adapters, draft submit + poll + download) | | yes |
| 9 | `finish` | `restore_original_audio` (`audio_workflow.finish_preview`) + `complete_draft` (HD finalize through the same provider) | | HD yes |

Existing modes become chains (the `mode` field is still accepted and recorded in `workflow-mode.json`):

- `depth` (Advanced): depth on, mask on, composite `depth_cutout`, face `off`.
- `face_mesh` (Fast): depth `off`, mask `off`, composite `original`, face `mediapipe_mesh` strict.
- `depth_mesh` (Advanced + mesh): depth on, mask on, composite `depth_cutout`, face `mediapipe_mesh` lenient.

The prepared clip `seedance-input.mp4` (composite + chosen audio, `audio_workflow.prepare_seedance_video`) is produced
at the end of the preparation chain exactly as today; keep `depth-composite-silent.mp4` for depth_mesh.

### Tool interface

```
class Tool:
    name: str            # registry key, e.g. "sam3_replicate"
    stage: str           # "mask"
    label: str           # plain words for the UI: "SAM 3 on Replicate"
    paid: bool
    experimental: bool   # opt-in, labelled in the UI
    def estimate_cost(self, inputs, params) -> float | None   # USD, before running
    def run(self, inputs: dict, params: dict, folder: Path, status: callable) -> dict   # returns outputs (artifact names)
```

Every run writes `runs/<id>/stages/<stage>/report.json` (keys: `tool`, `params`, `inputs` (names + sha256),
`outputs`, `frames` {covered, filled, missing}, `gaps` (ranges in seconds), `warnings` (plain sentences), `health`
(one plain sentence for the Studio card, e.g. "hands lost 2.1–2.4 s, filled"), `seconds`, `cost_usd`,
`cached_from` (run id or null), `started`, `finished`). A stage that is off writes a report with `tool: "off"`.

### Cache and branching

- Cache key per stage = sha256(stage name, tool name, canonical JSON of params, sha256 of each input artifact).
  Stored in the report and in `run.json`.
- `run.json` at the run root: `{id, parent, created, preset, changed: "face: mediapipe_mesh strict → off" | null,
  chain: {stage: {tool, params, key, cached_from}}, cost_usd_total, mode}`.
- `POST /jobs/{id}/branch` with form or JSON `{stage, tool, params}` creates a child run: a new 32-hex id,
  `run.json.parent = id`, hard-links (fallback: copies) every artifact of stages before `stage` from the parent,
  re-runs `stage` and everything after. The parent folder is never written to. `changed` is one plain line.
- `GET /jobs` adds `parent` and `changed` per run, and `GET /jobs/tree` returns the forest (parent → children).
- `runs/<id>/calls.jsonl`: one line per external API call (`{time, provider, endpoint, stage, tool, cost_usd,
  ok}`), plus the same line appended to `runs/calls.log` globally. This is how "zero Replicate calls" is checked.
- `PUPPETEER_OFFLINE=1`: every paid tool raises a plain `OfflineError("… is switched off in offline mode")` before
  any network call. Free tools run normally.

### Cost meter

`stages/costs.py` holds per-tool estimates (USD) with a `source` string and date; `GET /costs` returns them;
`run.json.cost_usd_total` sums `calls.jsonl`. Paid endpoints (`POST /jobs` in a paid chain, `POST /jobs/{id}/seedance`,
`POST /jobs/{id}/hd`, `POST /jobs/{id}/branch` when the re-run includes a paid stage, mask wand hosted tools) require
the form field `confirm_cost=true`; without it they return 402 with `{estimated_cost_usd, message}` and nothing runs.
The UI shows the estimate on the button itself ("Prepare · about $0.40"), so one click is both the look and the
confirmation (Quick mode stays one click).

### Presets

`presets.json` at the project root holds the four built-ins (Talking head = Fast chain, Full body = Advanced,
Expressive = Advanced + mesh, Profile-heavy = Advanced with mesh off) plus user-saved ones (`POST /presets` from
any run's chain). `GET /presets` lists them. A preset is a chain (tool + params per stage) plus a name and a
one-line description.

## D. Order of work

1. Agent 1: `tests/test_regression.py` FIRST (green against the untouched code), then stages package, caching,
   branching, offline switch, calls log, costs, presets endpoints, `docs/STAGES.md`.
2. Agent 2: UI restructure (readable `static/index.html` + `static/app.js` + `static/app.css`), Quick / Studio /
   Lab, presets, cost meter, the three bugs, plain-language errors, Runs page with the tree.
3. Agent 3: `input_doctor` `doctor` tool with auto-fixes, mask wand backend + review UI (click +, Alt-click −,
   brush/eraser), hosted point-prompt SAM tool (choice documented in `docs/MASK-WAND.md`), free local fallback
   that works offline.
4. Reviewer: fresh agent, checks the Definition of Done line by line in the browser (port 8775, offline) and in
   the tests, reports pass/fail per line with evidence.
