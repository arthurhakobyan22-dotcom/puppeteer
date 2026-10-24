# Tidy pass, Agent 3: what moved where (for Agent 4 and the reviewer)

Branch `tidy-pass`. Frontend only, except the approved run-name addition (`PUT /jobs/{id}/name`, `run_summary().name`,
the README line in `stages/export.py`, `tests/test_run_name.py`). The look is `docs/tidy/directions/hybrid.html`: every
token in `static/tokens.css` (dark on `:root` regardless of the system theme; light under `:root[data-theme="light"]`,
header toggle, `localStorage pp-theme`, applied before paint by `static/theme.js`), every component in
`static/components.css`, layout only in `static/app.css`.

## 1. Screens and files

| Screen | URL | Module | Template(s) |
|---|---|---|---|
| Runs (default) | `/`, `/?view=runs` (`&flat=1` list view) | `runs.js` | `tpl-runs`, `tpl-run-card`, `tpl-version-row` |
| New run (Quick start) | `/?view=new` (old `view=quick` without a job) | `start.js` | `tpl-start` |
| Workspace | `/?job=<id>&step=prep\|edit\|world\|generate\|export` (no step = the most useful one; old `view=quick`, `view=studio` → Details on Stages) | `workspace.js` + `prep.js`, `edit.js` (+ `editor.js`, `timeline.js`, `track-*.js`), `world.js`, `generate.js` (+ `generator.js`), `export.js` | `tpl-ws-head`, `tpl-prep`, `tpl-edit`, `tpl-editor`, `tpl-world`, `tpl-generate`, `tpl-export` |
| Compare | `/?view=compare&runs=a,b&stage=<file>` (old `view=lab`) | `compare.js` | `tpl-compare`, `tpl-compare-tile` |
| Details drawer (level 3) | `&details=run\|stages\|reports\|costs` opens it | `drawer.js` (+ `stagecard.js` for the nine stage rows) | the `#details` aside in `index.html`, `tpl-stage-card` |

Each step switch is a `history.pushState` entry (`goStep()` in `state.js`); `popstate` re-renders and the workspace only
swaps the visible step when the run is the same, so the editor's videos survive Back / Forward. `window.puppeteer` keeps
`state, api, navigate, loadJob, registerReviewTool, goStep, openDetails, editor, edits`.

## 2. Deleted (and where the features went)

| Deleted | Features now in |
|---|---|
| `quick.js` (hero + form + `mountFlow`) | `start.js` (the form) and `workspace.js` (the steps) |
| `studio.js` (stage rack + legacy form) | Details drawer → Stages (`drawer.js` + `stagecard.js`); the legacy "Preparation method" select is the "Prep method" field under New run → More options |
| `review.js` (review panel, review box, Needs fixing) | `edit.js`: the editor plus the approve bar; "Needs fixing" is gone (the editor is the fix); "Take the approval back" stays |
| `wand.js` (classic mask wand) | the Mask lane (`track-mask.js`): one method select (Free local · SAM 3 on fal · SAM 2 on Replicate · Brush), one Apply, Tool settings (quality quick / full, Find hands, Clear all). `POST /jobs/{id}/mask/apply` is unused by the UI (untouched on the server); its "one version per apply" is replaced by Apply + Save as new version. The wand never exposed a propagation direction, so nothing was lost there |
| `draft.js` (steps 03 / 04) | `world.js` (set / look / light, background, prompt), `generate.js` (generator, references, draft, final, a render made elsewhere, request files), `export.js` (subtitles) |
| `promptkit.js` | folded into `world.js` (prompt preview + "Edit prompt": rebuild, spoken lines, references, Describe with Claude vision) |
| `runhead.js` | `workspace.js` (the run header: All runs, name with inline rename, chip, spent, Compare, Details); Save as preset → Prep → More |
| `lab.js` | `compare.js` (tray + search instead of the 108-box picker, "Continue with this version", Details) |
| `track-placeholders.js` | unused since the real lanes landed |
| `slots.js` `mountSlots` / `backgroundChip` | `world.js`; `slots.js` keeps the helpers (assets, fit maths, `backgroundControls`, the mode names) |

Duplicates closed (docs/UX-AUDIT.md): the second upload form (A-16/17), the two mask tools (A-38/44/45), the three
provider mentions (A-56: one generator card list), the view rows inside the lane panels (A-47), the steps mounted twice
(A-69), Set / Look / Background in two places (A-72: World & Look → Set carries the placement canvas; the Motion clip
stage row in Details shows the same component for a new version with other settings), the .srt link in three places
(A-55: Export → Downloads only), the failure printed four times (A-05: the banner plus the Prep fix buttons only).

## 3. Levels per step (what is visible by default)

