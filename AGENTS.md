# Puppeteer — agent contract

For installation requests, follow `docs/SETUP-AGENT.md` first. Do not run paid inference during setup. Distinguish a running UI from a generation-ready configuration (`doctor.py --require-keys`).

Carry authorized jobs through preparation, review, generation and delivery without stopping after each processing stage. Ask only for missing creative choices or for a submission approval not already given. Never finalize automatically: the user approves that step.

1. Preserve the source file (`upload.mp4`) and its complete original audio.
2. Embed the entire original audio in the prepared clip (packet-for-packet remux). Only when `clean_dialogue` is enabled, isolate vocals with Demucs and embed them instead. Do not attach separate audio to Seedance.
3. Depth mode: generate depth with Depth Anything and retain its exact colors. Obtain raw SAM 3 masks with one short noun phrase (comma-separated terms run as separate jobs and are unioned). The stage retries on the original RGB frames and then `SAM_FALLBACK_MODEL` by itself when the depth pass finds nothing; read `sam-report.json` and `sam-attempts.json` before any manual repair (`workflow.py repair-rgb`), and never retry a run that stopped on a billing or rate-limit error.
4. Mandatory full-clip review before EVERY generation: inspect the whole clip, including cuts, extremities, hair, hands, clothing, background spill, holes, alignment and flicker (mesh modes: face tracking, eyes, mouth, alignment). Automated checks and sampled contact sheets do not establish approval. Repair failures within the authorized scope, then review again. Never approve a known-bad input. `mask_review` binds approval to the artifact fingerprint; any change clears it. User approval may be recorded as user approval, never as a review you did not perform.
5. References are identity only. `char1` (required) is an image or an identity video; `char2` (optional) is an image. `@Image1`/`@Image2` define face, hair, outfit and proportions; pose, motion, timing and lip-sync come from `@Video1`. Match the references to the actual subjects in this job; never carry over a previous job's mapping.
6. Show the exact creative prompt before submission, including the adapter-appended text in `seedance-request.json`. Existing explicit authorization to submit is sufficient; do not ask again unnecessarily.
7. Submit the draft through the selected provider (`fal` or `enhancor`; see `docs/PROVIDERS.md`). Persist `seedance-response.json` and `generation.json`. Resume saved requests (`workflow.py resume`) instead of ever duplicating a paid request.
8. Retrieve the result and restore the entire untouched original audio, discarding generated audio. Preserve draft artifacts. Report failures honestly with the local job and request IDs; never claim a submission or completion without an actual result.
9. On explicit approval only, finalize the accepted draft (`workflow.py hd` or the UI button): fal completes the same `draft_id` at 1080p; Enhancor completes via `draft_id`. Then restore the original audio again under `hd/`.
10. Show the final preview and download. Keep status persisted and the UI preview selection stable. Never expose credentials: keys live only in `.env` and never appear in logs, run folders, URLs or the UI.

## Reference-mode routing (required)

An image `char1` uses the provider's edit path: one video (`@Video1`, the prepared clip) plus `@Image1` and optional `@Image2`. A video `char1` is an identity reference: fal adds it to `video_urls` as `@Video2`; Enhancor switches to `multi_reference` with `videos: [prepared, identity]`, a supported aspect ratio and whole-second duration. Use the identity clip for appearance only unless the user explicitly asks for its voice or performance, and do not convert it to stills without permission. Show the actual mode in the UI and in `generation.json`. Preserve the full source audio in the final export and disclose any short last-frame hold.

## Modes

- **Advanced · Depth + SAM** (`depth`): Replicate depth and SAM 3; full mask review required.
- **Fast · Face mesh** (`face_mesh`): MediaPipe landmarks drawn on the original frames; no depth or SAM calls; needs `bash setup-face-mesh.sh` (Python 3.12, isolated `.venv-face`, model downloaded on first use). One speaker; the crop follows the face, so it need not be centred, and gaps of up to 6 frames are interpolated (drawn dimmer). Review face tracking, not a mask.
- **Advanced + Face mesh** (`depth_mesh`): depth pipeline plus the mesh over the depth composite; landmarks in `face-landmarks.json`. Review both mask coverage and tracking.

In mesh modes, the prompt must say the mesh lines are motion guidance that must disappear, that the whole identity including hair is replaced, and that all dialogue and timing are preserved. Keep advanced depth mode available. Never submit automatically during setup.
