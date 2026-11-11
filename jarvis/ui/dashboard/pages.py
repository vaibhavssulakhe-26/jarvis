"""The dashboard pages. Each page has refresh(), called when it is shown and every couple of seconds while it is."""
import time
from datetime import datetime

import psutil
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (QCheckBox, QColorDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QPushButton, QSlider,
                             QSpinBox, QTextEdit, QVBoxLayout, QWidget)

from ...actions import coder, mpvctl, play, procs, stats, study
from ...brain import brain
from ...core import config, state
from ...memory import notes as notes_store, rag
from ...scheduling import pomodoro, reminders
from . import themes
from .widgets import MemoryGraph, Orb, Panel, RingGauge, mono

KEYS = ("GROQ_API_KEY", "OPENROUTER_API_KEY", "GMAIL_APP_PASSWORD", "GROQ_VISION_MODEL")
QUICK = ("what time is it", "start focus 25", "quiz me", "read my screen", "jarvis stats", "good morning")


class Context:
    """What the pages share: the theme, the animation clock, a way to run a typed command, and the live feed."""

    def __init__(self, theme, clock, run):
        self.theme, self.clock, self.run = theme, clock, run
        self.feed = []
        self.ollama = False
        self.mode = "idle"
        self.log = []


def cap(text):
    lab = QLabel(text.upper())
    lab.setObjectName("cap")
    return lab


def value_label(text="", big=False):
    lab = QLabel(text)
    lab.setFont(mono(10))
    lab.setWordWrap(True)
    if big:
        lab.setObjectName("big")
    return lab


class ConfirmBar(Panel):
    """Shows a waiting yes or no question (a risky click, a download, an install) with Yes and No buttons."""

    def __init__(self, ctx):
        super().__init__(ctx.theme)
        self.ctx = ctx
        row = QHBoxLayout()
        self.text = value_label("")
        self.yes = QPushButton("Yes")
        self.no = QPushButton("No")
        self.yes.clicked.connect(lambda: ctx.run("yes"))
        self.no.clicked.connect(lambda: ctx.run("no"))
        row.addWidget(self.text, 1)
        row.addWidget(self.yes)
        row.addWidget(self.no)
        self.box.addLayout(row)
        self.setVisible(False)

    def refresh(self):
        from ...core import main as core
        from ...voice import voice
        waiting = bool(core.PENDING) and time.time() < core.PENDING.get("until", 0)
        if waiting:
            self.text.setText(voice.LAST[0][:300])
        self.setVisible(waiting)
        return waiting


