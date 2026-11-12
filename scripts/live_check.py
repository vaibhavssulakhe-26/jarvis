"""Phase 12 pieces that need no network or window: live answers, BRAIN=offline, browser launch flags, themes of voice and queue.
Run: python scripts/live_check.py"""
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

scratch = tempfile.mkdtemp()
os.environ["JARVIS_DATA"] = scratch
os.environ["XDG_RUNTIME_DIR"] = scratch
os.environ["GROQ_API_KEY"] = "gsk_not_a_real_key_for_the_check"
os.environ["OPENROUTER_API_KEY"] = "sk-or-not-a-real-key"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis.actions import browser, play  # noqa: E402
from jarvis.brain import brain  # noqa: E402
from jarvis.core import config  # noqa: E402
from jarvis.research import live  # noqa: E402
from jarvis.voice import speech, voices  # noqa: E402

bad = []


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (f"  {detail}" if detail and not ok else ""))
    if not ok:
        bad.append(name)


PAGE = '''
<a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.example-news.org%2Fa&amp;rut=1">Pune weather today</a>
<a class="result__snippet" href="x">Pune is <b>31</b> degrees and cloudy. Rain later.</a>
<a rel="nofollow" class="result__a" href="https://weather.example.net/b">Forecast</a>
<a class="result__snippet" href="x">Light rain expected this evening.</a>
'''
rows = live.parse_results(PAGE)
check("result links are unwrapped", rows and rows[0]["url"] == "https://www.example-news.org/a" and rows[1]["url"] == "https://weather.example.net/b", rows)
check("snippets lose their markup", rows[0]["snippet"].startswith("Pune is 31 degrees"), rows[0]["snippet"])

for text, want in (("what's the weather in Pune", True), ("latest news on ISRO", True), ("bitcoin price", True),
                   ("open the weather site", False), ("remind me about the news", False), ("tell me a joke", False)):
    check(f"is_live({text!r}) is {want}", live.is_live(text) == want)

with mock.patch.object(live, "search", lambda q: rows), mock.patch.object(live, "page_text", lambda u: ""), \
        mock.patch.object(brain, "ask", lambda *a, **k: "It is 31 degrees and cloudy in Pune. Extra sentence."):
    out = live.live_answer({"query": "weather in Pune"})
check("the live answer is one sentence plus its sources", out.startswith("It is 31 degrees and cloudy in Pune.") and "Extra" not in out
      and "example-news.org" in out and "weather.example.net" in out, out)
with mock.patch.object(live, "search", lambda q: rows), mock.patch.object(live, "page_text", lambda u: ""), \
        mock.patch.object(brain, "ask", lambda *a, **k: ""):
    out = live.live_answer({"query": "weather in Pune"})
check("without a brain the snippets are used", "31 degrees" in out, out)
check("the answer is two spoken sentences at most", len(speech.sentences(speech.shorten(out))) <= 2)

# BRAIN=offline never touches a cloud provider
os.environ["BRAIN"] = "offline"
calls = []
with mock.patch.object(brain._http, "post", lambda *a, **k: calls.append(a) or (_ for _ in ()).throw(AssertionError("cloud call"))), \
        mock.patch.object(brain, "_try_ollama", lambda m, t, j: ("{\"action\": \"chat\"}", 200)), \
        mock.patch.object(brain, "PROVIDERS", [("groq", brain._try_groq), ("openrouter", brain._try_openrouter), ("ollama", brain._try_ollama)]):
    text, who = brain.route([{"role": "user", "content": "hi"}])
check("offline mode answers from ollama only", who == "ollama" and not calls, (who, calls))
check("offline mode is reported", config.brain_mode() == "offline" and config.offline())
os.environ["STT"] = "groq"
check("offline mode turns cloud speech recognition off", not config.stt_cloud())
os.environ["STT"] = "local"
with mock.patch.object(live.brain, "ask", lambda *a, **k: (_ for _ in ()).throw(AssertionError("brain used"))):
    try:
        live.live_answer({"query": "weather in Pune"})
        check("live answers refuse politely when offline", False)
    except Exception as e:
        check("live answers refuse politely when offline", "offline" in str(e).lower(), str(e))
os.environ["BRAIN"] = "hybrid"
check("hybrid is the default mode", config.brain_mode() == "hybrid")

# browser: sandbox stays on unless root, blank pages never stay
src = Path(browser.__file__).read_text()
check("the browser launch never passes --no-sandbox", "--no-sandbox" not in src)
check("the launch asks for the sandbox unless root", "chromium_sandbox=not _is_root()" in src)


class FakePage:
    def __init__(self, url="about:blank"):
        self.url, self.closed, self.context = url, False, mock.Mock()
        self.loaded = []

    def goto(self, url, **kw):
        self.loaded.append(("goto", kw.get("wait_until")))
        self.url = url

    def wait_for_load_state(self, state, timeout=0):
        self.loaded.append(("wait", state))

    def is_closed(self):
        return self.closed

    def close(self):
        self.closed = True


page, blank = FakePage(), FakePage()
page.context.pages = [page, blank]
browser.goto(page, "https://example.org/")
check("goto navigates and waits for load", page.url == "https://example.org/" and ("wait", "load") in page.loaded)
check("a leftover about:blank tab is closed", blank.closed and not page.closed)

# media queue
items = [{"id": f"a{i:010d}", "title": t, "channel": c, "duration": d, "views": v, "live": live_}
         for i, (t, c, d, v, live_) in enumerate([
             ("Binary search explained", "NeetCode", 900, 900000, False),
             ("24/7 lofi radio", "Lofi", 0, 50000, True),
             ("tiny clip", "x", 20, 10, False),
             ("Binary search full course", "freeCodeCamp", 3600, 2000000, False)])]
ranked = play.rank(items, "learning", "binary search tutorial")
check("only candidates that pass the ranking stay queued", [r["title"] for r in ranked] == ["Binary search full course", "Binary search explained", "24/7 lofi radio"],
      [r["title"] for r in ranked])
check("the best result is kept when none pass", [r["title"] for r in play.rank([items[2]], "learning")] == ["tiny clip"])
play._state.update(results=ranked, i=1, now=ranked[1])
with mock.patch.object(play.mpvctl, "active", lambda: True):
    item, idx = play.now()
check("now playing and the queue pointer share one state", item is ranked[1] and idx == 1)
with mock.patch.object(play.mpvctl, "active", lambda: False):
    check("nothing playing only when mpv is idle", play.now() is None)

# voice
check("length_scale defaults to about 0.92", abs(voices.length_scale() - 0.92) < 0.001, voices.length_scale())
os.environ["VOICE_SPEED"] = "1.15"
check("VOICE_SPEED shortens the phoneme length", voices.length_scale() < 0.82, voices.length_scale())
os.environ.pop("VOICE_SPEED")
check("quality ranks high above medium", voices.quality("en_US-x-high") > voices.quality("en_US-x-medium") > voices.quality("en_US-x-low"))
check("spoken replies keep at most two sentences", speech.shorten("One. Two. Three.") == "One. Two.")
sys.exit(1 if bad else 0)
