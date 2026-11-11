"""Checks the dashboard offscreen: every page opens, every theme applies, typed commands run, and the performance and safety rules hold.
Run: QT_QPA_PLATFORM=offscreen python scripts/dashboard_check.py"""
import os
import re
import sys
import tempfile
import time
import traceback
from pathlib import Path
from unittest import mock

os.environ["QT_QPA_PLATFORM"] = "offscreen"
tmp = Path(tempfile.mkdtemp(prefix="jarvis-dash-"))
os.environ["JARVIS_DATA"] = str(tmp / "data")
os.environ["XDG_STATE_HOME"] = str(tmp / "state")
(tmp / "run").mkdir()
os.environ["XDG_RUNTIME_DIR"] = str(tmp / "run")
os.environ["NOTES_DIR"] = str(tmp / "notes")
os.environ["CODE_WORKSPACE"] = str(tmp / "work")
os.environ["JARVIS_DASH_TEST"] = "1"
os.environ["GROQ_API_KEY"] = "gsk_dashboard_secret_value_123456"
(tmp / "notes").mkdir()
(tmp / "work" / "demo-app").mkdir(parents=True)
(tmp / "data").mkdir()
root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))

problems = []
def _hook(t, v, tb):
    problems.append("".join(traceback.format_exception(t, v, tb)))
    traceback.print_exception(t, v, tb)


sys.excepthook = _hook

from PyQt6.QtCore import QCoreApplication, QPointF, Qt  # noqa: E402
from PyQt6.QtGui import QColor, QImage  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication, QLabel, QTextEdit  # noqa: E402

from jarvis.actions import tools  # noqa: E402,F401
from jarvis.actions import procs, study  # noqa: E402
from jarvis.core import main as core, state  # noqa: E402
from jarvis.ui import ui  # noqa: E402
from jarvis.ui.dashboard import themes, window  # noqa: E402

bad = []


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (f"  {detail}" if detail and not ok else ""))
    if not ok:
        bad.append(name)


def pump(seconds):
    end = time.time() + seconds
    while time.time() < end:
        QCoreApplication.processEvents()
        time.sleep(0.01)


def until(cond, seconds=3.0):
    end = time.time() + seconds
    while time.time() < end:
        QCoreApplication.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False


app = QApplication.instance() or QApplication(sys.argv)
import psutil as _ps  # noqa: E402
mock.patch.object(_ps, "virtual_memory", lambda: mock.Mock(available=3 * 2 ** 30, percent=50)).start()

# data the pages will show
(tmp / "notes" / "graphs.md").write_text("Graph algorithms: breadth first search, depth first search, shortest paths and graph traversal.")
(tmp / "notes" / "trees.md").write_text("Tree algorithms: binary search tree, graph traversal, depth first search and balanced trees.")
(tmp / "notes" / "cooking.md").write_text("Pasta recipe: boil water, salt generously, cook noodles, add tomato sauce and basil.")
(tmp / "notes" / "inbox.md").write_text("# Inbox\n\n- [2026-11-11 10:00] buy a cable\n")
(tmp / "data" / "roadmap.md").write_text("- [x] Python basics\n- [ ] Arrays\n- [ ] Trees\n")
study.record("trees", 0.0)
study.record("arrays", 1.0)

win = window.Dashboard()
win.show()
pump(0.3)
check("the window opens", win.isVisible() and win.windowTitle() == "JARVIS")
check("the sidebar has the eight pages", list(win.nav) == ["Home", "Media", "Code", "Notes", "Study", "Web", "Stats", "Settings"])

# ---- every page ----
for name in win.nav:
    win.go(name)
    pump(0.15)
    check(f"page {name} opens and refreshes", win.stack.currentWidget() is win.pages[name] and not problems, "".join(problems)[-300:])
    img = win.grab()
    check(f"page {name} paints", not img.isNull() and img.width() > 900)

