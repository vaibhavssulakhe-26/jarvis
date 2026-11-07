"""Script detection, language switch commands and voice choice per language, all mocked.
Run: python scripts/language_check.py"""
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

scratch = tempfile.mkdtemp(prefix="jarvis-lang-")
os.environ["JARVIS_DATA"] = scratch
os.environ["XDG_STATE_HOME"] = scratch
os.environ["XDG_RUNTIME_DIR"] = scratch
os.environ.pop("STT_LANGUAGE", None)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis.actions import tools  # noqa: E402,F401
from jarvis.brain import brain  # noqa: E402
from jarvis.core import lang, main  # noqa: E402
from jarvis.voice import stt, voice, voices  # noqa: E402

bad = []


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (f"  {detail}" if detail and not ok else ""))
    if not ok:
        bad.append(name)


check("devanagari is hindi", lang.script("नमस्ते जार्विस, आज मौसम कैसा है") == "hi")
check("kannada script is kannada", lang.script("ನಮಸ್ಕಾರ, ಇಂದು ಹವಾಮಾನ ಹೇಗಿದೆ") == "kn")
check("latin hinglish stays english", lang.script("aaj mausam kaisa hai") == "en")
check("plain english", lang.script("what time is it") == "en")

spoken = []
for phrase, mode, code in (("listen in Hindi", "listen", "hi"), ("listen in kannada", "listen", "kn"),
                           ("listen in english", "listen", "en"), ("listen in auto", "listen", ""),
                           ("reply in Hindi", "reply", "hi")):
    with mock.patch.object(main.voice, "say", lambda t: spoken.append(t)):
        main._handle(phrase)
    got = lang.listening() if mode == "listen" else lang._session["reply"] or ""
    check(f"{phrase!r} sets {mode} to {code or 'auto'}", got == code, got)
lang.set_reply("auto")
check("reply can go back to auto", lang._session["reply"] is None)

lang.set_listening("hi")
lang._session["listen"] = None
check("english is the default listen language", lang.listening() == "en", lang.listening())
lang.set_listening("hi")
check("hindi prompt is in hindi", any("ऀ" <= c <= "ॿ" for c in stt._prompt()))
check("hint is passed to the speech service", lang.listening() == "hi")
lang.set_listening("auto")
check("auto sends no language", lang.listening() == "" and stt._prompt().startswith("Names:"))
os.environ["STT_LANGUAGE"] = "kannada"
lang._session["listen"] = None
check("STT_LANGUAGE is the default hint", lang.listening() == "kn")
os.environ.pop("STT_LANGUAGE")
lang._session["listen"] = None

sent = {}
with mock.patch.object(stt, "_http") as http, mock.patch.dict(os.environ, {"GROQ_API_KEY": "k"}):
    http.post.return_value.status_code = 200
    http.post.return_value.json.return_value = {"text": "ok", "language": "english"}
    import numpy as np
    lang.set_listening("auto")
    stt._groq(np.zeros(1600, dtype=np.float32))
    sent = http.post.call_args.kwargs["data"]
    lang.set_listening("kn")
    stt._groq(np.zeros(1600, dtype=np.float32))
    kn_sent = http.post.call_args.kwargs["data"]
check("groq uses whisper-large-v3 by default", sent.get("model") == "whisper-large-v3", str(sent.get("model")))
check("groq auto-detects when no hint", "language" not in sent)
check("groq gets the hint when set", kn_sent.get("language") == "kn")
lang.set_listening("auto")

check("hindi reply hint", "Hindi" in lang.reply_hint("नमस्ते"))
check("english replies are limited to en, hi, kn", "English, Hindi or Kannada" in lang.reply_hint("hello"))
check("hint reaches a small chat request", "Answer in Kannada" in brain.chat_system("ನಮಸ್ಕಾರ"))
check("english chat prompt stays small", brain.estimate([{"content": brain.chat_system("hello")}]) < 300)

# regression: short English heard as Turkish must be retried in English and never answered in Turkish
turkish = mock.Mock(status_code=200)
turkish.json.return_value = {"text": "Tamam, bu iyi", "language": "turkish"}
english = mock.Mock(status_code=200)
english.json.return_value = {"text": "Yeah okay, this is good", "language": "english"}
with mock.patch.object(stt, "_http") as http, mock.patch.dict(os.environ, {"GROQ_API_KEY": "k"}):
    http.post.side_effect = [turkish, english]
    lang.set_listening("auto")
    heard = stt._groq(np.zeros(1600, dtype=np.float32))
    second = http.post.call_args_list[1].kwargs["data"]
check("turkish detection is re-transcribed in English", heard == "Yeah okay, this is good" and second.get("language") == "en", str(heard))
check("only English, Hindi and Kannada are accepted", lang.allowed("english") and lang.allowed("hindi") and lang.allowed("kannada")
      and not lang.allowed("turkish") and not lang.allowed("tr"))
lang.set_listening("en")

fake = {"en_US-ryan-medium": Path("ryan.onnx"), "hi_IN-pratham-medium": Path("hi.onnx"), "jarvis": Path("jarvis.onnx")}
with mock.patch.object(voices, "installed", lambda: fake):
    check("english text uses the chosen voice", voices.path_for("hello there") == voices.current_path())
    check("hindi text uses the hindi voice", voices.path_for("नमस्ते दोस्त") == Path("hi.onnx"))
    check("kannada has no voice", voices.for_language("kn") is None)
    check("kannada text falls back to the english voice path", voices.path_for("ನಮಸ್ಕಾರ") == voices.current_path())
    check("hindi voice is not offered as the english voice", "hi_IN-pratham-medium" not in voices.english())
    check("jarvis voice is listed", "jarvis" in voices.english() and voices.find("jarvis") == "jarvis")
    check("jarvis voice has a label", "Jarvis" in voices.label("jarvis"))
    with mock.patch.object(main.voice, "say", lambda t: spoken.append(t)):
        del spoken[:]
        main._handle("use the jarvis voice")
    check("'use the jarvis voice' works", voices.current_name() == "jarvis", str(spoken))
    voices.choose("en_US-ryan-medium")

with mock.patch.object(voices, "installed", lambda: {"en_US-ryan-medium": Path("r.onnx"), "en_GB-alan-medium": Path("a.onnx")}), \
        mock.patch.object(main.voice, "say", lambda t: spoken.append(t)):
    del spoken[:]
    main._handle("use the jarvis voice")
check("missing jarvis voice says where to put it and lists the voices",
      "models/voices/jarvis.onnx" in spoken[0] and "models/voices/jarvis.onnx.json" in spoken[0] and "Ryan" in spoken[0] and "Alan" in spoken[0], str(spoken))

said, clips, queued = [], [], []
with mock.patch.object(voices, "installed", lambda: {"en_US-ryan-medium": Path("r.onnx")}), \
        mock.patch("jarvis.actions.screen.write_clip", lambda t: clips.append(t) or True), \
        mock.patch.object(voice, "_queue") as q, mock.patch.object(voice.events, "emit"):
    q.put.side_effect = lambda item: queued.append(item[1])
    voice.say("ನಮಸ್ಕಾರ, ನಾನು ಜಾರ್ವಿಸ್")
check("kannada reply is copied to the clipboard", clips == ["ನಮಸ್ಕಾರ, ನಾನು ಜಾರ್ವಿಸ್"], str(clips))
check("kannada notice is spoken in english", any("cannot speak Kannada" in t for t in queued), str(queued))
check("kannada text itself is never sent to a voice", not any(lang.script(t) == "kn" for t in queued))
sys.exit(1 if bad else 0)
