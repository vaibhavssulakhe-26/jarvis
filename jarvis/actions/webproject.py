"""Web project helper for hackathons: scaffold a static site with the coder agent, check it for the basics of accessibility, preview it on a
local port and export a zip. Jarvis never deploys, pushes or publishes anything: export only prints the steps for you to follow.

Everything stays inside the code workspace (CODE_WORKSPACE). The preview server listens on 127.0.0.1 only and serves that one folder."""
import atexit
import http.server
import re
import threading
import zipfile
from pathlib import Path

from . import coder, events
from .tools import ToolError, _browser, tool

BRIEF = ("a static website for {topic}. Files: index.html, style.css and script.js, no build step, no frameworks, no external fonts, CDN or network calls. "
         "Mobile first responsive layout with flexbox or grid. Semantic HTML: lang on the html tag, a viewport meta tag, one h1 and headings in order, "
         "header, main and footer, a skip link, descriptive alt text on every image, buttons and links with real text, colours with good contrast "
         "(at least 4.5 to 1 for text) and a clearly visible keyboard focus style.")
FOCUS_CSS = "\n/* keyboard focus */\n:focus-visible {\n  outline: 3px solid currentColor;\n  outline-offset: 3px;\n}\n"
SKIP_CSS = ("\n/* skip link */\n.skip-link {\n  position: absolute;\n  left: 0.5rem;\n  top: -4rem;\n  padding: 0.5rem 1rem;\n  background: #000;\n  color: #fff;\n}\n"
            ".skip-link:focus {\n  top: 0.5rem;\n}\n")
SKIP_LINK = '<a class="skip-link" href="#main">Skip to content</a>\n'
_server = {"httpd": None, "folder": None, "port": 0}


# ---------- finding the project ----------
def sites():
    """Static projects (a folder with index.html) in the workspace, newest first."""
    if not coder.WORKSPACE.is_dir():
        return []
    found = [d for d in coder.WORKSPACE.iterdir() if d.is_dir() and not d.name.startswith(".") and (d / "index.html").is_file()]
    return sorted(found, key=lambda d: d.stat().st_mtime, reverse=True)


def current(name=""):
    """The folder the user means: a spoken name, the project just built, or the newest static site."""
    want = re.sub(r"[^a-z0-9]+", "", str(name).lower())
    if want:
        for d in sites():
            if want in re.sub(r"[^a-z0-9]+", "", d.name.lower()):
                return d
        raise ToolError(f"I do not have a site called {name[:30]} in the workspace.")
    last = coder.last.get("dir")
    if last and Path(last).is_dir() and (Path(last) / "index.html").is_file() and coder.inside(last):
        return Path(last)
    found = sites()
    if not found:
        raise ToolError("There is no website in the workspace yet. Say make a website for, and the topic.")
    return found[0]


# ---------- the accessibility pass ----------
def _hex(value):
    v = value.strip().lstrip("#")
    if len(v) == 3:
        v = "".join(c * 2 for c in v)
    try:
        return tuple(int(v[i:i + 2], 16) / 255 for i in (0, 2, 4)) if len(v) == 6 else None
    except ValueError:
        return None


def luminance(rgb):
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a, b):
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _declared(css, selectors, prop):
    """The value of `prop` in the first rule for one of the selectors, resolving one level of var(--x)."""
    custom = dict(re.findall(r"(--[\w-]+)\s*:\s*([^;}]+)", css))
    for sel in selectors:
        for body in re.findall(rf"(?:^|[}}\s,]){re.escape(sel)}\s*\{{([^}}]*)\}}", css):
            m = re.search(rf"(?:^|[;\s]){prop}\s*:\s*([^;]+)", body)
            if m:
                value = m.group(1).strip()
                var = re.match(r"var\(\s*(--[\w-]+)", value)
                return custom.get(var.group(1), "").strip() if var else value
    return ""


def css_contrast(css):
    """The text contrast ratio of the page body, or None when the colours are not plain hex values."""
    roots = ("body", ":root", "html")
    fg = _declared(css, roots, "color")
    bg = _declared(css, roots, "background-color") or _declared(css, roots, "background")
    fg, bg = (_hex(fg) if fg.startswith("#") else None), (_hex(bg) if bg.startswith("#") else None)
    return contrast(fg, bg) if fg and bg else None