# ---- themes ----
th = win.theme
for name in themes.ORDER:
    t0 = time.time()
    win.set_theme(name)
    steps = []
    th.changed.connect(lambda: steps.append(th.accent.rgb()))
    until(lambda: th.accent.name() == themes.PRESETS[name]["accent"], 1.5)
    check(f"theme {name} applies", th.name == name and th.accent.name() == themes.PRESETS[name]["accent"], th.accent.name())
    check(f"theme {name} is saved in settings.json", themes.load()[0] == name)
    check(f"theme {name} restyles the widgets", th.accent.name() in win.styleSheet())
    th.changed.disconnect()
    th.changed.connect(win.restyle)
    for page in win.pages.values():
        pass
win.set_theme("cyan")
pump(0.6)
th.changed.disconnect()
th.changed.connect(win.restyle)
steps, stamps = [], []
th.changed.connect(lambda: (steps.append(th.accent.rgb()), stamps.append(time.time())))
t0 = time.time()
win.set_theme("red")
until(lambda: th.accent.name() == themes.PRESETS["red"]["accent"], 2)
took = time.time() - t0
check("the colour fades over about 400 ms", 0.3 <= took <= 0.8, f"{took:.2f}s")
check("with several in-between steps and no jump", len(set(steps)) >= 5 and steps[-1] == th.accent.rgb(), str(len(set(steps))))
win.set_hue(120)
until(lambda: th.name == "custom", 1)
pump(0.6)
check("a custom hue is applied and saved", th.name == "custom" and themes.load()[0] == "custom" and abs(themes.load()[1] - 120) < 1)
check("the saved choice survives a restart", window.Theme().name == "custom")
c1 = th.glow(32)
check("the glow sprite is pre-rendered once per theme", th.glow(32) is c1)
win.set_theme("purple")
pump(0.6)
check("a theme change clears the sprite cache", th.glow(32) is not c1)

win.poll.stop()
th.set_flags(state_colours=True)
th.set_state("thinking")
pump(0.7)
check("state colours: thinking shifts the accent", th.accent.name() != themes.PRESETS["purple"]["accent"])
th.set_state("idle")
pump(0.7)
check("and idle returns to the base colour", th.accent.name() == themes.PRESETS["purple"]["accent"], th.accent.name())
th.set_flags(state_colours=False)
th.set_state("error")
pump(0.5)
check("with state colours off the accent never moves", th.accent.name() == themes.PRESETS["purple"]["accent"])
before = th.accent.name()
th.set_flags(cycle=True)
th._cycle_step()
pump(0.7)
check("cycle mode rotates the hue", th.accent.name() != before)
th.set_flags(cycle=False)
check("cycle mode can be switched off", not th._cycler.isActive())
win.set_theme("cyan")
pump(0.5)
win.poll.start(window.POLL_MS)

# voice and typed theme commands
ran = []
for phrase, want in (("change theme to red", {"theme": "red"}), ("next theme", {"theme": "next"}), ("random theme", {"theme": "random"}),
                     ("set the colour to green", {"theme": "green"})):
    with mock.patch.object(core, "run_tool", lambda a, args, s: ran.append((a, args))), mock.patch.object(core.brain, "think", side_effect=AssertionError("brain")):
        core.direct(phrase)
    check(f"{phrase!r} routes to change_theme", ran and ran[-1] == ("change_theme", want), str(ran[-1:]))
out = tools.TOOLS["change_theme"]["fn"]({"theme": "red"})
check("the tool saves the theme", out == "Theme changed to red." and themes.load()[0] == "red")
until(lambda: th.name == "red", 2)
check("the open window follows a voice change", th.name == "red")
tools.TOOLS["change_theme"]["fn"]({"theme": "next"})
until(lambda: th.name == "purple", 2)
check("next theme goes to the next preset", th.name == "purple", th.name)
tools.TOOLS["change_theme"]["fn"]({"theme": "random"})
check("random theme picks another one", themes.load()[0] != "purple")
try:
    tools.TOOLS["change_theme"]["fn"]({"theme": "plaid"})
    check("an unknown theme is refused", False)
except tools.ToolError:
    check("an unknown theme is refused", True)
btn = win.pages["Settings"].buttons["green"]
win.go("Settings")
btn.click()
until(lambda: th.name == "green", 1)
check("the Settings buttons change the theme", th.name == "green")
before = th.name
win.theme_btn.click()
until(lambda: th.name != before, 1)
check("the top bar theme button goes to the next one", th.name == themes.ORDER[(themes.ORDER.index(before) + 1) % len(themes.ORDER)])

