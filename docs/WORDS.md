# Words track: transcription, dialogue beats, mouth guidance, subtitles (Agent 4)

The timeline's **Words** lane shows the run's words as blocks. Transcribe once (free, on this Mac), fix the words and
their timing by hand, then use them three ways: timed dialogue beats in the prompt, `mouth-guidance.json` for a later
stage, and subtitles (an `.srt` file, or burned into a copy of the final). Contract: `docs/TIMELINE-SPEC.md` §6, §A4.

## 1. Engine choice (measured 2026-10-24 on this Mac: Apple M4, 24 GB, macOS 26)

Setup: `bash setup-words.sh` makes `.venv-words` (Homebrew Python 3.12) with `mlx-whisper==0.4.3` (pulls mlx 0.32.4,
torch 2.14.1, numba, tiktoken, huggingface_hub; `.venv-words` is 1.2 GB on disk) and downloads the model once into
`models/whisper/whisper-large-v3-turbo/` (**1.6 GB**, 1.5 GiB on disk, from `mlx-community/whisper-large-v3-turbo`). After that nothing
needs the network (the worker runs with `HF_HUB_OFFLINE=1` and a local model folder). Other models for a comparison:
`WORDS_MODELS="whisper-large-v3-turbo whisper-large-v3-mlx whisper-small-mlx" bash setup-words.sh`.

Fixture: `runs/85e5dbe6…/upload.mp4` (8.13 s, a sung line over music) and the isolated `vocals.wav` of the same clip
(`runs/3c54f295…`). The RMS envelope of the vocals (0.1 s bins) gives the reference timing: a held "And" from 0.7 s,
"I need you" from 2.7 s, "I miss you" from 5.3 s, the next line starting at 7.9 s. Lyric heard: *"And I need you, and I
miss you, and …"*. Times are wall-clock for the whole worker run (process start + model load + transcription); a
second run is no faster because every run is a fresh process.

| model (mlx) | size | run time (mix) | text (speech mode, mix) | "I" of "I need" / "miss" (ref 2.7 / ~5.4 s) | problems |
|---|---|---|---|---|---|
| whisper-small-mlx | 0.46 GB | 2.0 s | "And I need you. And I miss you." | 2.88 / 5.64 | drops the last "and"; on the isolated vocals it hallucinates Turkish ("Majesteleri") in both modes |
| **whisper-large-v3-turbo** | **1.6 GB** | **4.0 s** (singing mode 3.6 s) | "And I need you, and I miss you, and I'm a" | 2.90 / 5.62 | a 2-word tail squeezed into the last 0.06 s ("I'm a"); the zero-length "a" is dropped by the tail filter |
| whisper-large-v3-mlx | 2.9 GB | 13.7 s (singing mode 18.8 s) | the line, then a repetition loop: 170 words of "and I miss you" at 8.08–8.10 s | 2.70 / 5.54 | loops on the music mix; adds "Ooh" in singing mode |

**Choice: `whisper-large-v3-turbo`.** Its words are right on both the mix and the isolated vocals in both modes, it
runs in 4 s for an 8 s clip (a 30 s clip ≈ 10 s), it never looped, and it is half the download of large-v3. Large-v3's
timing is ~0.15 s closer to the vocal onsets, but it loops on music and takes 3–5× longer; the timing difference is a
one-frame-drag fix on the lane, a repetition loop is not. All three put the held first "And" at 2.1–2.2 s instead of
0.7 s (sustained singing), which is what Singing mode + manual edge drags are for. whisper.cpp was not tried
(it needs a separate build and gives the same Whisper models; mlx is the native Apple Silicon path).

