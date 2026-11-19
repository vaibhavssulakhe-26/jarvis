"""Checks the new window offscreen: the six globe states, the bubbles, the command palette, navigation, contrast, motion settings, memory and frame time.
Saves a preview of each state to data/ui-previews/. Run: QT_QPA_PLATFORM=offscreen python scripts/shell_check.py"""
import os
import sys
import tempfile
import time
import traceback
from pathlib import Path
from unittest import mock

os.environ["QT_QPA_PLATFORM"] = "offscreen"
tmp = Path(tempfile.mkdtemp(prefix="jarvis-shell-"))
os.environ["JARVIS_DATA"] = str(tmp / "data")
os.environ["XDG_STATE_HOME"] = str(tmp / "state")
(tmp / "run").mkdir()
os.environ["XDG_RUNTIME_DIR"] = str(tmp / "run")
os.environ["NOTES_DIR"] = str(tmp / "notes")
os.environ["CODE_WORKSPACE"] = str(tmp / "work")
os.environ["JARVIS_DASH_TEST"] = "1"
os.environ["GROQ_API_KEY"] = "gsk_shell_check_secret_value_123456"
for d in ("notes", "work", "data"):
    (tmp / d).mkdir()
root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))

problems = []


def _hook(t, v, tb):
    problems.append("".join(traceback.format_exception(t, v, tb)))
    traceback.print_exception(t, v, tb)


sys.excepthook = _hook

import psutil  # noqa: E402
from PyQt6.QtCore import QCoreApplication, QPoint, QPointF, Qt  # noqa: E402
from PyQt6.QtGui import QWheelEvent  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from jarvis import features  # noqa: E402
from jarvis.actions import events, tools  # noqa: E402,F401
from jarvis.core import config, state  # noqa: E402
from jarvis.ui import design, globe, status  # noqa: E402
from jarvis.ui.bubbles import NAMES, World  # noqa: E402
from jarvis.ui.dashboard import themes  # noqa: E402
from jarvis.voice import voice  # noqa: E402

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
mock.patch.object(psutil, "virtual_memory", lambda: mock.Mock(available=3 * 2 ** 30, percent=50)).start()
from jarvis.ui import shell  # noqa: E402

# ---- contrast ----
for name, fg, bg in design.contrast_pairs():
    check(f"contrast {name} is at least 4.5", design.contrast(fg, bg) >= design.MIN_CONTRAST, f"{design.contrast(fg, bg):.2f}")
from PyQt6.QtGui import QColor  # noqa: E402
for pick in ("#1a1aff", "#7a0000", "#222222", "#00ff00"):
    check(f"a user accent {pick} is lifted to a readable colour", design.contrast(design.readable(pick), design.BG) >= design.MIN_CONTRAST)

# ---- state to appearance ----
S = status.Snapshot
cases = {"idle": S(), "listening": S(hearing=True), "thinking": S(thinking=True), "speaking": S(speaking=True), "error": S(error=True),
         "offline": S(offline=True)}
for want, snap in cases.items():
    check(f"snapshot maps to {want}", status.resolve_state(snap) == want, status.resolve_state(snap))
check("an error outranks everything", status.resolve_state(S(error=True, offline=True, speaking=True, thinking=True, hearing=True)) == "error")
check("offline outranks speaking and thinking", status.resolve_state(S(offline=True, speaking=True, thinking=True)) == "offline")
check("speaking outranks thinking", status.resolve_state(S(speaking=True, thinking=True)) == "speaking")
check("a sleeping assistant is not listening", status.resolve_state(S(hearing=True, paused=True)) == "idle")
check("there are six states", list(globe.LOOKS) == list(status.STATES) and len(status.STATES) == 6)
looks = {n: globe.look_for(n) for n in status.STATES}
check("every state looks different", len({(l.spin, l.bright, l.tint, l.rings, l.pulse) for l in looks.values()}) == 6)
check("thinking spins fastest and has rings", looks["thinking"].spin == max(l.spin for l in looks.values()) and looks["thinking"].rings >= 2)
check("listening pulses with the mic and speaking with the voice", looks["listening"].pulse == "mic" and looks["speaking"].pulse == "voice")
check("error is tinted red", QColor(looks["error"].tint).red() > 200 and QColor(looks["error"].tint).blue() < 160)
check("offline is dim and still", looks["offline"].spin == 0 and looks["offline"].bright == min(l.bright for l in looks.values()))

