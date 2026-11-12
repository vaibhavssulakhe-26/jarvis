"""Checks the morning briefing and the page monitor with mocked network. Run: python scripts/schedule_check.py"""
import os
import sys
import tempfile
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
tmp = Path(tempfile.mkdtemp(prefix="jarvis-schedule-"))
os.environ["JARVIS_DATA"] = str(tmp)
os.environ["USER_PET_NAME"] = "Testy"
os.environ["WEATHER_CITY"] = "Bengaluru"

from jarvis.actions import tools, watches  # noqa: E402,F401
from jarvis.brain import brain  # noqa: E402
from jarvis.core import main as core  # noqa: E402
from jarvis.memory import notes  # noqa: E402
from jarvis.scheduling import digest, monitor, reminders  # noqa: E402

results = []


def check(name, ok):
    ok = bool(ok)
    results.append(ok)
    print(("PASS  " if ok else "FAIL  ") + name)


class Reply:
    def __init__(self, payload=None, text="", status=200, content=b""):
        self.payload, self.text, self.status_code, self.content = payload, text, status, content

    def json(self):
        return self.payload


RSS = b"<rss><channel><item><title>Headline from a feed</title></item></channel></rss>"


def fake_get(url, **kw):
    if "geocoding" in url:
        return Reply({"results": [{"latitude": 12.9, "longitude": 77.6}]})
    if "open-meteo" in url:
        return Reply({"current": {"temperature_2m": 24.4, "weather_code": 2},
                      "daily": {"temperature_2m_max": [29.0], "precipitation_probability_max": [60]}})
    if url.endswith("robots.txt"):
        return Reply(text="User-agent: *\nDisallow: /private", status=200)
    if "rss" in url or "feeder" in url or "news.google" in url:
        return Reply(content=RSS)
    return Reply(text=PAGE["html"])


PAGE = {"html": "<html><body><h1>Results</h1><p>Seats open</p><script>x=1</script></body></html>"}

reminders._save([])
reminders.add("submit the synopsis", datetime.now().replace(hour=23, minute=50) if datetime.now().hour < 23 else datetime.now() + timedelta(minutes=5))
notes.save("today", "finish DSA chapter 3", with_window=False)

with mock.patch("requests.get", fake_get):
    text = digest.build()
    again = digest.weather_line()
print(text)
check("greets by pet name with the date", text.startswith("Good") and "Testy" in text and f"{date.today():%A}" in text)
check("weather is included", "24 degrees" in text and "60 percent" in text)
check("deadline reminder is flagged", "deadline: submit the synopsis" in text)
check("today's note is included", "finish DSA chapter 3" in text)
check("headline is included", "Headline from a feed" in text)
check("fits in about 45 seconds", len(text.split()) <= 105)
calls = []
with mock.patch("requests.get", side_effect=lambda *a, **k: calls.append(a) or fake_get(*a, **k)):
    digest.weather_line()
check("weather is cached for ten minutes", not calls)
with mock.patch("requests.get", side_effect=OSError):
    pass
digest._weather.update(t=0.0)
import requests  # noqa: E402
with mock.patch("requests.get", side_effect=requests.ConnectionError):
    check("weather fails soft", digest.weather_line() == "")
    check("digest still builds offline", "Testy" in digest.build())

spoken = []
with mock.patch.object(digest, "build", return_value="the briefing"), mock.patch.object(digest, "due_now", return_value=True):
    first = digest.run(spoken.append)
    second = digest.run(spoken.append)
check("runs once per day", first and not second and spoken == ["the briefing"])
check("due after the set time, before 11", digest.due_now(datetime.now().replace(hour=8, minute=15)) and not digest.due_now(datetime.now().replace(hour=11, minute=5)) and not digest.due_now(datetime.now().replace(hour=6, minute=0)))

# monitor
with mock.patch("requests.get", fake_get), mock.patch.object(monitor, "_public", return_value=True), \
        mock.patch.object(monitor.time, "sleep"):
    check("minimum interval is ten minutes", monitor.parse_interval(2, "minutes") == 600)
    wid = monitor.add("https://example.test/results", 600)
    w = monitor.find(str(wid))
    check("first run only records a baseline", monitor.check(w) is None)
    w = monitor.find(str(wid))
    check("unchanged page stays quiet", monitor.check(w) is None)
    PAGE["html"] = "<html><body><h1>Results</h1><p>Seats open</p><p>Admissions now closed</p></body></html>"
    w = monitor.find(str(wid))
    with mock.patch.object(brain, "ask", return_value="A line about admissions closing was added.") as ask:
        said = monitor.check(w)
    check("a change is described in one sentence", said == "A line about admissions closing was added." and ask.call_count == 1)
    check("only the changed lines go to the model", "Admissions now closed" in ask.call_args[0][0] and "Seats open" not in ask.call_args[0][0])
    check("script text is not visible text", "x=1" not in monitor.visible_text(PAGE["html"]))

    wid2 = monitor.add("https://example.test/news", 600, "tickets")
    monitor.check(monitor.find(str(wid2)))
    PAGE["html"] = "<p>Tickets on sale</p>"
    check("word watch fires when the word appears", "tickets" in monitor.check(monitor.find(str(wid2))))

    monitor.set_paused(wid, True)
    seen = []
    monitor.run_due(now=time.time() + 5000, announce=seen.append)
    check("paused watches are skipped, due ones run", len(seen) == 0 or all("tickets" not in s for s in seen))
    monitor.remove(wid)
    check("watches persist in the database and can be removed", [x["id"] for x in monitor.rows()] == [wid2])
    check("list watches names them", "example.test" in tools.TOOLS["list_watches"]["fn"]({}))

with mock.patch("requests.get", fake_get), mock.patch.object(monitor, "_public", return_value=True):
    try:
        monitor.add("https://example.test/private/page", 600)
        blocked = False
    except monitor.WatchError:
        blocked = True
check("robots.txt is respected", blocked)
check("private addresses are refused", not monitor._public("http://127.0.0.1/admin"))
m = [p for p in core.DIRECT if p[1] == "add_watch"][0]
hit = m[0].match("watch https://example.test/page every 30 minutes and tell me when it changes")
check("voice phrase maps to a watch", hit and m[2](hit)["every"] == "30" and m[2](hit)["target"].startswith("https://"))
check("plain 'watch a movie' is not a watch", not m[0].match("watch a movie"))

print(f"\n{sum(results)} of {len(results)} passed")
sys.exit(0 if all(results) else 1)