def check_html(html, name):
    """(fixed html, fixes, issues) for one page."""
    fixes, issues = [], []
    if not re.search(r"<html[^>]*\blang=", html, re.I):
        html = re.sub(r"<html\b", '<html lang="en"', html, count=1, flags=re.I) if re.search(r"<html\b", html, re.I) else html
        fixes.append(f"{name}: added lang to the html tag")
    if not re.search(r'<meta[^>]+name=["\']viewport', html, re.I) and re.search(r"<head[^>]*>", html, re.I):
        html = re.sub(r"(<head[^>]*>)", r'\1\n  <meta name="viewport" content="width=device-width, initial-scale=1">', html, count=1, flags=re.I)
        fixes.append(f"{name}: added the viewport tag")
    if not re.search(r"<title>\s*\S", html, re.I):
        issues.append(f"{name}: no page title")
    levels = [int(x) for x in re.findall(r"<h([1-6])\b", html, re.I)]
    if levels.count(1) != 1:
        issues.append(f"{name}: needs exactly one h1, found {levels.count(1)}")
    if any(b - a > 1 for a, b in zip(levels, levels[1:])):
        issues.append(f"{name}: headings skip a level")

    def alt(m):
        tag = m.group(0)
        if re.search(r"\balt=", tag, re.I):
            return tag
        src = re.search(r'src=["\']([^"\']+)', tag)
        words = re.sub(r"[-_]+", " ", Path(src.group(1)).stem).strip() if src else ""
        fixes.append(f"{name}: added alt text to an image ({words or 'decorative'}), please improve it")
        return tag[:-1].rstrip("/ ") + f' alt="{words}">'
    html = re.sub(r"<img\b[^>]*>", alt, html, flags=re.I)
    for tag, body in re.findall(r"<(a|button)\b[^>]*>(.*?)</\1>", html, re.I | re.S):
        if not re.sub(r"<[^>]+>", "", body).strip() and "aria-label" not in body:
            issues.append(f"{name}: a {tag} has no text")
            break
    if re.search(r"<main\b", html, re.I) and "skip-link" not in html:
        if not re.search(r"<main\b[^>]*\bid=", html, re.I):
            html = re.sub(r"<main\b", '<main id="main"', html, count=1, flags=re.I)
        html = re.sub(r"(<body[^>]*>)", r"\1\n" + SKIP_LINK, html, count=1, flags=re.I)
        fixes.append(f"{name}: added a skip link")
    elif not re.search(r"<main\b", html, re.I):
        issues.append(f"{name}: no main landmark")
    return html, fixes, issues


def a11y_pass(folder):
    """Fix what can be fixed safely and list what needs a person. Returns (fixes, issues); writes only inside the project."""
    folder = Path(folder)
    fixes, issues = [], []
    css_text = ""
    for page in sorted(folder.glob("*.html")):
        html, f, i = check_html(page.read_text(errors="replace", encoding="utf-8"), page.name)
        if f:
            coder.write_project_file(folder, page.name, html, backup=True)
        fixes += f
        issues += i
    for sheet in sorted(folder.glob("*.css")):
        css = sheet.read_text(errors="replace", encoding="utf-8")
        css_text += css
        add = ""
        if not re.search(r":focus(?:-visible)?\s*\{", css):
            add += FOCUS_CSS
            fixes.append(f"{sheet.name}: added a visible keyboard focus style")
        elif re.search(r"outline\s*:\s*(?:none|0)\b", css) and ":focus-visible" not in css:
            add += FOCUS_CSS
            fixes.append(f"{sheet.name}: restored a visible keyboard focus style")
        if "skip-link" in "".join(p.read_text(errors="replace", encoding="utf-8") for p in folder.glob("*.html")) and ".skip-link" not in css:
            add += SKIP_CSS
        if add:
            coder.write_project_file(folder, sheet.name, css + add, backup=True)
    if not css_text:
        issues.append("no stylesheet found")
    elif not re.search(r"@media|grid|flex-wrap|clamp\(|min\(|max-width", css_text):
        issues.append("style.css: nothing makes the layout responsive (no media query, grid, wrap or max-width)")
    ratio = css_contrast(css_text)
    if ratio is not None and ratio < 4.5:
        issues.append(f"style.css: body text contrast is {ratio:.1f} to 1, below the 4.5 to 1 minimum")
    return fixes, issues