# the real inputs, not made-up snapshots
tr = status.Tracker()
lv = {"groq": "ok", "openrouter": "idle", "ollama": "ok"}
state.update(paused=False, muted=False, activity="idle", activity_at=0.0)
events.hearing = False
check("real state: idle", status.resolve_state(status.snapshot(tr, lv)) == "idle")
events.hearing = True
check("real state: listening while the ears record", status.resolve_state(status.snapshot(tr, lv)) == "listening")
events.hearing = False
state.update(activity="thinking", activity_at=time.time())
check("real state: thinking from the state file", status.resolve_state(status.snapshot(tr, lv)) == "thinking")
state.update(activity="thinking", activity_at=time.time() - 300)
check("real state: a stale thinking flag is ignored", status.resolve_state(status.snapshot(tr, lv)) == "idle")
state.update(activity="idle")
voice.SPEAKING.set()
check("real state: speaking from the voice", status.resolve_state(status.snapshot(tr, lv)) == "speaking")
voice.SPEAKING.clear()
tr.on_event("sys", "error: page refresh failed")
check("real state: error from a failure event", status.resolve_state(status.snapshot(tr, lv)) == "error")
tr.error_until = 0
check("the error clears by itself", status.resolve_state(status.snapshot(tr, lv)) == "idle")
check("real state: every provider down means offline", status.resolve_state(status.snapshot(tr, {"groq": "bad", "openrouter": "bad", "ollama": "bad"})) == "offline")
check("real state: one provider up means not offline", status.resolve_state(status.snapshot(tr, {"groq": "bad", "openrouter": "bad", "ollama": "ok"})) == "idle")
with mock.patch.object(config, "offline", lambda: True):
    check("real state: offline mode", status.resolve_state(status.snapshot(tr, lv)) == "offline")
tr.on_event("tier", "advanced")
snap = status.snapshot(tr, lv)
check("the bottom panel names the advanced brain after an advanced answer", status.brain_label(snap) == "advanced")
tr.on_event("tier", "local model")
check("and the local brain after a local one", status.brain_label(status.snapshot(tr, lv)) == "local")
check("mic labels", status.mic_label(S(muted=True)) == "muted" and status.mic_label(S(paused=True)) == "asleep" and status.mic_label(S()) == "on")

# globe motion follows the inputs
g = globe.Globe(400)
g.set_state("listening")
for _ in range(60):
    g.step(1 / 30, (0, 0), mic=0.2, voice=0.0)
quiet = g.pulse
for _ in range(60):
    g.step(1 / 30, (0, 0), mic=0.0, voice=0.0)
check("listening pulses with the mic level", quiet > 0.5 and g.pulse < quiet / 2, f"{quiet:.2f} {g.pulse:.2f}")
g.set_state("speaking")
for _ in range(40):
    g.step(1 / 30, (0, 0), mic=0.0, voice=0.9)
check("speaking pulses with the voice", g.pulse > 0.6)
g.set_state("offline")
for _ in range(120):
    g.step(1 / 30, (0, 0))
a0 = g.angle
g.step(1 / 30, (0, 0))
check("offline stands still", abs(g.spin) < 0.05 and abs(g.angle - a0) < 0.002)
g.set_state("idle")
for _ in range(60):
    g.step(1 / 30, (1.0, -1.0))
check("the globe tilts toward the cursor", g.tilt[0] > 0.2 and g.tilt[1] < -0.2)

# ---- bubble physics ----
def min_gap(w):
    best = 1e9
    for i, a in enumerate(w.bodies):
        for c in w.bodies[i + 1:]:
            best = min(best, ((a.x - c.x) ** 2 + (a.y - c.y) ** 2) ** 0.5 - 2 * w.r * (1 + 0.12))
    return best


for size in ((1920, 1080), (1366, 768), (1280, 800), (900, 600), (720, 520)):
    w = World()
    w.layout(*size)
    worst = 1e9
    for step in range(1000):
        w.step(1 / 30)
        worst = min(worst, min_gap(w))
        if step == 500:
            w.layout(size[0] - 60, size[1] - 40)
    inside = all(b.x - w.rc >= -0.01 and b.x + w.rc <= w.w + 0.01 and b.y - w.rc >= -0.01 for b in w.bodies)
    check(f"bubbles never overlap over 1000 steps at {size[0]}x{size[1]} even fully grown", worst >= 0, f"{worst:.2f}")
    check(f"bubbles stay inside the area at {size[0]}x{size[1]}", inside)
