"""Changing the speaking voice by command."""
from ..voice import voices
from .tools import ToolError, tool


@tool("change_voice", 'args {"which": "next, male, female, british, or a voice name"} - switch the speaking voice; for "change your voice", "use a male voice", "use the British voice"')
def change_voice(args):
    which = str(args.get("which") or "next").strip().lower()
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
