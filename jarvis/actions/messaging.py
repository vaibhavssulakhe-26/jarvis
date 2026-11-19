"""WhatsApp messages and screenshots to saved contacts, sent through a virtual keyboard."""
import difflib
import re
import subprocess
import threading
import time
from urllib.parse import quote

from .. import platform
from ..core import config, jsonfile
from ..voice import voice
from .tools import ToolError, _browser, capture_screen, heard_recently, tool

CONTACTS = config.DATA / "contacts.json"
CONTACT_ALIASES = {"mom": {"mum", "mummy", "mother", "mama", "amma", "ma"},
                   "dad": {"daddy", "father", "papa", "appa", "pa"}}


def _contacts():
    return jsonfile.read(CONTACTS, {}, dict)


def _find_contact(spoken):
    name = re.sub(r"[^a-z ]", "", str(spoken).lower()).strip()
    book = _contacts()
    if name in book:
        return name, book[name]
    for key, alts in CONTACT_ALIASES.items():
        if name == key or name in alts:
            for cand in (key, *alts):
                if cand in book:
                    return cand, book[cand]
    close = difflib.get_close_matches(name, list(book), n=1, cutoff=0.8)
    if close:
        return close[0], book[close[0]]
    return None, None


def _prepare_message(args, check=True):
    name, entry = _find_contact(args.get("contact", ""))
    if not entry or not str(entry.get("phone", "")).isdigit():
        known = ", ".join(_contacts()) or "nobody yet"
        raise ToolError(f"I do not have a number saved for {args.get('contact') or 'that contact'}. "
                        f"Saved contacts: {known}.")
    text = str(args.get("text") or "").strip()[:500]
    if not re.search(r"\w", text):
        raise ToolError("What should the message say? I will not send an empty message or just punctuation.")
    if check and not heard_recently(text):
        raise ToolError(f"I did not hear what the message to {name} should say. What should I write?")
    return name, entry["phone"], text


def _describe_message(args):
    name, phone, text = _prepare_message(args)
    args["_checked"] = True
    return f'I will send {name} this exact message on WhatsApp: "{text}".'


def _trusted(args):
    try:
        trusted = {x.strip().lower() for x in config.get("JARVIS_TRUSTED_CONTACTS").split(",") if x.strip()}
        name, entry = _find_contact(args.get("contact", ""))
        return bool(name and name in trusted and len(str(args.get("text", ""))) <= 120
                    and heard_recently(args.get("text", "")))
    except Exception:
        return False


PASTE_SETTLE = 0.8


def _deliver(delay, name, text, paste):
    """Press the keys that send the message and return what to say. Text with letters outside ASCII is pasted from the clipboard, never typed key by key.
    Nothing here can see the chat, so the line never claims the message arrived."""
    time.sleep(delay)
    try:
        if paste:
            if not platform.clipboard_write(text):
                return f"I could not put the message on the clipboard, so I did not send anything to {name}."
            platform.send_paste()
            time.sleep(PASTE_SETTLE)
        platform.send_enter()
    except Exception as e:
        return f"I could not finish pressing the keys, {type(e).__name__}. I cannot tell whether anything reached {name}, so please check WhatsApp."
    return f"I pressed send for {name}, but I cannot verify that it went through. Please look at the chat."


def _send_later(delay, name, text, paste):
    threading.Thread(target=lambda: voice.say(_deliver(delay, name, text, paste)), daemon=True).start()


@tool("message_contact", 'args {"contact": "<name as said, for example mom>", "text": "<the message>"} - send a WhatsApp message to a saved contact; the program types it and presses send after the user confirms',
      risk="confirm", describe=_describe_message, skip=_trusted)
def message_contact(args):
    name, phone, text = _prepare_message(args, check=not args.get("_checked"))
    paste = not text.isascii()
    if paste and not platform.clipboard_write(text):
        raise ToolError("I need a clipboard tool to send a message in Hindi or Kannada, so I did not send it.")
    try:
        delay = max(5.0, min(40.0, float(config.get("JARVIS_SEND_DELAY", "13"))))
    except ValueError:
        delay = 13.0
    _browser(f"https://web.whatsapp.com/send?phone={phone}" + ("" if paste else f"&text={quote(text)}"))
    _send_later(delay, name, text, paste)
    return (f"Opening WhatsApp for {name}. I will {'paste' if paste else 'fill in'} this message and press send: {text}. "
            "I cannot check that it arrives, so I will tell you only what I pressed. Please keep your hands off the keyboard for a few seconds.")


def _copy_image(path):
    platform.clipboard_write_image(path)


def _paste_and_send(delay, name, path):
    def go():
        time.sleep(delay)
        try:
            platform.send_paste()
            time.sleep(3.0)
            platform.send_enter()
            voice.say(f"I pasted the screenshot and pressed send for {name}. Take a quick look to make sure it went through.")
        except Exception as e:
            voice.say(f"I could not send the picture, {type(e).__name__}. It is still on your clipboard, so you can paste it yourself.")
        finally:
            config.discard(path)
    threading.Thread(target=go, daemon=True).start()


def _describe_screenshot(args):
    name, phone, _ = _prepare_message({**args, "text": "screenshot"}, check=False)
    return f"I will take a screenshot of your screen and send it to {name} on WhatsApp."


@tool("send_screenshot", 'args {"contact": "<name as said, for example mom>"} - take a screenshot of the screen and send it as a picture to a saved contact on WhatsApp; the program pastes it into the chat and presses send after the user confirms',
      risk="confirm", describe=_describe_screenshot)
def send_screenshot(args):
    name, phone, _ = _prepare_message({**args, "text": "screenshot"}, check=False)
    path = config.runtime_file("whatsapp-shot.png")
    capture_screen(path)
    try:
        _copy_image(path)
    except (ToolError, subprocess.SubprocessError):
        config.discard(path)
        raise ToolError("I could not put the screenshot on the clipboard.")
    try:
        delay = max(5.0, min(40.0, float(config.get("JARVIS_SEND_DELAY", "13"))))
    except ValueError:
        delay = 13.0
    _browser(f"https://web.whatsapp.com/send?phone={phone}")
    _paste_and_send(delay, name, path)
    return f"Sending a screenshot to {name}. Please keep your hands off the keyboard for a few seconds."