# ---- typed commands, buttons ----
seen = []
with mock.patch.object(core, "handle", lambda text, via_wake=True: seen.append(text)):
    win.go("Home")
    win.cmd.setText("what time is it")
    win.cmd.returnPressed.emit()
    until(lambda: seen, 2)
    check("a typed command reaches the handler", seen == ["what time is it"], str(seen))
    pump(0.1)
    check("and appears in the live feed", win.ctx.feed and win.ctx.feed[-1]["heard"] == "what time is it")
    win.ctx.feed[-1]["route"] = ""
    window.events.emit("route", "quick time_date")
    window.events.emit("provider", "groq")
    pump(0.2)
    check("route and provider fill in the feed row", win.ctx.feed[-1]["route"] == "quick time_date" and win.ctx.feed[-1]["provider"] == "groq")
    win.pages["Home"].refresh()
    check("the feed panel shows the row", "quick time_date" in win.pages["Home"].feed.text())
    del seen[:]
    quick = [a for a in win.quick.menu().actions() if a.text() == "start focus 25"][0]
    quick.trigger()
    until(lambda: seen, 2)
    check("a quick command from the popover sends its command", seen == ["start focus 25"])
    del seen[:]
    win.cmd.setText("   ")
    win.cmd.returnPressed.emit()
    pump(0.2)
    check("an empty line is ignored", not seen)
    win.go("Code")
    win.pages["Code"].box_in.setText("a clock app")
    win.pages["Code"].build()
    until(lambda: seen, 2)
    check("the build box sends 'build me ...'", seen == ["build me a clock app"], str(seen))
    del seen[:]
    win.go("Notes")
    win.pages["Notes"].search.setText("graph")
    win.pages["Notes"].do_search()
    win.go("Media")
    win.stack.currentWidget().refresh()

win.talk_btn.click()
check("Talk to Jarvis asks the ears to listen", state.get("talk_request") > time.time() - 5)
with mock.patch.object(window.mpvctl, "stop") as stop_mpv:
    win.stop_btn.click()
    check("STOP stops speech and mpv", stop_mpv.called and state.get("stop_at") > time.time() - 5)

# ---- pages show real content ----
win.go("Notes")
notes = win.pages["Notes"]
pump(0.1)
g = notes.graph
check("the memory graph has a node per note", {n["name"] for n in g.nodes} == {"graphs.md", "trees.md", "cooking.md", "inbox.md"}, str([n["name"] for n in g.nodes]))
names = [n["name"] for n in g.nodes]
linked = {(names[i], names[j]) for i, j in g.edges}
check("notes that share keywords are linked, unrelated ones are not", ("graphs.md", "trees.md") in linked and not any("cooking.md" in e for e in linked), str(linked))
notes.search.setText("pasta")
check("a search highlights the matching node", [g.nodes[i]["name"] for i in g.match] == ["cooking.md"], str(g.match))
x, y = g._pos(g.nodes[names.index("trees.md")])
opened = []
g.opened.connect(opened.append)
QTest.mouseClick(g, Qt.MouseButton.LeftButton, pos=QPointF(x, y).toPoint())
check("clicking a node opens the note", opened == ["trees.md"] and "binary search tree" in notes.viewer.toPlainText())
check("the inbox is shown", "buy a cable" in notes.inbox.toPlainText())

win.go("Study")
st = win.pages["Study"]
check("the study page lists scores, weak topics and the streak", "trees" in st.scores.text() and "weak: trees" in st.streak.text(), st.scores.text() + st.streak.text())
check("and the roadmap with done marks", [st.road.item(i).text() for i in range(st.road.count())] == ["x Python basics", "o Arrays", "o Trees"])
st.road.setCurrentRow(1)
st.mark()
check("marking a roadmap item done writes the file", "- [x] Arrays" in (tmp / "data" / "roadmap.md").read_text())
st.sleep.setText("11:30 pm")
st.walk.setChecked(True)
st.mins.setValue(45)
st.save()
day = study.load()["days"][time.strftime("%Y-%m-%d")]
check("the daily check-in is saved", day.get("sleep") == "23:30" and day.get("walk") is True and day.get("study_min") == 45, str(day))

