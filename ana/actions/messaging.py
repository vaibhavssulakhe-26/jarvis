"""WhatsApp messages and screenshots to saved contacts, sent through a virtual keyboard."""
import difflib
import json
import re
import shutil
import subprocess
import threading
import time
from urllib.parse import quote

from ..core import config
from ..voice import voice
from .tools import ToolError, _browser, capture_screen, heard_recently, tool

CONTACTS = config.DATA / "contacts.json"
CONTACT_ALIASES = {"mom": {"mum", "mummy", "mother", "mama", "amma", "ma"},
                   "dad": {"daddy", "father", "papa", "appa", "pa"}}


def _contacts():
    try:
        data = json.loads(CONTACTS.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


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
    text = str(args.get("text", "")).strip()[:500]
    if not text:
        raise ToolError("What should the message say?")
    if check and not heard_recently(text):
        raise ToolError(f"I did not hear what the message to {name} should say. What should I write?")
    return name, entry["phone"], text


def _describe_message(args):
    name, phone, text = _prepare_message(args)
    args["_checked"] = True
    return f"I will send {name} this on WhatsApp: {text}."


def _trusted(args):
    try:
        trusted = {x.strip().lower() for x in config.get("ANA_TRUSTED_CONTACTS").split(",") if x.strip()}
        name, entry = _find_contact(args.get("contact", ""))
        return bool(name and name in trusted and len(str(args.get("text", ""))) <= 120
                    and heard_recently(args.get("text", "")))
    except Exception:
        return False


def _press(*steps):
    """Each step is a tuple of key names pressed together, followed by a pause in seconds."""
    from evdev import UInput, ecodes as e
    ui = UInput({e.EV_KEY: [e.KEY_ENTER, e.KEY_LEFTCTRL, e.KEY_V]}, name="ana-keyboard")
    try:
        time.sleep(0.5)
        for keys, pause in steps:
            codes = [getattr(e, "KEY_" + k) for k in keys]
            for code in codes:
                ui.write(e.EV_KEY, code, 1)
            ui.syn()
            time.sleep(0.05)
            for code in reversed(codes):
                ui.write(e.EV_KEY, code, 0)
            ui.syn()
            time.sleep(pause)
    finally:
        ui.close()


def _press_enter():
    _press((("ENTER",), 0.2))


def _send_later(delay, name):
    def go():
        time.sleep(delay)
        try:
            _press_enter()
            voice.say(f"I pressed send for {name}. Take a quick look to make sure it went through.")
        except Exception as e:
            voice.say(f"I could not press send, {type(e).__name__}. You can press Enter yourself.")
    threading.Thread(target=go, daemon=True).start()


@tool("message_contact", 'args {"contact": "<name as said, for example mom>", "text": "<the message>"} - send a WhatsApp message to a saved contact; the program types it and presses send after the user confirms',
      risk="confirm", describe=_describe_message, skip=_trusted)
def message_contact(args):
    name, phone, text = _prepare_message(args, check=not args.get("_checked"))
    try:
        delay = max(5.0, min(40.0, float(config.get("ANA_SEND_DELAY", "13"))))
    except ValueError:
        delay = 13.0
    _browser(f"https://web.whatsapp.com/send?phone={phone}&text={quote(text)}")
    _send_later(delay, name)
    return f"Sending to {name}: {text}. Please keep your hands off the keyboard for a few seconds."


def _copy_image(path):
    if shutil.which("wl-copy") is None:
        raise ToolError("I need wl-copy to send a picture.")
    with open(path, "rb") as f:
        subprocess.run(["wl-copy", "--type", "image/png"], stdin=f, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=10, check=True)


def _paste_and_send(delay, name, path):
    def go():
        time.sleep(delay)
        try:
            _press((("LEFTCTRL", "V"), 3.0), (("ENTER",), 0.2))
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
        delay = max(5.0, min(40.0, float(config.get("ANA_SEND_DELAY", "13"))))
    except ValueError:
        delay = 13.0
    _browser(f"https://web.whatsapp.com/send?phone={phone}")
    _paste_and_send(delay, name, path)
    return f"Sending a screenshot to {name}. Please keep your hands off the keyboard for a few seconds."
