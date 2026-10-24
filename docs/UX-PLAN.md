# UX plan: one flow for Puppeteer (tidy pass, Agent 1, 2026-10-24)

The audit is `docs/UX-AUDIT.md` (issue codes A-nn are referenced here); the names are `docs/GLOSSARY.md` (G-nn).
Rule for the whole tidy pass: **no backend behaviour change**. The one additive exception proposed here is the run
name (§3.2). Everything else is frontend: templates, modules, CSS and copy.

## 1. The flow in one picture

```
RUNS (library)  ──►  WORKSPACE of one run  ──►  COMPARE (a mode, from anywhere)
  cards, search        Prep → Edit → World & Look → Generate → Export        2–4 versions side by side
  "New run" ─► QUICK START (one panel) ─► lands in the workspace at Prep, progress shown
```

Three screens instead of four views: **Runs**, **Workspace** (one run; Quick start is the empty state of a new
run), **Compare** (a mode over any 2–4 versions). Studio disappears as a place; its stage cards live in an
**Advanced** drawer inside the step they belong to (§4.3). Lab becomes Compare.

Why this is a better starting point than the owner's sketch in two places, and the same everywhere else:

1. **Quick start is the "New run" button of the library, not a tab.** The owner's sketch keeps "QUICK = a guided
   entry". Agreed, but it should not be a top-level destination: the brand link and "New run" open it, it has one
   panel and no hero, and after "Prepare" the user is in the workspace of the new run watching the Prep step
   progress. There is no second upload form anywhere (A-16).
2. **The workspace opens on the step that needs attention, not on step 1.** A finished, unapproved run opens on
   Edit; an approved run without a draft opens on World & Look; a run with a draft opens on Generate. The top bar
   still shows all five steps, so the user can go back. This alone removes one click from journeys (a), (d) and
   (e) and the 1 500 px scroll from every run page (A-09).

## 2. Screens

### 2.1 Runs (library) — URL `/?view=runs` (unchanged)

| Element | Content |
|---|---|
| Toolbar | "New run" (primary, opens Quick start), search box (name, preset, method, what-changed text, id prefix), sort (newest · last worked on · spent), filter chips (needs approval · draft ready · final ready · failed), "Compare (n)" tray button (hidden until one run is in the tray). |
| Card (one per **root** run) | thumbnail (§3.1), **name** (§3.2), state chip, "n versions" link, date, "Spent $x", one-line summary ("Motion clip + face mesh · approved · draft ready"), menu "⋯" (Rename, Compare, Save as preset, Details, Open folder path). Click = open the workspace. |
| Versions (on demand) | "n versions ▸" expands an indented list under the card: name or "What changed" line, state, date, spent, "Compare" tick, open. The tree is the existing `GET /jobs/tree` data; nothing new. The flat list toggle is removed (A-24); the search box replaces it. |
| Empty | "No runs yet." + primary "New run". |
| Loading | 6 skeleton cards. |
| Error | the `showError` toast with "Try again" (as today) plus an inline line in the grid. |

Paging: render 24 cards, "Show more" button (frontend only). Ids never appear on a card; the Details drawer shows
"Run id 0be4cf2c… (copy)".

### 2.2 Quick start — URL `/` (unchanged) and from "New run"

One panel, no hero: "New run". Upload → preset cards (as today, with the price line) → Character 1 / Character 2 →
`Advanced ▸` (Subject to mask, Depth model, Clean dialogue · paid) → price line + **"Prepare · free, runs locally"**
/ **"Prepare · about $0.12"**. Submit navigates to `/?job=<id>` (as today), which shows the Prep step with the
progress line and the step bar. The legacy "Preparation method" form is deleted; its mode select is replaced by the
four presets (they map 1:1 to the modes; A-16, A-17).

### 2.3 Workspace — URL `/?job=<id>` (+ `#prep | #edit | #world | #generate | #export`)

Old URLs keep working: `&view=quick` and `&view=studio` both open the workspace (`studio` opens with the Advanced
drawer of the current step open); `&view=studio#stage-composite` opens Prep/World with that stage expanded.

```
┌ top bar ─────────────────────────────────────────────────────────────────────────────┐
│ ‹ Runs   [Name of the run ✎]  DONE  Spent $0.00        Compare ▢   ⋯ (menu)          │
│ ● Prep ─── ● Edit ─── ○ World & Look ─── ○ Generate ─── ○ Export                      │
│ Next: Approved · now choose the world and the prompt →                                 │
└───────────────────────────────────────────────────────────────────────────────────────┘
  step body (one at a time) … Advanced ▸ drawer at the bottom of the step
  sticky action bar (380 px only): [primary button of the step]
```

- Step dots: done (filled accent), current (ring), waiting (grey), failed (red). The dot of a step with an
  unsaved-edits count shows a small badge.
