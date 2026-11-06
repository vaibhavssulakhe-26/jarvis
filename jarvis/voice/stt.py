"""Speech to text: faster-whisper on this laptop, or Groq's hosted Whisper if JARVIS_STT=groq."""
import io
import threading
import wave

import numpy as np
import requests

from ..core import config

SR = 16000
GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
CLOUD = config.get("JARVIS_STT", "local").lower() == "groq"
_http = requests.Session()
_whisper = [None]
_lock = threading.Lock()


def _names():
    words = [config.ASSISTANT, config.get("USER_PET_NAME"), config.GOD_NAME] + config.FULL_NAME.split()
    return ", ".join(w for w in dict.fromkeys(words) if w)


PROMPT = ("Names: " + _names() + ". Commands: open YouTube Music, send mom hi on WhatsApp, remind me in two "
          "minutes to stretch, take a screenshot, set the volume to forty percent.")


def wav_bytes(audio):
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def save_last(audio):
    """Keep the last command so you can listen to exactly what Jarvis heard."""
    config.runtime_file("last.wav").write_bytes(wav_bytes(audio))


def _model():
    with _lock:
        if _whisper[0] is None:
            from faster_whisper import WhisperModel
            _whisper[0] = WhisperModel("base.en", device="cpu", compute_type="int8")
        return _whisper[0]


def warm():
    if not CLOUD:
        threading.Thread(target=_model, daemon=True).start()


def _local(audio):
    segments, _ = _model().transcribe(
        audio, language="en", vad_filter=True, vad_parameters={"threshold": 0.4},
        initial_prompt=PROMPT, beam_size=1, condition_on_previous_text=False,
        no_speech_threshold=0.6, without_timestamps=True)
    return " ".join(s.text.strip() for s in segments).strip()


def _groq(audio):
    key = config.get("GROQ_API_KEY")
    if not key:
        return None
    try:
        r = _http.post(
            GROQ_URL, headers={"Authorization": "Bearer " + key},
            files={"file": ("command.wav", wav_bytes(audio), "audio/wav")},
            data={"model": "whisper-large-v3-turbo", "language": "en", "temperature": "0",
                  "response_format": "json", "prompt": PROMPT},
            timeout=15)
        if r.status_code >= 400:
            print(f"  (cloud speech unavailable: HTTP {r.status_code})")
            return None
        return str(r.json().get("text", "")).strip()
    except Exception as e:
        print(f"  (cloud speech unavailable: {type(e).__name__})")
        return None


def transcribe(audio):
    level = float(np.percentile(np.abs(audio), 99))
    if 0.0005 < level < 0.3:
        audio = np.clip(audio * min(20.0, 0.4 / level), -1.0, 1.0)
    save_last(audio)
    if CLOUD:
        text = _groq(audio)
        if text is not None:
            return text
        print("  (falling back to local speech recognition)")
    return _local(audio)