- **Prep** (existing run): picture, prep method, one input-check line, face found / lost, background line, saved characters, progress / fix buttons. Level 2 "More": save as preset, link to Details · Stages. New run: presets, characters, the clip; level 2 "More options": subject to mask, depth model, clean dialogue, prep method.
- **Edit**: views (Prepared clip · Original · Depth · Mask · Motion clip), viewer, transport, lanes, the selected lane's tools, the Save bar (only while something is unsaved) or the approve bar. Level 2: "More views" (Face mesh · editable, Overlay), the lane's "Tool settings", "Downloads".
- **World & Look**: Set (mode, image, background placement + Apply as background), Look, Light + Describe with Claude vision, the read-only prompt. Level 2: "Edit prompt" (text, rebuild, spoken lines, references, task line).
- **Generate**: generator cards, cost line, references (Character 1 / 2 tiles, prepared clip), read-only prompt, Create draft; after a draft: the video, Make the final, Export instead, download. Level 2 "More": a render made elsewhere, generator details, submitted prompt and request / response files.
- **Export**: target cards, What's in it, alpha format, unsaved-edits note, Export; the README + zip after. Level 2: "Choose files", "Earlier exports", "Downloads" (every single file), the Subtitles panel (burn in) appears once a draft or final exists.
- **Details** (level 3, every step and every Runs card): Run · Stages (nine rows, Make a new version from here, Use my own file…) · Reports & log · Costs.

Level-2 panels remember open / closed in `localStorage` (`pp-open-<key>`, keyed per panel); the drawer's last tab is
`pp-details-tab`; the Mask lane's method and quality are `pp-mask-method` / `pp-mask-quality`.

## 4. Feature map with levels (docs/UX-PLAN.md §5)

Clicks are counted from a freshly opened workspace. L1 = always visible, L2 = one click (collapsible / More), L3 = Details drawer.

| # | Feature | Where now | Level | Clicks |
|---|---|---|---|---|
| F-01 | Upload + preset + characters + prepare | New run (`/?view=new`, header "New run") | L1 | 1 |
| F-02 | Subject to mask, depth model, clean dialogue (+ prep method) | New run → More options | L2 | 2 |
| F-03 | Preparation progress + failure fix buttons | Prep (stage rail + status line; banner on failure) | L1 | 0 |
| F-04 | Re-run with lenient gaps · free | banner and Prep fix row; Details → Stages → Face mesh | L1 / L3 | 0 / 3 |
| F-05 | Stage rows: method, settings, health, numbers, warnings, previews | Details → Stages | L3 | 2 (Details, expand a row) |
| F-06 | Make a new version from a stage | Details → Stages → row → button (price on it) | L3 | 3 |
| F-07 | Use my own file (depth / mask / face / motion clip) | Details → Stages → row → "Use my own file…" | L3 | 3 (+ the file pick) |
| F-08 | Per-file downloads, folder zips, masks zip | Export → Downloads; Edit → Downloads; Details → Reports & log | L2 | 2 |
| F-09 | Input check lists | Prep (one line) + Details → Stages → Input check (full lists) | L1 / L3 | 0 / 3 |
| F-10 | Background behind the person | World & Look → Set (canvas + Apply as background); Details → Stages → Motion clip | L1 / L3 | 2 / 3 |
| F-11 | Views (prepared clip / original / depth / mask / motion clip / overlay / face mesh editable) | Edit tabs; Overlay and Face mesh · editable under More views | L1 / L2 | 1–2 |
| F-12 | Transport, counter, zoom, keys | Edit | L1 | 0–1 |
| F-13 | Range selection, markers | Edit timeline | L1 | 1 |
| F-14 | Mask fixes (+ / −, brush, list, preview) | Edit → Mask lane (brush = a method in Tool settings) | L1 / L2 | 2–3 |
| F-15 | Apply to the clip (quick / full / SAM 3 / SAM 2) | Mask lane → Apply (method + quality in Tool settings) | L1 / L2 | 3 |
| F-16 | Flagged frames, Prev / Next, Find hands | Mask lane (flagged frames L1; Find hands in Tool settings) | L1 / L2 | 2–3 |
| F-17 | Face mesh: hide, adjust (drag / fields), expressions, reset, prev / next | Edit → Face lane | L1 | 2–3 |
| F-18 | Words: transcribe (free / paid), singing, select / edit / drag / split / merge / add / delete | Edit → Words lane | L1 | 2–3 |
| F-19 | Subtitles .srt, words.json, mouth-guidance.json | Export → Downloads | L2 | 2 |
| F-20 | Undo / redo / discard / save as new version | Edit Save bar (shown while something is unsaved) | L1 | 1 |
| F-21 | Approve / take the approval back (409 → Reload the latest clip) | Edit approve bar | L1 | 1 |
| F-22 | Face found / lost line, background line | Prep; the approve bar repeats the face line | L1 | 0 |
| F-23 | Audio stems download | Edit → Downloads; Export → Downloads | L2 | 2 |
| F-24 | Character 1 / 2 | New run (before) and Generate → References (after) | L1 | 1 |
| F-25 | Generator picker, resolution, limits | Generate (first block) | L1 | 1 |
| F-26 | Set / Look / Light, image pickers + upload | World & Look | L1 | 1–2 |
| F-27 | Build the prompt, final text + references, warnings | World & Look (preview + warnings L1; Edit prompt L2) | L1 / L2 | 1–2 |
| F-28 | Describe set & light with Claude vision | World & Look → Light block | L1 | 1 |
| F-29 | Insert spoken lines | World & Look → Edit prompt (where the text box is; the plan listed it under Generate) | L2 | 2 |
| F-30 | Create draft | Generate primary | L1 | 1 |
| F-31 | Draft video, download, submitted prompt & request id | Generate (video L1; prompt + request files under More) | L1 / L2 | 1–2 |
| F-32 | Make the final | Generate primary after a draft | L1 | 1 |
| F-33 | Burn subtitles into the final | Export → Subtitles panel (shown once a draft / final exists) | L1 | 1 |
| F-34 | Add a render made elsewhere | Generate → More | L2 | 2 |
| F-35 | Export targets, files, alpha format, progress, README, zip, earlier exports | Export (files and earlier exports L2) | L1 / L2 | 1–2 |
| F-36 | Save as preset | Prep → More | L2 | 2 |
| F-37 | Compare picks | header Compare, run header Compare, Runs cards "Pick to compare", version rows, post-save notice | L1 | 1 |
| F-38 | Runs tree / list | Runs cards + versions; List view (`&flat=1`) | L1 / L2 | 1 |
| F-39 | Open workspace / All runs / based-on link | header "This run", run header "All runs", Details → Run "Based on" | L1 / L3 | 1 |
| F-40 | Run id, based on, record note, recipe | Details → Run / Stages / Costs | L3 | 1 |
| F-41 | Spent | run header, Runs cards, Details → Costs | L1 | 0 |
| F-42 | 402 price confirmation | toast "Yes, spend about $x" / "Not now" everywhere (`costActions` in `ui.js`) | L1 | 1 |
| F-43 | Rename a run | run header pencil, Runs card pencil, version rows (name shown) | L1 | 1 |
| F-44 | Keyboard: ← → Shift+← → Space Home End [ ] Esc Cmd/Ctrl+Z Shift+Cmd/Ctrl+Z Ctrl+Y Ctrl+wheel; new: Cmd/Ctrl+S save; Space on a focused control presses it | Edit | L1 | 0 |
| F-45 | calls / health / costs / presets data | Details → Reports & log links calls.jsonl; `/costs` feeds the Describe price | L3 | 2 |
| F-46 | Offline refusals, "not set up · KEY" | inline lines; key names only in Generate → More, generator cards, Describe hint | L1 / L2 | 0 |