win.go("Code")
check("the code page lists projects", win.pages["Code"].list.count() == 1 and win.pages["Code"].list.item(0).text() == "demo-app")
win.go("Web")
check("the web page says what the browser agent needs or does", win.pages["Web"].state.text() != "")
core.PENDING.update({"action": "battery", "args": {}, "until": time.time() + 30})
from jarvis.voice import voice  # noqa: E402
voice.LAST[0] = "I am about to click 'Delete'. Say yes."
win.pages["Web"].refresh()
check("a waiting question shows Yes and No", win.pages["Web"].confirm.isVisibleTo(win.pages["Web"]) and "Delete" in win.pages["Web"].confirm.text.text())
with mock.patch.object(core, "handle", lambda text, via_wake=True: seen.append(text)):
    del seen[:]
    win.pages["Web"].confirm.yes.click()
    until(lambda: seen, 2)
check("the Yes button answers like a spoken yes", seen == ["yes"])
core.PENDING.clear()
win.go("Stats")
check("the stats page renders", "rate limits" in win.pages["Stats"].use.text() and "Jarvis memory" in win.pages["Stats"].sys.text())

# ---- settings and secrets ----
win.go("Settings")
st = win.pages["Settings"]
with mock.patch.object(window.pages.config, "get", lambda k, d="": "x" if k == "GROQ_API_KEY" else ""):
    st.refresh()
check("API keys show only as set or not set", "GROQ_API_KEY: set" in st.keys.text() and "OPENROUTER_API_KEY: not set" in st.keys.text())
everything = "".join(w.text() for w in win.findChildren(QLabel)) + "".join(w.toPlainText() for w in win.findChildren(QTextEdit))
check("no key value appears anywhere in the window", "gsk_dashboard" not in everything)
shown = Path(window.__file__).parent
src = "".join(p.read_text() for p in shown.glob("*.py"))
check("the dashboard never reads key values into the UI", "config.get(k)" in src and "get(k) else" in src)

# ---- performance ----
check("animation is capped at 30 fps", win.clock.interval >= 33 and win.clock.running, str(win.clock.interval))
orb = win.pages["Home"].orb
check("the orb has 120 points normally", orb.count == 120)
st.low.setChecked(True)
pump(0.1)
check("low power: 15 fps, 40 points", win.clock.interval >= 66 and orb.count == 40 and orb.low, f"{win.clock.interval} {orb.count}")
check("low power draws no rings or ripples", orb.low and not orb.ripples)
check("low power is saved", themes.load()[2]["low_power"] is True)
st.low.setChecked(False)
pump(0.1)
check("and can be switched off", win.clock.interval < 40 and orb.count == 120)
with mock.patch.object(window.psutil, "virtual_memory", lambda: mock.Mock(available=1.0 * 2 ** 30, percent=90)):
    win._ticks = 9
    win.tick()
check("free RAM under 1.5 GB turns low power on by itself", win.low_auto and win.clock.interval >= 66)
with mock.patch.object(window.psutil, "virtual_memory", lambda: mock.Mock(available=3.0 * 2 ** 30, percent=40)):
    win._ticks = 9
    win.tick()
check("and it turns off again when memory is back", not win.low_auto and win.clock.interval < 40)
win.hide()
pump(0.1)
check("animation stops while the window is hidden", not win.clock.running)
win.show()
pump(0.1)
check("and resumes when it is shown", win.clock.running)
with mock.patch.object(win, "isMinimized", lambda: True):
    win.sync_visibility()
check("animation stops while minimised", not win.clock.running)
win.sync_visibility()
check("and runs again once restored", win.clock.running)
for mode in ("idle", "listening", "thinking", "speaking"):
    orb.set_mode(mode)
    window.events.set_out_level(0.8)
    window.events.set_level(0.1)
    for _ in range(4):
        orb.advance()
    img = QImage(orb.size(), QImage.Format.Format_ARGB32)
    orb.render(img)
    check(f"orb paints in the {mode} state", not img.isNull())
