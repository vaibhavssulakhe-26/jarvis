"""Downloads the extra Piper voices into models/voices. Run: python scripts/get_voices.py"""
import sys
from pathlib import Path

import requests

BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
VOICES = {"en_US-ryan-medium": "en/en_US/ryan/medium", "en_US-joe-medium": "en/en_US/joe/medium",
          "en_GB-alan-medium": "en/en_GB/alan/medium", "hi_IN-pratham-medium": "hi/hi_IN/pratham/medium"}
OUT = Path(__file__).resolve().parent.parent / "models" / "voices"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    failed = []
    for name, folder in VOICES.items():
        for ext in (".onnx", ".onnx.json"):
            target = OUT / (name + ext)
            if target.exists() and target.stat().st_size > 0:
                continue
            url = f"{BASE}{folder}/{name}{ext}"
            try:
                r = requests.get(url, stream=True, timeout=30)
                r.raise_for_status()
                with open(target.with_suffix(".part"), "wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
                target.with_suffix(".part").replace(target)
                print("downloaded", target.name)
            except requests.RequestException as e:
                target.with_suffix(".part").unlink(missing_ok=True)
                failed.append((url, target))
                print(f"could not download {target.name}: {type(e).__name__}")
    if failed:
        print("\nDownload these by hand and put each file in", OUT)
        for url, _ in failed:
            print("  " + url)
    print("\nNo Kannada voice is available yet: Jarvis shows Kannada text and copies it instead of speaking it.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
