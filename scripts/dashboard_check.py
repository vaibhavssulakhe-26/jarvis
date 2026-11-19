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
check("the rail has the eleven pages", list(win.nav) == ["Home", "Chat", "Activity", "Media", "Code", "Notes", "Study", "Jobs", "Web", "Stats", "Settings"])

# ---- every page ----
for name in win.nav:
    win.go(name)
    pump(0.15)
    check(f"page {name} opens and refreshes", win.stack.currentWidget() is win.pages[name] and not problems, "".join(problems)[-300:])
    img = win.grab()
    check(f"page {name} paints", not img.isNull() and img.width() > 900)

check("Study is hidden from the sidebar unless STUDY=on", win.nav["Study"].isHidden())
os.environ["STUDY"] = "on"
win.show_study()
check("Study appears with STUDY=on", not win.nav["Study"].isHidden())
os.environ.pop("STUDY")
win.show_study()
check("the status pill shows the brain mode", "LOCAL FIRST" in win.pill.text(), win.pill.text())
os.environ["BRAIN"] = "offline"
win.refresh_page()
check("the status pill follows BRAIN=offline", "OFFLINE" in win.pill.text())
os.environ.pop("BRAIN")
win.go("Notes")
check("the Notes page shows the indexed file count", "indexed" in win.pages["Notes"].count.text(), win.pages["Notes"].count.text())

# ---- themes ----
import colorsys  # noqa: E402