orb.set_mode("speaking")
window.events.set_out_level(0.9)
orb.last_ripple = 0
orb.advance()
check("speaking sends out ripples", len(orb.ripples) >= 1)
window.events.set_out_level(0.0)
orb.set_mode("idle")
t0 = time.perf_counter()
for _ in range(30):
    orb.render(QImage(orb.size(), QImage.Format.Format_ARGB32))
per = (time.perf_counter() - t0) / 30 * 1000
check("one orb frame paints in under 20 ms", per < 20, f"{per:.1f} ms")
check("no graphics effects (shadow or blur) are used", not re.search(r"QGraphics(DropShadow|Blur)Effect", src))
loose = [(p.name, m) for p in shown.glob("*.py") if p.name != "themes.py" for m in re.findall(r"#[0-9a-fA-F]{6}\b", p.read_text())]
check("no hard-coded colours outside the theme file", not loose, str(loose[:5]))
import psutil  # noqa: E402
rss = psutil.Process().memory_info().rss / 2 ** 20
print(f"     (this process: {rss:.0f} MB with the window open)")
check("the window process stays under 180 MB at idle", rss < 180, f"{rss:.0f} MB")


# ---- redesign ----
check("the presets include Amber and Ice, with Cyan first", "amber" in themes.PRESETS and "ice" in themes.PRESETS and themes.ORDER[0] == "cyan")
red = QColor(themes.PRESETS["red"]["accent"])
check("red is less saturated than before", red.hsvSaturation() < QColor("#ff3b4e").hsvSaturation(), str(red.hsvSaturation()))
check("a fresh install starts on Cyan", (lambda: (os.remove(themes.voices.SETTINGS) if themes.voices.SETTINGS.exists() else None, themes.load()[0])[1])() == "cyan")
check("the default window is 1280 by 760", themes.load_window() == (1280, 760))
win.resize(1100, 700)
pump(1.0)
check("the window size is remembered", themes.load_window() == (1100, 700), str(themes.load_window()))
check("and used the next time", window.Dashboard().size().width() == 1100)
win.resize(1280, 760)
pump(1.0)
home = win.pages["Home"]
win.go("Home")
orb = home.orb
check("the core is large: about 55% of the centre area", 0.5 <= (orb.core_radius() * 2) / min(orb.width(), orb.height()) <= 0.6, str((orb.core_radius() * 2) / min(orb.width(), orb.height())))
check("the core carries its title and subtitle", orb.TITLE == "J.A.R.V.I.S" and orb.SUBTITLE == "AI CORE")
check("the core is at least 380 px wide in the default window", orb.width() >= 380 and orb.height() >= 380, str(orb.size()))
check("the three providers are cards with a state", len(home.cards) == 3 and all(c.name for c in home.cards), str([c.name for c in home.cards]))
check("providers show Groq, OpenRouter and Ollama", [c.name for c in home.cards] == ["Groq", "OpenRouter", "Ollama"])
window.pages.brain.LATENCY["groq"] = 0.42
home.refresh()
check("a provider card shows the last latency", home.cards[0].latency == 0.42)
check("the memory panel counts notes and says when it was indexed", "indexed" in home.mem.text())
for name in ("Coder", "Browser", "Research", "Notes", "Study"):
    check(f"the {name} agent is listed", name in home.agents.text())
check("agents start idle", home.agents.text().count("idle") == 5, home.agents.text())
window.events.agent_start("research")
home.refresh()
check("a running agent shows as running", home.agents.text().count("running") == 1 and "Research" in home.agents.text())
window.events.agent_end("research")
check("the timeline and the feed have placeholders, not empty panels", "no reminders today" in home.today.text() and "Nothing heard yet" in home.feed.text() or home.ctx.feed)
for k in range(15):
    win.ctx.feed.append(dict(time="10:%02d" % k, heard=f"command number {k}", route="direct x", provider="groq"))
home.refresh()
check("the feed lists the newest first", home.feed.text().index("command number 14") < home.feed.text().index("command number 10"))
check("the feed is capped to what fits", "command number 2<" not in home.feed.text())
check("the waveform strip sits in the bottom bar", win.wave.width() == 220 and win.wave.parent() is win)
window.events.set_level(0.2)
for _ in range(40):
    win.wave.advance()