class Page(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(0, 0, 0, 0)
        self.root.setSpacing(10)

    def refresh(self):
        pass


def provider_states():
    """[(name, label, level)] where level is ok, warn or bad."""
    now = time.time()
    out = []
    for key, env in (("groq", "GROQ_API_KEY"), ("openrouter", "OPENROUTER_API_KEY")):
        if not config.get(env):
            out.append((key.title() if key == "groq" else "OpenRouter", "no key", "bad"))
        elif brain._busy.get(key, 0) > now or brain._offline_until[0] > now:
            out.append((key.title() if key == "groq" else "OpenRouter", "rate-limited", "warn"))
        else:
            out.append((key.title() if key == "groq" else "OpenRouter", "connected", "ok"))
    return out


class Home(Page):
    def __init__(self, ctx):
        super().__init__(ctx)
        t = ctx.theme
        row = QHBoxLayout()
        row.setSpacing(12)
        left = QVBoxLayout()
        gauges = Panel(t, "System")
        g = QHBoxLayout()
        self.cpu, self.ram, self.disk = RingGauge(t, "CPU"), RingGauge(t, "RAM"), RingGauge(t, "DISK")
        for w in (self.cpu, self.ram, self.disk):
            g.addWidget(w)
        gauges.box.addLayout(g)
        self.up = value_label("")
        gauges.box.addWidget(self.up)
        prov = Panel(t, "Providers")
        self.prov = value_label("")
        self.prov.setTextFormat(Qt.TextFormat.RichText)
        prov.box.addWidget(self.prov)
        left.addWidget(gauges)
        left.addWidget(prov)
        left.addStretch(1)
        centre = QVBoxLayout()
        self.orb = Orb(t, ctx.clock)
        self.status = QLabel("")
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status.setObjectName("cap")
        centre.addWidget(self.orb, 1)
        centre.addWidget(self.status)
        right = QVBoxLayout()
        feed = Panel(t, "Live feed")
        self.feed = value_label("")
        self.feed.setTextFormat(Qt.TextFormat.RichText)
        self.feed.setAlignment(Qt.AlignmentFlag.AlignTop)
        feed.box.addWidget(self.feed, 1)
        today = Panel(t, "Today")
        self.today = value_label("")
        self.today.setTextFormat(Qt.TextFormat.RichText)
        today.box.addWidget(self.today)
        right.addWidget(feed, 1)
        right.addWidget(today)
        for col, stretch in ((left, 2), (centre, 4), (right, 3)):
            holder = QWidget()
            holder.setLayout(col)
            col.setContentsMargins(0, 0, 0, 0)
            row.addWidget(holder, stretch)
        self.root.addLayout(row, 1)

    def refresh(self):
        t = self.ctx.theme
        self.cpu.set_value(psutil.cpu_percent(None))
        self.ram.set_value(psutil.virtual_memory().percent)
        self.disk.set_value(psutil.disk_usage("/").percent)
        free = psutil.virtual_memory().available / 2 ** 30
        self.up.setText(f"free memory {free:.1f} GB")
        states = provider_states()
        states.append(("Ollama", "connected" if self.ctx.ollama else "offline", "ok" if self.ctx.ollama else "bad"))
        colour = {"ok": t.ok.name(), "warn": t.warn.name(), "bad": t.bad.name()}
        self.prov.setText("<br>".join(f'<span style="color:{colour[lv]}">&#9679;</span> {n} <span style="color:{t.dim.name()}">{lab}</span>'
                                      for n, lab, lv in states))
        rows = []
        for r in self.ctx.feed[-7:][::-1]:
            rows.append(f'<span style="color:{t.dim.name()}">{r["time"]}</span> {r["heard"][:34]}<br>'
                        f'&nbsp;&nbsp;<span style="color:{t.accent.name()}">{r["route"] or "..."}</span> '
                        f'<span style="color:{t.dim.name()}">{r["provider"]}</span>')
        self.feed.setText("<br>".join(rows) or f'<span style="color:{t.dim.name()}">nothing heard yet</span>')
        today = []
        now = datetime.now()
        mine = [r for r in reminders.pending() if datetime.fromisoformat(r["due"]).date() == now.date()]
        today.append(f"reminders {len(mine)}" + (": " + mine[0]["text"][:28] if mine else ""))
        cur = pomodoro.status()
        today.append(f"focus {pomodoro.left() / 60:.0f} min left ({cur['kind']})" if cur else "focus timer off")
        today.append("next: " + (study.next_item() or "no roadmap")[:34])
        self.today.setText("<br>".join(today))
        self.status.setText(self.ctx.mode.upper())


class Media(Page):
    def __init__(self, ctx):
        super().__init__(ctx)
        t = ctx.theme
        now = Panel(t, "Now playing")
        self.title = value_label("nothing playing", big=True)
        self.pos = value_label("")
        now.box.addWidget(self.title)
        now.box.addWidget(self.pos)
        row = QHBoxLayout()
        for text, fn in (("Pause / resume", lambda: mpvctl.send("cycle", "pause")), ("Next", lambda: ctx.run("next")),
                         ("Back 10s", lambda: mpvctl.seek(-10)), ("Forward 10s", lambda: mpvctl.seek(10)), ("Stop", mpvctl.stop)):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, f=fn: f())
            row.addWidget(b)
        now.box.addLayout(row)
        vol = QHBoxLayout()
        vol.addWidget(cap("Volume"))
        self.vol = QSlider(Qt.Orientation.Horizontal)
        self.vol.setRange(0, 100)
        self.vol.valueChanged.connect(lambda v: mpvctl.send("set_property", "volume", v))
        vol.addWidget(self.vol, 1)
        now.box.addLayout(vol)
        queue = Panel(t, "Queue")
        self.queue = QListWidget()
        queue.box.addWidget(self.queue)
        self.root.addWidget(now)
        self.root.addWidget(queue, 1)

    def refresh(self):
        if not mpvctl.running():
            self.title.setText("nothing playing")
            self.pos.setText("")
        else:
            title = (mpvctl.send("get_property", "media-title") or {}).get("data") or "playing"
            p = (mpvctl.send("get_property", "time-pos") or {}).get("data")
            d = (mpvctl.send("get_property", "duration") or {}).get("data")
            paused = (mpvctl.send("get_property", "pause") or {}).get("data")
            self.title.setText(str(title)[:80])
            if isinstance(p, (int, float)) and isinstance(d, (int, float)):
                self.pos.setText(f"{int(p) // 60}:{int(p) % 60:02d} / {int(d) // 60}:{int(d) % 60:02d}" + ("  paused" if paused else ""))
            v = (mpvctl.send("get_property", "volume") or {}).get("data")
            if isinstance(v, (int, float)) and not self.vol.isSliderDown():
                self.vol.blockSignals(True)
                self.vol.setValue(int(min(100, v)))
                self.vol.blockSignals(False)
        self.queue.clear()
        results = play._state.get("results") or []
        for i, item in enumerate(results):
            mark = ">" if i == play._state.get("i", 0) else " "
            self.queue.addItem(f"{mark} {str(item.get('title', item))[:90]}")


