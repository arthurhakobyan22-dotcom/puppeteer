---
name: tein-video-workflow
description: Run this project's depth, SAM 3 and Enhancor video subject replacement workflow, including full-clip mask review, draft generation, retrieval, and approved HD export.
---

Read the project root AGENTS.md and docs/AGENT-OPERATIONS.md before running a job. Resolve the root as the folder containing workflow.py, not a machine-specific path. Consult docs/ENHANCOR-API.md for request routing and recovery and docs/MEDIA-HOSTING.md before changing upload providers.

Use workflow.py and the local UI; do not recreate credentials or hardcode prior users' media, subjects or request IDs. Carry authorized preparation and collection through to the final preview. Full-clip visual mask QA is mandatory before any generation; if you cannot inspect the video, ask the user to review it. Fix coverage failures with raw masks and, when needed, original-RGB segmentation; preserve the depth model's colors. Approval is invalid after artifact changes.

Prepare the clip with the entire original audio embedded; enable clean dialogue only when the user wants Demucs-isolated vocals in the lip-sync input. Route an image identity reference to Edit and video identity reference to Omni. Show the exact prompt and honor the authorized submission scope. Restore the entire original soundtrack on return. Inspect saved request IDs before retrying; resume retrieval instead of duplicating paid requests. Ask before HD unless explicitly approved already. Bound repair attempts to the authorized scope; stop and explain persistent provider or visual failures rather than claiming success.


## Fast alternative: face mesh

Choose **Fast · Face mesh** in the UI, or use `workflow.py prepare VIDEO --mode face_mesh`. Install the optional worker once with `bash setup-face-mesh.sh` (Python 3.12 required; isolated `.venv-face`). The model downloads from Google's official storage on first use.

This path keeps the original video, tracks and saves facial landmarks, draws the mesh and embeds the original audio (or isolated vocals with clean dialogue). It makes **no depth or SAM calls**. It is currently designed for a single centered speaker; inspect all frames and stop on tracking gaps or incorrect face alignment. Do not claim mask review in this mode: review facial tracking and audio instead. Saved artifact hashes gate submission.

Use the same character references, draft-first submission, collection, original-audio restoration and explicitly approved HD upgrade. In the prompt, explain that mesh lines are motion guidance and must disappear, replace the complete original identity including hair, and preserve all dialogue and timing. Image reference uses Edit; video identity uses Omni. Keep advanced depth mode available. Do not submit automatically during setup.


### Combined depth + face mesh

Select **Advanced + Face mesh** in the UI or use `workflow.py prepare VIDEO --mode depth_mesh`. This runs the original depth/SAM pipeline, preserves its depth composite, then tracks the face from the original frames and overlays the mesh onto that composite. Landmarks are saved in `face-landmarks.json`. Review BOTH mask coverage and face tracking before approval. All artifacts, including depth, mask, mesh and embedded audio, are bound to review approval. Follow the same draft → approved HD → original-audio restoration flow.

For setup with all three preparation modes, also install Python 3.12 and run `bash setup-face-mesh.sh`. This creates an isolated mesh environment; the main app can retain its existing Python version. A Google Face Landmarker model is downloaded at first use. No SAM/depth inference is used by fast mode. Mesh modes are experimental and currently optimized for one centered speaker.
