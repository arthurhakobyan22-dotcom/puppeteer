#!/usr/bin/env bash
# Local word-level transcription for the timeline's Words track (free, Apple Silicon): an isolated .venv-words on
# Python 3.12 with mlx-whisper, plus the Whisper model downloaded once into models/whisper/ (see docs/WORDS.md).
# WORDS_MODELS="whisper-large-v3-turbo whisper-small-mlx" downloads more models (mlx-community repo names).
set -euo pipefail
cd "$(dirname "$0")"
WORDS_PYTHON="${WORDS_PYTHON:-python3.12}"
WORDS_MODELS="${WORDS_MODELS:-whisper-large-v3-turbo}"
"$WORDS_PYTHON" -m venv .venv-words
.venv-words/bin/python -m pip install --upgrade pip >/dev/null
.venv-words/bin/python -m pip install mlx-whisper==0.4.3
mkdir -p models/whisper
for model in $WORDS_MODELS; do
  echo "Downloading mlx-community/$model into models/whisper/$model (once; about 1.6 GB for large-v3-turbo; .venv-words itself is about 1.2 GB)"
  .venv-words/bin/python -c "import sys;from huggingface_hub import snapshot_download;snapshot_download('mlx-community/'+sys.argv[1],local_dir='models/whisper/'+sys.argv[1])" "$model"
done
echo "Words track ready: .venv-words and models/whisper/ ($WORDS_MODELS)"
