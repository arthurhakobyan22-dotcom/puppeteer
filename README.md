# Puppeteer

Puppeteer turns a driving video into a motion-control clip and renders a character over it with Seedance 2.5. Preparation runs Depth Anything plus a SAM 3 cutout of the subject over the original background (or a MediaPipe face mesh, or both), you review the prepared clip frame by frame, then the clip and your character reference images go to Seedance 2.5 through fal or Enhancor. The source audio is passed through untouched: it drives lip-sync during preparation and is remuxed over the final video. Use it only with footage you own or have licensed.

## Setup

1. `python3.14 -m venv .venv && bash setup.sh` (Python 3.12+; installs deps, copies `.env.example` to `.env`, runs `doctor.py`).
2. Fill `.env` with `FAL_KEY` and/or `ENHANCOR_API_KEY`, plus `REPLICATE_API_TOKEN` for depth, SAM 3 and Demucs.
3. Optional face-mesh modes: `bash setup-face-mesh.sh` (needs Python 3.12; isolated `.venv-face`).
4. `bash start.command` (starts the app and, when cloudflared is installed, the Enhancor callback tunnel).
5. Open http://127.0.0.1:8770.
6. `.venv/bin/python doctor.py --require-keys` reports which keys, tools and providers are ready; it never makes a paid call.

## Providers

| Provider | Draft | Finalize | Max resolution | Hosting | Needs webhook/tunnel |
|---|---|---|---|---|---|
| fal (`FAL_KEY`) | 480p draft via `bytedance/seedance-2.5/reference-to-video` | Completes the same draft at 1080p via `draft/complete` (`draft_id`, valid 7 days); identical to the draft | 1080p | fal storage (`fal_client.upload_file`); never a public host | No |
| Enhancor (`ENHANCOR_API_KEY`) | 1080p draft (`is_draft: true`) | Completes the draft via `draft_id` on `POST /queue` | 1080p | tmpfiles links (public, expiring) | Yes: cloudflared tunnel from `start.command`, or `ENHANCOR_WEBHOOK_URL` |

Pick a provider in the draft panel, with `workflow.py submit --provider`, or with `SEEDANCE_PROVIDER` in `.env`. Details: `docs/PROVIDERS.md`.

## Modes

- **Advanced · Depth + SAM** (`depth`): colored depth from Depth Anything, SAM 3 raw masks, subject cutout over the original background. Calls Replicate.
- **Fast · Face mesh** (`face_mesh`): MediaPipe face mesh drawn on the original frames. No depth or SAM calls. The crop follows the face (padded, smoothed), re-detecting on the full frame when tracking is lost, so the speaker need not be centred. Gaps of up to 6 frames are interpolated and drawn dimmer; the run fails only for a longer gap or more than 15% missing frames, and the error lists the lost ranges in seconds. Full 90° profiles are outside MediaPipe's range. `face-tracking.json` and the review screen show tracked / filled / missing counts.
- **Advanced + Face mesh** (`depth_mesh`): the depth pipeline with the face mesh overlaid on the depth composite.

## Review gate

Every submission requires a full-clip review in the UI (or `workflow.py review`). Approval is bound to a sha256 fingerprint of the prepared artifacts (mask, composite, prepared clip, landmarks); any change to them, including a repair or a re-prepared clip, clears the approval and blocks submission until you review again.

## Audio

The prepared clip carries the original audio by default, remuxed packet-for-packet from the upload. `clean_dialogue` (UI checkbox, `--clean-dialogue` on the CLI) runs Demucs and embeds only the isolated vocals so the lip-sync input has no music bed. The final export always restores the full original track; generated audio is discarded.

## Hosting & privacy

- Enhancor needs public media URLs: the default host is tmpfiles (temporary, expiring links).
- Catbox is **off by default**. It is public and persistent; opt in only by setting `MEDIA_HOST=catbox` or `MEDIA_HOST_FALLBACKS=catbox`. See `docs/MEDIA-HOSTING.md`.
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