def _report(fixes, issues):
    line = f"Accessibility pass: fixed {len(fixes)}, {len(issues)} to check."
    text = "\n".join(["Accessibility pass"] + [f"fixed: {f}" for f in fixes] + [f"check: {i}" for i in issues])
    events.emit("build", text)
    print(text)
    return line


# ---------- tools ----------
@tool("make_website", 'args {"topic": "<what the site is about>"} - scaffold a responsive static website (HTML, CSS, JS, no build step) with the coder agent and run an accessibility pass; for "make a website for a plant shop"')
def make_website(args):
    topic = " ".join(str(args.get("topic") or "").split())[:120]
    if not topic:
        raise ToolError("What is the website for?")
    line = coder.build_project({"request": BRIEF.format(topic=topic)})
    folder = coder.last.get("dir")
    if not folder or not (Path(folder) / "index.html").is_file():
        return line
    fixes, issues = a11y_pass(folder)
    return f"{line} {_report(fixes, issues)} Say preview it to see it."


def _handler(folder):
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(folder), **kw)

        def translate_path(self, path):
            parts = [p for p in path.split("?")[0].split("/") if p]
            if any(p.startswith(".") or p.endswith(".bak") for p in parts):
                return str(Path(folder) / "__blocked__")
            return super().translate_path(path)

        def log_message(self, *a):
            pass
    return Quiet


def stop_server():
    httpd = _server["httpd"]
    _server.update(httpd=None, folder=None, port=0)
    if httpd:
        httpd.shutdown()
        httpd.server_close()
    return httpd is not None


atexit.register(stop_server)


@tool("preview_site", 'args {"name": "<project name, empty for the latest>"} - serve the website folder on a free local port and open it in the browser; for "preview it"')
def preview_site(args):
    folder = current(args.get("name") or "")
    stop_server()
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _handler(folder))
    _server.update(httpd=httpd, folder=folder, port=httpd.server_address[1])
    threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True).start()
    url = f"http://127.0.0.1:{_server['port']}/"
    print(f"  preview: {url}")
    events.emit("build", f"Preview of {folder.name}: {url}")
    try:
        _browser(url)
    except ToolError:
        return f"The preview is running at {url} but I could not open a browser. Open it yourself, and say stop preview when you are done."
    return f"Previewing {folder.name} at {url}. Say stop preview when you are done."


@tool("stop_preview", 'args {} - stop the local website preview; for "stop preview"')
def stop_preview(args):
    return "Preview stopped." if stop_server() else "No preview is running."


EXPORT_STEPS = """Export ready: {zip}

GitHub Pages (you do this, I never publish anything):
  1. Create an empty repository on github.com.
  2. In the project folder run: git init, git add ., git commit -m "site", then the git remote add and git push lines GitHub shows you.
     Or unzip the export and use Add file, Upload files on the repository page.
  3. Repository Settings, Pages, Deploy from a branch, main, / (root). The site appears at https://<you>.github.io/<repository>/ in a minute.

Netlify (also yours to do):
  1. Open app.netlify.com/drop and drag the project folder onto the page.
  2. Or install the Netlify CLI and run netlify deploy --dir . from the project folder, then netlify deploy --prod when it looks right.
"""


@tool("export_site", 'args {"name": "<project name, empty for the latest>"} - zip the website folder and print the GitHub Pages and Netlify steps; for "export it"')
def export_site(args):
    folder = current(args.get("name") or "")
    target = coder.WORKSPACE / f"{folder.name}.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(folder.rglob("*")):
            rel = p.relative_to(folder)
            if p.is_file() and not any(part.startswith(".") or part == "__pycache__" for part in rel.parts) and not p.name.endswith(".bak"):
                z.write(p, Path(folder.name) / rel)
    text = EXPORT_STEPS.format(zip=target)
    print(text)
    events.emit("build", text)
    return f"Exported {folder.name} to a zip in the workspace. The GitHub Pages and Netlify steps are on your screen. I do not deploy anything myself."
