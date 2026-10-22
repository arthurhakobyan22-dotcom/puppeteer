# Validation status

An honest record of what has been checked in the Puppeteer fork, and what has not.

## Validated

- Unit tests: `.venv/bin/python -m pytest -q` passes (Python 3.14, macOS ARM64). Coverage includes mask-review fingerprint invalidation, duplicate-submission refusal, original-audio packet restoration, prepared-clip audio identical to the source when `clean_dialogue` is off, Demucs vocals embedded when it is on, tmpfiles link extraction, catbox never used on default settings, explicit catbox opt-in and its warning, and per-provider payloads (fal `reference-to-video` draft and `draft/complete`; Enhancor `/queue` draft and `draft_id` completion) with mocked HTTP / mocked `fal_client`.
- `test_composite.py`: synthetic four-frame compositing (depth foreground, original background, aligned output).
- Provider adapters: payload shapes, poll state mapping, finalize payloads, missing-`draft_id` error and capabilities keys are covered with mocks only. The fal payload shape was checked against the published OpenAPI schema on 2026-10-21.
- Face-mesh worker (2026-10-22, macOS ARM64, Python 3.12.15): `setup-face-mesh.sh` installed MediaPipe 1.1.0 into `.venv-face`; `doctor.py --mesh` reports the worker OK; a dry run on a synthetic faceless clip downloaded the Face Landmarker model, wrote `face-tracking.json` and refused the clip with the expected tracking-gap error. Tracking quality on real faces has not been checked here.
- Face-first tracking (2026-10-22, worker in `.venv-face`): built from a 31-frame frontal segment of a user clip at 960×550. Off-centre variant (face scaled to 45% in the lower-left corner): 31/31 tracked. 5-frame full-frame occlusion (0.21 s): passes with 5 frames marked filled. 10-frame occlusion (0.42 s): fails with "lost face 0.5–0.92 s; 32% of frames missing". The original 195-frame clip, which the fixed centre crop tracked on 125 frames, now tracks 162 and fills 14; the remaining gaps (0.42–0.71 s and 2.08–2.58 s) are full 90° profile turns, which MediaPipe Face Landmarker does not detect, so that clip still fails with those ranges in the message. Filled frames are drawn at 45% brightness; the review screen shows the counts and ranges.
- Advanced + Face mesh, lenient gaps (2026-10-22): the same 195-frame clip prepared successfully with the depth and SAM output of an earlier run; tracked 163 / filled 13 / missing 19, gaps 0.42–0.71 s and 2.08–2.58 s shown as a warning, mesh present on frontal frames and absent on the profile frames.
- UI: loads at desktop width and at 380px with no horizontal overflow and no console errors; `/health`, `/providers` and the three mode choices render without any key configured.

## Not validated in this fork

- Live fal or Enhancor runs: no draft, finalize, upload, webhook or billing path has been exercised against a real account. Provider access, balance, limits and output quality are unverified.
- Live Replicate depth, SAM 3 or Demucs calls.
- Face-mesh tracking on footage with many speakers, extreme lighting or very small faces.
- Fresh installation on Linux or Windows/WSL.
- Full-clip visual mask approval is a human step; the test suite cannot stand in for it.

Treat any claim beyond the first list as untested until you run it yourself with your own keys.
