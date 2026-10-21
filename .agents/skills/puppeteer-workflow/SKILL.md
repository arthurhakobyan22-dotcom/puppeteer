---
name: puppeteer-workflow
description: Run Puppeteer's motion-control workflow — prepare a driving video (depth + SAM 3, face mesh, or both), pass the mandatory review gate, create a Seedance 2.5 draft through fal or Enhancor with char1/char2 references, and finalize an approved draft with the original audio restored.
---

Read the project root `AGENTS.md` and `docs/AGENT-OPERATIONS.md` before running a job. Resolve the project root as the folder containing `workflow.py`, not a machine-specific path. Read `docs/PROVIDERS.md` before choosing a provider and `docs/MEDIA-HOSTING.md` before touching upload settings. Never hardcode previous users' media, subjects or request IDs. Never run a paid call during setup.

## Modes

Choose one preparation mode per job (`--mode` on `workflow.py prepare`, or the "Preparation method" select in the UI):

- `depth` (Advanced · Depth + SAM): Depth Anything colored depth, SAM 3 raw masks, subject cutout composited over the original background. Calls Replicate.
- `face_mesh` (Fast · Face mesh): MediaPipe Face Landmarker overlay on the original frames. No depth or SAM calls. Needs `bash setup-face-mesh.sh` (Python 3.12, isolated `.venv-face`). One centered speaker.
- `depth_mesh` (Advanced + Face mesh): the depth pipeline, then the mesh drawn over the depth composite. Landmarks saved in `face-landmarks.json`.

## Audio

The prepared clip `seedance-input.mp4` carries the entire original audio, remuxed packet-for-packet from `upload.mp4`. Pass `--clean-dialogue` (UI checkbox "Clean dialogue") only when the user wants Demucs-isolated vocals in the lip-sync input; that is the only time `separate()` runs. `audio-manifest.json` is always written and records the choice. The final export (`finish_preview`) always restores the full original soundtrack, so generated audio is discarded.

## Mandatory review gate

Every generation requires a full-clip visual review bound to a sha256 fingerprint of the current artifacts (`mask_review`). Depth modes: inspect the whole mask across cuts, hair, hands, clothing, background spill, holes and flicker; fix failures with `workflow.py repair-rgb` (new SAM inference; clears approval). Mesh modes: inspect face tracking, eyes, mouth and alignment on every frame; there is no SAM mask to review. Any artifact change, including a re-prepared clip or its audio, clears approval. If you cannot inspect the video yourself, ask the user to review it in the UI. Never approve a known-bad input, and never claim a full-clip review you did not perform.

## Character references

`char1` is required: an image or an identity video (`char1-reference.<ext>`). `char2` is an optional image (`char2-reference.<ext>`). Prompt tokens: `@Video1` is the prepared clip, `@Image1`/`@Image2` are the characters, `@Video2` is the identity video when char1 is a video. References define identity only (face, hair, outfit, proportions); pose, motion, timing and lip-sync come from `@Video1`. An image reference routes to the provider's edit path; a video identity reference routes to reference/multi-reference mode (`@Video1` motion, `@Video2` appearance). Show the actual mode in the UI and in `generation.json`.

## Providers

Submit through one adapter in `providers/` (`--provider`, the UI dropdown, or `SEEDANCE_PROVIDER`):

- `fal`: `bytedance/seedance-2.5/reference-to-video`, 480p draft, files go to fal storage, no webhook or tunnel. Finalize is `draft/complete` at 1080p on the same `draft_id` (valid 7 days). Raises instead of re-running when `draft_id` is missing.
- `enhancor`: Seedance 2.5 edit/multi_reference, 1080p draft (`is_draft`), media hosted through `media_host.upload` (tmpfiles; catbox only on explicit opt-in), needs `ENHANCOR_WEBHOOK_URL` or the cloudflared tunnel from `launch.py`. Finalize is `POST /queue` with `draft_id`.

Check `GET /providers` or `doctor.py` for which providers are configured; keys live only in `.env` and are never printed, logged, written to a run folder or placed in a URL.

## Draft → approved finalize

1. Show the exact creative prompt before submission (the adapter appends the `@Video1`/`@Image2` instructions; inspect `seedance-request.json` too). Existing explicit authorization to submit is sufficient; do not ask again unnecessarily.
2. Submit the draft. Save `seedance-response.json`; resume collection with `workflow.py resume JOB` instead of ever submitting the same job twice.
3. Collect the result, restore the full original audio, show `/runs/JOB/final-preview.mp4`.
4. Finalize (`workflow.py hd JOB`, or the UI "Approve" button) only on explicit approval of that draft. Never auto-submit a paid job, never auto-finalize. The HD export restores the original audio again under `hd/`.

Report provider failures with the local job and request IDs only. Stop on ambiguous outcomes (a queue POST that timed out before an ID was saved) and ask the user to check the provider dashboard rather than retrying blindly.