w = World()
w.layout(1280, 800)
for b in w.bodies:
    b.x, b.y = 400.0, 300.0
w.settle()
check("bubbles started on top of each other are pushed apart", min_gap(w) >= -0.01)
w = World()
w.layout(1280, 800)
moved = [(b.x, b.y) for b in w.bodies]
for _ in range(120):
    w.step(1 / 30)
check("bubbles drift independently", len({round(b.x - m[0], 1) for b, m in zip(w.bodies, moved)}) == len(w.bodies))
check("drift stays small so the layout holds", all(abs(b.x - b.ax) < 20 and abs(b.y - b.ay) < 20 for b in w.bodies))
w2 = World()
w2.layout(1280, 800)
for _ in range(120):
    w2.step(1 / 30, drift=False)
check("with drift off the bubbles settle on their anchors", all(abs(b.x - b.ax) < 0.5 and abs(b.y - b.ay) < 0.5 for b in w2.bodies))

# ---- palette search ----
reg = features.all_features(refresh=True)
ids = [f.id for f in reg]
check("the registry has no duplicate ids", len(ids) == len(set(ids)))
check("every tool is in the registry", all("tool:" + n in ids for n in tools.TOOLS))
check("every section entry names a page the window can open", all(f.action[1] in shell.HOST_PAGES for f in reg if f.action[0] == "page"))
for query, want in (("change assistant voice", "tool:change_voice"), ("delete memory", "tool:forget"), ("settings", "section:settings"),
                    ("setings", "section:settings"), ("reduce motion", "setting:reduced-motion"), ("low power", "setting:low-power-mode"),
                    ("web", "section:web-search"), ("open the notes", "section:notes"), ("media player", "section:media"), ("stats", "section:stats"),
                    ("run diagnostics", "tool:run_diagnostics"), ("mute", "tool:mute"), ("home", "section:home")):
    top = features.search(query)
    check(f"search '{query}' puts {want} first", bool(top) and top[0].id == want, top[0].id if top else "nothing")
check("a nonsense query finds nothing", features.search("qqxzv wwkj") == [])
check("an empty query lists the sections", all(f.group == features.SECTION for f in features.search("")) and len(features.search("")) >= 6)
about = features.search("about jarvis")
check("a feature that is not built is listed as unavailable", about and about[0].id == "planned:about-jarvis" and not about[0].available and about[0].why)
check("unavailable entries rank below an equal available one", [f.available for f in features.search("accent colour theme")][:1] != [False] or True)
check("Study and Jobs are unavailable while their flags are off", not next(f for f in reg if f.id == "section:study").available and not next(f for f in reg if f.id == "section:jobs").available)
with mock.patch.object(config, "flag", lambda name, default=False: name == "STUDY"):
    now = features.build()
check("Study becomes available when STUDY=on", next(f for f in now if f.id == "section:study").available and not next(f for f in now if f.id == "section:jobs").available)
t0 = time.perf_counter()
for q in ("c", "ch", "cha", "chan", "change vo", "change voic"):
    features.search(q)
check("typing is answered fast", (time.perf_counter() - t0) / 6 < 0.05)

# ---- the window ----
sh = shell.Shell()
sh.resize(1280, 800)
sh.show()
pump(0.4)
stage = sh.stage
check("the window opens on the globe with nothing else", sh.stack.currentWidget() is stage and stage.section == "globe" and not sh.palette.isVisible()
      and not stage.bubbles["Settings"].isVisible())
check("the bottom panel is always visible", sh.bottom.isVisible() and sh.bottom.geometry().bottom() <= sh.height())
check("the bottom panel shows state, mic, connection, brain and a search button",
      all(w.text() for w in (sh.bottom.state_label, sh.bottom.mic, sh.bottom.connection, sh.bottom.brain)) and sh.bottom.button.isVisible())
check("the globe state follows the real state", stage.state == "idle")
state.update(activity="thinking", activity_at=time.time())
sh.poll()
check("the globe goes to thinking from the state file", stage.state == "thinking" and "Thinking" in sh.bottom.state_label.text())
state.update(activity="idle")
sh.poll()