def hue_of(hex_):
    r, g, b = (int(hex_[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return colorsys.rgb_to_hsv(r, g, b)[0] * 360


print("preset accents:")
for pname, spec in themes.PRESETS.items():
    print(f"  {pname:7} accent {spec['accent']} hue {hue_of(spec['accent']):5.1f}  panel {spec['panel']} hue {hue_of(spec['panel']):5.1f}")
pa = themes.PRESETS["purple"]
rgb = [int(pa["accent"][i:i + 2], 16) for i in (1, 3, 5)]
check("purple is a real purple, not blue-dominant", 275 <= hue_of(pa["accent"]) <= 295 and rgb[0] >= 0.7 * rgb[2] and rgb[0] > rgb[1])
check("purple panel tint follows the accent", abs(hue_of(pa["panel"]) - hue_of(pa["accent"])) < 15)
for pname, lo, hi in (("pink", 315, 340), ("red", 340, 365)):
    spec = themes.PRESETS[pname]
    hh = hue_of(spec["accent"]) + (360 if hue_of(spec["accent"]) < 10 else 0)
    check(f"{pname} accent sits in its hue range", lo <= hh <= hi, f"{hh:.0f}")
    pp = hue_of(spec["panel"]) + (360 if hue_of(spec["panel"]) < 10 else 0)
    check(f"{pname} panel tint follows the accent", abs(pp - hh) < 15, f"{pp:.0f} vs {hh:.0f}")
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
    with mock.patch.object(core, "run_tool", lambda a, args, s: ran.append((a, args))), mock.patch.object(core.brain, "tool_turn", side_effect=AssertionError("brain")):
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
    win.pages["Activity"].refresh()
    check("the routing panel shows the row", "quick time_date" in win.pages["Activity"].feed.text())
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

from jarvis.jobs import tracker as jobs_tracker  # noqa: E402
jobs_tracker.add("Acme", "Data Analyst", "DA", status="applied")
jobs_tracker.add("Globex", "Business Analyst", "BA")
check("Jobs is hidden from the sidebar unless JOBS=on", win.nav["Jobs"].isHidden())
os.environ["JOBS"] = "on"
win.show_study()
check("Jobs appears with JOBS=on", not win.nav["Jobs"].isHidden())
win.go("Jobs")
jp = win.pages["Jobs"]
jp.refresh()
check("the Jobs page lists the tracker", jp.table.rowCount() == 2 and "Acme" in [jp.table.item(r, 0).text() for r in range(2)])
check("and counts per status and resume type", "applied 1" in jp.summary.text() and "DA 1" in jp.summary.text() and "BA 1" in jp.summary.text(), jp.summary.text())
jp.filter.setCurrentText("applied")
check("the status filter narrows the table", jp.table.rowCount() == 1 and jp.table.item(0, 0).text() == "Acme")
jp.filter.setCurrentText("all")
os.environ.pop("JOBS")
win.show_study()
from jarvis import bench as bench_mod, doctor as doctor_mod  # noqa: E402
bench_mod.save({"date": "2026-11-12", "time": "10:00:00", "mode": "mock", "total": 30, "passed": 30, "avg_ms": 1.5, "p95_ms": 3.2, "brain_requests": 3,
                "avg_tokens": 305, "providers": {"local": 27, "mock": 3}, "results": []})
win.pages["Stats"].refresh()
check("the Stats page shows the latest benchmark", "p95 3.2 ms" in win.pages["Stats"].bench.text(), win.pages["Stats"].bench.text())

# ---- settings and secrets ----
win.go("Settings")
st = win.pages["Settings"]
fake_results = [doctor_mod.item("microphone", "pass", "fake mic, level 0.020"), doctor_mod.item("mpv", "warn", "not found", "sudo dnf install mpv"),
                doctor_mod.item("Groq key", "pass", "set")]
with mock.patch.object(doctor_mod, "run", lambda *a, **k: fake_results):
    st.doctor_btn.click()
    until(lambda: st._doctor["results"] is not None and not st._doctor["running"], 3)
    st.refresh()
check("the Doctor card lists each item with its fix", "mpv" in st.doctor_text.text() and "sudo dnf install mpv" in st.doctor_text.text()
      and "fake mic" in st.doctor_text.text(), st.doctor_text.text())
check("the Doctor button is usable again", st.doctor_btn.isEnabled())
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
check("the presets include Amber and Ice, with Ice first", "amber" in themes.PRESETS and "ice" in themes.PRESETS and themes.ORDER[0] == "ice")
red = QColor(themes.PRESETS["red"]["accent"])
check("red is less saturated than before", red.hsvSaturation() < QColor("#ff3b4e").hsvSaturation(), str(red.hsvSaturation()))
check("a fresh install starts on Ice", (lambda: (os.remove(themes.voices.SETTINGS) if themes.voices.SETTINGS.exists() else None, themes.load()[0])[1])() == "ice")
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
check("the core is large: about 55% of its area", 0.5 <= (orb.core_radius() * 2) / min(orb.area().width(), orb.area().height()) <= 0.6)
check("the core carries its title and subtitle", orb.TITLE == "J.A.R.V.I.S" and orb.SUBTITLE == "AI CORE")
check("the core is a background layer over the whole page", orb.width() >= home.width() - 2 and orb.height() >= home.height() - 2 and orb.core_radius() * 2 >= 220, str(orb.size()))
check("it sits between the side panels and the chat, not under them", home.left_holder.geometry().right() <= orb.area().left() + 1 and orb.area().right() <= home.chat_panel.geometry().left() + 1)
act = win.pages["Activity"]
check("the three providers are cards with a state", len(home.cards) == 3 and all(c.name for c in home.cards), str([c.name for c in home.cards]))
check("providers show Groq, OpenRouter and Ollama", [c.name for c in home.cards] == ["Groq", "OpenRouter", "Ollama"])
window.pages.brain.LATENCY["groq"] = 0.42
home.refresh()
check("a provider card shows the last latency", home.cards[0].latency == 0.42)
act.refresh()
check("the memory panel counts notes and says when it was indexed", "indexed" in act.mem.text())
for name in ("Coder", "Browser", "Research", "Notes", "Study"):
    check(f"the {name} agent is listed", name in home.agents.text())
check("agents start idle", home.agents.text().count("idle") == 5, home.agents.text())
window.events.agent_start("research")
home.refresh()
check("a running agent shows as running", home.agents.text().count("running") == 1 and "Research" in home.agents.text())
check("every agent name has a gap before its state", len(re.findall(r"(?:Coder|Browser|Research|Notes|Study)(?:&nbsp;){2,}<span", home.agents.text())) == 5, home.agents.text())
from jarvis.memory import threads as _threads  # noqa: E402
_before = len(_threads.current()["messages"])
window.events.emit("hear", "dropped (repeated syllables): da da da da")
window.events.emit("hear", "accepted (wake word): open the browser")
pump(0.2)
check("heard lines reach the Activity log with the reason", any("dropped (repeated syllables)" in l for l in win.ctx.activity) and any("accepted (wake word)" in l for l in win.ctx.activity), win.ctx.activity[-3:])
check("a dropped line is never a chat message or a routed command", len(_threads.current()["messages"]) == _before and not any("da da da" in f["heard"] for f in win.ctx.feed))
check("no activity label touches its text", all(re.match(r"^\d\d:\d\d \S+ +\S", l) for l in win.ctx.activity), win.ctx.activity[:3])
window.events.agent_end("research")
check("the timeline and the feed have placeholders, not empty panels", "no reminders today" in act.today.text() and ("Nothing heard yet" in act.feed.text() or home.ctx.feed))
for k in range(15):
    win.ctx.feed.append(dict(time="10:%02d" % k, heard=f"command number {k}", route="direct x", provider="groq"))
act.refresh()
check("the feed lists the newest first", act.feed.text().index("command number 14") < act.feed.text().index("command number 10"))
check("the feed is capped to what fits", "command number 2<" not in act.feed.text())
check("the waveform strip sits in the bottom bar", win.wave.width() == 220 and win.wave.isVisible())
window.events.set_level(0.2)
for _ in range(40):
    win.wave.advance()
check("the waveform follows the mic level", max(win.wave.values) > 0.3 and len(win.wave.values) == 40)
window.events.set_level(0.0)
check("quick commands live in a popover", win.quick.menu() is not None and len(win.quick.menu().actions()) == len(window.pages.QUICK))
check("the rail has an icon and a tooltip per page, and no text", all(not b.icon().isNull() and b.toolTip() and not b.text() for b in win.nav.values()) and win.nav["Home"].parent().width() == 56)
with mock.patch.object(window.psutil, "virtual_memory", lambda: mock.Mock(available=0.8 * 2 ** 30, percent=95)):
    win._ticks = 9
    win.tick()
check("under 1 GB free: low power turns on and the pill says LOW RAM", win.low_auto and win.clock.interval >= 66 and "LOW RAM" in win.pill.text(), win.pill.text())
with mock.patch.object(window.psutil, "virtual_memory", lambda: mock.Mock(available=1.2 * 2 ** 30, percent=80)):
    win._ticks = 9
    win.tick()
check("between 1 and 1.5 GB low power stays on without the warning", win.low_auto and "LOW RAM" not in win.pill.text())
with mock.patch.object(window.psutil, "virtual_memory", lambda: mock.Mock(available=3 * 2 ** 30, percent=40)):
    win._ticks = 9
    win.tick()
check("with enough memory both go away", not win.low_auto and "LOW RAM" not in win.pill.text())

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
win.set_theme("ice")
pump(0.5)
print(f"     previews: {previews}")


# ---- dashboard v3 ----
from jarvis.ui.dashboard import privacy  # noqa: E402
from jarvis.ui.dashboard.theme import Theme, contrast  # noqa: E402
from jarvis.memory import threads  # noqa: E402

th = win.theme
low = []
for name in themes.ORDER + ["custom"]:
    if name == "custom":
        th.set_hue(40, animate=False, save=False)
    else:
        th.set_name(name, animate=False)
    for label, fg, bg in th.contrast_pairs():
        if contrast(fg, bg) < 4.5:
            low.append((name, label, round(contrast(fg, bg), 2)))
check("all text reads at 4.5 to 1 or better in every theme", not low, str(low[:4]))
for hue in (0, 60, 120, 200, 280, 330):
    th.set_hue(hue, animate=False, save=False)
    low += [(hue, l) for l, f, b in th.contrast_pairs() if contrast(f, b) < 4.5]
check("and in custom hues", not low, str(low[:4]))
win.set_theme("ice")
pump(0.5)
check("Ice is the default theme and has two accents", themes.PRESETS["ice"]["secondary"] != themes.PRESETS["ice"]["accent"] and themes.DEFAULT == "ice")
check("Amber pairs amber with red", QColor(themes.PRESETS["amber"]["secondary"]).hue() < 15)
check("the background is charcoal in every preset", all(max(QColor(v["bg"]).getRgb()[:3]) <= 32 and max(QColor(v["bg"]).getRgb()[:3]) - min(QColor(v["bg"]).getRgb()[:3]) <= 12 for v in themes.PRESETS.values()))
bd = win.theme.backdrop(800, 600)
check("the grid and scan lines are one pre-rendered layer", win.theme.backdrop(800, 600) is bd and bd.width() == 800)
check("the grid layer is drawn by the window", "backdrop" in Path(window.__file__).read_text())

# rail, top bar, pill
rail = win.nav["Home"].parent()
check("the rail is thin and icon only", rail.width() == 56 and all(not b.text() for b in win.nav.values()))
check("the top bar shows date and time", re.search(r"\d{2}:\d{2}", win.clock_label.text()) and re.search(r"[A-Z]{3} \d{2} [A-Z]{3}", win.clock_label.text()), win.clock_label.text())
win.update_pill()
check("one status pill has mode, state and warnings", win.pill.text().count("\u00b7") >= 1 and win.theme_btn.text() == "THEME")
check("the pill detail is closed until clicked", win.pill_detail.isHidden())
check("the System, Brains and Agents panels are folded into the pill by default", win.pages["Home"].status_block.isHidden())
win.pill.click()
pump(0.1)
check("clicking the pill opens the details", not win.pill_detail.isHidden() and "Mode" in win.pill_text.text() and "Groq" in win.pill_text.text(), win.pill_text.text())
check("the pill opens them with the details", not win.pages["Home"].status_block.isHidden())
rows = [l for l in win.pill_text.text().splitlines() if l.strip()]
check("every status label is followed by spaces before its value", all(re.match(r"^\S.*?\S {2,}\S", l) for l in rows), rows)
check("the values line up in one column", len({len(l) - len(l.split("  ", 1)[1].lstrip()) for l in rows}) == 1, rows)
check("Offline model and OpenRouter have a gap too", any(re.match(r"^OpenRouter {2,}\S", l) for l in rows) and any(re.match(r"^Offline model {2,}\S", l) for l in rows), rows)
check("a provider is described by its last call, not as reachable", "reachable" not in win.pill_text.text() and "not called yet" in win.pill_text.text() or "last call" in win.pill_text.text(), win.pill_text.text())
win.pill.click()
check("and clicking again closes them", win.pill_detail.isHidden() and win.pages["Home"].status_block.isHidden())

# orb states are clearly different
frames = {}
orb = win.pages["Home"].orb
window.events.set_level(0.08)
window.events.set_out_level(0.8)
for mode in ("idle", "listening", "thinking", "speaking", "error"):
    orb.set_mode(mode)
    orb.angle = 1.0
    orb.last_ripple = 0
    orb.mic = 0.5
    orb.voice = 0.8
    orb.ripples = [time.monotonic() - 0.4] if mode == "speaking" else []
    img = QImage(orb.size(), QImage.Format.Format_ARGB32)
    img.fill(0)
    orb.render(img)
    frames[mode] = bytes(img.constBits().asarray(img.sizeInBytes()))
check("the five orb states each look different", len(set(frames.values())) == 5)
err = QImage(orb.size(), QImage.Format.Format_ARGB32)
err.fill(0)
orb.set_mode("error")
orb.render(err)
def reddish(img):
    return sum(1 for x in range(0, img.width(), 2) for y in range(0, img.height(), 2) if (c := QColor(img.pixel(x, y))).alpha() > 60 and c.red() > c.blue() + 40)


orb.set_mode("idle")
idle = QImage(orb.size(), QImage.Format.Format_ARGB32)
idle.fill(0)
orb.render(idle)
check("the error state is red and the others are not", reddish(err) > 60 and reddish(err) > 5 * (reddish(idle) + 1), f"{reddish(err)} vs {reddish(idle)}")
orb.set_mode("idle")
window.events.set_level(0.0)
window.events.set_out_level(0.0)
check("the animation runs at 30 fps and 15 in low power", win.clock.interval in (33, 34) or win.clock.low, str(win.clock.interval))

# chat cards, chips, cursor, copy
win.go("Home")
home = win.pages["Home"]
chat = home.chat
threads.add("user", "what is in my pictures folder, mail me@example.com or call +91 98765 43210")
pump(0.2)
events_mod = window.events
events_mod.emit("tool", "list folder: done")
events_mod.emit("tool", "play music: failed")
pump(0.1)
threads.add("assistant", "Pictures has 6 items.", tier="fast")
pump(0.3)
user_b = next(b for b in chat.bubbles if b.role == "user" and "pictures" in b.raw)
bot_b = next(b for b in chat.bubbles if b.role == "assistant" and "Pictures has" in b.raw)
check("user and assistant messages are separate cards", user_b.objectName() == "bubble_user" and bot_b.objectName() == "bubble_bot")
check("message text is large and sans", "font-size: 15px" in bot_b.body.styleSheet() and "mono" not in win.styleSheet().split("QWidget {")[1][:200].lower())
chips = [bot_b.chips.itemAt(i).widget().text() for i in range(bot_b.chips.count()) if bot_b.chips.itemAt(i).widget()]
check("tool chips sit under the reply", chips == ["list folder: done", "play music: failed"], str(chips))
check("a failed tool chip is styled as failed", [bot_b.chips.itemAt(i).widget().objectName() for i in range(2)] == ["chip_ok", "chip_bad"])
check("each card has a copy button", bot_b.copy.text() == "Copy")
events_mod.emit("stream", "Hello wor")
pump(0.4)
check("a streaming reply shows a cursor", chat.live is not None and "\u258d" in chat.live.body.toPlainText(), chat.live.body.toPlainText() if chat.live else "no live bubble")
events_mod.emit("stream_end", "")
pump(0.2)
check("and the cursor goes when it ends", chat.live is None or "\u258d" not in chat.live.body.toPlainText())
chat.live = None

# masking
check("phone numbers and emails are masked in the chat", "98765" not in user_b.body.toPlainText() and "me@example.com" not in user_b.body.toPlainText() and "[email]" in user_b.body.toPlainText(), user_b.body.toPlainText())
window.events.emit("sys", "routine ran for me@example.com")
pump(0.2)
win.go("Activity")
act = win.pages["Activity"]
act.refresh()
check("the activity log masks them by default", "me@example.com" not in act.log.toPlainText() and "[email]" in act.log.toPlainText())
win.pill.click()
win.reveal.setChecked(True)
pump(0.3)
act.refresh()
check("the reveal switch shows them", "me@example.com" in act.log.toPlainText() and privacy.state["reveal"] is True)
win.reveal.setChecked(False)
pump(0.3)
act.refresh()
check("and hides them again", privacy.state["reveal"] is False and "me@example.com" not in act.log.toPlainText())
win.pill.click()

# three separate records
window.events.emit("build", "wrote index.html for +91 98765 43210")
pump(0.2)
win.go("Activity")
act = win.pages["Activity"]
act.refresh()
win.go("Code")
code = win.pages["Code"]
code.refresh()
in_chat = " ".join(b.body.toPlainText() for b in chat.bubbles + win.pages["Chat"].view.bubbles)
check("system messages go to Activity only", "routine ran" in act.log.toPlainText() and "routine ran" not in code.log.toPlainText() and "routine ran" not in in_chat)
check("coder output goes to the Build log only", "wrote index.html" in code.log.toPlainText() and "wrote index.html" not in act.log.toPlainText() and "wrote index.html" not in in_chat)
check("conversation stays in Chat only", "Pictures has" in in_chat and "Pictures has" not in act.log.toPlainText() and "Pictures has" not in code.log.toPlainText())
check("masking applies to the activity and build logs", "[email]" in act.log.toPlainText() and "[number]" in code.log.toPlainText() and "98765" not in code.log.toPlainText())

# the drawer
win.go("Media")
win.dock_open = False
win.toggle_dock()
pump(0.1)
check("the chat drawer opens on other pages", not win.drawer.isHidden() and win.dock_btn.isChecked())
win.split.setSizes([700, 480])
pump(0.1)
check("and is resizable with the splitter", win.drawer.width() > 440, str(win.drawer.width()))
win.go("Home")
check("Home and Chat have their own chat, so the drawer steps aside", win.drawer.isHidden())
win.go("Media")
win.toggle_dock()
check("the drawer closes again", win.drawer.isHidden())

# the Code page has content on both sides
win.go("Code")
pump(0.2)
left = code.list.parent()
check("Code: projects and the build box are on one side", code.list.isVisible() and code.box_in.isVisible() and code.list.mapTo(win, code.list.rect().center()).x() < code.log.mapTo(win, code.log.rect().center()).x())
check("Code: the build log and the run controls are on the other", code.log.isVisible() and any(b.text() == "Run" and b.isVisible() for b in code.findChildren(type(win.theme_btn))))
check("Code: the log is never an empty box", len(code.log.toPlainText().strip()) > 0)

# previews of every page in the default theme
for old in previews.glob("page-*.png"):
    old.unlink()
win.set_theme("ice")
win.resize(1280, 760)
pump(0.5)
win.ctx.activity[:] = ["10:41 ROUTE   direct time_date", "10:41 TOOL    time date: done", "10:42 SYS     notes reindexed"]
for name in win.nav:
    if win.nav[name].isHidden():
        continue
    win.go(name)
    pump(0.25)
    img = win.grab()
    img.save(str(previews / f"page-{name.lower()}.png"))
check("a preview of every page is saved", len(list(previews.glob("page-*.png"))) >= 9)
rss = psutil.Process().memory_info().rss / 2 ** 20
check("the UI stays under 180 MB with every page built", rss < 180, f"{rss:.0f} MB")

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
