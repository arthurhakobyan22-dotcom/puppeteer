# Seedance 2.5 providers

Puppeteer submits the prepared clip (`seedance-input.mp4`) plus the character references through one of two adapters in `providers/`. Choose with the **Seedance provider** dropdown in the draft panel, `workflow.py submit --provider`, or `SEEDANCE_PROVIDER` in `.env`. When unset, the default is `enhancor` if `ENHANCOR_API_KEY` is set, else `fal` if `FAL_KEY` is set. `GET /providers` returns each adapter's capabilities plus `configured: true|false` (keys are never exposed). `python doctor.py` prints a readiness line per provider.

| | fal | Enhancor |
|---|---|---|
| Env key | `FAL_KEY` | `ENHANCOR_API_KEY` |
| Draft | 480p, `draft: true` | 1080p, `is_draft: true` |
| Final | 1080p via `draft/complete` | 1080p via draft completion |
| Finalize identical to draft | Yes (same `draft_id`, valid 7 days) | Yes (provider reuses the draft parameters) |
| Media hosting | fal storage (`fal_client.upload_file`) | `media_host.upload` (tmpfiles by default) |
| Webhook / cloudflared | Not needed | Required (`ENHANCOR_WEBHOOK_URL` or the automatic cloudflared tunnel) |
| Identity video for Character 1 | `@Video2` in `video_urls` | `multi_reference` mode |
| Max clip length | 30 s | 30 s |

Both adapters build the same prompt through `providers.base.build_prompt`: your prompt, then a sentence describing `@Video1` (the colored-depth composite or face-mesh overlay with the dialogue embedded), then `@Image2` rules when Character 2 is set, plus the mesh-mode sentence that removes mesh lines and depth colors. The orchestrator (`seedance_bridge.py`) handles the mask-review gate, duplicate-submission refusal, audio preparation, polling, downloading `seedance-result.mp4` and `finish_preview` (entire original source audio restored).

## fal (`providers/fal.py`)

- Draft endpoint: `bytedance/seedance-2.5/reference-to-video`. Every local file is uploaded to fal storage with `fal_client.upload_file`; nothing goes to tmpfiles or catbox.
- Payload: `{'prompt', 'video_urls': [prepared (+ char1 video)], 'image_urls': [char1 image, char2]` (omitted when empty)`, 'task': FAL_TASK, 'draft': True, 'resolution': '480p', 'generate_audio': True}`. `duration` and `aspect_ratio` are not sent: `task: editing` coerces them to `auto`.
- `FAL_TASK` (default `editing`) accepts `auto | reference | editing | extension`. `editing` modifies the prepared clip; `reference` treats it as a style/motion reference.
- Local checks before any upload (no paid call): each video 1.8–30.2 s, ≤200 MB, 300–6000 px per side, aspect 0.4–2.5, 24–60 fps; images ≤30 MB.
- Polling: `fal_client.status` → `Queued` (queue position shown), `InProgress`, `Completed`; then `fal_client.result` is saved to `fal-result.json` (`video.url`, `seed`, `draft_id`) and `draft_id` is copied into `generation.json`.
- Finalize: `bytedance/seedance-2.5/draft/complete` with `{'draft_id': ..., 'resolution': '1080p'}`. This is a true completion of the same draft (same account, valid for 7 days), so the 1080p result matches the approved 480p draft. If the result carried `draft_id: null`, finalize raises instead of re-running.
- The key is read by `fal_client` from the environment (`config.load_env()` copies `.env`). It is never logged, written to a run folder or placed in a URL; `fal_client` errors are re-raised as `RuntimeError` with the key redacted.

## Enhancor (`providers/enhancor.py`)

- Base URL `ENHANCOR_BASE_URL` (default `https://apireq.enhancor.ai/api/seedance2.5/v1`), header `x-api-key`.
- Draft: `POST /queue` with `mode: edit`, `is_draft: true`, `resolution: 1080p`, `output_format: mp4`, `pass_faces: true`, `aspect_ratio: adaptive`, `videos: [prepared]`, `images: [char1, char2?]`, `audios: []`, `webhook_url`. When Character 1 is a video the mode becomes `multi_reference` with `videos: [prepared, char1]`, a `duration` (4–30, rounded from the prepared clip) and the nearest `aspect_ratio`.
- Media must be publicly reachable, so files are hosted through `media_host.upload` (tmpfiles by default; see `docs/MEDIA-HOSTING.md`).
- Polling: `POST /status` with `{'request_id'}`; `COMPLETED` → `result` URL, `FAILED`/`CANCELED` → error, anything else keeps polling. Callbacks to the webhook are accepted but never trusted; polling is authoritative.
- Finalize: `POST /queue` with `{'draft_id': <draft request id>, 'webhook_url': <same as draft>}`. Enhancor reuses the draft parameters, so the 1080p output corresponds to the approved draft.
- Needs a public HTTPS callback: `launch.py` starts a cloudflared tunnel when the binary is installed, or set `ENHANCOR_WEBHOOK_URL`.

## Files written per run

- `seedance-request.json`: the exact payload sent (no secrets).
- `seedance-response.json`: `{'requestId', 'provider', 'endpoint'?}`; `wait_and_finish`, startup resume and `workflow.py resume` read the provider from here.
- `generation.json`: `{'request_id', 'provider', 'prompt', 'mode', 'video', 'draft_id'?}`.
- `provider-status.json`: last poll result. `fal-result.json`: raw fal result.
- `hd/request.json`, `hd/response.json`: finalize payload and `{'requestId', 'provider', 'endpoint'?}`.