**How word timestamps are made:** `mlx_whisper.transcribe(word_timestamps=True)` aligns each decoded token to the audio
with dynamic time warping over the cross-attention weights of the alignment heads (OpenAI's method), then joins tokens
into words; `words_worker.py` returns `segments[].words[] = {word, start, end, probability}`. The app then cleans them
(`stages/words.py: clean`): text trimmed, sorted, no overlap (an earlier word is trimmed to the next start), a minimum
length (speech 0.06 s, singing 0.20 s), gaps shorter than 0.04 s (singing 0.25 s) closed by extending the earlier word,
clamped to the clip, and words shorter than 20 ms in the last 0.15 s of the audio dropped (Whisper's tail artifact).

**Singing mode** (checkbox next to Transcribe; a separate cache entry): the worker does not condition on the previous
text (repeated lyrics send Whisper into loops), accepts less certain segments (`no_speech_threshold 0.8`,
`logprob_threshold −1.5`, `compression_ratio_threshold 2.8`); the cleaning gives sung words a 0.20 s minimum and lets
held notes fill gaps up to 0.25 s. Expect to drag edges afterwards. Speech mode uses `condition_on_previous_text` and
`hallucination_silence_threshold 2.0`. No punctuation splitting in either mode (punctuation stays on its word).

**Paid fallback:** `fal-ai/elevenlabs/speech-to-text` (fal's live OpenAPI: input `audio_url`, `language_code`, `diarize`,
`tag_audio_events`; output `words[] = {text, start, end, type: word|spacing|audio_event}`), **$0.03 per minute** on its
fal page (read 2026-10-23; the billing granularity is not published, so the estimate counts every started minute: an
8 s clip shows "about $0.03"). `fal-ai/whisper` (`chunk_level: word`) was the other candidate but its page lists "$0 per
compute second", so no honest estimate can be shown; it is not used. The fallback needs `FAL_KEY`, shows its estimate on
the button, sends `confirm_cost=true` from that click (402 otherwise), and calls `record_call` (run's `calls.jsonl`)
before any upload, so `PUPPETEER_OFFLINE=1` stops it with a plain message. It was never run for real (mocked in tests).

## 2. Files and endpoints

- **Audio**: `vocals.wav` when clean dialogue made one (cleaner), else `upload.mp4` (the untouched source audio), else
  the prepared clip; decoded with PyAV to 16 kHz mono, hashed (sha256 of the samples).
- **Cache**: `runs/_cache/words/<audio sha>-<local|fal>-<speech|singing>.json` (`GET /jobs` and the tree skip `_cache`).
  A re-run with the same audio, engine and mode is instant and free (also for fal: a cached result needs no confirmation).
- **`words.json`** (written into the run only when it has none; never overwritten):
  `{version: 1, engine: "mlx-whisper:whisper-large-v3-turbo", language: "en", singing: false, words: [{text, start, end}], audio: {source, sha256, seconds}}`.
  A child made by "Save edits" gets `{…, edited: true}` with the edited words.
- `POST /jobs/{id}/words/transcribe {engine?: local|fal, singing?, language?, confirm_cost?, estimate_only?}` →
  `{words, engine_label, engine_name, language, singing, cached, written, guidance_written, seconds, source, estimated_cost_usd}`.
  Synchronous (≈ 4 s locally for the fixture); the panel says "Transcribing on this Mac…" meanwhile. Plain 400s: not
  installed / model missing (fix: `bash setup-words.sh`; offline says so), no audio track, offline + fal.
- `GET /jobs/{id}/words` → `{words (pending edits first, else words.json), source: edits|words.json|null, meta, words_file, frames, fps, seconds, engines: [{name, label, paid, estimated_cost_usd, ready, problem, offline_blocked}], has_audio}`. Writes nothing.
- When the run already has `words.json` (or pending word edits), a new transcription becomes a **pending edit**
  (`layer.words = {words, singing, edited: [], replaced: {engine, language}}`, summary "transcribed again (N words,
  singing mode)"), undoable, saved with "Save edits".

## 3. The lane and panel (`static/track-words.js`)

Blocks are DOM elements (`data-tl-item`): click = select + jump to its start; double-click = edit the text inline
(Enter keeps, Esc cancels, empty = delete); drag the left/right edge = timing (snaps to frames, clamped between the
neighbours, at least one frame; one commit per drag). Panel: engine select (local "free, runs locally" / fal "paid ·
about $0.03"), Singing mode, Transcribe; the selected word's text field and times (s + frames); Split at playhead
(text split at the nearest space, else proportionally), Merge with next, Add word at playhead / in range (an inline
field; fills the range or up to 0.4 s, never over a neighbour), Delete, ◀ Prev / Next ▶; Export subtitles (.srt),
`words.json ↓`, `mouth-guidance.json ↓`. While the track is selected the current word is drawn as a caption on the
overlay. Every edit is `edits.commit('words', …)` (shared undo/redo, persists across reloads).

## 4. Dialogue beats (prompt)

`stages/words.py: beats(words, pause=0.4)` groups words split at pauses ≥ 0.4 s and sentence ends:
`0.0–1.8 s says: "Hello there."` (double quotes inside become single quotes). `GET /jobs/{id}/words/beats` →
`{text, lines, source}` (pending edits first). The draft step's **Insert dialogue beats** button appends
`Dialogue beats (timing from the original audio; keep the lip-sync on these):` + the lines to the prompt textarea
(replacing an earlier inserted block). The textarea is sent as `prompt` to `POST /jobs/{id}/seedance` as before, and the
adapter still appends its @Video1/@Image rules (`providers.base.build_prompt`), so what you see plus those rules is what
is sent (also stored in `generation.json`).

## 5. Mouth guidance (data only)

`mouth-guidance.json` = `{version, fps, frames, words: [{text, start, end, start_frame, end_frame}] (inclusive frames),
per_frame: [{frame, word: index|null, mouth_hidden: bool|null}], summary: {words, frames_with_speech,
speech_frames_mouth_hidden}, note}`. `mouth_hidden` = face missing or interpolated (`face-tracking.json`
`missing_frames` ∪ `filled_frames`, or its `gaps`) ∪ mesh switched off (`edited.off_frames`); `null` when the run has
no face tracking. Written next to `words.json` on transcribe (only when absent), by the save hook into the child, and
refreshed after every branch run (`app.run_child` → `words.refresh_guidance`), so a child whose face stage re-ran
(mesh off 100–102) lists those frames. Nothing is generated from it yet.

## 6. Subtitles

- `stages/subtitles.py: cues(words, duration)`: phrases ≤ 42 characters and ≤ 5 s, split at pauses ≥ 0.6 s and
  sentence ends, each shown ≥ 0.5 s unless the next starts first, never past the clip. `srt()` writes index,
  `HH:MM:SS,mmm --> HH:MM:SS,mmm`, text, blank line. `GET /jobs/{id}/subtitles.srt` (pending edits first) answers
  `application/x-subrip` with `Content-Disposition: attachment; filename="<id8>-subtitles.srt"`; 404 + fix when there
  is no transcript (the buttons are disabled then).
- **Burn subtitles into final** (finish step, **off by default**): `POST /jobs/{id}/subtitles {burn: true}` re-encodes
  `final-preview.mp4` (and `hd/final-preview.mp4` when present) into `final-preview-subtitled.mp4` /
  `hd/final-preview-subtitled.mp4` next to the untouched finals: frames decoded with PyAV, text drawn with PIL (white,
  black 2 px outline, 2 px shadow, bottom-centred, Arial Bold from the macOS system fonts with Arial Unicode /
  Helvetica / DejaVu / PIL's default as fallbacks), libx264 crf 18, the audio packets copied unchanged. This FFmpeg has
  no `subtitles`/`drawtext` filter. The layout is computed for a 380 px wide picture and scaled (16 px text, 14 px side
  margins, 18 px from the bottom at 380 px; lines wrap at 380 − 2·14 px), so the text reads the same on a phone; on the
  846 px draft that is 36 px text. ~1.5 s for the 8 s draft. `{burn: false}` turns it off (the file stays, unused).
  State in `subtitles.json` `{version, burn, updated, source, words_sha, cues, files}`; `GET /jobs/{id}/subtitles` →
  `{burn, words, cues, source, up_to_date, finals: [{final, subtitled, has_final, exists, url}]}` (up_to_date false when
  the words changed since: the panel offers "Burn again · free").

## 7. Verification (2026-10-24, port 8778, `PUPPETEER_OFFLINE=1`)

`0be4cf2cadd945008a9c9131b6c75f12` = hard-link copy of `85e5…`; `5af8e90d1bf34849b7e768935da65cf2` = hard-link copy of
`3c54f295…` (Advanced + mesh with a draft `final-preview.mp4`). Details in `docs/TIMELINE-SPEC.md` §A4.
