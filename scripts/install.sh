#!/usr/bin/env bash
# Installs the system packages Jarvis wants (apt, dnf or Homebrew, whichever exists), then runs the setup wizard.
# Usage: scripts/install.sh [wizard options, for example --yes --voice en_US-ryan-medium --profile sister]
set -e
cd "$(dirname "$0")/.."

ask() { printf '%s [y/N] ' "$1"; read -r answer; [ "$answer" = "y" ] || [ "$answer" = "Y" ]; }

case "$(uname -s)" in
  Darwin)
    if ! command -v brew >/dev/null 2>&1; then
      echo "Homebrew is needed first: https://brew.sh"
      exit 1
    fi
    packages="python@3.11 mpv tesseract ollama portaudio git"
    if ask "Install with Homebrew: $packages?"; then brew install $packages; fi
    ;;
  Linux)
    if command -v dnf >/dev/null 2>&1; then
      packages="python3 git mpv tesseract wl-clipboard playerctl portaudio"
      if ask "Install with dnf (sudo): $packages?"; then sudo dnf install -y $packages; fi
    elif command -v apt-get >/dev/null 2>&1; then
      packages="python3 python3-venv python3-pip git mpv tesseract-ocr wl-clipboard xclip playerctl libportaudio2 libegl1"
      if ask "Install with apt (sudo): $packages?"; then sudo apt-get update && sudo apt-get install -y $packages; fi
    else
      echo "No dnf or apt-get found. Install python3, git, mpv, tesseract and a clipboard tool yourself."
    fi
    ;;
  *)
    echo "Unsupported system: $(uname -s)"
    exit 1
    ;;
esac

PY=""
for candidate in python3.12 python3.11 python3; do
  if command -v "$candidate" >/dev/null 2>&1; then PY="$candidate"; break; fi
done
[ -n "$PY" ] || { echo "Python 3 was not found."; exit 1; }
exec "$PY" -m jarvis.setup "$@"
