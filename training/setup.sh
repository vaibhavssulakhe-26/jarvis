#!/usr/bin/env bash
# Prepares everything needed to train the Jarvis wake word model, then trains it.
# Run from anywhere: ./training/setup.sh [prepare|train]
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK="$HERE/work"
VENV="$HERE/.venv"
HF="https://huggingface.co/datasets/davidscripka/openwakeword_features/resolve/main"
GEN="$WORK/piper-sample-generator"

prepare() {
    mkdir -p "$WORK"
    [ -d "$VENV" ] || uv venv --python 3.11 "$VENV"
    uv pip install --python "$VENV/bin/python" \
        torch torchaudio --index-url https://download.pytorch.org/whl/cpu
    uv pip install --python "$VENV/bin/python" \
        openwakeword onnxruntime numpy scipy scikit-learn pyyaml tqdm \
        torchinfo torchmetrics speechbrain audiomentations torch-audiomentations \
        mutagen pronouncing webrtcvad-wheels acoustics datasets soundfile \
        piper-phonemize

    [ -d "$GEN" ] || git clone https://github.com/rhasspy/piper-sample-generator "$GEN"
    [ -f "$GEN/models/en_US-libritts_r-medium.pt" ] || curl -L --create-dirs \
        -o "$GEN/models/en_US-libritts_r-medium.pt" \
        https://github.com/rhasspy/piper-sample-generator/releases/download/v2.0.0/en_US-libritts_r-medium.pt

    # Small validation set, and about 17 GB of precomputed negative features.
    [ -f "$WORK/validation_set_features.npy" ] || curl -L -C - -o "$WORK/validation_set_features.npy" \
        "$HF/validation_set_features.npy"
    [ -f "$WORK/openwakeword_features_ACAV100M_2000_hrs_16bit.npy" ] || curl -L -C - \
        -o "$WORK/openwakeword_features_ACAV100M_2000_hrs_16bit.npy" \
        "$HF/openwakeword_features_ACAV100M_2000_hrs_16bit.npy"

    "$VENV/bin/python" - <<PY
from pathlib import Path
from datasets import load_dataset
import scipy.io.wavfile, numpy as np

out = Path("$WORK/mit_rirs")
if not out.exists():
    out.mkdir(parents=True)
    rows = load_dataset("davidscripka/MIT_environmental_impulse_responses", split="train", streaming=True)
    for i, row in enumerate(rows):
        audio = row["audio"]
        scipy.io.wavfile.write(out / f"{i}.wav", 16000, (np.array(audio["array"]) * 32767).astype(np.int16))
PY
    mkdir -p "$WORK/background"
    echo "Put 16 kHz mono wav files of ordinary background audio (music, speech, noise) in $WORK/background"
}

train() {
    cd "$HERE"
    [ -n "$(ls -A "$WORK/background" 2>/dev/null)" ] || { echo "$WORK/background is empty"; exit 1; }
    "$VENV/bin/python" -m openwakeword.train --training_config jarvis.yaml --generate_clips --augment_clips --train_model
    cp "$WORK/output/jarvis.onnx" "$HERE/../models/jarvis.onnx"
    echo "Installed models/jarvis.onnx. WAKE_WORD=jarvis in .env picks it up."
}

case "${1:-prepare}" in
    prepare) prepare ;;
    train) train ;;
    *) echo "usage: $0 [prepare|train]"; exit 2 ;;
esac
