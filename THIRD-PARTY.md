# Third-party notices

Puppeteer is a fork of **Genjutsu Open Source Workflow** by Sirio Berati (MIT, https://github.com/sirioberati/Genjustsu-Open-Source-Workflow). The original MIT license file is retained unchanged as `LICENSE` and continues to cover the inherited code and documentation; Puppeteer's changes are released under the same MIT terms.

Python dependencies listed in `requirements.txt` retain their respective licenses.

Hosted models are **not redistributed** in this repository and remain subject to their providers' terms and your own account access:

- Demucs (`htdemucs`) via Replicate, used only when clean dialogue is enabled
- Depth Anything (video) via Replicate or Hugging Face
- SAM 3 (video segmentation) via Replicate
- MediaPipe Face Landmarker (Google), downloaded by the optional face-mesh worker on first use
- Seedance 2.5 (ByteDance) via fal or Enhancor

cloudflared is an optional external executable distributed by Cloudflare; this repository does not bundle it. Google Fonts are requested by CSS at runtime, not vendored here.

No example media, branding assets, logos or third-party footage are included in this repository. No license to any third-party footage, music or likeness is granted by this package; use only video you own or have licensed.
