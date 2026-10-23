# Costs research

Public list prices collected on **2026-10-22** for every hosted tool Puppeteer calls, with a per-tool formula and an estimate for the reference clip: **10 s, 24 fps = 240 frames**, 1280×720 unless noted. Numbers are list prices without volume discounts; "listed per-run" figures are Replicate's own averages over recent predictions, not a measurement on our clip. Anything not read from a vendor page is marked **unverified**. Use this to fill `stages/costs.py`.

## Platform rates

| Platform | Rate | Source |
|---|---|---|
| Replicate, Nvidia T4 | $0.000225/s ($0.81/h) | https://replicate.com/pricing |
| Replicate, Nvidia L40S | $0.000975/s ($3.51/h) | same |
| Replicate, Nvidia A100 80GB | $0.001400/s ($5.04/h) | same |
| Replicate, Nvidia H100 | $0.001525/s ($5.49/h) | same |
| fal, H100 (fallback for models without output pricing) | $0.00125/s list, "as low as" $0.000692/s | https://fal.ai/pricing ; https://fal.ai/docs/documentation/model-apis/pricing |
| Hugging Face ZeroGPU credits beyond quota | $1 per 10 GPU-minutes (PRO/Team/Enterprise only) | https://huggingface.co/docs/hub/spaces-zerogpu |

Replicate bills public models by predict time at the hardware rate above; the per-run figure on each model page is "approximately $X to run … or N runs per $1", an average over recent predictions.

## Per-tool prices and 10 s / 24 fps estimate

