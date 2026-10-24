# UX audit of the current Puppeteer UI (tidy pass, Agent 1, 2026-10-24)

Measured on the read-only verification instance (`PORT=8791 PUPPETEER_OFFLINE=1`, branch `tidy-pass`) with
Playwright at 1440 px and 380 px. Screenshots: `docs/tidy/before/<name>-desktop.png` and `<name>-380.png`, 45 screens × 2 widths
(`docs/tidy/before/shots.json` holds console errors and horizontal-scroll results per shot; the state screens that need a
select change or a mocked write come from `docs/tidy/measure/states.py`; `docs/tidy/measure/shoot.py` is `shoot.py` with a
load wait that does not need network idle, because the editor's video preloads keep the network busy). Fixture runs used:
`0be4cf2c…` (Advanced + Face mesh, review pending, words.json), `3c54f295…` (approved, draft ready, Character 1
saved, stems), `ccd73397…` (failed Talking head), `36536b28…` (imported mask), `f5a3f11d…` (Fast, reviewed),
`e3396214…` and its face-pad child `a73448dc…`. No run folder was changed: every write the journeys would make
(`POST /jobs`, `PUT /edits`, `POST /edits/save`, `POST /mask-review`, `POST /branch`, `POST /seedance`,
`POST /hd`, `PUT /slots`, `POST /export`) was answered by a Playwright route mock.

Companion files: `docs/UX-PLAN.md` (the proposed flow) and `docs/GLOSSARY.md` (the plain names).

Issue codes: **A-nn**. Flags used in the tables: **DUP** duplicate (of what), **DEAD** dead end (no obvious next
action), **NAME** confusing name, **BURIED** (how deep), **TERM** inconsistent term (variants), **NEXT** next
action not obvious.

## 1. Inventory

### 1.1 Shell (every page) — `static/index.html`, `app.js`, `ui.js`, `jobdata.js`

| Control / message | What it does | Issues |
|---|---|---|
| Brand link "Puppeteer / MOTION CONTROL" | goes to `/` (Quick) | **A-01 NEXT**: the brand goes to the upload form, not to the library; from inside a run it drops the run. |
| Nav "Quick · Studio · Lab · Runs" (`aria-label="Depth"`) | four views; Quick/Studio keep `?job=`, Lab keeps `&runs=` | **A-02 NAME**: "Quick" and "Studio" are two renderings of the same run, not two places; "Depth" as the aria name means nothing to a user. **A-03 TERM**: the same run is reached by "Quick view", "Open in Studio", "Studio view", "All runs", nav links (5 wordings). |
| `#notices` toast stack (bottom right, max 4; `role=alert` for errors) | every page notice: upload failures, saved presets, 402, save refusals | **A-04**: toasts carry the only "fix" button for 402 / 409 / save refusals, far from the control that raised them (e.g. the Save bar is mid-page, the toast is bottom right; `toast-save-blocked-by-pending-mask-fix-desktop.png`). |
| `#job-banner` (page flow, under the header) | status of the job in the URL + fix buttons | **A-05 DUP**: on a failed run the same sentence appears 4 times: banner, step 02 progress line, the review status line and the tracking line (`run-failed-quick-desktop.png`). |
| Network error copy "The app could not be reached. Is it still running? Restart it and reload." + fix "Start the app again from its folder (bash start.command)…" | api.js | fine; tone matches. |
| Footer "Puppeteer · Original audio in your final export." | static | **A-06**: a product promise in the footer of every page; it belongs in the Export / Generate step copy, not as a footer. |
| `document.title` "Puppeteer · Quick · 0be4cf2c" | | **A-07 NAME**: tab title shows the view name and an id, never the run's name. |

### 1.2 Quick (no run) — `tpl-quick`, `quick.js` (`quick-empty-*.png`, `quick-more-options-*.png`)

| Control / message | Issues |
|---|---|
| Hero "Your performance. Your character." + two sentences | **A-08**: 190 px of marketing above the first field on every visit; the sentence "You review the prepared clip next, then create the draft" is the only hint of the steps to come. |
| Panel "01 Start with your video" | numbered 01, but steps 02–04 are on a different page, so the user never sees 01 and 02 together. **A-09 NEXT**. |
| Upload "Choose original video · MP4 or MOV · up to 30 seconds" | fine. |
| Preset radios (Talking head / Full body / Expressive / Profile-heavy, each with a description and a price line "about $0.12 for a 10 s clip") | Good pattern. **A-10**: the price line is monospaced amber on white (4.9:1, passes) but says "for a 10 s clip" until a file is chosen; the preset descriptions use the terms "Depth Anything", "SAM 3", "face mesh", "Advanced", "Fast" (**TERM**, see G-25). Radio targets are 7×13 px (A-60). |
| "Character 1 · for the draft · Image, or an identity video" / "Character 2 · optional · Image" | **A-11 TERM**: the same two uploads reappear in step 03 as "Character 1 · required" with other sub-labels; "identity video" is jargon (G-26). |
| `details` "More options": "Subject to replace" (text), "Depth provider" (select), "Clean dialogue (… Demucs …; paid)" | **A-12 BURIED (1)**: "Clean dialogue" is a paid choice hidden in a disclosure with a hint that mentions "SAM jobs (each billed)". **A-13 NAME**: "Subject to replace" is the SAM prompt; "Depth provider" is a vendor choice no beginner can make. |
| Cost hint + button "Prepare · free, runs locally" / "Prepare · about $0.12" | the best pattern in the app; keep. |
| Empty text "No presets could be loaded. Reload the page; if it happens again, check that the app is running." | fine. |
| 402 toast "Prepare anyway · about $x" | **A-14 TERM**: the 402 action is worded five ways across the app ("Prepare anyway", "Run anyway", "Import anyway", "Transcribe anyway", "Accept · full quality · $x"). |

### 1.3 Studio (no run) — `tpl-studio-new`, `studio.js` (`studio-new-*.png`, `studio-legacy-form-settings-*.png`)

| Control / message | Issues |
|---|---|
| Hero "Open a run to see its stage rack." + link "Runs page" | **A-15 DEAD**: the Studio tab without a run is a dead end that points elsewhere. |
| Form "Prepare a new video": upload, "Preparation method" select ("Advanced · Depth + SAM" / "Fast · Face mesh (no depth or SAM)" / "Advanced + Face mesh · Depth + SAM + facial motion"), hint, `details` "Preparation settings · depth modes only" (Subject, Depth provider, "Depth colors are preserved. Preparation runs at 24 fps, up to 960 px. Media is uploaded to the selected providers."), "Clean dialogue", button "Prepare video · about $0.12" | **A-16 DUP** of the Quick form with a mode select instead of presets (the presets map 1:1 onto the modes; "Profile-heavy" = depth). Two upload forms to maintain, two button labels ("Prepare →" vs "Prepare video →"), two cost hints. **A-17 TERM**: "Preparation method" / "mode" / "preset" / "stage rack" all describe the recipe. The same form is mounted a third time at the bottom of every Studio run page as "Prepare another video (preparation method)" (`run-studio-prepare-another-*.png`). |

### 1.4 Runs page — `tpl-runs`, `tpl-run-row`, `runs.js` (`runs-tree-*.png`, `runs-flat-*.png`)

| Control / message | Issues |
|---|---|
| Heading "Runs · 108", toggle "flat list", hint "Every job under runs/. Branches sit under the run they were made from…", "Open Lab (n)" button (hidden until 2 runs are in the Lab) | **A-18 TERM**: "job" / "run" / "branch" in one sentence. **A-19**: no search, no filter, no sort; 108 rows make an 11 771 px page (`runs-tree-desktop.png`). |
| Row: title link = preset name or mode label + suffix ("· draft ready" / "· final ready" / "· reviewed"), state chip, "imported · mask" chip, date, detail line ("What changed: …" or status + short id), "Spent $0.00", links "Open in Studio", "Quick view", button "Add to Lab" / "In Lab ✓" | **A-20 NAME**: runs have no names; 60 of 108 rows are titled "Advanced + Face mesh" (`run.json` has `preset` and `changed`, no `name` key, see UX-PLAN §3). **A-21 NEXT**: the title link opens Quick, the row offers Studio too; nothing says which to pick. **A-22**: no thumbnail; the only visual difference between rows is the chip colour. **A-23**: every row has three 17–19 px tall links (A-60). |
| Flat list: `a.flat` with mode + suffix, date, status, full id | **A-24 DUP** of the tree with less information; the id is shown in full. |
| Empty: "No runs yet. Prepare a video in Quick first." | fine. |

### 1.5 Run header — `tpl-run-head`, `runhead.js` (top of every run page)

| Control / message | Issues |
|---|---|
| Title = preset or mode label; chip (done/error/running); "Spent so far: $0.00"; facts: date · mode (+ "· made before the stage rack") · "Branched from 0be4cf2c…" · "What changed: …" · the 32-hex id in mono | **A-20** again (no name); **A-25**: the full id is body text on every run page; "made before the stage rack" is developer language. |
| Buttons: "Open in Studio" / "Quick view" (whichever is not current), "Export…" (Studio only; scrolls to `#export`), "Add to Lab" / "In Lab ✓ · open", "Save as preset", "All runs" | **A-26 DUP**: four navigation buttons duplicate the top nav. **A-27 BURIED (Studio only)**: "Export…" exists only in Studio although the export kit is on both pages. **A-28 NAME**: "In Lab ✓ · open" is a button whose label changes meaning (adds vs opens). |
| "Save as preset" form: Preset name, Description, Save preset, Cancel; ok toast "Preset "x" saved. It is now in the Quick preset list." | fine, but the form appears inline above the step panels (`run-head-save-preset-*.png`). |

### 1.6 Step 02 "Review the prepared input" — `tpl-review`, `review.js` (`run-quick-review-*.png`, `run-fast-reviewed-quick-*.png`, `run-failed-quick-*.png`)

| Control / message | Issues |
|---|---|
| Heading "02 Review the prepared input" + hint "Review the full mask or face-mesh tracking, and listen to the embedded audio before generating." | **A-29 TERM**: "prepared input" / "prepared clip" / "Prepared input" tab / "seedance-input.mp4" / "control video" (G-08). |
| Progress / failure status line ("Preparing… <status>", "Preparation failed: …" + fix + fix buttons "Re-run with lenient gaps · free", "Open the failed stage in Studio") | duplicates the banner (A-05). |
| Empty "Your original video and prepared previews will appear here." | fine. |
| View tabs: Prepared input · Original · Mesh edit · Depth · Mask · Composite · Tint (from files + tracks) | **A-30 NAME**: "Mesh edit" and "Tint" are tool names used as views; "Composite" means the cutout. Clicking the Face lane silently switches the tab to "Mesh edit" and back (A-37). |
| Viewer: video with native controls + overlay canvas; transport "−1 s · ◀ frame · ▶ Play · frame ▶ · +1 s · frame 0 / 195 · 0.00 s · zoom − + fit"; caption; "Download prepared input ↓" (+ "Masks as PNGs (.zip) ↓" on mask views) | **A-31 DUP**: two play controls (native video controls and the transport's Play), two scrub bars (native and the timeline). **A-32 NAME**: "fit" and "zoom" are 11 px labels; the counter text wraps on 380 px. |
| Timeline: ruler, lanes MASK / FACE / WORDS (labels are buttons), playhead, range band; hint paragraph with the key list | **A-33 NEXT**: nothing on the lanes says they are clickable; the only hint is a 12 px paragraph under the timeline. **A-34**: the lanes, the ruler drag and the word blocks are pointer-only (no keyboard path, see §4). |
| Save bar: "No pending edits" / "N pending edits" + summary; Undo · Redo · Discard (→ "Discard 2 pending edits? Yes, discard · Keep") · "Save edits · free, creates one new version"; warn "This run changed after you started editing…" | **A-35**: the Save bar sits above the review box, so "Save edits" (free, makes a new version) and "Approve input" (approve this version) are 300 px apart with no explanation of which comes first. **A-36 TERM**: "pending edits" / "unsaved" / "session" / "new version" / "branch" (G-20). |
| Background chip "BACKGROUND · ORIGINAL FRAMES" (link to Studio `#stage-composite`) | **A-37 NEXT**: a chip that is secretly a link to another page. |
| Mask wand: button "Fix the mask" + hint; open: frame label, −1 s / ◀ frame / frame ▶ / +1 s, Tool select (Local propagation (free, rougher edges) / SAM 3 on fal (point prompts) · paid / SAM 2 on Replicate · paid / Brush (free)), + include / − exclude / "Alt-click = exclude", Paint / Erase / radius / "on N frames from here", info line, "N pending clicks on M frames", Undo last click, Clear all, "Apply to the whole clip · free" | **A-38 DUP**: the whole wand duplicates the Mask track (own frame stepper, own tool select, own include/exclude, own brush, own undo, own apply). Two ways to fix a mask with different results (one version per apply vs. pending edits). The mask panel even links to it: "Classic wand (one version per apply)". |
| Review box: "Required · Review the complete input", hint, status line (pending / approved / rejected / unavailable / failed), tracking line ("Face lost 0.42–0.71 s and 2.08–2.58 s; the depth composite stands in there. Tracked 163 of 195 frames, 13 filled…"), checkbox "I reviewed the entire prepared clip; its mask or face mesh is correctly aligned throughout.", "Approve input" (disabled until ticked), "Input needs fixing" | **A-39 NAME**: "Input needs fixing" records a rejection note ("Mask needs correction. Seedance submission is blocked.") but does not open any fixing tool (**DEAD**). **A-40**: the checkbox + button is a two-click approval; the checkbox is 16 px. **A-41 TERM**: "input" / "prepared input" / "clip". |
| `details` "Audio downloads": Isolated vocals ↓ / Music stem ↓ / Original audio ↓ or "The prepared clip carries the original audio; no separate stems were made." | **A-42 BURIED (1) DUP**: the same files are export items. |

### 1.7 Mask track panel — `track-mask.js` (`run-editor-mask-track-*.png`, `run-editor-mask-brush-*.png`, `run-editor-mask-tint-*.png`, `run-editor-mask-pending-fix-*.png`)

| Control / message | Issues |
|---|---|
| Help line; mode row "+ include" / "− exclude" / "Brush" (+ Paint / Erase / radius slider / "on N frames from here") / "Alt-click = exclude" | **A-43**: 3 modes + 2 brush modes + a slider + a number in one row; at 380 px it wraps to 4 lines. |
| "No pending fixes" / "N pending fixes (n clicks on m frames)" · Undo last · Clear all; list of fixes (frame · + include · ✕) | **A-44 DUP**: a second undo ("Undo last") next to the Save bar's Undo. |
| "Tool" select (Local propagation · free / SAM 3 on fal · paid / SAM 2 on Replicate · paid); "Apply to clip · quick preview · free"; "Apply at full quality · free" / "Apply with SAM 3 · about $x" | **A-45 NAME**: "quick preview" vs "full quality" vs "Accept · full quality" (three apply buttons for one idea). |
| Accept row: "Quick result shown (7 frames changed)." · "Accept · full quality · free" · Undo | see A-45. |
| Problems row: "2 problem ticks (18 flagged frames)" · ◀ Prev tick · Next tick ▶ · "Grab hands on flagged frames · free" · "Grab hands on a range" | **A-46 NAME**: "problem ticks", "flagged frames", "Grab hands" (G-12). |
| View row: B/W · Composite · Tint · link "Classic wand (one version per apply)" | **A-47 DUP**: a third view switcher (tabs above the video, this row, and the face panel's own view row). |
| Info line "Preview on frame 52 in 0.31 s (this frame only; nothing is propagated until Apply)…" | **A-48**: developer measurements (latency) in a user line. |
| Save refusal "1 mask click is not applied yet. Apply it to the clip first, or remove it." + actions "Apply now" / "Save without it" | good copy, wrong place (toast, A-04). |

### 1.8 Face track panel — `track-face.js` (`run-mesh-edit-view-*.png`, `run-editor-face-mesh-off-pending-*.png`, `run-editor-savebar-discard-*.png`)

| Control / message | Issues |
|---|---|
| Help "Drag inside the mesh to move it, the corner square to scale, the top circle to rotate…"; "Applies to frame N / frames a–b" + "drag across the ruler to pick a range" | the only place that explains the handles; nothing on the picture itself says they exist (no cursor change until hover). **A-49 NEXT**. |
| "Mesh off on this frame" / "Mesh off on range" · "Mesh on" · "off: 28–53" | **A-50 NAME**: "Mesh off" (G-14: Hide mesh). |
| dx · dy · scale · rot ° number fields · "Set key here" | **A-51 NAME**: dx/dy/rot/"key" are animation jargon. |
| Six sliders (Jaw open, Mouth smile, Mouth pucker, Blink left (their left), Blink right (their right), Brow up) with outputs | fine; label "(their left)" is a good touch. |
| ◀ Prev key · Next key ▶ · Reset frame · Reset range | **A-44** again: Reset is a third undo-like action. |
| View row "Mesh edit" / "Prepared input"; status "No correction on this frame. This session: 1 off range."; legend tracked · filled · missing · off · ◆ key · ● expression · ▨ mesh off | **A-52 TERM**: "session" (G-20); legend colours amber #e0b341 on white 1.96:1 (A-62). |

### 1.9 Words track panel — `track-words.js` (`run-editor-words-track-*.png`, `run-editor-words-selected-*.png`, `run-editor-words-paid-engine-offline-*.png`)

| Control / message | Issues |
|---|---|
| Help; source line "10 words · from words.json (mlx-whisper:whisper-large-v3-turbo, en)"; engine select ("Whisper large-v3-turbo on this Mac (mlx) · free, runs locally" / fal "· paid · about $0.03") · "Singing mode" · "Transcribe · free, runs locally" | **A-53**: model ids in the user line. Offline warning for the paid engine names the env var `PUPPETEER_OFFLINE=1`. |
| "Selected" / "At the playhead" + text field + "2.24–2.90 s (frames 53–69)"; Split at playhead · Merge with next · Add word at playhead / in range · Delete · ◀ Prev · Next ▶ | **A-54**: six actions in one row; "Split at playhead" is disabled-looking when no word is under the playhead but the refusal only comes as a toast after the click. |
| Export row: "Export subtitles (.srt) ↓" · "words.json ↓" · "mouth-guidance.json ↓" | **A-55 DUP**: the same .srt link appears in step 04 subtitles and as an export item. |
| Lane: word blocks (click, double-click to edit, drag edges), empty text "No transcript yet · select Words and click Transcribe" | pointer-only (A-34). |

### 1.10 Step 03 "Create your draft" — `tpl-draft`, `draft.js`, `tpl-slots`, `slots.js`, `promptkit.js`, `generator.js` (`run-draft-step-*.png`, `run-world-slots-described-style-*.png`, `run-prompt-builder-final-*.png`)

| Control / message | Issues |
|---|---|
| Meta chips "Provider · fal · Seedance 2.5" · "Seedance · Edit" · "Draft · 480p" · "Final · 1080p" | **A-56 TERM/DUP**: "Provider" here, "Generator" 600 px below, `select[name=provider]` hidden in between; "Seedance · Edit" / "Omni reference" are API mode names. |
| Character 1 · required / Character 2 · optional (upload labels; "Saved reference · click to replace") | A-11 duplicate of step 01. |
| "Set, look and light" box: hint "…Saved with this run (slots.json); the prompt builder reads it…"; Set select (5 modes with a sentence each), set picker (thumbnails + "Upload image…"), Set description; Look select (3 modes), style picker, Look description; Light input; "Apply as background (new run) · free" (+ note); task line "Task · editing (original set)"; saved line | **A-57 NAME**: file names (`slots.json`) and terms "plate", "slots", "task", "true swap", "set_ref", "style_ref" (G-15/16). **A-58**: five set modes whose consequences differ (two of them need a new run) are a flat select. |
| Prompt builder: "Build prompt from slots" + hint; `details` "Final prompt · what the adapter sends, with the references beside it" (refs strip with @ImageN tokens, "Text sent" pre, provider line); warnings list ("@Image1 is mentioned but only 0 image references are attached."); "Describe set & light from this frame · about $0.01" + hint ("…needs ANTHROPIC_API_KEY in .env"); result line | **A-59 BURIED (1)**: the exact text that is sent is behind a disclosure; the warning about a missing reference shows even before the user had a chance to add one (`run-quick-review-desktop.png`, step 03). **A-60**: "adapter", "fence", "@Image1" in user copy. |
| Generator: radio cards (Enhancor "not configured · ENHANCOR_API_KEY" / fal · Seedance 2.5 "about $2.15 draft" / Wan 2.2 Animate · replace (fal) "about $0.49 · one render"), summary line, limits list, Resolution select (Wan), draft line "Draft 480p → 1080p on approval (the same draft completed)." | good data; **A-61 BURIED**: it sits at the bottom of a 1 300 px panel, after the slots it constrains (the generator decides whether Set / Look images are allowed, but is chosen after them). |
| "Generation prompt" textarea (7 rows, prefilled with the default); "Insert dialogue beats" + hint; actions hint "Review this prompt first. Full quality is a separate approval below." · "Create draft · about $2.15" (disabled until approved) | **A-62 NEXT**: when the button is disabled nothing near it says why ("Review and approve the prepared input first" appears only as a toast after a forced submit). |

### 1.11 Step 04 "Approve & export" — `tpl-final`, `draft.js mountFinal`, `tpl-export`, `export.js` (`run-draft-step-*.png`, `run-final-details-open-*.png`, `run-export-kit-after-effects-*.png`, `run-export-kit-custom-*.png`)

| Control / message | Issues |
|---|---|
| Heading "04 Approve & export"; hint "Every finished preview uses the entire original source audio…"; empty "Your draft will appear here when generation finishes." | **A-63 NAME**: "Approve" is used for two different things (approve the prepared clip in 02; approve the draft in 04). |
| Draft video + badge "DRAFT · ORIGINAL AUDIO" + "Download draft ↓"; "Happy with this draft?" + hint + "Approve & complete at 1080p → · about $11.34" (label comes from the provider) + warning "Result will not be identical to the draft."; status line | **A-64 TERM**: "complete", "HD", "full resolution", "1080p", "finalize", "upgrade" for one action (G-11). |
| Subtitles box: checkbox "Burn subtitles into final · free, runs locally; off by default" + line; "Burn again · free"; subtitled video; "Export subtitles (.srt) ↓" · "Download draft with subtitles ↓" | **A-55** (third .srt link). |
| `details` "View submitted prompt & generation ID" (provider · request id, prompt pre, "Download raw Seedance result") | fine as a drawer. |
| `details` "Import a generated result manually" (upload "Choose Seedance result" + "Restore original audio") | **A-65 BURIED (1) NAME**: this is how a user brings in a render made on the Seedance website after an export; it is named after what the server does, not what the user wants ("Add a render you made elsewhere"). |
| Export kit: heading "Export kit · free, runs locally" + hint; "Target" select (Seedance web / Kling / ComfyUI / After Effects / Custom); "What's in it: …" line; 14 tick boxes with a sentence each (unavailable ones greyed with the reason); alpha format select; pending-edits line; hint + "Export · free, local"; progress; result (README `<pre>` open, "Download x.zip ↓", "Open the new version →"); `details` "Earlier exports" | **A-66**: 14 tick boxes with full sentences is the densest block in the app (`run-export-kit-custom-desktop.png`); a beginner needs only the target. **A-67 BURIED (2 from Quick: scroll past 02 and 03)**: export sits at the bottom of a 4 500–5 400 px page and is reachable by a button only in Studio (A-27). |

### 1.12 Studio run page — `studio.js`, `tpl-stage-card`, `stagecard.js` (`run-studio-stage-cards-*.png` 10 097 px tall, `run-studio-with-draft-*.png` 10 941 px, `run-studio-import-own-*.png`, `run-studio-composite-set-image-*.png`, `run-studio-card-changed-setting-*.png`, `run-imported-studio-*.png`)

| Control / message | Issues |
|---|---|
| Panel "⋮ Stage rack" + hint ("One card per stage… click "Re-run from here": that makes a new branch run…") | **A-68 NAME**: "stage rack", "branch run". |
| Nine cards (01 Input check … 09 Finish), each: number, label, state chip (done / cached / off / error / not run / waiting / running), "on" toggle, "Tool" select (with "· paid", "· experimental", "· from "Save edits" only", "· use "Import my own…"" suffixes), params from the schema, health line, numbers chips (covered / filled / missing / lost / seconds / cost / "reused from …"), "Download" links per output file, warnings, error line, checklists (Checks / Fixes applied / Advice), `details` "Import my own…" (depth, mask, face, composite), preview (video / image / audio / prompt text / "No output to preview for this stage."), cost line, fix buttons, "Re-run from here" → "Re-run from here with these settings" → "Run now · free" / "Run now · about $x · click to confirm" | **A-69**: everything is open at once: 9 cards × (select + params + preview + downloads) = a 10 000 px page where the review, draft and export panels are repeated below the rack (**DUP** of the Quick page, mounted a second time). **A-70 NAME**: the button label changes three times before anything runs. **A-71**: raw tool ids in the "What changed" line ("mask: sam3_replicate (prompt: person) → local_propagate") and in the Lab diff. |
| Composite card: Background select (Original frames / Full depth / Plain colour / Set image), plain colour, set-plate picker, drag canvas, scale slider, "Centre & cover", fit line | **A-72 DUP**: a second place to choose the set image (the other is step 03 Set "True swap" + "Apply as background"), with different words ("plate" vs "set image", "Set image" vs "True swap"). |
| Prompt card: textarea param `text` + preview `<pre>` | **A-73 DUP**: a third prompt box (step 03 textarea, the Final prompt preview, this card). |
| Generate / Finish cards: tool select (fal / enhancor / wan_fal; restore_original_audio / complete_draft), "Re-run from here" | **A-74**: re-running "generate" from a card bypasses the approval gate copy ("Create draft" is the designed path); the card shows "This tool is paid; the estimate shows on the button before anything runs." |
| Bottom: `details` "Prepare another video (preparation method)" with the legacy form | A-16/A-17. |

### 1.13 Lab — `tpl-lab`, `tpl-lab-tile`, `lab.js` (`lab-empty-*.png`, `lab-two-runs-*.png`, `lab-four-runs-draft-*.png`)

| Control / message | Issues |
|---|---|
| Heading "A/B Lab · compare runs side by side"; picker (every run as a checkbox, 200 px tall scroll box with "└" tree glyphs, id prefixes, "what changed", date, state); "Output to compare" select (Prepared input / Original / Depth / Mask / Composite / Draft / Final); "Note for your pick (optional)" | **A-75**: picking from 108 checkboxes in a 200 px box is the hardest selection in the app; the Runs page already has "Add to Lab" (two pickers). **A-76 NAME**: "Lab" says nothing; "A/B" badge; "Output" = view. |
| Controls: Play · 1× · 0.25× · scrub · "0.00 / 8.13 s" (sticky) | 1×/0.25× are glyph-only accessible names (A-61). |
| Tiles: letter, name (+ "· what changed"), chip, full id, video, "This run has no draft output.", diff list ("Reference chain (A). The other tiles list how they differ from it." / "Same chain as A." / "mask: prompt person, hands → person" / full prompt diffs), numbers chips, "Pick this one" / "Picked" / "Your pick · note", "Open in Studio" | **A-77**: the diff prints raw param keys and whole prompts (`lab-two-runs-desktop.png`, tile B). **A-78 NEXT**: after a pick there is no "continue with this one" action; "Open in Studio" is a 12 px link. |
| Empty: "Choose at least two runs above." / "Choose one more run to compare."; warn "None of the chosen runs has this output; pick another output above."; "The Lab compares up to four runs at a time." | fine. |

### 1.14 Keyboard shortcuts (editor; `editor.js onKey`, capture phase, ignored while typing)

| Key | Action | Issues |
|---|---|---|
| ← / → | one frame | fine |
| Shift+← / → | one second | fine |
| Space | play / pause (except on a focused button outside the editor) | **A-79**: Space on a focused button *inside* the editor (e.g. "Mesh off") toggles playback instead of pressing the button (`key === ' ' && … !node.contains(t)` only exempts outside buttons). |
| Home / End | first / last frame | fine |
| [ / ] | previous / next marker of the selected track (or all) | **A-80**: undiscoverable; only listed in the hint paragraph. |
| Esc | clear the range (also closes a focused toast) | fine |
| Cmd/Ctrl+Z, Shift+Cmd/Ctrl+Z, Ctrl+Y | undo / redo | fine |
| Ctrl/Cmd + wheel over the timeline | zoom | only in button tooltips |
| Enter / Esc in a word block or the word field | commit / cancel | fine |
| (none) | no key for Apply, Save, Approve, select a track, switch view, open help | **A-81**: no "?" overlay; no save shortcut. |

### 1.15 Messages that need rewording (copy inventory)

Collected from `static/*.js` and `index.html` (69 distinct user-facing sentences longer than twelve characters plus ~140 short labels). Those with a problem:

| Where | Current text | Problem |
|---|---|---|
| review box | "Mask needs correction. Seedance submission is blocked." (note saved on reject) | names the vendor; "submission" |
| review status | "Review the entire prepared input: mask coverage for depth mode; facial tracking and overlay alignment for fast mode." | three modes' instructions in one line |
| Save bar title | "Saves every pending edit as one new branch run; this run stays as it is and its approval does not carry over" | "branch run", "pending", 25 words in a tooltip |
| mask panel | "Each fix previews on its frame at once; nothing is propagated, paid or saved until you apply." | "propagated" |
| face panel | "No face on frame 12 (missing), so there are no handles here. You can still place a key here with the fields or "Set key here"; it blends into the tracked frames around it." | "handles", "key", "blends" |
| words engine warn | "Offline mode (PUPPETEER_OFFLINE=1) blocks the paid engine; nothing would be sent. Use the free local engine, or start the app without PUPPETEER_OFFLINE." | env var in UI |
| slots | "Saved with this run (slots.json). Nothing re-runs." | file name |
| slots note | "This run has no depth person (composite tool: original), so there is no background to change. Prepare the clip with a depth preset (Full body, Expressive) to use this set mode." | tool id |
| prompt builder | "Final prompt · what the adapter sends, with the references beside it" / "The last lines are the rules the adapter appends." | "adapter" |
| describe hint | "…Paid, about a cent; needs ANTHROPIC_API_KEY in .env." | env var |
| generator | "not configured · ENHANCOR_API_KEY" / "Add FAL_KEY=… to the .env file in the project folder and restart the app." | acceptable in a details line, not on a radio card |
| step 04 | "Happy with this draft?" + "Approve & complete at 1080p → · about $11.34" + "Result will not be identical to the draft." | three tones in one block |
| export | "Pending timeline edits are saved first as one new version, so every export includes them." | "pending" |
| stage card | "Re-run from here with these settings" → "Run now · about $0.13 · click to confirm" | label mutation |
| stage card | "This tool runs from "Save edits" in the editor (review step 02): make the change on the timeline and save it. A plain re-run has nothing to feed it." | "feed" |
| run head | "Advanced + Face mesh · made before the stage rack" | developer history |
| jobdata | "No status was saved for this run (it was interrupted before preparation finished)." + "Open it in Studio and re-run the stage that did not finish." | ok but "stage" |
| import | "Imported "x" into a new version (this one). It is fitted to the clip; any change is listed as a warning on the Mask card." | ok |
| lab tile | "Reference chain (A). The other tiles list how they differ from it." | "chain" |
| studio hint | "One card per stage, in the order they run. Change a tool or a setting and click "Re-run from here": that makes a new branch run from this one…" | "branch run" |
| runs hint | "Every job under runs/. Branches sit under the run they were made from, newest roots first." | "job", "branches", "roots", a folder name |

## 2. Journeys (measured)

Counting rule: one click, tap, keypress batch or file pick = 1; a `<select>` change = 2 (open + choose); a drag = 1;
scrolling = 0 (noted). "Load" = a page render (`render()`), including in-app navigations. The "after" column is the
prediction from `docs/UX-PLAN.md` §8 and is filled there.

| Journey | Exact click path today (measured with `docs/tidy/measure/journeys.py` against the real pages; writes mocked; log in `docs/tidy/measure/journeys-before.log`) | Before | Loads | After (plan) |
|---|---|---|---|---|
| (a) Quick: upload → press the paid draft button | `/` → Choose original video (1) + pick (1) → preset: first is pre-selected (0; +1 for another) → Character 1 (1) + pick (1) → "Prepare · free, runs locally" (1) → *run page loads, preparation runs* → scroll to 02, tick "I reviewed the entire prepared clip…" (1) → "Approve input" (1) → scroll to 03, Character 1 is already saved (0) → "Create draft · about $2.15" (1) | **8** (9 with a non-default preset) | 2 | 7 |
| (b) Fix a mask | `/?view=runs` → "Quick view" on the run (1) → scroll to the editor, click the MASK lane label (1) → click the picture (+ include) (1) → "Apply to clip · quick preview · free" (1) → "Save edits · free, creates one new version" (1) | **5** (6 via Runs → Studio, 7 with "Accept · full quality") | 3 | 4 |
| (c) Fix the face mesh (mesh off on a range) | Runs → "Quick view" (1) → FACE lane label (1; the view switches to Mesh edit) → drag across the ruler to select the range (1) → "Mesh off on range" (1) → "Save edits" (1). Transform variant: open (1) → FACE (1) → drag inside the mesh box (1) → "Save edits" (1) = 4 | **5** (4 for a transform) | 3 | 4 (4) |
| (d) Set + look + prompt → draft | Runs → "Quick view" (1) → scroll to 03; Set select open + "Set reference" (2) → pick a set plate thumbnail (1) → Look select open + "Style image" (2) → pick a style image (1) → click Light + type (1) → "Build prompt from slots" (1) → "Create draft · about $2.15" (1) | **10** (+2 if Character 1 is not saved; +2 per image that must be uploaded) | 2 | 7 |
| (e) Export for another tool (After Effects) | Runs → "Open in Studio" (1) → run head "Export…" (1, scrolls 10 000 px) → Target select open + "After Effects / Nuke" (2) → "Export · free, local" (1). From Quick: Runs → "Quick view" (1) → scroll past 02 and 03 (0) → Target (2) → Export (1) = 4 | **5** (4 from Quick, with a long scroll) | 2 | 3 |
| (f) Branch a stage and compare | Runs → "Open in Studio" (1) → Face card: click "pad", type 2.0, Tab (1) → "Re-run from here with these settings" (1; free → the child opens) → child run head "Add to Lab" (1; opens Lab with one run) → Lab picker: tick the parent (1) → "Play" (1) | **6** | 4 | 5 (6 the first time) |

Notes from the drive: (a) the "Create draft" button only enables after the two-click approval; (b) after "Apply
to clip" an extra "Accept · full quality · free" row appears, which most users will read as required (+1); (d) the
"Final prompt" preview warned "@Image1 is mentioned but only 0 image references are attached" on a run that has
Character 1 saved until the strip refreshed; (e) the export kit is the last block of the page in both views; (f) the
child opens in Studio at the top, so "Add to Lab" needs no scroll, but the Lab then shows one tile and an empty state
"Choose one more run to compare." instead of pre-selecting the parent.

## 3. Design critique

Screenshots referenced are in `docs/tidy/before/`.

**Hierarchy.** The page is a vertical stack of equal white panels (`.panel`) with the same radius, shadow, and a
number badge; nothing says "you are here". On a run page the eye lands on the green job banner and then the run
header's four grey buttons, while the actual next action (approve, then create the draft) is 1 500 px down
(`run-quick-review-desktop.png`). In Studio the nine stage cards push the review, draft and export panels below
7 000 px (`run-studio-stage-cards-desktop.png`, 10 097 px tall). The primary button colour is used for "Play",
"Fix the mask", "Build prompt from slots", "Apply to clip", "Save edits", "Approve input", "Create draft",
"Export", "Import · free" at the same time on one page, so there are nine primary buttons visible in one scroll.

**Consistency.** Three different ways to switch what the viewer shows (tabs, the mask panel's view row, the face
panel's view row; `run-editor-mask-track-desktop.png`). Two complete mask tools. Three prompt boxes. Two upload
forms. Two set-image pickers. Four names for the same run-opening action. Buttons mutate their label as state
changes ("Re-run from here" → "Re-run from here with these settings" → "Run now · free"), which reads as a
different control each time (`run-studio-card-changed-setting-desktop.png`).

**Density.** The quick run page is 4 457 px tall before any panel is opened (5 450 px with the Final prompt open);
the 380 px version is 7 053 px (`run-editor-mask-track-380.png`). Hints are everywhere: every panel, every row and
most buttons carry a 12 px grey sentence, so the real instructions ("tick, then approve") have the same weight as
"Saved with this run (slots.json). Nothing re-runs." The export kit alone is 14 labelled tick boxes with a sentence
each. The Runs page renders 108 rows × 5 lines with no paging (`runs-tree-desktop.png`, 11 771 px).

**Typography.** Four families (Schibsted Grotesk for the hero, Space Grotesk for h2/h3, Hanken Grotesk for body,
IBM Plex Mono for ids, chips, costs, counters, the eyebrow and the lane labels). Mono is used for emphasis
("Spent so far", the preset prices, "BACKGROUND · ORIGINAL FRAMES" chip) and for ids alike, so money and ids look
the same. Body is 15 px but most of the UI is 11–13 px (`.hint` 12 px, `.chip` 11 px, `.mono` 11 px, `.tl-label`
11 px, `.asset` 10 px, ruler 10 px). Headings h3 are 14 px, smaller than body text.

**Colour.** One accent (#1f18c0) for links, primary buttons, active tabs, the playhead band, pending-edit markers
and the "info" lines, so an info line looks like a clickable element (`run-draft-step-desktop.png`, "Task ·
editing (original set)" and "Draft 480p → 1080p on approval" are tinted boxes with no action). Semantic colours
(green ok, amber warn, red error) are right but the amber text on white fails AA in two places (§4). The video area
is near-black (#09090c) with white controls; the page is near-white; the switch is abrupt at every viewer.

**Spacing.** Panel padding 24 px, card padding 16 px, rows gap 8–12 px: consistent. But vertical rhythm inside a
panel is not: the step 03 panel stacks meta chips, two uploads, the slots box (own border), the prompt builder (a
rule), the generator (a rule), the textarea, the beats row and the actions with margins of 20/12/8/18 px, producing
visible "sub-panels inside panels" (`run-draft-step-desktop.png`).

**Iconography.** Glyph-only or glyph-first labels: "↑" upload icon, "◀ frame", "frame ▶", "❚❚ Pause", "−" / "+"
zoom, "×" close, "└" tree, "✕" remove, "◆ ● ▨" legend, "⋮" and "≡" and "A/B" as panel numbers. No icon set; the
glyphs render in the text font and differ in weight between fonts. There is no icon on any step, state or run, so
the only pictures on the page are the videos.

**Motion.** A pulse on the running dot (not disabled under `prefers-reduced-motion`; only the toast slide-in is),
smooth scroll on "Export…", no transitions elsewhere. Polling re-renders panels every 2.5 s while a run prepares,
which can move the page under the pointer (the Studio cards redraw their preview element only when the file
changes, but the numbers and chips are replaced on every poll).

**Copy tone.** Mostly good: short, plain, with a fix sentence after every error (the strongest part of the app).
It drifts in three ways: developer vocabulary leaks (job, branch, stage rack, slot, plate, fence, adapter,
session, propagate, env var names, model ids), the same thing is named differently in neighbouring panels (§1.15,
`docs/GLOSSARY.md`), and some lines explain the implementation rather than the outcome ("Preview on frame 52 in
0.31 s (this frame only; nothing is propagated until Apply)").

## 4. Accessibility review

Measured with `docs/tidy/measure/a11y.py` (computed colours from `app.css`; tabbing through every page; element boxes at
380 px). Full numbers in `docs/tidy/measure/a11y-before.json`; summary here.

### 4.1 Contrast (WCAG AA: 4.5:1 for text under 24 px / 18.66 px bold; 3:1 for UI components)

Failing pairs:

| Pair | Colours | Ratio | Where |
|---|---|---|---|
| `--muted` #7a7e8a on white | 4.05:1 | every `.hint`, `p`, `.mono` id, tabs, summary-less hints, `.asset` labels (10 px), `.upload small` |
| `--muted` on page bg #fafafb | 3.89:1 | nav links (inactive), `.tl-label` lane names (11 px), footer, eyebrow, legend, `.ft-slider output`, `.wand-inline` |
| `--muted` on #f4f4f7 | 3.69:1 | `.numbers` chips on stage cards and Lab tiles |
| disabled primary button (white on #1f18c0 at 45 % opacity) | 2.65:1 | every disabled "Create draft", "Approve input", "Export", "Save edits" (`run-quick-review-desktop.png`) |
| ruler frame numbers #9a9eab on #f6f6f9 | 2.48:1 | timeline ruler when zoomed |
| lane empty text #9a9eab on white | 2.67:1 | "No transcript yet · select Words and click Transcribe", "Checking the mask…" |
| finalize warning #d9a24a on white (inline style) | 2.28:1 | step 04 "Result will not be identical to the draft." |
| placeholder text (Chrome default #757575) on #fafafb | 4.42:1 | every input placeholder |
| input border #dfe2e8 vs #fafafb (UI component) | 1.24:1 | every text field, select and textarea border |
| card / panel border #ececef vs white | 1.18:1 | every panel and card edge (decorative, but it is the only boundary of a card) |
| face lane "filled" #e0b341 on white | 1.96:1 | the amber lane segments and legend swatch |

Passing (for the record): body text 12.8:1, chips 4.6–9.5:1, status lines 4.6–9.5:1, primary button 10.8:1, links
10.8:1, `.cost.paid` 4.9:1, ruler second labels 5.8:1, word blocks 15.6:1, selected word 10.8:1, playhead 4.3:1.

**A-82**: the muted grey is the body colour of most of the UI and fails everywhere; raise `--muted` to about
#636774 (5.0:1 on white) or use `--text` for hints and keep grey for decoration only. **A-83**: disabled buttons
must keep ≥3:1 or show a visible reason instead of fading (the reason is more useful anyway, A-62).

### 4.2 Focus visibility (keyboard, Chrome, `:focus-visible`)

- Buttons, links and `summary` get a 2 px accent outline (`button:focus-visible…`): visible. Upload labels get an
  outline via `.upload:focus-within`: visible.
- **A-84**: `input`, `select` and `textarea` have `outline: none` and only a border colour change (#dfe2e8 →
  #1f18c0) on focus. Measured on every page: 6 fields on the run page, 12 selects on the Studio page, 2 in Lab,
  5 in step 03 take focus with no outline. The 1 px border change is below 3:1 against its unfocused state for
  light fields and invisible on the dark viewer edge.
- Checkboxes, radios and range sliders use the browser ring (visible). The Quick preset cards have no
  `:focus-within` style, so the ring is on the 13 px radio only.
- Tab order: Quick 11 stops, run page 43, Studio 140+ (every download link, every select), Lab 126 (every picker
  checkbox): keyboard users on the Runs page tab through 450 controls (3 per row). **A-85**.

### 4.3 Keyboard reachability

- **A-86 pointer-only**: the timeline lanes and ruler (click = playhead, drag = range), the overlay canvas (mask
  clicks, brush, mesh handles), the word blocks (select, edit, drag edges) and the background drag canvas have no
  keyboard path. There is a key for the playhead (← →) but none to set a range (Shift+arrows is taken by
  "one second"), to add a mask point at the playhead, to select a track, or to pick a word (`.wb` are `div`s).
- Tool buttons use `aria-label` from `ariaFor()` so "◀ frame" reads "frame" and "−" reads "Zoom out": good.
- The toasts are `role=alert` / `role=status` and the close button is labelled; Esc closes a focused toast only.
- Space on a focused button inside the editor toggles playback (A-79).

### 4.4 Labels and ARIA

- Measured: 0 unnamed controls on every page (every input has `aria-label` or a wrapping label; buttons have
  text). One glyph-only accessible name: the Lab speed buttons "1×" / "0.25×" (**A-87**).
- Lane labels are `button`s with `aria-label="Mask track"` but `aria-pressed` is missing, so a screen reader cannot
  tell which track is selected; the view tabs are plain buttons with `.active`, no `role=tab` / `aria-selected`
  (**A-88**). The Quick preset list has no `fieldset`/`legend` ("Preset" is an `h3`).
- Status lines use `role=status` and the counters `aria-live=off`: fine. Canvas overlays have `aria-label` but no
  text alternative for what they show (the mesh, the markers).

### 4.5 Touch targets at 380 px (WCAG 2.5.8 minimum 24 × 24; 44 px recommended)

| Page | Controls | < 24 px | < 44 px | Typical offenders |
|---|---|---|---|---|
| Quick | 14 | 6 | 13 | preset radios 7×13, "More options" 20 px tall, checkbox 16 |
| Runs | 450 | 255 | 448 | every row's "Talking head", "Open in Studio", "Quick view" links 17–19 px tall |
| Run page (mask track open) | 83 | 19 | 76 | "Download prepared input ↓" 18 px, "Classic wand" 18 px, every tick box 16, `summary` rows 20 px |
| Studio run page | 140 | 50 | 132 | every per-file download link 18–19 px, "on" toggles 16, "Import my own…" 20 px |
| Lab | 126 | 114 | 125 | 108 picker checkboxes at 16 px |
| Run page with a draft | 75 | 25 | 67 | stems links, "Download draft ↓", "Burn subtitles" box, "Download raw Seedance result" 16 px |

**A-89**: links in rows and tick boxes are the systematic offenders; small buttons (`.small`, 32 px tall) pass
24 px but not 44 px.

### 4.6 Horizontal scroll at 380 px

None: all 48 shots report `scrollWidth == clientWidth` (`shots.json`). The timeline scrolls inside `.tl-scroll`
(251 px content in a 250 px box at fit). The 380 px pages are long instead: 7 053 px for the run page with the mask
track open, and the transport counter wraps to its own line (`run-editor-mask-track-380.png`).

### 4.7 Motion and reduced motion

`prefers-reduced-motion` only disables the toast entrance; the running-dot pulse (`@keyframes pulse`, infinite)
and `scrollIntoView({behavior: 'smooth'})` are not gated (**A-90**). Video autoplay never happens without a
click: good.

### 4.8 Console errors

None on any shot (`shots.json`), including the mocked 402 / 409 states.

## 5. Top 15 problems, ranked by user pain

1. **No single flow.** Quick, Studio and Lab are three renderings of one run with the steps duplicated (review,
   draft, export mounted twice) and no "where am I / what is next" indicator (A-02, A-09, A-69). Measured: the next
   action after a run finishes is 1 500 px below the fold in Quick and 7 000 px in Studio.
2. **Runs have no names and no pictures.** 60 of 108 rows are titled "Advanced + Face mesh"; ids are body text
   everywhere; no thumbnail, search, sort or paging (A-20, A-22, A-19, A-25).
3. **Two mask tools** (the Mask track and the classic wand) with different semantics and their own steppers, tool
   selects, undo and apply (A-38, A-44, A-45).
4. **The vocabulary is developer vocabulary**: job, branch, stage rack, slot, plate, fence, adapter, session,
   propagate, HD, finalize, provider, env-var names and model ids in user sentences (A-18, A-36, A-57, A-60, A-64,
   §1.15).
5. **The export kit is buried** at the bottom of the longest page, reachable by a button only in Studio, and opens
   with 14 sentence-long tick boxes (A-27, A-66, A-67).
6. **The approval is unexplained and double**: tick + button, "Approve input" vs "Save edits" 300 px apart, and
   "Input needs fixing" leads nowhere (A-35, A-39, A-40, A-63).
7. **Disabled buttons never say why** (2.65:1 contrast, no reason text): "Create draft" after preparation, "Apply"
   before a click, "Export" with nothing ticked (A-62, A-83).
8. **Muted grey text fails AA across the UI** (4.05:1 / 3.89:1 / 3.69:1) and most of the UI is set in it at
   11–12 px (A-82).
9. **Fields have no visible focus ring** (border colour change only); the timeline, overlay and word blocks have
   no keyboard path at all (A-84, A-86).
10. **Set / Look / Background are configured in two places with two vocabularies** (step 03 slots with "True swap /
    Apply as background" vs the composite card's "Set image / plate" canvas) (A-72, A-58).
11. **Generator is chosen after the things it constrains** (bottom of step 03, while Set / Look options above are
    disabled by it) and the provider appears three times (meta chip, hidden select, generator cards) (A-56, A-61).
12. **Studio shows all nine stages fully open** with previews, params and per-file downloads, then repeats the
    whole Quick page under them: a 10 000 px page (A-69, A-73, A-74).
13. **The same failure is printed four times** on a failed run while the fix button is small and grey (A-05).
14. **Toasts carry the only fix actions** (402 "Run anyway", 409 "Reload", save refusals "Apply now") far from the
    control that raised them, and the action label is worded five ways (A-04, A-14).
15. **Touch targets**: 255 of 450 controls on the Runs page and 114 of 126 in the Lab are under 24 px; every row
    link and tick box (A-89, A-23).

## 6. What was not verified

- Live preparation progress (polling UI while a run prepares) and the HD polling: no free run completes on the
  fixture clip offline except Talking head, which fails on purpose; the screens were judged from code and the
  failed run. Transcription with the local Whisper, "Grab hands", "Apply at full quality" and "Describe set & light"
  were not executed (they write into `runs/` or need a key); their copy was read from the source.
- Screen-reader output was not listened to; names and roles were computed from the DOM.
- Colour measurements are from the CSS tokens, not from screenshots (anti-aliasing can lower effective contrast
  further for 10–11 px text).
