"""Watches: check a page or a news topic every so often and say when it changes."""
import difflib
import hashlib
import html
import ipaddress
import re
import shutil
import socket
import subprocess
import threading
import time
import urllib.robotparser
import xml.etree.ElementTree as ET
from datetime import datetime
from urllib.parse import quote, urlparse

import requests

from ..core import config
from ..memory import store

MIN_INTERVAL = 600
DEFAULT_INTERVAL = 3600
HOST_GAP = 60
TIMEOUT = 10
MAX_TEXT = 200000
SNAPSHOT = 8000
AGENT = "JarvisWatch/1.0 (personal page monitor)"
NEWS = "https://news.google.com/rss/search?q="
_last_host = {}
_robots = {}
_lock = threading.Lock()


class WatchError(Exception):
    pass


def _public(url):
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        return False
    try:
        for info in socket.getaddrinfo(u.hostname, None, proto=socket.IPPROTO_TCP):
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return False
    except (OSError, ValueError):
        return False
    return True


def allowed(url):
    """True unless the site's robots.txt says no to this path. An unreachable robots.txt counts as yes."""
    u = urlparse(url)
    base = f"{u.scheme}://{u.netloc}"
    hit = _robots.get(base)
    if not hit or time.time() - hit[0] > 86400:
        parser = urllib.robotparser.RobotFileParser()
        try:
            r = requests.get(base + "/robots.txt", headers={"User-Agent": AGENT}, timeout=TIMEOUT)
            parser.parse(r.text.splitlines() if r.status_code == 200 else [])
        except requests.RequestException:
            parser.parse([])
        hit = _robots[base] = (time.time(), parser)
    return hit[1].can_fetch(AGENT, url)


def visible_text(raw):
    raw = re.sub(r"(?is)<(script|style|noscript|svg|head)[^>]*>.*?</\1>", " ", raw)
    raw = re.sub(r"(?s)<[^>]+>", "\n", raw)
    lines = [" ".join(ln.split()) for ln in html.unescape(raw).splitlines()]
    return "\n".join(ln for ln in lines if ln)[:MAX_TEXT]


def fetch(target, kind):
    """Visible text of a page, or the headlines for a topic."""
    url = target if kind == "url" else NEWS + quote(target)
    if not _public(url):
        raise WatchError("that address is not a public website")
    with _lock:
        host = urlparse(url).netloc
        wait = HOST_GAP - (time.time() - _last_host.get(host, 0))
        if wait > 0:
            time.sleep(min(wait, HOST_GAP))
        _last_host[host] = time.time()
    r = requests.get(url, headers={"User-Agent": AGENT}, timeout=TIMEOUT)
    if r.status_code >= 400:
        raise WatchError(f"the site answered {r.status_code}")
    if kind == "topic":
        try:
            titles = [t.text for t in ET.fromstring(r.content).findall(".//item/title") if t.text]
        except ET.ParseError:
            raise WatchError("the news feed was not readable")
        return "\n".join(titles[:15])
    return visible_text(r.text)


def parse_interval(amount, unit):
    seconds = float(amount or 0) * (3600 if str(unit).lower().startswith(("h", "hr")) else 60)
    return max(MIN_INTERVAL, int(seconds)) if seconds else DEFAULT_INTERVAL


def add(target, interval=DEFAULT_INTERVAL, condition=""):
    target = target.strip()
    kind = "url" if re.match(r"https?://", target) else "topic"
    if kind == "url" and not _public(target):
        raise WatchError("I only watch public websites")
    if kind == "url" and not allowed(target):
        raise WatchError("that site's robots file asks automated tools to stay away")
    interval = max(MIN_INTERVAL, int(interval))
    with store.db() as con:
        con.execute("INSERT INTO watches(target, kind, interval, condition, last_hash, last_summary, last_run, "
                    "paused, created) VALUES(?,?,?,?,?,?,?,0,?)",
                    (target, kind, interval, condition.strip().lower(), "", "", 0.0,
                     datetime.now().isoformat(timespec="seconds")))
        return con.execute("SELECT last_insert_rowid() AS i").fetchone()["i"]


