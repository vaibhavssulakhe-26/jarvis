"""Web project helper: scaffold a static site with a fake brain, accessibility pass, serve it, fetch the page, stop, export.
Run: python scripts/webproject_check.py"""
import os
import re
import socket
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from unittest import mock

tmp = Path(tempfile.mkdtemp(prefix="jarvis-web-"))
os.environ["JARVIS_DATA"] = str(tmp / "data")
os.environ["XDG_RUNTIME_DIR"] = str(tmp)
os.environ["CODE_WORKSPACE"] = str(tmp / "work")
os.environ.pop("BRAIN", None)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests  # noqa: E402

from jarvis.actions import coder, tools, webproject  # noqa: E402
from jarvis.brain import brain  # noqa: E402
from jarvis.core import main as core  # noqa: E402
from jarvis.voice import voice  # noqa: E402

bad = []


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (f"  {detail}" if detail and not ok else ""))
    if not ok:
        bad.append(name)


def say(text):
    with voice.capture() as lines:
        core.direct(text)
    return " ".join(lines)


# a page with the usual mistakes: no lang, no viewport, no alt, a hidden focus ring, grey on white, a heading jump
PAGES = {
    "index.html": "<!DOCTYPE html>\n<html>\n<head>\n<title>Plant Shop</title>\n<link rel=\"stylesheet\" href=\"style.css\">\n</head>\n<body>\n"
                  "<header><h1>Plant Shop</h1></header>\n<main>\n<img src=\"fern-leaf.svg\">\n<h3>Our ferns</h3>\n<a href=\"#x\"><span></span></a>\n"
                  "</main>\n<script src=\"script.js\"></script>\n</body>\n</html>\n",
    "style.css": ":root { --fg: #999999; --bg: #ffffff; }\nbody { color: var(--fg); background: var(--bg); }\nbutton { outline: none; }\n",
    "script.js": "document.title = document.title;\n",
    "fern-leaf.svg": "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"10\" height=\"10\"></svg>\n",
}
plans = []


def fake_code(prompt, max_tokens=300, system=None):
    if system and system.startswith("You plan"):
        plans.append(prompt)
        return "name: plant shop\nindex.html: the page\nstyle.css: styles\nscript.js: behaviour\nfern-leaf.svg: picture"
    rel = re.search(r"Write the file (\S+):", prompt).group(1)
    return PAGES[rel]


launched = []
real_popen, real_run = subprocess.Popen, subprocess.run


def no_git(*a, **kw):
    cmd = a[0] if a else kw.get("args")
    if "git" in " ".join(map(str, cmd)) or "netlify" in " ".join(map(str, cmd)):
        raise AssertionError("must never run git or netlify")
    return real_run(*a, **kw) if real_run is not None else None


with mock.patch.object(brain, "code", fake_code), mock.patch.object(coder, "open_in_editor", lambda p: None), \
        mock.patch.object(subprocess, "run", no_git):
    reply = say("make a website for a plant shop")
folder = coder.WORKSPACE / "plant-shop"
check("the coder agent scaffolds the files", all((folder / f).is_file() for f in PAGES), reply)
check("the brief asks for the static, accessible shape", plans and "no build step" in plans[0] and "alt text" in plans[0] and "responsive" in plans[0].lower())
check("the reply reports the accessibility pass", "Accessibility pass" in reply and "to check" in reply, reply)

html = (folder / "index.html").read_text()
css = (folder / "style.css").read_text()
check("lang was added", '<html lang="en"' in html)
check("viewport was added", 'name="viewport"' in html)
check("alt text was added from the file name", 'alt="fern leaf"' in html, html)
check("a skip link and a main id were added", 'class="skip-link"' in html and '<main id="main"' in html)
check("a visible focus style was added", ":focus-visible" in css and ".skip-link" in css)
check("the originals were kept as .bak", (folder / "index.html.bak").is_file())
fixes, issues = webproject.a11y_pass(folder)
check("a second pass changes nothing", not fixes, str(fixes))
check("the heading jump is reported", any("skip a level" in i for i in issues), str(issues))
check("the empty link is reported", any("has no text" in i for i in issues), str(issues))
check("low contrast is reported with the ratio", any("contrast" in i and "2.8" in i for i in issues), str(issues))
check("contrast maths", round(webproject.contrast((0, 0, 0), (1, 1, 1)), 1) == 21.0)

# preview
opened = []
with mock.patch.object(webproject, "_browser", opened.append):
    out = say("preview it")
port = webproject._server["port"]
check("preview picks a free port and opens the browser", port > 1024 and opened == [f"http://127.0.0.1:{port}/"], out)
r = requests.get(f"http://127.0.0.1:{port}/", timeout=5)
check("the page is served", r.status_code == 200 and "Plant Shop" in r.text and 'lang="en"' in r.text)
check("the stylesheet is served", requests.get(f"http://127.0.0.1:{port}/style.css", timeout=5).status_code == 200)
check("dotfiles and backups are not served", requests.get(f"http://127.0.0.1:{port}/.jarvis.json", timeout=5).status_code == 404
      and requests.get(f"http://127.0.0.1:{port}/index.html.bak", timeout=5).status_code == 404)
check("nothing outside the folder is served", requests.get(f"http://127.0.0.1:{port}/../../etc/passwd", timeout=5).status_code in (301, 400, 404))
check("it listens on localhost only", webproject._server["httpd"].server_address[0] == "127.0.0.1")
with mock.patch.object(webproject, "_browser", opened.append):
    say("preview it")
check("a second preview replaces the first", webproject._server["port"] != 0 and len(opened) == 2)
old_port = port
port = webproject._server["port"]
if old_port != port:
    s = socket.socket()
    s.settimeout(1)
    check("the old server is gone", s.connect_ex(("127.0.0.1", old_port)) != 0)
    s.close()
check("stop preview", "stopped" in say("stop preview").lower() and webproject._server["httpd"] is None)
s = socket.socket()
s.settimeout(1)
check("the port is closed after stop", s.connect_ex(("127.0.0.1", port)) != 0)
s.close()
check("stop with nothing running", "No preview" in say("stop preview"))

# export
with mock.patch.object(subprocess, "run", no_git), mock.patch.object(subprocess, "Popen", side_effect=AssertionError("no processes")):
    out = say("export it")
zips = list(coder.WORKSPACE.glob("*.zip"))
check("export makes a zip in the workspace", len(zips) == 1 and "Exported" in out, out)
names = zipfile.ZipFile(zips[0]).namelist()
check("the zip holds the site, not metadata or backups", "plant-shop/index.html" in names and not any(".jarvis" in n or n.endswith(".bak") for n in names), str(names))
check("it says it deploys nothing", "do not deploy" in out)

# a named project that does not exist, and no site at all
with voice.capture() as lines:
    try:
        webproject.export_site({"name": "nonexistent"})
    except tools.ToolError as e:
        lines.append(str(e))
check("an unknown name is refused", "do not have a site" in " ".join(lines))
with mock.patch.object(webproject, "sites", lambda: []), mock.patch.dict(coder.last, {"dir": None}):
    check("preview with no site says what to do", "make a website" in say("preview it").lower())

# the phone cannot start it
from jarvis import telegram  # noqa: E402
check("blocked from the phone by default", telegram.GATE.blocked("make_website") != "" and telegram.GATE.blocked("preview_site") != "")

print("\nall passed" if not bad else f"\n{len(bad)} failed: {bad}")
sys.exit(1 if bad else 0)
