# Enhancor / Seedance 2.5 integration

This is the request/response reference for Puppeteer's `providers/enhancor.py` adapter, derived from the working implementation. The fal adapter is documented in `docs/PROVIDERS.md`. It is not a copy of a complete vendor specification. Confirm current account support and limits in the [Enhancor API dashboard](https://app.enhancor.ai/api-dashboard). The public dashboard requires browser access; its full 2.5 schema was not independently retrievable during packaging. Live requests verified the required webhook field, queue acceptance and the model/reference mode used here.

Base URL: `https://apireq.enhancor.ai/api/seedance2.5/v1`
Authentication: `x-api-key: YOUR_KEY` (server-side only).

## Submit a draft — POST /queue

```json
{
  "mode": "edit",
  "resolution": "1080p",
  "aspect_ratio": "adaptive",
  "is_draft": true,
  "output_format": "mp4",
  "pass_faces": true,
  "videos": ["https://YOUR_HOST/prepared.mp4"],
  "images": ["https://YOUR_HOST/character.png"],
  "audios": [],
  "prompt": "@Image1 defines the character's identity only ... Pose, motion, timing and lip-sync come from @Video1. ...",
  "webhook_url": "https://YOUR_RECEIVER/callback"
}
```

Response used by the app: `{"requestId":"PROVIDER_ID"}`. Save it immediately. Edit uses one input video. For video identity references use `mode: "multi_reference"`, `videos: [prepared_url, identity_url]`, a supported aspect ratio and a whole-second duration string. The adapter chooses nearest duration from 4–30 seconds and nearest aspect ratio. These are adapter constraints, not a promise of every account's supported limits. `@Video1` controls movement/audio; `@Video2` controls appearance only. An optional second image is `@Image1` in this mode, not `@Image2`.

Images should be actual decodable PNG/JPEG/WebP bytes, not an HTML download page renamed as an image. References must be reachable remotely. Local paths and localhost URLs are not provider-accessible.

## Poll — POST /status

Body: `{"request_id":"PROVIDER_ID"}`.
The collector polls every 10 seconds, for up to 360 attempts. It reads `status`, saves `provider-status.json`, downloads the HTTPS `result` on `COMPLETED`, and reports `FAILED`/`CANCELED` with the provider error. A timeout leaves request IDs saved; resume collection, do not requeue automatically. Transport errors also preserve the ID for recovery.

Live testing confirmed that webhook_url is required: an empty value returns HTTP 400. Set your own HTTPS receiver or install cloudflared and use launch.py, which starts webhook.py behind a temporary Quick Tunnel. The receiver accepts callbacks but never mutates jobs; polling remains authoritative. The receiver exposes no files or UI. Do not reuse the original author’s callback. Keep the tunnel alive while generation runs; its URL changes on restart.

## Complete an approved draft — POST /queue

```json
{"draft_id":"ACCEPTED_DRAFT_REQUEST_ID","webhook_url":""}
```

Do not send a new creative prompt or input files with draft completion. The provider reuses the draft settings (1080p requested initially). This is a separate billed operation and requires approval. Save the new request ID in `hd/response.json`, poll it, then restore the full original soundtrack. Never overwrite the draft preview. Media for Enhancor is hosted through `media_host.upload` (tmpfiles by default; catbox only on explicit opt-in, see `docs/MEDIA-HOSTING.md`).

## Local routes

- `POST /jobs`: multipart `video`, `mode` (`depth`, `face_mesh`, `depth_mesh`), `prompt` (segmentation subject), `provider` (depth provider), `clean_dialogue`.
- `GET /jobs/{id}`: local progress.
- `GET /jobs/{id}/mask-review`: artifact fingerprint and approval.
- `GET /jobs/{id}/files`: relative paths of every file in the run folder (the UI reads this once per refresh instead of probing optional files).
- `POST /jobs/{id}/mask-review`: `approved`, `fingerprint`, `note`.
- `POST /jobs/{id}/seedance`: `prompt`, `char1` (Character 1: image or identity video), optional `char2` (second image), optional `provider` (`enhancor` or `fal`; defaults per `SEEDANCE_PROVIDER`). Files are saved as `char1-reference.<ext>` / `char2-reference.<ext>`.
- `GET /providers`: capabilities and `configured` flag per provider plus the `default`; see `docs/PROVIDERS.md`.
- `POST /jobs/{id}/hd`, `GET /jobs/{id}/hd`: approved upgrade and progress.
- `POST /jobs/{id}/finish`: manually upload returned `video` and restore original audio.
- `GET /health`: `{"status":"ok","service":"Puppeteer"}`.
- `/docs`: FastAPI-generated local endpoint documentation.

No paid POST is automatically retried after an ambiguous timeout. Check the provider dashboard before deliberately creating another request. Public media may expire while queued; use a longer-lived host if necessary.

Get access at [Enhancor.ai](https://enhancor.ai) and obtain your own key in the [API dashboard](https://app.enhancor.ai/api-dashboard). The integration requests human-face support with `pass_faces: true`; provider terms and account limitations still apply.