| Tool | Hardware / unit | Listed price | Formula | 10 s @ 24 fps estimate | Source |
|---|---|---|---|---|---|
| Replicate `lucataco/depth-anything-video` (version `9143691405af…`) | T4, per second | "approximately $0.040 to run, or 25 runs per $1"; "typically complete within 3 minutes" | `0.000225 × predict_seconds` | **$0.04** (listed average; per-frame speed unverified) | https://replicate.com/lucataco/depth-anything-video |
| Replicate `chenxwh/depth-any-video` (version `4055afe2aba3…`) | A100 80GB, per second | "approximately $0.14 to run, or 7 runs per $1"; "typically complete within 100 seconds" | `0.0014 × predict_seconds` | **$0.14** (listed average) | https://replicate.com/chenxwh/depth-any-video |
| Replicate `lucataco/sam3-video` (version `408f82fc20c3…`) | L40S, per second | "approximately $0.0022 to run, or 454 runs per $1"; "typically complete within 3 seconds" (clearly measured on tiny inputs) | `0.000975 × predict_seconds`; SAM 3 tracking on L40S runs ≈0.35 s/frame (gener8 measurement, same model family) → `≈ 0.000975 × 0.35 × frames` | **≈$0.08** (240 frames × 0.35 s = 84 s). Unverified for this wrapper; floor is the listed $0.0022 | https://replicate.com/lucataco/sam3-video ; https://replicate.com/8digit/gener8-sam3 (readme timing) |
| Replicate `8digit/gener8-sam3` (version `a6f50615da4c…`) | L40S, per second | "approximately $0.043 to run, or 23 runs per $1"; readme: 576 frames, 26 people, no preview = 200 s GPU ≈ $0.20; with preview 291 s ≈ $0.28; max 2000 frames | `0.000975 × (0.35 × frames [+ 0.115 × frames if preview])` | **≈$0.08** no preview, ≈$0.11 with preview (fewer objects than the readme's crowd → likely less) | https://replicate.com/8digit/gener8-sam3 |
| Replicate `cjwbw/demucs` (version `25a173108cff…`) | T4, per second | "approximately $0.015 to run, or 66 runs per $1"; "typically complete within 68 seconds" | `0.000225 × predict_seconds` (scales with audio length and `shifts`) | **≤$0.015** (10 s of audio is shorter than the listed average input) | https://replicate.com/cjwbw/demucs |
| Replicate `meta/sam-2-video` (version `33432afdfc06…`) | L40S, per second | "approximately $0.029 to run, or 34 runs per $1"; "typically complete within 30 seconds" | `0.000975 × predict_seconds` | **≈$0.03–0.09** (30–90 s; per-frame speed unverified) | https://replicate.com/meta/sam-2-video |
| fal `fal-ai/sam2/video` | "$0 per compute seconds" on the model page (placeholder); docs say such models bill per GPU-second | `gpu_rate × runtime` (rate unverified; H100 list $0.00125/s) | **≈$0.04 unverified** (30 s on H100) | https://fal.ai/models/fal-ai/sam2/video/llms.txt |
| fal `fal-ai/sam-3/video` and `/video-rle` | per 16 frames of video input | "$0.005 per 16 frames" | `0.005 × ceil(frames / 16)` | **$0.075** (15 blocks) | https://fal.ai/models/fal-ai/sam-3/video-rle/llms.txt |
| fal `fal-ai/sam-3-1/video` and `/video-rle` | per 16 frames | "$0.01 per 16 frames" | `0.01 × ceil(frames / 16)` | **$0.15** | https://fal.ai/models/fal-ai/sam-3-1/video/llms.txt |
| fal `bytedance/seedance-2.5/reference-to-video` | per output second (token-derived) | 480p "roughly $0.2205" /s; 720p "roughly $0.4730" /s; 1080p "roughly $1.164" /s. Token price $0.0214 per 1k tokens (480p/720p), $0.0234 per 1k (1080p). `tokens ≈ H × W × (input_video_duration + output_duration) × 24 / 1024`. "If video inputs are provided the price is multiplied by 0.6" and "you will be charged for both input and output videos" (with video refs: 720p ≈$0.2838 /s, 480p ≈$0.1323 /s). Audio and image refs are free. `draft: true` forces 480p. Duration 4–30 s. | no video ref: `rate_res × out_s`; with video ref: `0.6 × rate_res × (in_s + out_s)` | 480p draft, no video ref: **$2.21**; 480p draft with a 10 s reference video: **$2.65**; 720p: **$4.73** / **$5.68** with 10 s video ref; 1080p: **$11.64** / **$13.97** with video ref | https://fal.ai/models/bytedance/seedance-2.5/reference-to-video/llms.txt ; OpenAPI `endpoint_id=bytedance/seedance-2.5/reference-to-video` |
| fal `bytedance/seedance-2.5/draft/complete` | per output second, 1080p only | "roughly $1.164 per second of generated video"; $0.0234 per 1k tokens; same ×0.6 rule for video inputs; `draft_id` valid 7 days, same account | `1.164 × out_s` (×0.6 × (in_s + out_s) when the draft used a video ref) | **$11.64**, or **$13.97** when the draft had a 10 s video reference (the draft's own 480p charge is paid separately, so draft → complete ≈ $13.85–16.62 total) | https://fal.ai/models/bytedance/seedance-2.5/draft/complete/llms.txt |
| Enhancor Seedance 2.5 API (`apireq.enhancor.ai/api/seedance2.5/v1`) | — | **Unverified / not public.** enhancor.ai and enhancor.ai/pricing render only "Enhancor - AI Skin Texture Enhancement Tool" server-side; no API price list was found by search; our own `docs/ENHANCOR-API.md` notes the dashboard "requires browser access". Read the per-job price from https://app.enhancor.ai/api-dashboard while logged in and record it here. | — | — | https://enhancor.ai ; docs/ENHANCOR-API.md |
| Hugging Face Space `depth-anything/Video-Depth-Anything` | ZeroGPU (API reports hardware `zero-a10g`; HF docs now describe ZeroGPU as half/full RTX Pro 6000). `@spaces.GPU(duration=240)` → max 240 s GPU per call. UI defaults: `max_len` 500 frames (slider −1…1000), `target_fps` 15 (−1…30), `max_res` 1280 (480…1920), encoder `vitl`. | Free within daily ZeroGPU quota: unauthenticated 2 min, free account 5 min, PRO 40 min (then $1 / 10 min credits); quota resets 24 h after first use | `$0` while `gpu_seconds_today ≤ quota`; PRO overflow `0.1 × gpu_minutes` | **$0** (a 10 s clip at the default 15 fps = 150 frames; one call ≈ 1–2 GPU-min, so a free account gets ~2–4 clips/day, unverified) | https://huggingface.co/spaces/depth-anything/Video-Depth-Anything (raw `app.py`) ; https://huggingface.co/api/spaces/depth-anything/Video-Depth-Anything ; https://huggingface.co/docs/hub/spaces-zerogpu |

## Worked totals for the reference clip (10 s, 24 fps, 720p)

| Pipeline | Tools | Estimate |
|---|---|---|
| Segment (text prompt) | `lucataco/sam3-video` | ≈$0.08 (unverified; listed floor $0.0022) |
| Segment fallback | `8digit/gener8-sam3` | ≈$0.08–0.11 |
| Mask wand (one correction pass) | fal `sam-3/video-rle` | $0.075 |
| Mask wand fallback | Replicate `meta/sam-2-video` | ≈$0.03–0.09 |
| Depth | `lucataco/depth-anything-video` / `chenxwh/depth-any-video` / HF Space | $0.04 / $0.14 / $0 |
| Stems | `cjwbw/demucs` | ≤$0.015 |
| Seedance 2.5 draft (480p, 10 s reference video) | fal `reference-to-video`, `draft: true` | $2.65 |
| Seedance 2.5 finalize (1080p) | fal `draft/complete` | $13.97 |
| **Draft-only run** (segment + wand + depth + stems + 480p draft) | | **≈$2.9** |
| **Full run incl. 1080p complete** | | **≈$16.9** |

Seedance dominates every run; everything else together is under $0.40. For `stages/costs.py`, model the per-tool formulas above with `frames = round(duration_s × fps)` and expose the three unverified runtime constants (SAM 3 s/frame on L40S, SAM 2 s/frame, fal `sam2/video` GPU rate) as named defaults so they can be replaced with measured values after the first paid runs.
