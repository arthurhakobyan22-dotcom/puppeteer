# Puppeteer

Puppeteer turns a video of you (or any performer you have the rights to) into a motion-control clip, then renders a
character over it with Seedance 2.5. You upload the video, the app prepares it (a depth map and a cutout of the
subject, or a face mesh, or both), you review the prepared clip, you add a character reference and create a draft,
and when you like the draft you approve it for the full-resolution version. The original sound stays exactly as it
was: it drives the lip-sync and is put back over the finished video. Use it only with footage you own or have licensed.

## The three depths

The app has one page with a switch at the top: **Quick**, **Studio**, **Lab**, plus a **Runs** page.

- **Quick**: upload, pick a preset, add the character reference, click Go. One click takes you to the review step;
  the page shows progress while the clip is prepared and opens the review as soon as it is done. Use it when you
  just want a result.
- **Studio**: the same run as a rack of cards, one per stage (input check, audio, depth, mask, composite, face mesh,
  prompt, generate, finish). Each card shows the tool in use, its settings, a preview of what it produced, a plain
  health line ("Face tracked on 163 of 195 frames; lost 0.42–0.71 s, the depth composite stands in there") and the
  numbers behind it. Change a tool or a setting and click **Re-run from here**. Studio also hosts the review, draft
  and finalize steps, the old "Preparation method" form, and **Save as preset**. Use it when something is not right
  and you want to change one step.
- **Lab**: compare two to four runs side by side. Pick which output to look at (prepared input, original, depth,
  mask, composite, draft, final), play them in sync at 1× or 0.25×, see how each run's settings differ from the
  first tile and its numbers, and pick the one you prefer. Picks are saved (for the scoring phase later) and survive
  a reload. Use it to decide between variants.
- **Runs**: every run, as a tree. A run you branched sits under the run it came from with a one-line "what changed",
  its state, date and total spent. Open any run in Studio or add it to the Lab. A "flat list" toggle shows the old
  newest-first list.

Links keep working: `/?job=<id>` opens a run (add `&view=studio` or `&view=lab`), `/?view=runs` is the Runs page.

## The four presets

| preset | what it does | when to use it | preparation cost |
|---|---|---|---|
| **Talking head** | Fast: draws the face mesh on your original video. No depth, no cutout. | A single speaker facing the camera; you want it quick. The face must stay visible: a gap longer than 6 frames stops the run (you then get a one-click "re-run with lenient gaps"). | free, runs on your machine |
| **Full body** | Advanced: a depth map plus a cutout of the subject over the original background. | Whole-body motion, hands, props; anything where the pose matters more than the face. You review the whole mask. | paid (depth + SAM, usually well under $0.50) |
| **Expressive** | Advanced + face mesh: the depth cutout with the facial motion drawn on top. Tracking gaps only warn; the depth composite stands in where the face is lost. | Dialogue with a lot of expression, where you want both the body and the face guided. | paid (same as Full body) |
| **Profile-heavy** | Advanced with the face mesh off. | The speaker turns away from the camera a lot (a mesh would lose the face anyway). | paid (same as Full body) |

Any run's chain can be saved as your own preset (Studio → Save as preset); it then appears in Quick next to the
built-ins with the description you gave it.

## How branching works

A run is never changed after it has run. When you change a stage in Studio and click **Re-run from here**, the app
makes a new **child run**: everything before that stage is linked in from the parent (not copied, not re-done), that
stage and everything after it run again, and the parent stays exactly as it was. The child shows "Branched from …"
and a one-line "what changed" ("face: mediapipe_mesh pad: 1.8 → 2.0"), and the Runs page shows it under its parent.
Paid steps that already ran with the same input, tool and settings are reused, never billed again. You can branch a
branch; the tree keeps growing and nothing is lost.

## The cost meter

