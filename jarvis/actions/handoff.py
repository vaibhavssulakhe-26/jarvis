"""Send text, links and file paths to another device through an outbox folder.
Point HANDOFF_DIR at a folder your phone or laptop syncs (Syncthing, KDE Connect, a share); each device has its own file."""
import re
import shutil
from datetime import datetime
from pathlib import Path

from ..core import config
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
    with open(box / f"{device}.txt", "a") as f:
        f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] {item}\n")
    return label


@tool("send_to_device", 'args {"device": "phone or laptop", "what": "<text, link or file path, or empty for the clipboard>"} - hand text, a link or a file to the phone or laptop; for "send this to my phone"')
def send_to_device(args):
    device = DEVICES.get(str(args.get("device") or "phone").strip().lower())
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
    return f"Sent the {label} to your {device}."