class Code(Page):
    def __init__(self, ctx):
        super().__init__(ctx)
        t = ctx.theme
        row = QHBoxLayout()
        proj = Panel(t, "Projects")
        self.list = QListWidget()
        self.list.currentTextChanged.connect(self.pick)
        proj.box.addWidget(self.list, 1)
        run = QHBoxLayout()
        for text, fn in (("Run", lambda: ctx.run("run it")), ("Stop", lambda: procs.stop(coder.PROJECT)),
                         ("Fix last error", lambda: ctx.run("fix the last error")), ("Git init", lambda: ctx.run("git init this project"))):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, f=fn: f())
            run.addWidget(b)
        proj.box.addLayout(run)
        build = Panel(t, "Build")
        self.box_in = QLineEdit()
        self.box_in.setPlaceholderText("a flask app that shows the time")
        self.box_in.returnPressed.connect(self.build)
        go = QPushButton("Build")
        go.clicked.connect(self.build)
        line = QHBoxLayout()
        line.addWidget(self.box_in, 1)
        line.addWidget(go)
        build.box.addLayout(line)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(mono(9))
        build.box.addWidget(cap("Build log"))
        build.box.addWidget(self.log, 1)
        row.addWidget(proj, 2)
        row.addWidget(build, 3)
        self.root.addLayout(row, 1)

    def pick(self, name):
        folder = coder.find_project(name)
        if folder:
            meta = coder.load_meta(folder)
            coder.last.update(dir=folder, main=folder / (meta.get("entry") or "main.py"))

    def build(self):
        text = self.box_in.text().strip()
        if text:
            self.box_in.clear()
            self.ctx.run("build me " + text)

    def refresh(self):
        names = sorted(p.name for p in coder.WORKSPACE.iterdir() if p.is_dir() and not p.name.startswith(".")) if coder.WORKSPACE.is_dir() else []
        if names != [self.list.item(i).text() for i in range(self.list.count())]:
            self.list.blockSignals(True)
            self.list.clear()
            self.list.addItems(names)
            self.list.blockSignals(False)
        lines = [l for l in self.ctx.log[-60:]]
        folder = coder.last.get("dir")
        tail = procs.tail(folder / ".run.log", 12) if folder and (folder / ".run.log").exists() else ""
        self.log.setPlainText("\n".join(lines) + (("\n--- run log ---\n" + tail) if tail else ""))
        self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())