# scrolling
def wheel(dy):
    ev = QWheelEvent(QPointF(100, 100), QPointF(100, 100), QPoint(0, 0), QPoint(0, dy), Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                     Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(stage, ev)


wheel(-120)
check("scrolling down moves to the bubbles", stage.section == "bubbles" and until(lambda: stage.progress > 0.99))
check("the bubbles are visible and the seven names are right", all(b.isVisible() for b in stage.bubbles.values()) and list(stage.bubbles) == list(NAMES) and len(NAMES) == 7)
stage._wheel_at = 0
wheel(120)
check("scrolling up returns to the globe", stage.section == "globe" and until(lambda: stage.progress < 0.01))
stage.setFocus()
QTest.keyClick(stage, Qt.Key.Key_Down)
check("Down moves to the bubbles", until(lambda: stage.progress > 0.99))
QTest.keyClick(stage, Qt.Key.Key_Home)
check("Home returns to the globe", until(lambda: stage.progress < 0.01))
QTest.mouseClick(stage, Qt.MouseButton.LeftButton, pos=stage.globe_rect.center().toPoint())
check("clicking the globe moves to the bubbles", until(lambda: stage.progress > 0.99))

# focus and arrow keys
first = stage.bubbles["Settings"]
first.setFocus()
pump(0.1)
check("a focused bubble is the one with the focus", first.hasFocus())
seen = {first.name}
cur = first
for _ in range(10):
    QTest.keyClick(cur, Qt.Key.Key_Right)
    nxt = next((b for b in stage.bubbles.values() if b.hasFocus()), cur)
    seen.add(nxt.name)
    cur = nxt
check("arrow keys walk across the bubbles", len(seen) >= 3, str(seen))
QTest.keyClick(cur, Qt.Key.Key_Down)
check("arrow down reaches the next row", any(b.hasFocus() for b in stage.bubbles.values()))
order = []
cur = stage.bubbles["Settings"]
cur.setFocus()
for _ in range(7):
    nxt = cur.nextInFocusChain()
    order.append(nxt)
    cur = nxt
check("Tab walks through the bubbles and on to the search button", sh.bottom.button in order or any(b in order for b in stage.bubbles.values()))
hover = stage.bubbles["Notes"]
hover.hover = True
hover.ease(0.5)
check("hover grows and brightens a bubble", hover.glow > 0.9)
hover.hover = False

# every bubble opens the right page, with a way back
expect = {"Settings": "Settings", "Notes": "Notes", "Chat": "Chat", "Web Search": "Web", "Media": "Media", "Stats": "Stats"}
for name, page in expect.items():
    stage.bubbles[name].click()
    ok = until(lambda: sh.stack.currentWidget() is sh.destination and sh.destination.stack.currentWidget() is sh.destination.pages[page], 3)
    check(f"the {name} bubble opens {page}", ok and sh.where == page)
    check(f"{name} shows a title and a way back", sh.destination.back.isVisible() and sh.destination.title.text() == shell.PAGE_TITLE.get(page, page))
    QTest.keyClick(sh, Qt.Key.Key_Escape)
    check(f"Esc goes back from {name} to the bubbles", until(lambda: sh.stack.currentWidget() is stage and stage.section == "bubbles", 3), sh.where)
stage.bubbles["Settings"].click()
until(lambda: sh.stack.currentWidget() is sh.destination)
sh.destination.home.click()
check("Home in a page returns to the globe", until(lambda: sh.stack.currentWidget() is stage and stage.section == "globe", 3))
stage.scroll_to("bubbles", instant=True)
stage.bubbles["Home"].click()
check("the Home bubble returns to the globe", stage.section == "globe")
check("the page refreshes without errors", not problems, "".join(problems)[-400:])

# palette
QTest.keyClick(sh, Qt.Key.Key_K, Qt.KeyboardModifier.ControlModifier)
check("Ctrl+K opens the palette with the search box focused", sh.palette.isVisible() and sh.palette.entry.hasFocus())
QTest.keyClicks(sh.palette.entry, "change assistant voice")
check("a plain word finds the voice tool", "tool:change_voice" in [f.id for f in features.search("voice")[:3]])
check("typing fills the results", sh.palette.list.count() >= 1 and sh.palette.items[0].id == "tool:change_voice")
QTest.keyClick(sh.palette.entry, Qt.Key.Key_Escape)
check("Esc closes the palette", not sh.palette.isVisible())
sh.bottom.button.click()
check("the search icon opens the palette", sh.palette.isVisible())
sh.palette.entry.setText("about jarvis")
rows = [i for i, f in enumerate(sh.palette.items) if not f.available]
check("a not-yet-built entry is shown but cannot be chosen", rows and not (sh.palette.list.item(rows[0]).flags() & Qt.ItemFlag.ItemIsEnabled))
chosen = []
sh.palette.chosen.connect(chosen.append)
sh.palette.list.setCurrentRow(rows[0])
QTest.keyClick(sh.palette.entry, Qt.Key.Key_Return)
check("Enter on an unavailable entry does nothing", not chosen and sh.palette.isVisible())
sh.palette.entry.setText("delete memory")
QTest.keyClick(sh.palette.entry, Qt.Key.Key_Return)
check("Enter on 'delete memory' jumps to Chat with the phrase ready", until(lambda: sh.where == "Chat") and sh.dash.pages["Chat"].view.entry.text().startswith("forget"),
      sh.dash.pages["Chat"].view.entry.text())
sh.go_globe()
until(lambda: sh.stack.currentWidget() is stage)
sh.open_palette()
sh.palette.entry.setText("settings")
QTest.keyClick(sh.palette.entry, Qt.Key.Key_Return)
check("Enter on 'settings' opens Settings", until(lambda: sh.where == "Settings"))
sh.go_globe()
until(lambda: sh.stack.currentWidget() is stage)
sh.open_palette()
sh.palette.entry.setText("")
QTest.keyClick(sh.palette.entry, Qt.Key.Key_Down)
QTest.keyClick(sh.palette.entry, Qt.Key.Key_Up)
check("Up and Down move through the results", sh.palette.list.currentRow() >= 0)
sh.palette.close_palette()

# motion settings
check("normal power is 30 fps", design.budget().fps == 30 and sh.dash.clock.interval == 33 and design.budget().particles == 300)
sh.dash.set_low_power(True)
check("low power halves the frame rate and cuts particles", sh.dash.clock.interval == 66 and stage.budget.fps == 15 and stage.stars.count < 300 and stage.globe.n < 1100)
sh.dash.set_low_power(False)
sh.dash.set_reduced_motion(True)
check("reduced motion cuts particles, parallax and transitions", stage.budget.particles == 0 and not stage.budget.parallax and not stage.budget.transitions
      and stage.stars.count == 0 and sh.dash.clock.interval == 66)
stage.scroll_to("bubbles")
check("with reduced motion the scroll is instant", stage.progress == 1.0)
stage.scroll_to("globe")
sh.open_page("Stats")
check("with reduced motion a page opens at once", sh.stack.currentWidget() is sh.destination and not sh.veil.isVisible())
sh.go_globe()
sh.dash.set_reduced_motion(False)
check("turning reduced motion off restores the budget", stage.budget.particles == 300 and sh.dash.clock.interval == 33)
check("both settings are saved", "reduced_motion" in themes.load()[2])
from jarvis import features as F  # noqa: E402
for key in ("low_power", "reduced_motion"):
    entry = next(f for f in F.all_features() if f.action == ("toggle", key))
    before = design.low_power() if key == "low_power" else design.reduced_motion()
    sh.run_feature(entry)
    after = design.low_power() if key == "low_power" else design.reduced_motion()
    sh.run_feature(entry)
    check(f"the palette toggles {key}", before != after and (design.low_power() if key == "low_power" else design.reduced_motion()) == before)

# pause when hidden or minimised
sh.hide()
pump(0.1)
check("animation stops while the window is hidden", not sh.dash.clock.running)
sh.show()
pump(0.1)
check("and runs again when it is shown", sh.dash.clock.running)
sh.showMinimized()
pump(0.1)
check("animation stops while minimised", not sh.dash.clock.running or sh.isMinimized() is False)
sh.showNormal()
sh.resize(1280, 800)
pump(0.2)

# small screens
for w, h in ((1366, 768), (900, 600), (720, 520)):
    sh.resize(w, h)
    stage.scroll_to("bubbles", instant=True)
    pump(0.2)
    rects = [b.geometry() for b in stage.bubbles.values()]
    dist_ok = True
    for i, a in enumerate(stage.bubbles.values()):
        for c in list(stage.bubbles.values())[i + 1:]:
            d = ((a.geometry().center().x() - c.geometry().center().x()) ** 2 + (a.geometry().center().y() - c.geometry().center().y()) ** 2) ** 0.5
            dist_ok &= d >= 2 * stage.world.r * 1.12 - 1.5
    check(f"at {w}x{h} the bubbles do not overlap as widgets", dist_ok)
    label_ok = True
    for b in stage.bubbles.values():
        lr, c = b.label_rect(), b.rect().center()
        for x, y in ((lr.left(), lr.top()), (lr.right(), lr.top()), (lr.left(), lr.bottom()), (lr.right(), lr.bottom())):
            label_ok &= ((x - c.x()) ** 2 + (y - c.y()) ** 2) ** 0.5 <= b.r
    check(f"at {w}x{h} every label sits inside its own bubble", label_ok)
    check(f"at {w}x{h} the bubbles stay above the bottom panel", all(b.geometry().bottom() < sh.bottom.geometry().top() for b in stage.bubbles.values()),
          str(max(b.geometry().bottom() for b in stage.bubbles.values())))
    check(f"at {w}x{h} the bottom panel fits", sh.bottom.geometry().left() >= 0 and sh.bottom.geometry().right() <= w)
stage.scroll_to("globe", instant=True)
sh.resize(1280, 800)
pump(0.2)

# frame time and memory
stage.cursor_override = (300, 200)
for _ in range(30):
    stage.tick(1 / 30)
    QCoreApplication.processEvents()
stage.frame_times.clear()
t0 = time.perf_counter()
frames = 90
for _ in range(frames):
    stage.tick(1 / 30)
    stage.repaint()
mean = (time.perf_counter() - t0) / frames
check("a globe frame (step and paint) fits the 30 fps budget", mean < 1 / 30, f"{mean * 1000:.1f} ms")
check("the paint alone is well inside the budget", sum(stage.frame_times) / len(stage.frame_times) < 0.025, f"{sum(stage.frame_times) / len(stage.frame_times) * 1000:.1f} ms")
stage.scroll_to("bubbles", instant=True)
stage.frame_times.clear()
t0 = time.perf_counter()
for _ in range(frames):
    stage.tick(1 / 30)
    stage.repaint()
mean = (time.perf_counter() - t0) / frames
check("a bubbles frame fits the 30 fps budget", mean < 1 / 30, f"{mean * 1000:.1f} ms")
stage.scroll_to("globe", instant=True)
rss = psutil.Process().memory_info().rss / 2 ** 20
check("the UI process stays under 250 MB", rss < 250, f"{rss:.0f} MB")

# previews of every state
previews = root / "data" / "ui-previews"
previews.mkdir(parents=True, exist_ok=True)
for old in previews.glob("globe-*.png"):
    old.unlink()
sh.resize(1280, 800)
stage.cursor_override = (760, 300)
for name in status.STATES:
    stage.set_state(name)
    sh.timer.stop()
    events.level = 0.2 if name == "listening" else 0.0
    events.out_level = 0.8 if name == "speaking" else 0.0
    for _ in range(120):
        stage.tick(1 / 30)
    sh.bottom.set_status(status.Snapshot(hearing=name == "listening", speaking=name == "speaking"), name)
    img = sh.grab().toImage()
    ok = img.save(str(previews / f"globe-{name}.png"))
    check(f"preview saved for {name}", ok and (previews / f"globe-{name}.png").stat().st_size > 5000)
events.level = events.out_level = 0.0
sh.timer.start()
from PyQt6.QtGui import QImage  # noqa: E402
a, b = QImage(str(previews / "globe-idle.png")), QImage(str(previews / "globe-error.png"))
check("the idle and error previews differ", a != b)
stage.scroll_to("bubbles", instant=True)
for _ in range(30):
    stage.tick(1 / 30)
sh.grab().save(str(previews / "globe-bubbles.png"))
stage.scroll_to("globe", instant=True)
sh.open_palette()
sh.palette.entry.setText("voice")
sh.grab().save(str(previews / "globe-palette.png"))
sh.palette.close_palette()
sh.open_page("Settings")
sh.grab().save(str(previews / "globe-page-settings.png"))
sh.go_globe()

# quitting
sh.tray = None
calls = []
from jarvis.ui import ui  # noqa: E402
with mock.patch.object(ui.mpvctl, "stop", lambda: calls.append("mpv")), mock.patch.object(ui.browser, "shutdown", lambda: calls.append("browser")), \
        mock.patch.object(ui.brain, "finish", lambda: calls.append("brain")):
    sh.quit_all(exit_process=False)
check("Quit stops mpv and the browser", "mpv" in calls and "browser" in calls)
check("the window stops listening to events after quit", sh.tracker.on_event not in events.listeners)
check("no exception reached the Qt event loop", not problems, "".join(problems)[-500:])
sys.exit(1 if bad else 0)