def rows():
    with store.db() as con:
        return [dict(r) for r in con.execute("SELECT * FROM watches ORDER BY id")]


def find(ref):
    """A watch by number or by words from its target."""
    ref = str(ref).strip().lower()
    items = rows()
    if ref.isdigit():
        return next((w for w in items if w["id"] == int(ref)), None)
    return next((w for w in items if ref and ref in w["target"].lower()), None)


def set_paused(watch_id, paused):
    with store.db() as con:
        con.execute("UPDATE watches SET paused=? WHERE id=?", (1 if paused else 0, watch_id))


def remove(watch_id):
    with store.db() as con:
        con.execute("DELETE FROM watches WHERE id=?", (watch_id,))
        con.execute("DELETE FROM meta WHERE k=?", (f"watch_text:{watch_id}",))


def label(w):
    where = urlparse(w["target"]).netloc + urlparse(w["target"]).path if w["kind"] == "url" else w["target"]
    every = f"{w['interval'] // 3600} hours" if w["interval"] % 3600 == 0 else f"{w['interval'] // 60} minutes"
    cond = f", for the word {w['condition']}" if w["condition"] else ""
    return f"{w['id']}: {where[:50]} every {every}{cond}" + (" (paused)" if w["paused"] else "")


def _change_text(old, new):
    diff = [ln[1:].strip() for ln in difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm="", n=0)
            if ln[:1] in "+-" and ln[:3] not in ("+++", "---") and ln[1:].strip()]
    return "\n".join(diff)[:600]


def check(w):
    """Run one watch. Returns a sentence to announce, or None when nothing worth saying happened."""
    text = fetch(w["target"], w["kind"])
    digest = hashlib.sha256(text.encode()).hexdigest()
    old_text = store.get_meta(f"watch_text:{w['id']}", "")
    store.set_meta(f"watch_text:{w['id']}", text[:SNAPSHOT])
    with store.db() as con:
        con.execute("UPDATE watches SET last_hash=?, last_run=? WHERE id=?", (digest, time.time(), w["id"]))
    if not w["last_hash"]:
        return None
    word = w["condition"]
    if word:
        was, now = word in old_text.lower(), word in text[:SNAPSHOT].lower()
        if now and not was:
            return f"The word {word} just appeared on {urlparse(w['target']).netloc or w['target']}."
        return None
    if digest == w["last_hash"]:
        return None
    from ..brain import brain
    diff = _change_text(old_text, text[:SNAPSHOT])
    said = brain.ask("In one short sentence, say what changed on this page. Changed lines:\n" + diff, 60) if diff else ""
    said = " ".join(said.split()) or "The page changed."
    with store.db() as con:
        con.execute("UPDATE watches SET last_summary=? WHERE id=?", (said, w["id"]))
    return said


def alert(text):
    print(f"\n*** WATCH: {text} ***")
    if shutil.which("notify-send"):
        subprocess.run(["notify-send", "Jarvis watch", text], timeout=5)
    if config.flag("SPEAK_MONITOR_ALERTS"):
        from ..voice import voice
        voice.say(text)


def run_due(now=None, announce=alert):
    now = now or time.time()
    for w in rows():
        if w["paused"] or now - (w["last_run"] or 0) < w["interval"]:
            continue
        try:
            said = check(w)
        except (WatchError, requests.RequestException) as e:
            with store.db() as con:
                con.execute("UPDATE watches SET last_run=? WHERE id=?", (now, w["id"]))
            print(f"  (watch {w['id']} skipped: {e})")
            continue
        if said:
            announce(said)


def watch():
    """A slow thread: looks at the watch list every 30 seconds and runs the ones that are due."""
    def loop():
        time.sleep(45)
        while True:
            try:
                run_due()
            except Exception as e:
                print(f"  (watch check failed: {type(e).__name__})")
            time.sleep(30)
    threading.Thread(target=loop, daemon=True).start()
