"""Changing the speaking voice by command."""
from ..core import lang
from ..voice import voices
from .tools import ToolError, tool


def _names():
    return ", ".join((n.split("-")[1] if "-" in n else n).replace("_", " ").title() for n in voices.installed()) or "none"


@tool("list_voices", 'args {} - say which voices are installed; for "what voices do you have"')
def list_voices(args):
    return "My voices are " + _names() + "."


@tool("change_voice", 'args {"which": "next, male, female, british, or a voice name"} - switch the speaking voice; for "change your voice", "use a male voice", "use the British voice"')
def change_voice(args):
    which = str(args.get("which") or "next").strip().lower()
    if which == "jarvis" and "jarvis" not in voices.installed():
        raise ToolError("I do not have the Jarvis voice yet. Put it at models/voices/jarvis.onnx and models/voices/jarvis.onnx.json. "
                        "The voices I found are " + _names() + ".")
    name = voices.next_name() if which in ("next", "") else voices.find(which)
    if name is None:
        if not voices.installed():
            raise ToolError("I have no voices installed.")
        raise ToolError(f"I do not have a {which} voice.")
    voices.choose(name)
    return f"Okay, this is my new voice: {voices.label(name)}."


@tool("what_voice", "args {} - say which voice is in use; for \"what voice are you using\"")
def what_voice(args):
    name = voices.current_name()
    if name not in voices.installed():
        raise ToolError("I have no voice installed.")
    return f"I am using {voices.label(name)}."


@tool("set_language", 'args {"mode": "listen or reply", "language": "hindi, kannada, english or auto"} - set the language Jarvis listens for or answers in; for "listen in Hindi", "reply in Kannada"')
def set_language(args):
    mode = "reply" if str(args.get("mode")).lower() == "reply" else "listen"
    raw = str(args.get("language") or "auto").strip().lower()
    code = lang.code(raw)
    if raw not in ("auto", "automatic", "any language", "my language") and not code:
        raise ToolError("I can do Hindi, Kannada, English or auto.")
    name = lang.NAMES.get(code, "")
    if mode == "listen":
        lang.set_listening(code)
        return f"Okay, I will listen for {name}." if name else "Okay, I will work out the language myself."
    lang.set_reply(code)
    if code == "kn" and voices.for_language("kn") is None:
        return "Okay, I will answer in Kannada. I cannot speak it yet, so you will get the text on screen."
    return f"Okay, I will answer in {name}." if name else "Okay, I will answer in whatever language you use."