- The "Next:" line is the one next-step indicator (§6). Its arrow is a link to that step.
- The `⋯` menu holds: Rename, Save as preset, Details (ids, based on, recipe table, "made before the stage rack"
  note, downloads of every file = today's per-card download links), Open the folder path, All versions.
- "Compare ▢" toggles the Compare tray with this run ticked (§2.4).
- Job banner: kept, but it is the only place a failure is printed (A-05); the step bodies show the fix buttons,
  not the sentence again.

Step bodies: §4.

### 2.4 Compare — URL `/?view=lab&runs=…&stage=…` (unchanged; the word "Lab" never shows)

Reachable from: the workspace top bar ("Compare ▢"), a Runs card menu, a version row tick, and the banner that
appears after "Make a new version" / "Save as new version" ("New version · Compare with the one it came from").
The picker becomes a **tray**: the current run's family (root + versions) as a short list with ticks, plus a
search field for anything else; the 108-checkbox box goes (A-75). Tiles as today with: plain recipe differences
("Mask method: SAM 3 → free local", prompt diffs collapsed behind "prompt changed ▸"; A-77), "Pick A" / "Picked",
and a primary "Continue with this version" that opens its workspace (A-78). Speed buttons get names ("Normal",
"Slow ¼"). The "Output" select is renamed "View" and uses the G-28 names.

## 3. Runs need names and pictures

### 3.1 Thumbnails (frontend only)

Per card, first available: `/runs/<id>/preview.jpg` (written by the face stage; exists in every mesh run), else
`GET /jobs/<id>/mask/frame?i=0` (a JPEG of the first frame; exists for any run with `original.mp4`), else a
`<video preload="metadata" src="/runs/<id>/original.mp4#t=0.5">` poster, else a grey tile with the state. The file
list is already in the tree summary (`draft`, `final`, `reviewed`, `imported`); the thumbnail URL is derived from
the id, so no new data is needed.

### 3.2 Names (the one allowed additive exception, or the frontend fallback)

Checked: `run.json` has `id, parent, created, preset, changed, chain, …` and **no `name` key**; `run_summary()`
in `app.py` returns `preset` and `changed`; `runhead.js` titles the run `preset || modeLabel(mode)`. So a real
rename needs storage.

Proposed smallest additive shape (flagged as the exception):

- `run.json.name` (string, optional). `stages.load_run` already returns the whole dict, so `run_summary()` only
  adds `'name': run.get('name')` and `GET /jobs/{id}/run` carries it through unchanged.
- One endpoint: `PUT /jobs/{ident}/name` with form or JSON `{name}` → trims, caps at 80 characters, writes the key
  into `run.json` (via `stages.save_run`) and answers the new summary. Nothing else reads it, so no behaviour
  changes; a run without a name displays the derived default below. Tests: one happy path, one 404, one empty
  name clears it.

Frontend default name when `name` is empty (used today already, so nothing looks worse): `<preset or prep method>
· <date dd Mon> · <first clause of "what changed">`, e.g. "Expressive · 22 Oct", "Motion clip + face mesh · 23 Oct ·
mask: 5 clicks applied". The branch's `changed` line is already in plain words from `plain_changed()`.

Frontend-only alternative if the exception is refused: `localStorage['puppeteer.names'] = {id: name}` with the
same derived default. Trade-off: names are per browser profile, do not travel with the run folder, never appear in
export READMEs or in another machine's library, and are lost when site data is cleared. Acceptable for a single
owner on one Mac; not acceptable if runs are shared. The plan prefers the endpoint.

## 4. The five steps and where every stage card goes

### 4.1 Prep (stages 1–6)

Body: a summary card: thumbnail, prep method (G-25), input check advice list (today's checklists), the "Face
found / lost" line, "Background behind the person: original frames" line with "Change ▸" (opens the Motion clip stage in
Advanced), the Character 1 / 2 references saved with the run. While running: the progress line with the status
text and a cancel-free "This can take a minute" note. **Advanced ▸** drawer: stage cards **01 Input check, 02
Audio, 03 Depth, 04 Mask, 05 Motion clip, 06 Face mesh** as compact accordion rows (name · method · state chip · "⌄");
an expanded row is today's card (method select, settings, health, numbers, warnings, preview, "Use my own file",
downloads moved to Details) with **one** button "Make a new version from here" whose label carries the price when
paid ("… · about $0.13"; the click with a price is the confirmation, as today's second click).

### 4.2 Edit (the timeline editor)

Body: views (G-28 names) · viewer · transport · timeline (lanes MASK / FACE / WORDS, now with a small "tools"
glyph on each label and the hint "Click a lane to edit it") · the selected lane's tools · **one bar** that merges
today's Save bar and review box:

```
[ 3 unsaved edits · Undo · Redo · Discard · Save as new version · free ]   or, with none:
[ Watched the whole clip?  ● Approve this clip ]   Approved ✓ 22 Oct · Approve again if you change it
```

Rules: the approve button is disabled while there are unsaved edits ("Save or discard your edits first"), the
save button is disabled while there are none; "Needs fixing" is removed as a button (A-39): the editor is the fix.
The classic wand is deleted; "Fix the mask" is a secondary button that selects the Mask lane (A-38). **Advanced
▸**: stage cards **04 Mask, 06 Face mesh** (the same component as in Prep, filtered). The Words lane keeps
Transcribe; its exports move to the Export step (A-55).

### 4.3 World & Look

Order (fixes A-61): **Generator** (cards, with price and "cannot: …" lines) → **Characters** (1 and 2; the only
place they are picked after prep) → **Set · Look · Light** (Set and Look as mode cards with one sentence each,
picker below the chosen mode; "Put the set image behind the person" shows an inline "Apply as background · free,
new version" with the plate canvas from the Motion clip card, so the background is edited in one place, A-72) →
**Prompt** (textarea; it is rebuilt automatically from the slots while the box is untouched, with "Rebuild from
slots" once the user has edited it; "Insert spoken lines"; "Describe set & light · about $0.01"; `Final text ▸`
with the References strip). The primary is **"Create draft · about $2.15"** at the bottom and in the Next line.
**Advanced ▸**: stage cards **05 Motion clip (Background)** and **07 Prompt**.

### 4.4 Generate

Body: the price summary line ("Draft 480p · about $2.15 · then the final at 1080p · about $11.34 · fal ·
Seedance 2.5"), **"Create draft · about $2.15"** (disabled with the reason inline: "Approve the clip in Edit
first →"), the draft video with "Download draft", **"Make the final · 1080p · about $11.34"** with its one-line
note ("the same draft completed" / "a new render; it will differ"), the final video when it exists, Subtitles
(burn in · free), `Submitted prompt & request id ▸`, and `Add a render you made elsewhere ▸` (today's "Import a
generated result manually"). **Advanced ▸**: stage cards **08 Generate, 09 Finish**.

### 4.5 Export

Body: **target cards** (Seedance web · Kling · ComfyUI · After Effects / Nuke · Custom), each with "What's in it"
and its own **"Export for <target> · free"** button; `Choose the files ▸` (today's 14 tick boxes, opened by
default only for Custom); the alpha format select when relevant; the unsaved-edits note; result (README, zip link,
"Open the new version"); `Earlier exports ▸`; `Single files ▸` (every file of the run with its plain name and the
file name: today's stage-card download links, audio stems, words.json, .srt, mouth-guidance.json, masks zip).

## 5. Feature map (every existing feature → where it lives → clicks from the workspace top)

"Clicks" = from a freshly opened workspace (top bar visible), counting step switches; "(A)" = inside the Advanced
drawer, counted with the drawer click (the drawer's open state is remembered per step in `localStorage`, so a
power user pays it once). Routes come from `app.py`.

| # | Feature (route) | Now | Will live | Clicks |
|---|---|---|---|---|
| F-01 | Upload + preset + characters + prepare (`POST /jobs`, `POST /estimate`) | Quick form; Studio legacy form (×2) | Quick start (from Runs "New run" / brand) | 1 (New run) |
| F-02 | Subject to mask, depth model, clean dialogue | Quick "More options"; legacy "Preparation settings" | Quick start → Advanced ▸ | 2 |
| F-03 | Preparation progress + failure fix buttons (`GET /jobs/{id}`, poll) | banner + step 02 line | banner + Prep body | 0 |
| F-04 | "Re-run with lenient gaps · free" (`POST /branch`) | banner / review / face card | banner fix button + Prep → Advanced → Face mesh | 0 / 3 |
| F-05 | Stage cards: method select, settings, health, numbers, warnings, previews (`GET /stages`, `GET /jobs/{id}/run`) | Studio rack | Advanced drawer of the owning step (§4) | 2 (step, drawer) + 1 expand |
| F-06 | Make a new version from a stage (`POST /jobs/{id}/estimate`, `POST /branch`) | "Re-run from here" | Advanced → expanded card → one button | 3–4 |
| F-07 | Use my own file for depth / mask / face / motion clip (`POST /jobs/{id}/import`) | card `details` | Advanced → card → "Use my own file" | 4 (over the ≤3 rule; acceptable: a rare power action; alternatively a row in the `⋯` menu "Use my own file…" = 2) |
| F-08 | Per-file downloads, folder zips, masks zip (`GET /jobs/{id}/download/{name}`, `/runs/<id>/<file>`) | each card, editor foot, audio downloads | Export → `Single files ▸`; also `⋯` → Details | 2 |
| F-09 | Input check checklists | Input check card | Prep body (summary) | 0 |
| F-10 | Background behind the person (select, plate picker, drag canvas, scale) | Motion clip card (Studio) + slots "Apply as background" | World & Look → Set "Put the set image behind" (inline) and Prep → Advanced → Motion clip | 2 / 3 |
| F-11 | Views: prepared clip / original / depth / mask only / motion clip / overlay / face mesh editable | tabs + 2 view rows | Edit: one tab row (lane tools no longer repeat it) | 1 |
| F-12 | Transport, frame counter, zoom, keys | Edit | Edit (unchanged) | 0–1 |
| F-13 | Range selection, markers `[` `]` | drag on ruler | Edit; dragging on a lane also selects that lane | 1 |
| F-14 | Mask fixes: + / −, brush, pending list, preview (`POST /edits/mask/preview`) | Mask track + classic wand | Edit → Mask lane (the wand is deleted) | 2 |
| F-15 | Apply to clip (quick / full / paid SAM 3 / SAM 2) (`POST /edits/mask/apply`) | Mask track; classic wand `POST /mask/apply` | Edit → Mask lane → "Apply to clip" (one button + a "Quality: quick / full" toggle; paid method in the select) | 3 |
| F-16 | Flagged frames, Prev / Next, Find hands (`GET /mask/problems`, `POST /edits/mask/hands`) | Mask track | Edit → Mask lane | 2–3 |
| F-17 | Face mesh: hide on range, adjust (drag / fields), expressions, reset, prev/next adjustment | Face track | Edit → Face lane | 2–3 |
| F-18 | Words: transcribe local / paid (`POST /words/transcribe`), singing mode, select / edit / drag / split / merge / add / delete | Words track | Edit → Words lane | 2–3 |
| F-19 | Subtitles .srt, words.json, mouth-guidance.json (`GET /subtitles.srt`) | Words panel + step 04 + export | Export → `Single files ▸` (one place) | 2 |
| F-20 | Undo / redo / discard / save as new version (`/edits`, `/edits/undo|redo|save`) | Save bar | Edit bar | 1 |
| F-21 | Approve / un-approve (`POST /mask-review`, fingerprint 409 reload) | review box (tick + button) | Edit bar: one button "Approve this clip"; 409 → inline "Reload the latest clip" on the bar | 1 |
| F-22 | Face found / lost line, background chip | review box | Prep summary and Edit bar status line | 0 |
| F-23 | Audio stems download | review `details` | Export → Single files | 2 |
| F-24 | Characters 1 / 2 (saved references) | Quick + step 03 | Quick start (new run) and World & Look | 1 |
| F-25 | Generator picker, resolution, limits (`GET /jobs/{id}/generators`, `PUT /slots`) | bottom of step 03 | World & Look, first block | 1 |
| F-26 | Set / Look / Light slots (`GET/PUT /slots`), asset pickers + upload (`GET /assets`, `POST /jobs/{id}/assets`) | step 03 | World & Look | 1–2 |
| F-27 | Build prompt, Final text + references strip, warnings (`POST /prompt/assemble`) | step 03 prompt builder | World & Look → Prompt (auto-built; `Final text ▸`) | 1–2 |
| F-28 | Describe set & light with Claude (`POST /describe`) | step 03 | World & Look → Prompt | 2 |
| F-29 | Insert spoken lines (`GET /words/beats`) | step 03 | World & Look → Prompt | 2 |
| F-30 | Create draft (`POST /seedance`) | step 03 button | Generate primary; also the Next line after approval | 1 |
| F-31 | Draft video, download, submitted prompt & request id | step 04 | Generate | 1 |
| F-32 | Make the final (`POST /hd`, `GET /hd`) | step 04 "Approve & complete" | Generate | 1–2 |
| F-33 | Burn subtitles into the final (`GET/POST /subtitles`) | step 04 | Generate → Subtitles | 2 |
| F-34 | Add a render made elsewhere (`POST /finish`) | step 04 `details` | Generate → `Add a render you made elsewhere ▸` | 2 |
| F-35 | Export targets, items, alpha format, progress, README, zip, earlier exports (`GET/POST /export`, `/export/{name}`, `.zip`) | step 04 bottom | Export step | 1–2 |
| F-36 | Save as preset (`POST /presets`) | run head button + inline form | `⋯` → Save as preset (dialog) | 2 |
| F-37 | Add to Lab / compare picks (`GET/POST /compare/picks`, `GET /jobs/tree`) | run head, Runs rows, Lab picker | top bar "Compare ▢", Runs card menu, version rows, post-save banner | 1 |
| F-38 | Runs tree / flat list (`GET /jobs/tree`, `GET /jobs`) | Runs page | Runs cards + versions ▸ + search (flat list removed) | 1 (‹ Runs) |
| F-39 | Open in Studio / Quick view / All runs / Branched-from link | run head + rows | top bar "‹ Runs", Details "based on" link | 1 |
| F-40 | Run id, parent id, "made before the stage rack", recipe | run head facts | `⋯` → Details drawer | 2 |
| F-41 | Spent so far / spend per run | run head + rows | top bar + Runs cards | 0 |
| F-42 | Cost confirmation on 402 ("Run anyway") | toast action | inline under the button that was pressed ("Yes, spend about $x"); the toast stays for errors raised off-screen | 1 |
| F-43 | Rename a run (new, §3.2) | — | top bar name ✎, Runs card menu | 1 |
| F-44 | Keyboard: ← → Shift+← → Space Home End [ ] Esc Cmd+Z Shift+Cmd+Z Ctrl+Y, Ctrl+wheel zoom | Edit | Edit (kept) + §7 additions | 0 |
| F-45 | `GET /jobs/{id}/calls`, `GET /health`, `GET /costs`, `GET /presets` (data) | not surfaced / boot | unchanged (Details may link the calls log) | — |
| F-46 | Offline-mode refusals, "not configured · KEY" | inline lines + toasts | same wording rules (§6), key names only in `Advanced` / Details | 0 |

Nothing in the inventory is dropped except: the second upload form, the classic wand (every capability exists in
the Mask lane; the only semantic loss is "one version per apply", replaced by Apply + Save), the flat list, the
duplicate view rows, the duplicated download links and `.srt` links (one place each), and the "Needs fixing"
button (its note "Mask needs correction" was only ever a stored string; the state is now "not approved").

## 6. States and copy per step

Rules: one sentence, present tense, the fix is a button where the app can do it; a disabled primary button always
has the reason as a line right under it; a toast is used only when the cause is off-screen.

| Step | Empty (first action) | Loading | Success | Warning | Error (fix button) |
|---|---|---|---|---|---|
| Runs | "No runs yet." **[New run]** | 6 skeleton cards | cards | — | "The runs could not be listed." + fix from the server **[Try again]** |
| Quick start | the form itself; button "Prepare · free, runs locally" | "Estimating the price…" on the button (as today) | navigates to the workspace | "The price could not be estimated: <message> <fix>" under the button (as today) | upload failure toast with the server's fix; 402 → inline **[Yes, spend about $x]** |
| Prep | (never empty; a run always has a Prep) | "Preparing… <status>" + pulse; Next: "Preparing · the clip opens in Edit when it is done" | summary card; Next: "Prepared · now watch the clip and approve it →" | input check advice list (amber), "Face lost 0.42–0.71 s; the motion clip stands in there." | banner "Preparation failed: <reason>" + fix sentence; buttons **[Re-run with lenient gaps · free]** (when it applies) **[Open the failed stage]** (opens Advanced, expands it) |
| Edit | run still preparing: "The clip opens here when the preparation finishes." (no button) | views load; lanes show "Checking the mask…" / "Loading the face…" | bar: "Watched the whole clip? **[Approve this clip]**"; after: "Approved ✓ · Next: choose the world and the prompt →" | "This clip changed after you approved it. **[Approve again]**"; "3 unsaved edits · save or discard them before approving" | lane errors inline ("The mask could not be checked." + fix); save refusal inline on the bar: "1 mask click is not applied yet. **[Apply and save]** **[Save without it]**"; 409: "The clip changed since this page loaded. **[Reload the latest clip]**" |
| World & Look | Character 1 empty: "Add Character 1: a picture or a short video of the character." **[Choose Character 1]**; prompt box: auto-filled, never empty | "Building the prompt…" (replaces the box text only while untouched) | "Prompt ready · Next: create the draft →" | generator limits ("Wan takes one reference image: the set image is ignored here. Use Seedance for a set reference."), reference warnings under the box | "Describe" without a key: inline "No Anthropic key yet. Add ANTHROPIC_API_KEY to .env, then restart." (no button, as today); slot save failure: inline "Could not save the set. **[Try again]**" |
| Generate | "No draft yet." + the reason line under the disabled button when it applies: "Approve the clip in Edit first →" (a link) / "Add Character 1 in World & Look →" | "Draft in progress… <status>" + pulse; "Final in progress…" | draft video; Next: "Draft ready · judge it, then make the final or export →"; final: "Final ready · download or export →" | "The final will not be identical to the draft (a new render)." | 402 inline **[Yes, spend about $x]**; generation failure: the provider's message + fix + **[Try again · about $x]**; offline: "Offline mode: nothing is sent." (no button) |
| Export | target cards with "Export for <target> · free"; Custom: "Tick the files you need." | "Exporting… <status>" progress line | "Export ready: 7 files, 195 frames at 24 fps, 48 MB." **[Download seedance-web-….zip]** **[Open the new version]** | "2 unsaved edits will be saved first as a new version." | ffmpeg missing: "<message> <fix>" (no button); export failure: "<status> <fix>" **[Try again]** |

Generic error copy stays as in `api.js` (network: "The app could not be reached. Is it still running? Restart it
and reload." + fix). The failure sentence is printed once (banner); step bodies only show buttons.

## 7. Primary action and "Next" text per screen

| Screen / step | The one primary button | "Next:" line (top bar) |
|---|---|---|
| Runs | New run | — |
| Quick start | Prepare · free / · about $x | — |
| Prep (running) | — (no button; the step is working) | "Preparing · the clip opens in Edit when it is done" |
| Prep (done) | Watch and approve the clip → (goes to Edit) | "Prepared · now watch the clip and approve it →" |
| Prep (failed) | Re-run with lenient gaps · free (when it applies), else Open the failed stage | "Preparation failed · fix it in Advanced or start a new run" |
| Edit (unapproved, no edits) | Approve this clip | "Watch the whole clip, fix what is wrong, then approve →" |
| Edit (unsaved edits) | Save as new version · free | "3 unsaved edits · save them as a new version, then approve it" |
| Edit (approved) | Create draft · about $x (the Next line's button) | "Approved · choose the world and the prompt, or create the draft →" |
| World & Look | Create draft · about $x | "Prompt ready · create the draft →" |
| Generate (no draft) | Create draft · about $x | "Create the draft to judge the result" |
| Generate (draft) | Make the final · 1080p · about $y | "Draft ready · make the final, or export the clip for another tool →" |
| Generate (final) | Download final | "Final ready · download it or export →" |
| Export | Export for <selected target> · free | "Export ready · download the zip" |
| Compare | Pick A / B / C / D (secondary); Continue with this version (primary on the picked tile) | — |

Every other button on the step is `.secondary`; the accent fill is used exactly once per step body (A-69).

## 8. Keyboard shortcuts (set and conflicts)

| Key | Action | Conflict with today |
|---|---|---|
| Space | play / pause | keep; fix A-79: Space acts on a focused button anywhere (only `body`, the viewer and the timeline toggle playback) |
| ← / →, Shift+← / → | frame / second | keep |
| Home / End | first / last frame | keep |
| I / O | range in / out at the playhead (keyboard path for the range, A-86) | new; no conflict (unused) |
| M / F / W | select the Mask / Face / Words lane (toggle) | new; no conflict |
| [ / ] | previous / next marker | keep |
| Enter (lane selected, not typing) | the lane's default action: Mask = Apply to clip when fixes are pending; Face = hide / show the mesh on the frame or range; Words = edit the word under the playhead | new; Enter inside inputs is unchanged |
| Cmd/Ctrl+Z, Shift+Cmd/Ctrl+Z, Ctrl+Y | undo / redo | keep |
| Cmd/Ctrl+S | Save as new version (prevent the browser's save dialog) | new |
| Cmd/Ctrl+Enter | the step's primary button (Approve · Create draft · Make the final · Export); paid ones still show the price and this key counts as the click | new; never fires while a `<textarea>` is focused unless the key is Cmd+Enter (textarea Enter stays a newline) |
| 1 – 5 | go to step 1–5 (not while typing) | new; no conflict |
| Esc | clear the range → close the lane tools → close the drawer / dialog / toast | keep, extended |
| ? (Shift+/) | shortcuts overlay | new |
| Ctrl/Cmd + wheel over the timeline | zoom | keep |

Space-on-button fix and the overlay are the two mandatory items; the rest is additive.

## 9. Responsive rules (380 px up)

- The page never scrolls sideways (today: true on all 76 shots; keep the `.tl-scroll` inner scroll and the
  `min-width:0` discipline).
- Top bar: name on one line (ellipsis), the five steps as a horizontally scrollable segmented control that shows
  the current step name and "2 of 5"; the Next line below it, two lines max.
- A **sticky bottom action bar** holds the step's primary button (and the unsaved-edits count in Edit); toasts
  stack above it. Desktop: the primary stays in the body (no sticky bar).
- Timeline: lane labels 48 px, the lanes scroll inside their box, the counter moves under the transport (as
  today), zoom buttons stay 32 px wide but 44 px tall.
- Lane tools: one control per row group; the six mask mode buttons become a two-row segmented control; the six
  expression sliders stack (as today).
- Cards (Runs, targets, generator, set/look modes): one column below 640 px, two from 640, three from 1024.
- Touch targets: every link in a row or card is at least 24 px tall with 8 px padding; tick boxes 20 px with a
  44 px tall label row (A-89).
- The Advanced drawer opens full-width under the step body; its stage rows are 48 px tall.

## 10. Implementation notes for the later agents

**Frameworks.** Keep plain ES modules, templates in `index.html`, no build step. The code is ~5 000 lines in 27
small modules with a clean token/poll discipline (`state.js`), an edit layer client and a track registry that
already behave like components; a framework would buy nothing the next three agents need and would break the
"edit one file, reload" loop and the offline-port verification habit documented in `docs/UI.md` §8. The only
structural addition is a tiny `steps.js` (current step from the hash, step state from `state`) and a `drawer.js`
(Advanced drawer + Details drawer + dialog, one `<dialog>`-based helper).

**Templates (`index.html`).** Merge `tpl-quick` + `tpl-studio-new` → `tpl-start` (one form, preset cards; the
mode select is deleted). `tpl-run-head` → `tpl-topbar` (name, chip, spent, Compare, ⋯, step bar, Next line).
`tpl-review` + `tpl-editor` → `tpl-edit` (editor + the merged bar; the review box and `[data-review-tools]` go).
`tpl-draft` + `tpl-slots` → `tpl-world` (generator, characters, set/look/light, prompt). `tpl-final` → `tpl-generate`
(draft, final, subtitles, submitted prompt, add a render) and `tpl-export` stays (targets become cards, items go
under a `details`). `tpl-runs` / `tpl-run-row` → `tpl-runs` / `tpl-run-card` / `tpl-version-row`. `tpl-lab` /
`tpl-lab-tile` stay as `tpl-compare` / `tpl-compare-tile` with the tray. `tpl-stage-card` stays, plus a compact
row header (summary line + chevron). New: `tpl-drawer`, `tpl-details`, `tpl-shortcuts`.

**Modules.** `app.js`: three renderers (runs, workspace, compare; `/` with no job = start). `state.js`: add
`step` from `location.hash` and a `setStep()`; map `view=quick|studio` → workspace, `view=lab` → compare.
`quick.js` + `studio.js` → `start.js` (the form) and `workspace.js` (top bar + step bodies + drawers; owns
`mountPanels` logic). `runhead.js` → `topbar.js` (adds rename via `PUT /jobs/{id}/name` or the localStorage
fallback). `review.js` → `edit.js` (mounts the editor, the merged bar, approval; `registerReviewTool` is removed
with the wand). `wand.js`: **deleted** (and its import in `app.js`); keep `POST /mask/apply` server-side untouched.
`draft.js` → `world.js` (characters, generator, slots, prompt) and `generate.js` (draft, final, subtitles, finish).
`export.js`: target cards + `details` for items + the Single files list (moves `downloadLinks` out of
`stagecard.js` into `files.js`). `stagecard.js`: a `compact` option (row header) and a `stages` filter so each step
mounts its own subset; the per-card download row goes. `runs.js`: cards, search, sort, filter, paging, thumbnails,
versions expander, menu. `lab.js` → `compare.js` (tray instead of the 108-box picker, plain diff lines, "Continue
with this version"). `track-mask.js`: remove the "Classic wand" link and the duplicate view row; one Apply button
with a quality toggle. `track-face.js` / `track-words.js`: remove their view rows; rename copy per the glossary.
`editor.js`: Space fix, I/O, M/F/W, 1–5, Cmd+S, Cmd+Enter, `?` overlay, `aria-pressed` on lane labels,
`role=tablist` on views. `ui.js`: `notice()` gains `anchor` (render the action inline under a given element when it
is on screen; toast otherwise). `api.js`: add `name: (id, name) => send('/jobs/' + id + '/name', {name}, {method:
'PUT'})` behind a feature check (404 → localStorage fallback).

**CSS (`app.css`).** Tokens: `--muted` → #636774 (5.0:1 on white), a `--muted-soft` for decoration only; focus ring
for fields (`:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px }` on input/select/textarea,
drop `outline:none`); disabled buttons keep full colour at 0.7 opacity plus the reason line; step bar, cards,
drawer, sticky action bar, segmented controls; `prefers-reduced-motion` gates the pulse and smooth scroll; one
icon set (inline SVG sprite: upload, play, pause, step, zoom, chevron, check, warning, compare, more) instead of
text glyphs; h3 ≥ 15 px; mono only for ids, counters and file names (never for prices or chips).

**Deleted.** `wand.js`, `.wand*` CSS, the legacy form template and `mountLegacyForm`, the flat list, the
duplicate view rows in the two track panels, the review-box checkbox, the "Classic wand" link, the per-card
download rows (moved), the `aria-label="Depth"` nav.

**Docs.** `docs/UI.md` §1–§2 (files, URLs) and README "The three depths" are rewritten after the change; the
glossary's banned-word list (G §3) is grepped before closing.

**Order of work.** 1) CSS tokens + focus + copy pass with the glossary (no layout change; closes A-82, A-84, A-90
and the TERM items). 2) Workspace shell: top bar, steps, hash routing, Advanced drawer, old-URL mapping; Studio
and Quick render inside it unchanged. 3) Step bodies: merge the Edit bar, delete the wand, reorder World & Look,
split Generate / Export, target cards. 4) Runs cards, thumbnails, rename (with the endpoint or the fallback),
search. 5) Compare tray. Each step is verifiable on its own offline port with the shoot script into
`docs/tidy/after/` with the same names as `docs/tidy/before/`.

## 11. Journeys: predicted "after" counts

Same counting rule as the audit (select = 2, drag = 1, file pick = 1, scroll = 0).

| Journey | Before | After (predicted path) | After |
|---|---|---|---|
| (a) Quick: upload → draft button | 8 | New run is the landing form: Choose video (1) + pick (1) → Character 1 (1) + pick (1) → Prepare (1) → *lands in the workspace, opens Edit when prepared* → Approve this clip (1; no checkbox) → the Next line's "Create draft · about $x" (1) | **7** |
| (b) Fix a mask | 5 | Runs card (1; opens on Edit) → MASK lane (1) → click the picture (1) → "Apply and save as new version" (1; today's toast action "Apply now" becomes the bar's primary while clicks are unapplied) | **4** |
| (c) Fix the face mesh | 5 (4) | Runs card (1) → drag on the FACE lane (1; selects the lane and the range) → "Hide mesh on range" (1) → Save as new version (1). Transform: card (1) → FACE (1) → drag the mesh (1) → Save (1) | **4 (4)** |
| (d) Set + look + prompt → draft | 10 | Runs card (1; approved run opens on World & Look) → Set mode card "Use a set image" (1) → thumbnail (1) → Look mode card "Copy a look image" (1) → thumbnail (1) → Light + type (1) → prompt rebuilds itself (0) → Create draft (1) | **7** |
| (e) Export for After Effects | 5 (4) | Runs card (1) → Export step (1) → "Export for After Effects / Nuke · free" (1) | **3** |
| (f) New version + compare | 6 | Runs card (1) → Advanced ▸ on Prep (1; remembered open afterwards → 0) → expand Face mesh (1) → pad field + type (1) → "Make a new version from here" (1) → the new version opens with the banner "New version · Compare with the one it came from" (1; compare opens with both ticked and plays on that click) | **6 first time, 5 after** |

(a) is one click fewer than today and loses the two-page hop; (b)–(f) each lose one to two clicks and, more
importantly, every scroll of 1 500–10 000 px.

## 12. Owner decisions (2026-10-24, after the three directions)

**Look: hybrid of A and B.** B's layout, editorial typography, thumbnail run cards, step rail with a one-line status
under each step, spacing and friendliness; A's dark low-chroma palette with one accent so the video is always the
brightest thing on screen. Dark is the default; B's paper look is a light theme behind a persisted toggle (tokens only).
Direction C is dropped.

**Core principle: clean but powerful (progressive disclosure).** Every piece of UI has one of three levels:

| level | what | where |
|---|---|---|
| 1 · always visible | only what the current step needs: the video, the step's single primary action, the step rail, one status line | the step body |
| 2 · one click away | secondary controls: tool choice, settings, extra views (overlay / mask only), export options | collapsible panels, a "More" menu or a side drawer that remembers its open/closed state across reloads |
| 3 · on demand | technical info: run ids, frame counts, reports, logs, cost breakdowns, the nine-stage Advanced view | ONE "Details" drawer, in the same place on every step |

Visible by default per step: **Prep** clip, preset, character, Go · **Edit** video, timeline, active tool (mask / face /
words), Save · **World & Look** set, look, prompt preview · **Generate** generator, cost, Draft / Final · **Export** preset
picker, Export. Everything else is level 2 or 3; every existing feature stays reachable in ≤ 3 clicks from the workspace.
The feature map (§5) gets a "level" column.

**Navigation.** The step rail is clickable, the current step is clearly highlighted, the browser back button moves
between steps (each step is a history entry), and the way back to Runs is always visible.

**Decisions.** Run names are stored as `name` in `run.json` with one `PUT /jobs/{id}/name` endpoint (the approved
backend exception; shown on cards and in exports). The glossary term for the depth composite is **Motion clip** (not
Cutout); the rest of the glossary is approved. The Quick journey must be upload → draft in **4 clicks max**: upload,
preset + character, approve, draft.

**Order.** One hybrid mockup first (`docs/tidy/directions/hybrid.html`: Runs, Edit and Generate; desktop and 380 px;
dark and light), owner OK, then Step 4.
