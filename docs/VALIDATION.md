# Validation status

An honest record of what has been checked in the Puppeteer fork, and what has not.

## Validated

- Unit tests: `.venv/bin/python -m pytest -q` passes (Python 3.14, macOS ARM64). Coverage includes mask-review fingerprint invalidation, duplicate-submission refusal, original-audio packet restoration, prepared-clip audio identical to the source when `clean_dialogue` is off, Demucs vocals embedded when it is on, tmpfiles link extraction, catbox never used on default settings, explicit catbox opt-in and its warning, and per-provider payloads (fal `reference-to-video` draft and `draft/complete`; Enhancor `/queue` draft and `draft_id` completion) with mocked HTTP / mocked `fal_client`.
- `test_composite.py`: synthetic four-frame compositing (depth foreground, original background, aligned output).
- Provider adapters: payload shapes, poll state mapping, finalize payloads, missing-`draft_id` error and capabilities keys are covered with mocks only. The fal payload shape was checked against the published OpenAPI schema on 2026-10-21.
- Face-mesh worker (2026-10-22, macOS ARM64, Python 3.12.15): `setup-face-mesh.sh` installed MediaPipe 1.1.0 into `.venv-face`; `doctor.py --mesh` reports the worker OK; a dry run on a synthetic faceless clip downloaded the Face Landmarker model, wrote `face-tracking.json` and refused the clip with the expected tracking-gap error. Tracking quality on real faces has not been checked here.
- UI: loads at desktop width and at 380px with no horizontal overflow and no console errors; `/health`, `/providers` and the three mode choices render without any key configured.

## Not validated in this fork

- Live fal or Enhancor runs: no draft, finalize, upload, webhook or billing path has been exercised against a real account. Provider access, balance, limits and output quality are unverified.
- Live Replicate depth, SAM 3 or Demucs calls.
- Face-mesh tracking on real footage: only a faceless synthetic clip was run through the worker.
- Fresh installation on Linux or Windows/WSL.
- Full-clip visual mask approval is a human step; the test suite cannot stand in for it.

Treat any claim beyond the first list as untested until you run it yourself with your own keys.