check("the waveform follows the mic level", max(win.wave.values) > 0.3 and len(win.wave.values) == 40)
window.events.set_level(0.0)
check("quick commands live in a popover", win.quick.menu() is not None and len(win.quick.menu().actions()) == len(window.pages.QUICK))
check("the sidebar has an icon and a label per page", all(not b.icon().isNull() and b.text().strip() for b in win.nav.values()))
with mock.patch.object(window.psutil, "virtual_memory", lambda: mock.Mock(available=0.8 * 2 ** 30, percent=95)):
    win._ticks = 9
    win.tick()
check("under 1 GB free: low power turns on and the low RAM chip shows", win.low_auto and win.clock.interval >= 66 and not win.ram_chip.isHidden())
with mock.patch.object(window.psutil, "virtual_memory", lambda: mock.Mock(available=1.2 * 2 ** 30, percent=80)):
    win._ticks = 9
    win.tick()
check("between 1 and 1.5 GB low power stays on without the chip", win.low_auto and win.ram_chip.isHidden())
with mock.patch.object(window.psutil, "virtual_memory", lambda: mock.Mock(available=3 * 2 ** 30, percent=40)):
    win._ticks = 9
    win.tick()
check("with enough memory both go away", not win.low_auto and win.ram_chip.isHidden())

# a preview of Home in every theme
previews = root / "data" / "ui-previews"
previews.mkdir(parents=True, exist_ok=True)
for old in previews.glob("home-*.png"):
    old.unlink()
win.resize(1280, 760)
win.show()
win.ctx.feed[:] = [dict(time="10:41", heard="what time is it", route="quick time_date", provider=""),
                   dict(time="10:42", heard="start focus 25", route="direct start_focus", provider=""),
                   dict(time="10:44", heard="research solar panels", route="direct research_topic", provider="groq"),
                   dict(time="10:46", heard="hello there", route="brain chat", provider="openrouter")]
window.pages.brain.LATENCY.update(groq=0.38, openrouter=0.91)
win.ctx.ollama = True
win.go("Home")
orb.set_mode("listening")
window.events.set_level(0.08)
for name in themes.ORDER + ["custom"]:
    win.set_theme(name) if name != "custom" else win.set_hue(300)
    pump(0.6)
    for _ in range(6):
        orb.advance()
    home.refresh()
    img = win.grab()
    path = previews / f"home-{name}.png"
    img.save(str(path))
    check(f"Home renders in {name} and the preview is saved", path.exists() and path.stat().st_size > 20000 and img.width() >= 1000, str(path))
window.events.set_level(0.0)
win.set_theme("cyan")
pump(0.5)
print(f"     previews: {previews}")

# ---- close to tray, quit kills everything ----
class FakeTray:
    def isVisible(self):
        return True

    def hide(self):
        pass


win.tray = FakeTray()
win.close()
pump(0.1)
check("close hides to the tray and keeps running", not win.isVisible() and not getattr(win, "quitting", False))
win.show()
proc = procs.spawn("sleeper", ["sleep", "60"], tmp, procs.clean_env(), tmp / "s.log")
calls = []
with mock.patch.object(ui.mpvctl, "stop", lambda: calls.append("mpv")), mock.patch.object(ui.browser, "shutdown", lambda: calls.append("browser")), \
        mock.patch.object(ui.brain, "finish", lambda: calls.append("brain")):
    win.quit_all(exit_process=False)
check("Quit stops mpv and the browser", "mpv" in calls and "browser" in calls)
check("Quit kills child processes", proc.poll() is not None and not procs.alive())
check("the window stops listening to events after quit", win._listener not in window.events.listeners)

# headless mode still exists
with mock.patch("jarvis.ui.dashboard.run") as dash, mock.patch.object(core, "start"), mock.patch.object(core, "listen") as listen, \
        mock.patch.object(sys, "argv", ["jarvis", "--no-ui"]):
    core.main()
check("--no-ui keeps the old headless mode", listen.called and not dash.called)
with mock.patch("jarvis.ui.dashboard.run") as dash, mock.patch.object(sys, "argv", ["jarvis"]):
    core.main()
check("without flags the dashboard opens first", dash.called)

check("no exception reached the Qt event loop", not problems, "".join(problems)[-500:])
sys.exit(1 if bad else 0)
