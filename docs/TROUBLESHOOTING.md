# Troubleshooting

- Webhook URL required (Enhancor only): install cloudflared and use start.command, or set your own public HTTPS callback. Never tunnel the UI/runs directory. The callback-only receiver is separate. The fal provider needs no webhook.
- fal finalize refused with "no draft_id": the draft result carried `draft_id: null`; finalize will not silently re-run. Create a new draft.
- Missing credentials: populate this folder's `.env`; restart. Credentials are never obtained from a parent project.
- 401/403 or missing model: verify your account/key/access and provider model schema. Never paste secrets into logs.
- Invalid image / media download failure (Enhancor): use real PNG/JPEG/WebP files and reachable direct URLs. Tmpfiles URLs expire. The uploader rejects HTML/empty responses. It never falls back to catbox unless `MEDIA_HOST_FALLBACKS=catbox` is set.
- SAM returned no masks ("empty result, not a quota or model error"): the text prompt matched nothing. SAM 3 wants one short noun phrase ("person", "man in a dark suit"); "person, hands" as a single phrase returns a zip with only an overlay video. Comma-separated subjects are now run as separate jobs and combined. The stage first tries the depth video, then the original RGB frames, then `SAM_FALLBACK_MODEL`; every prediction is listed in `sam-attempts.json` with its id, status, error and log tail, and the chosen route in `sam-report.json`.
- SAM billing, credit or rate-limit errors stop immediately with Replicate's own message (HTTP 402/429 or an error mentioning credit/quota); no fallback is tried because it would hit the same limit. A failed prediction reports the model error and the relevant log lines.
- Frame alignment failed (original/depth/SAM): the three inputs have different frame counts; this no longer happens for an empty SAM result, which is reported as above.
- Mask holes, edge noise, chair spill: reject it, run RGB repair and review the full clip again. Cleanup is heuristic; never assume it proves correctness.
- Frame count/index mismatch: composition fails deliberately. Inspect output fps/frame IDs; align the provider output to the same source rather than forcing a shifted mask through.
- Original audio duration mismatch: the exporter permits a short final-frame hold for a 0.25–0.5 second provider rounding gap and records `duration-adjustment.json`. Larger differences are rejected. It never stretches or loops source audio. If the source codec cannot be remuxed into MP4, stop and choose an explicit compatible export plan.
- No source audio: currently unsupported; provide a source with an audio track or adapt the workflow explicitly.
- Restart: Seedance and HD result retrieval resume from saved responses. Earlier preparation failures require inspecting saved Replicate predictions. The local UI is not a durable distributed worker queue.
- UI fonts: Google Fonts is used, with system fallbacks if offline. No other remote assets are loaded.
- Lost pending status: use `workflow.py resume JOB` (or `--hd`), not another submit. Completed outputs remain in `runs`.
