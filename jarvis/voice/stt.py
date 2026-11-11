"""Speech to text: faster-whisper on this laptop, or Groq's hosted Whisper if STT=groq."""
import io
import re
import threading
import wave

import numpy as np
import requests

from ..core import config, lang

SR = 16000
GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
CLOUD = config.stt_cloud()
_http = requests.Session()
_whisper = [None]
_lock = threading.Lock()


def _names():
    words = [config.ASSISTANT, config.PET_NAME, config.GOD_NAME] + config.FULL_NAME.split()
    return ", ".join(w for w in dict.fromkeys(words) if w)


DEFAULT_HINTS = "Jarvis, Vibe, DSA, data structures and algorithms, LeetCode, mpv, Python, VS Code"
MIN_SECONDS = 0.4
MIN_LEVEL = 0.006
HEARD_WHEN_SILENT = {"you", "thank you", "thanks for watching", "thank you for watching", "thanks for listening",
                     "please subscribe", "like and subscribe", "see you next time", "see you in the next video"}
HEARD_PARTS = ("amara.org", "subtitles by", "subtitled by", "captions by", "transcribed by", "subtitles made by", "subscribe to my", "subscribe to the channel")
TAG = re.compile(r"^[\[\(\*♪#\s]*(?:music|applause|laughter|laughs|silence|noise|cheering|singing|blank audio|inaudible|"
                 r"background music|upbeat music|soft music|no audio|\.*)[\]\)\*♪#\s.]*$", re.I)


def hints():
    """Words the recogniser should spell right: STT_HINTS from .env, else the defaults."""
    return [w.strip() for w in config.get("STT_HINTS", DEFAULT_HINTS).split(",") if w.strip()]


def is_hallucination(text):
    """Phrases Whisper makes up for silence or background music."""
    t = text.strip()
    plain = re.sub(r"[^\w\s.]", "", t.lower()).replace(".", " ")
    plain = " ".join(plain.split())
    return (not plain or plain in HEARD_WHEN_SILENT or bool(TAG.match(t))
            or any(part in t.lower() for part in HEARD_PARTS))


def too_faint(audio):
    """True for clips too short or too quiet to be speech."""
    return len(audio) < int(MIN_SECONDS * SR) or float(np.percentile(np.abs(audio), 99)) < MIN_LEVEL


PROMPTS = {"hi": "{names}. नमस्ते, कैसे हैं आप?", "kn": "{names}. ನಮಸ್ಕಾರ, ಹೇಗಿದ್ದೀರಿ?"}


def _prompt():
    """A short prompt in the language being listened for, so the assistant's name and the user's name are spelled right."""
    lg = lang.listening()
    if lg in PROMPTS:
        return PROMPTS[lg].format(names=_names())
    words = "Names: " + _names() + ". Words: " + ", ".join(hints()) + "."
    if lg != "en":
        return words
    return words + " Commands: open YouTube Music, remind me in two minutes to stretch, take a screenshot, set the volume to forty percent."


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
            _whisper[0] = WhisperModel(config.get("STT_LOCAL_MODEL", "small"), device="cpu", compute_type="int8")
        return _whisper[0]


def warm():
    if not CLOUD:
        threading.Thread(target=_model, daemon=True).start()


def _local(audio, language=None):
    language = lang.listening() if language is None else language
    segments, info = _model().transcribe(
        audio, language=language or None, vad_filter=True, vad_parameters={"threshold": 0.4},
        initial_prompt=_prompt(), beam_size=1, condition_on_previous_text=False,
        no_speech_threshold=0.6, without_timestamps=True)
    text = " ".join(s.text.strip() for s in segments).strip()
    if not language and not lang.allowed(getattr(info, "language", "")):
        print(f"  (heard {info.language}, trying English instead)")
        return _local(audio, "en")
    return text


def _groq(audio, language=None):
    key = config.get("GROQ_API_KEY")
    if not key:
        return None
    language = lang.listening() if language is None else language
    try:
        data = {"model": config.get("STT_MODEL", "whisper-large-v3"), "temperature": "0",
                "response_format": "json" if language else "verbose_json", "prompt": _prompt()}
        if language:
            data["language"] = language
        r = _http.post(
            GROQ_URL, headers={"Authorization": "Bearer " + key},
            files={"file": ("command.wav", wav_bytes(audio), "audio/wav")}, data=data, timeout=15)
        if r.status_code >= 400:
            print(f"  (cloud speech unavailable: HTTP {r.status_code})")
            return None
        body = r.json()
        if not language and not lang.allowed(body.get("language")):
            print(f"  (heard {body.get('language')}, trying English instead)")
            return _groq(audio, "en")
        return str(body.get("text", "")).strip()
    except Exception as e:
        print(f"  (cloud speech unavailable: {type(e).__name__})")
        return None


def transcribe(audio):
    if too_faint(audio):
        return ""
    text = _transcribe(audio)
    if is_hallucination(text):
        if text.strip():
            print(f"  (ignored a made-up transcript: {text.strip()!r})")
        return ""
    return text


def _transcribe(audio):
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