class Notes(Page):
    def __init__(self, ctx):
        super().__init__(ctx)
        t = ctx.theme
        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("search notes and PDFs")
        self.search.returnPressed.connect(self.do_search)
        self.search.textChanged.connect(lambda q: self.graph.highlight(q))
        reindex = QPushButton("Reindex")
        reindex.clicked.connect(lambda: ctx.run("reindex my notes"))
        top.addWidget(self.search, 1)
        top.addWidget(reindex)
        self.root.addLayout(top)
        row = QHBoxLayout()
        gp = Panel(t, "Memory graph")
        self.graph = MemoryGraph(t)
        self.graph.opened.connect(self.open_note)
        gp.box.addWidget(self.graph, 1)
        side = QVBoxLayout()
        self.results = QListWidget()
        self.viewer = QTextEdit()
        self.viewer.setReadOnly(True)
        rp = Panel(t, "Results")
        rp.box.addWidget(self.results)
        vp = Panel(t, "Note")
        vp.box.addWidget(self.viewer, 1)
        ip = Panel(t, "Inbox")
        self.inbox = QTextEdit()
        self.inbox.setReadOnly(True)
        self.inbox.setMaximumHeight(110)
        ip.box.addWidget(self.inbox)
        side.addWidget(rp)
        side.addWidget(vp, 1)
        side.addWidget(ip)
        row.addWidget(gp, 3)
        holder = QWidget()
        holder.setLayout(side)
        side.setContentsMargins(0, 0, 0, 0)
        row.addWidget(holder, 2)
        self.root.addLayout(row, 1)
        self._sig = None
        self.files = {}

    def files_now(self):
        out = {}
        folder = notes_store.NOTES_DIR
        if folder.is_dir():
            for p in sorted(folder.rglob("*")):
                if p.suffix.lower() in (".md", ".txt") and p.is_file() and len(out) < 60:
                    out[p.name] = p
        return out

    def load_graph(self):
        self.files = self.files_now()
        sig = tuple((n, p.stat().st_mtime) for n, p in self.files.items())
        if sig != self._sig:
            self._sig = sig
            self.graph.load([(n, p.read_text(errors="replace")[:4000]) for n, p in self.files.items()])
            self.graph.highlight(self.search.text())

    def open_note(self, name):
        p = self.files.get(name)
        if p:
            self.viewer.setPlainText(p.read_text(errors="replace")[:6000])

    def do_search(self):
        q = self.search.text().strip()
        self.results.clear()
        for h in rag.search(q, 5) if q else []:
            self.results.addItem(f"{h['name']}: {h['text'][:80]}")
        if not self.results.count():
            self.results.addItem("nothing found")

    def refresh(self):
        self.load_graph()
        inbox = notes_store.NOTES_DIR / "inbox.md"
        self.inbox.setPlainText("\n".join(inbox.read_text(errors="replace").splitlines()[-8:]) if inbox.exists() else "no inbox yet")