Every button that spends money shows the estimate in its label before anything runs: "Prepare · about $0.12",
"Create draft · about $2.15", "Approve & complete at 1080p · about $11.34", "Run now · about $0.13 · click to
confirm". Free actions say "free, runs locally". Nothing paid starts without that click, and the app never retries a
paid request on its own (it only retries reading status after a network hiccup). Every run shows "Spent so far:
$x.xx"; the Runs page shows the spend per run. Estimates come from public list prices (`docs/COSTS-RESEARCH.md`);
the real amount is on the provider's bill. Set `PUPPETEER_OFFLINE=1` to block every paid call for safe experiments.

## The input doctor

Every run starts with the input doctor. It makes the 24 fps working copy as before and then checks it: resolution,
frame rate, length, brightness, face size, camera shake and whether there is audio. What is safe to fix, it fixes
on the working copy only (your upload is never altered): the frame rate is normalised, a dark clip is brightened a
little (with a before/after note such as "mean luma 0.04 → 0.17"), and a small face gets a zoomed copy that the face
tracker uses, with the result mapped back onto the full frame. Everything else becomes advice ("Face is small: move
closer or crop before uploading", "Stabilise the clip before uploading"). It never blocks a run. The Studio card
"Input check" lists the checks, the fixes applied and the advice.

## The mask wand

When a depth run misses a hand or includes some background, you fix it on the review screen without re-running SAM
on the whole clip: click **Fix the mask**, step to the frame, click **+** on the region that is missing or
**Alt-click** (or switch to **−**) on the spill. The app shows at once what the click selects, and **Apply to the
whole clip** follows that region forward and backward through the video and makes a new branch run with the
corrected mask; the depth stays as it was, nothing is paid again, the original run is untouched, and the new run
opens with its review pending so you check the result before approving. The default tool, local propagation, is
free and runs on your machine (edges are a little rougher than SAM's); SAM 3 on fal and SAM 2 on Replicate are the
hosted alternatives, labelled paid with the estimate on the button. For the last one percent there is a brush:
paint or erase on a range of frames.

## The review gate

Before every draft you review the whole prepared clip in the app (or with `workflow.py review`): the mask for
missing areas and spill, the face mesh for tracking and alignment, the embedded audio. Approval is tied to a
fingerprint of the prepared files; any change to them (a re-run, a mask repair, a new branch) clears it, and the
draft button stays off until you review again. While the clip is still being prepared the review panel says so;
if preparation failed it tells you why and offers the fix.

## Setup

1. `python3.14 -m venv .venv && bash setup.sh` (installs the dependencies, copies `.env.example` to `.env`, runs `doctor.py`).
2. Put your keys in `.env`: `FAL_KEY` and/or `ENHANCOR_API_KEY` for Seedance, `REPLICATE_API_TOKEN` for depth, SAM 3 and Demucs.
3. For the face-mesh presets: `bash setup-face-mesh.sh` once (needs Python 3.12; makes an isolated `.venv-face`).
   For the Words track (free word-level transcription on Apple Silicon): `bash setup-words.sh` once (Python 3.12; makes
   `.venv-words` with mlx-whisper and downloads the 1.6 GB Whisper large-v3-turbo model into `models/whisper/`; see `docs/WORDS.md`).
4. `bash start.command` (starts the app and, when cloudflared is installed, the Enhancor callback tunnel).
5. Open http://127.0.0.1:8770.
6. `.venv/bin/python doctor.py --require-keys` tells you which keys, tools and providers are ready; it never makes a paid call.

## Providers

| Provider | Draft | Finalize | Max resolution | Hosting | Needs webhook/tunnel |
|---|---|---|---|---|---|
| fal (`FAL_KEY`) | 480p draft via `bytedance/seedance-2.5/reference-to-video` | Completes the same draft at 1080p via `draft/complete` (`draft_id`, valid 7 days); identical to the draft | 1080p | fal storage (`fal_client.upload_file`); never a public host | No |
| Enhancor (`ENHANCOR_API_KEY`) | 1080p draft (`is_draft: true`) | Completes the draft via `draft_id` on `POST /queue` | 1080p | tmpfiles links (public, expiring) | Yes: cloudflared tunnel from `start.command`, or `ENHANCOR_WEBHOOK_URL` |

Pick a provider in the draft panel, with `workflow.py submit --provider`, or with `SEEDANCE_PROVIDER` in `.env`.
Details: `docs/PROVIDERS.md`.

## Preparation methods (what the presets run)

- **Advanced · Depth + SAM** (`depth`): colored depth from Depth Anything, SAM 3 masks, subject cutout over the
  original background; calls Replicate. The subject is one short noun phrase; comma-separated terms run as separate
  SAM jobs (each billed) and are combined. If SAM finds nothing on the depth video it retries on the RGB frames, then
  `SAM_FALLBACK_MODEL`; failures report the real reason and `sam-attempts.json` keeps every prediction.
- **Fast · Face mesh** (`face_mesh`): MediaPipe face mesh drawn on the original frames; no depth or SAM calls. The
  crop follows the face, so the speaker need not be centred. Gaps of up to 6 frames are interpolated (drawn dimmer);
  a longer gap or more than 15% missing frames stops the run and the message lists the lost ranges in seconds.
- **Advanced + Face mesh** (`depth_mesh`): the depth pipeline with the face mesh over the depth composite. Gaps do
  not stop this method: the mesh is drawn where the face is tracked, the depth composite stands alone where it is
  lost, and the review screen shows the lost ranges as a yellow warning.

Under the hood every method is a chain of stages with swappable tools, recorded in `run.json` with a plain report per
stage; see `docs/STAGES.md` for the tools, cache keys, branching and the endpoints, and `docs/UI.md` for the page.

## Audio

The prepared clip carries the original audio, copied packet for packet. "Clean dialogue" (checkbox, or
`--clean-dialogue` on the CLI) runs Demucs and embeds only the isolated vocals so the lip-sync input has no music
bed. The final export always restores the full original track; generated audio is discarded.

## Hosting & privacy

- Enhancor needs public media URLs: the default host is tmpfiles (temporary, expiring links).
- Catbox is **off by default** (public and persistent); opt in with `MEDIA_HOST=catbox` or `MEDIA_HOST_FALLBACKS=catbox`. See `docs/MEDIA-HOSTING.md`.
- fal never uses public hosts; files go to fal storage.
- Keys live only in `.env` (gitignored). They are never logged, written to `runs/`, placed in URLs or shown in the UI.

## CLI

```bash
.venv/bin/python workflow.py prepare SOURCE.mp4 --mode depth|face_mesh|depth_mesh [--subject person] [--clean-dialogue]
.venv/bin/python workflow.py status JOB
.venv/bin/python workflow.py review JOB --approve --fingerprint HASH --note "who reviewed, findings"
.venv/bin/python workflow.py repair-rgb JOB
.venv/bin/python workflow.py submit JOB --reference char1.png [--second-reference char2.png] [--prompt-file prompt.txt] [--provider fal|enhancor]
.venv/bin/python workflow.py resume JOB [--hd]
.venv/bin/python workflow.py hd JOB
```

## Tests

```bash
.venv/bin/python -m pytest -q
.venv/bin/python test_composite.py
```

All remote calls are mocked; no key or paid call is needed.

## License

MIT (see `LICENSE`). Puppeteer is a fork of Sirio Berati's [Genjutsu Open Source Workflow](https://github.com/sirioberati/Genjustsu-Open-Source-Workflow); see `THIRD-PARTY.md` for attribution and hosted-model terms.

## Words, subtitles and Import my own

On the review timeline the **Words** track transcribes the clip's audio word by word (free, on your Mac, after
`bash setup-words.sh`), and you fix the words and their timing by hand. The draft step can insert timed **dialogue
beats** into the prompt, the finish step exports **subtitles (.srt)** and can **burn them into a copy of the final**
(off by default). Every Studio card has **Download** links for its outputs, and the depth, mask, face and composite cards
have **Import my own…**: bring back a file you edited elsewhere (a painted mask, your own depth video, a face overlay,
a finished control video); it is fitted to the clip and becomes a new version labelled "imported". Details:
`docs/WORDS.md`, `docs/IMPORTS.md`.
