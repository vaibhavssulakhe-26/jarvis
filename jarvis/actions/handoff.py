"""Send text, links and file paths to another device through an outbox folder.
Point HANDOFF_DIR at a folder your phone or laptop syncs (Syncthing, KDE Connect, a share); each device has its own file."""
import re
import shutil
from datetime import datetime
from pathlib import Path

from ..core import config
from ..core.errors import Ask
from .screen import looks_secret, read_clip
from .tools import ToolError, tool

MAX_FILE = 25 * 1024 * 1024
DEVICES = {"phone": "phone", "mobile": "phone", "laptop": "laptop", "computer": "laptop", "pc": "laptop"}
THIS = {"this", "it", "that", "the clipboard", "my clipboard", ""}


def outbox():
    return Path(config.get("HANDOFF_DIR") or config.DATA / "outbox").expanduser()


def send(device, what):
    """Append one line to the device's outbox file; a file path is copied next to it. Returns a short label."""
    box = outbox()
    box.mkdir(parents=True, exist_ok=True)
    item = what
    path = Path(what).expanduser() if re.match(r"^(~|/|\./)", what) else None
    if path is not None and path.is_file():
        if path.stat().st_size > MAX_FILE:
            raise ToolError("That file is too big to hand off.")
        files = box / "files"
        files.mkdir(exist_ok=True)
        shutil.copy2(path, files / path.name)
        item = f"file: files/{path.name}"
        label = "file"
    else:
        label = "link" if re.match(r"^https?://\S+$", what) else "text"
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] {item}"
    try:
        with open(box / f"{device}.txt", "a", encoding="utf-8") as f:
            f.write(line + "\n")
        written = (box / f"{device}.txt").read_text(encoding="utf-8").splitlines()[-1:]
    except OSError as e:
        raise ToolError(f"I could not write to the {device} outbox ({type(e).__name__}).")
    if written != [line]:
        raise ToolError(f"I wrote to the {device} outbox but could not read the line back, so I cannot say it was sent.")
    if path is not None and path.is_file() and (box / "files" / path.name).stat().st_size != path.stat().st_size:
        raise ToolError("The copy of the file in the outbox is not the same size, so I did not send it.")
    return label


@tool("send_to_device", 'args {"device": "phone or laptop", "what": "<text, link or file path, or empty for the clipboard>"} - hand text, a link or a file to the phone or laptop; for "send this to my phone"')
def send_to_device(args):
    said = str(args.get("device") or config.get("HANDOFF_DEFAULT")).strip().lower()
    if not said:
        raise Ask("Send it to your phone or your laptop?")
    device = DEVICES.get(said)
    if not device:
        raise ToolError("I can send to your phone or your laptop.")
    what = str(args.get("what") or "").strip()
    if what.lower() in THIS:
        what = read_clip()
    if not what:
        raise ToolError("There is nothing to send. Copy it first, or tell me what to send.")
    if looks_secret(what):
        raise ToolError("That looks like a key or a password, so I will not send it.")
    label = send(device, what)
    return f"Saved the {label} in the {device} outbox, {outbox()}. It reaches the {device} when that folder syncs."