class Study(Page):
    def __init__(self, ctx):
        super().__init__(ctx)
        t = ctx.theme
        row = QHBoxLayout()
        left = QVBoxLayout()
        sc = Panel(t, "Quiz scores")
        self.scores = value_label("")
        self.scores.setTextFormat(Qt.TextFormat.RichText)
        sc.box.addWidget(self.scores)
        self.streak = value_label("", big=True)
        sc.box.addWidget(self.streak)
        quiz = QPushButton("Quiz me")
        quiz.clicked.connect(lambda: ctx.run("quiz me"))
        sc.box.addWidget(quiz)
        ci = Panel(t, "Daily check-in")
        form = QGridLayout()
        self.sleep = QLineEdit()
        self.sleep.setPlaceholderText("23:30")
        self.walk = QCheckBox("went for a walk")
        self.mins = QSpinBox()
        self.mins.setRange(0, 1000)
        self.mins.setSuffix(" min studied")
        save = QPushButton("Save today")
        save.clicked.connect(self.save)
        form.addWidget(cap("Sleep time"), 0, 0)
        form.addWidget(self.sleep, 0, 1)
        form.addWidget(self.walk, 1, 0, 1, 2)
        form.addWidget(self.mins, 2, 0, 1, 2)
        form.addWidget(save, 3, 0, 1, 2)
        ci.box.addLayout(form)
        self.note = value_label("")
        ci.box.addWidget(self.note)
        left.addWidget(sc)
        left.addWidget(ci)
        left.addStretch(1)
        road = Panel(t, "Roadmap")
        self.road = QListWidget()
        done = QPushButton("Mark selected done")
        done.clicked.connect(self.mark)
        road.box.addWidget(self.road, 1)
        road.box.addWidget(done)
        holder = QWidget()
        holder.setLayout(left)
        left.setContentsMargins(0, 0, 0, 0)
        row.addWidget(holder, 2)
        row.addWidget(road, 3)
        self.root.addLayout(row, 1)

    def save(self):
        values = {"study_min": self.mins.value(), "walk": self.walk.isChecked()}
        sleep = study.parse_sleep(self.sleep.text()) if self.sleep.text().strip() else None
        if sleep:
            values["sleep"] = sleep
        study.save_checkin(values)
        self.note.setText("saved")

    def mark(self):
        item = self.road.currentItem()
        if item:
            try:
                study.roadmap_done({"item": item.text()[2:]})
            except Exception as e:
                self.note.setText(str(e)[:80])
            self.refresh()

    def refresh(self):
        t = self.ctx.theme
        data = study.load()
        rows = []
        for topic, r in sorted(data["topics"].items()):
            acc = study.accuracy(r)
            colour = (t.bad if acc < study.WEAK_BELOW else t.ok).name()
            rows.append(f'{topic:<14}<span style="color:{colour}">{acc * 100:.0f}%</span> of {r["asked"]}')
        weak = study.weak_topics(data)
        self.scores.setText("<br>".join(rows) or "no quizzes yet")
        self.streak.setText(f"streak {study.streak(data)} days" + (f"   weak: {', '.join(weak[:2])}" if weak else ""))
        lines, items = study.roadmap_items()
        self.road.clear()
        for _, done, text in items:
            self.road.addItem(("x " if done else "o ") + text)
        if lines is None:
            self.road.addItem("no data/roadmap.md yet")


class Web(Page):
    def __init__(self, ctx):
        super().__init__(ctx)
        t = ctx.theme
        st = Panel(t, "Browser agent")
        self.state = value_label("")
        st.box.addWidget(self.state)
        self.confirm = ConfirmBar(ctx)
        self.root.addWidget(st)
        self.root.addWidget(self.confirm)
        rules = Panel(t, "Safety rules")
        rules.box.addWidget(value_label("Never types passwords, cards, codes or keys. Asks before submit, send, post, buy, delete and login clicks. "
                                        "Asks before any download. Page text is data, never instructions. Own profile in data/browser-profile."))
        self.root.addWidget(rules)
        quick = QHBoxLayout()
        for text in ("close the browser", "new tab", "read this page"):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, c=text: ctx.run(c))
            quick.addWidget(b)
        self.root.addLayout(quick)
        self.root.addStretch(1)

    def refresh(self):
        from ...actions import browser
        if not browser.playwright_ok():
            msg = "Playwright is not installed. Run: pip install playwright"
        elif not browser.ready():
            msg = "No browser found for Playwright. Install Google Chrome or run: playwright install chromium"
        else:
            msg = "browser open" if browser.active() else "browser closed, ready"
        self.state.setText(msg)
        self.confirm.refresh()