Nothing is over 3 clicks. F-07 (Use my own file) is 3 clicks plus the file pick.

## 5. Hooks left for Agent 4

- `help(term)` in `ui.js` (returns '' for now) and the `.tip` / `kbd` styles in `components.css`.
- Every button goes through `withCost(button, text, cost)` for the "· free" / "· about $x" suffix.
- `notice()` / `showError()` / `costActions()` in `ui.js` are the one toast API; the "?" overlay can use `editor.on` and the key list in `docs/UI.md`.
- State designs: `.empty`, `.skel-card`, `.loading`, `.statusline.running|.error`, chips `preparing · review · ready · draft · final · failed · imported`.

## 6. Verification (port 8792, `PUPPETEER_OFFLINE=1`, Playwright from `.venv-shots`)

Read-only fixture `0be4cf2c…`; writes (approve, take back, rename, 402 toast with a mocked route, set image behind the
person) on a hard-linked copy `38f2416f…` (delete it when done: it is mine). The script lives outside the repo
(scratchpad `verify.py`); the shots are `docs/tidy/after/`. Checked: step rail + Back / Forward, default step per state,
old URLs, the drawer's four tabs + Esc + focus return, five views + More views, the Mask / Face / Words lanes, a mask
click → Save bar + rail badge → Discard, approve → Generate unlocked → 402 toast → take the approval back, header
rename (run.json), Runs search / filters / pick to compare / versions / list view, Compare with two runs, the theme
toggle and its persistence, New run (free preset starts on the clip pick with a mocked POST /jobs; paid preset shows
the price button), 380 px without horizontal scroll, zero console errors apart from the intentional 402.

Caveat found while verifying: `stages.save_run` writes through a hard link, so the first rename on a `cp -al` copy
also wrote the name into the fixture's `run.json`. The endpoint now calls `stages.fresh()` first (tested in
`tests/test_run_name.py`); the fixture's `run.json` still carries `"name": "Kitchen monologue · take 2"` and should
have that key removed by hand (`runs/0be4cf2cadd945008a9c9131b6c75f12/run.json`).