class Stats(Page):
    def __init__(self, ctx):
        super().__init__(ctx)
        t = ctx.theme
        self.eval = Panel(t, "Eval")
        self.eval_text = value_label("", big=True)
        self.eval.box.addWidget(self.eval_text)
        use = Panel(t, "Provider use")
        self.use = value_label("")
        self.use.setTextFormat(Qt.TextFormat.RichText)
        use.box.addWidget(self.use)
        sysp = Panel(t, "This process")
        self.sys = value_label("")
        sysp.box.addWidget(self.sys)
        for w in (self.eval, use, sysp):
            self.root.addWidget(w)
        self.root.addStretch(1)

    def refresh(self):
        ev = stats.latest_eval()
        if ev:
            self.eval_text.setText(f"{ev['passed']}/{ev['total']} passed   {ev['avg_tokens']} tokens avg   {ev['date']}")
        else:
            self.eval_text.setText("no eval yet: python scripts/eval_phrases.py")
        week, today = stats.usage()
        rows = []
        for key, label in stats.PROVIDERS:
            r = week.get(key, {"calls": 0, "tokens": 0})
            rows.append(f"{label:<12} {r['calls']:>4} requests  {r['tokens']:>7} tokens  today {today.get(key, {}).get('calls', 0)}")
        rows.append(f"rate limits hit this session: {brain.LIMITED['count']}")
        self.use.setText("<pre>" + "\n".join(rows) + "</pre>")
        rss = psutil.Process().memory_info().rss / 2 ** 20
        self.sys.setText(f"Jarvis memory {rss:.0f} MB   free system memory {psutil.virtual_memory().available / 2 ** 30:.1f} GB   "
                         f"animation {self.ctx.clock.interval} ms per frame" + ("   low power" if self.ctx.clock.low else ""))


class Settings(Page):
    changed = pyqtSignal()

    def __init__(self, ctx, window):
        super().__init__(ctx)
        self.window = window
        t = ctx.theme
        tp = Panel(t, "Theme")
        row = QHBoxLayout()
        self.buttons = {}
        for name in themes.ORDER:
            b = QPushButton(name)
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, n=name: window.set_theme(n))
            self.buttons[name] = b
            row.addWidget(b)
        tp.box.addLayout(row)
        hue = QHBoxLayout()
        hue.addWidget(cap("Custom hue"))
        self.hue = QSlider(Qt.Orientation.Horizontal)
        self.hue.setRange(0, 359)
        self.hue.sliderReleased.connect(lambda: window.set_hue(self.hue.value()))
        pick = QPushButton("Pick colour")
        pick.clicked.connect(self.pick)
        hue.addWidget(self.hue, 1)
        hue.addWidget(pick)
        tp.box.addLayout(hue)
        opt = Panel(t, "Options")
        self.low = QCheckBox("Low power mode (15 fps, 40 points, no rings)")
        self.low.toggled.connect(window.set_low_power)
        self.tint = QCheckBox("State colours (accent follows listening, thinking, error)")
        self.tint.toggled.connect(lambda on: window.set_ui_flag("state_colours", on))
        self.cycle = QCheckBox("Slowly cycle the hue")
        self.cycle.toggled.connect(lambda on: window.set_ui_flag("cycle", on))
        self.mute = QCheckBox("Mute Jarvis's voice")
        self.mute.toggled.connect(lambda on: state.update(muted=bool(on)))
        for w in (self.low, self.tint, self.cycle, self.mute):
            opt.box.addWidget(w)
        keys = Panel(t, "Keys")
        self.keys = value_label("")
        keys.box.addWidget(self.keys)
        for w in (tp, opt, keys):
            self.root.addWidget(w)
        self.root.addStretch(1)

    def pick(self):
        c = QColorDialog.getColor(self.ctx.theme.accent, self, "Accent colour")
        if c.isValid():
            self.window.set_hue(max(0, c.hueF()) * 360)

    def sync(self):
        th = self.ctx.theme
        for name, b in self.buttons.items():
            b.blockSignals(True)
            b.setChecked(name == th.name)
            b.blockSignals(False)
        for box, value in ((self.low, self.window.low_manual), (self.tint, th.state_colours), (self.cycle, th.cycle), (self.mute, state.get("muted"))):
            box.blockSignals(True)
            box.setChecked(bool(value))
            box.blockSignals(False)
        self.hue.blockSignals(True)
        self.hue.setValue(int(th.hue) % 360)
        self.hue.blockSignals(False)

    def refresh(self):
        self.sync()
        self.keys.setText("\n".join(f"{k}: {'set' if config.get(k) else 'not set'}" for k in KEYS))
