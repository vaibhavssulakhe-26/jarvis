"""The dashboard pages. Each page has refresh(), called when it is shown and every couple of seconds while it is."""
import time
from pathlib import Path
from datetime import datetime
from html import escape

import psutil
from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QPainter, QPen
from PyQt6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QSlider,
                             QSpinBox, QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget)

from ...actions import coder, events, mpvctl, play, procs, stats, study
from ...brain import brain
from ...core import config, state
from ...memory import facts, notes as notes_store, rag
from ...scheduling import pomodoro, reminders
from ...voice import listen
from . import privacy, themes
from .theme import alpha
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
        self.activity = []
        self.build = []


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


def pad(label, width):
    """A label for rich text, followed by non-breaking spaces so the value never touches it (plain spaces collapse in a QLabel)."""
    return escape(str(label)) + "&nbsp;" * max(2, width - len(str(label)))


def provider_states():
    """[(name, label, level, seconds or None)] where level is ok, warn or bad. Each comes from the last real call to that provider, never a ping."""
    out = []
    for key, name in (("groq", "Groq"), ("openrouter", "OpenRouter"), ("ollama", "Ollama")):
        level, _ = brain.provider_state(key)
        if level == "ok":
            out.append((name, "last call worked", "ok", brain.LATENCY.get(key)))
        elif level == "idle":
            out.append((name, "not used yet", "warn", brain.LATENCY.get(key)))
        else:
            out.append((name, brain.why_down(key) or "last call failed", "bad", brain.LATENCY.get(key)))
    return out


class Card(QWidget):
    """One provider: a dot, the name, its state and the latency of its last answer."""

    def __init__(self, theme, parent=None):
        super().__init__(parent)
        self.theme = theme
        self.name = self.state = ""
        self.level = "bad"
        self.latency = None
        self.setFixedHeight(46)
        theme.changed.connect(self.update)

    def set(self, name, state, level, latency):
        self.name, self.state, self.level, self.latency = name, state, level, latency
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        t = self.theme
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(alpha(t.accent, 60), 1))
        p.setBrush(alpha(t.accent, 14))
        p.drawRoundedRect(r, 6, 6)
        colour = {"ok": t.ok, "warn": t.warn, "bad": t.bad}[self.level]
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(colour)
        p.drawEllipse(QPointF(16, r.height() / 2 + 0.5), 4.5, 4.5)
        p.setPen(t.text)
        p.setFont(mono(10, True))
        p.drawText(QRectF(30, 4, r.width() - 100, 20), Qt.AlignmentFlag.AlignVCenter, self.name)
        p.setPen(colour)
        p.setFont(mono(8))
        p.drawText(QRectF(30, 23, r.width() - 40, 18), Qt.AlignmentFlag.AlignVCenter, self.state)
        p.setPen(t.dim)
        p.setFont(mono(9))
        p.drawText(QRectF(r.width() - 80, 4, 72, 36), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   f"{self.latency * 1000:.0f} ms" if self.latency else "no data")


AGENTS = (("Coder", "coder"), ("Browser", "browser"), ("Research", "research"), ("Notes", "notes"), ("Study", "study"))


def agent_running(key):
    from ...actions import browser
    if events.busy.get(key, 0) > 0:
        return True
    if key == "coder":
        return procs.alive()
    if key == "browser":
        return browser.active()
    return False


class Chat(Page):
    """The full chat: conversation list on the left, the thread in the middle."""

    def __init__(self, ctx):
        super().__init__(ctx)
        from .chat import ChatView
        self.view = ChatView(ctx)
        self.root.addWidget(self.view, 1)


class Home(Page):
    """The core as a background layer, glass panels on the left, and the chat as the main panel on the right."""
    FEED_ROWS = 12

    def __init__(self, ctx):
        super().__init__(ctx)
        from .chat import ChatView
        t = ctx.theme
        self.orb = Orb(t, ctx.clock, self)
        self.orb.lower()
        row = QHBoxLayout()
        row.setSpacing(12)
        left = QVBoxLayout()
        left.setSpacing(10)
        gauges = Panel(t, "System")
        g = QHBoxLayout()
        self.cpu, self.ram, self.disk = RingGauge(t, "CPU"), RingGauge(t, "RAM"), RingGauge(t, "DISK")
        for w in (self.cpu, self.ram, self.disk):
            g.addWidget(w)
        gauges.box.addLayout(g)
        self.up = value_label("")
        gauges.box.addWidget(self.up)
        prov = Panel(t, "Brains")
        self.cards = [Card(t) for _ in range(3)]
        for c in self.cards:
            prov.box.addWidget(c)
        brief = Panel(t, "Briefing")
        self.brief = value_label("")
        self.brief.setTextFormat(Qt.TextFormat.RichText)
        self.brief.setWordWrap(True)
        self.brief.setAlignment(Qt.AlignmentFlag.AlignTop)
        brief.box.addWidget(self.brief, 1)
        agents = Panel(t, "Agents")
        self.agents = value_label("")
        self.agents.setTextFormat(Qt.TextFormat.RichText)
        agents.box.addWidget(self.agents)
        self.status_block = QWidget()
        status = QVBoxLayout(self.status_block)
        status.setContentsMargins(0, 0, 0, 0)
        status.setSpacing(10)
        for w in (gauges, prov, agents):
            status.addWidget(w)
        self.status_block.setVisible(False)
        left.addWidget(brief, 1)
        left.addWidget(self.status_block)
        holder = QWidget()
        holder.setLayout(left)
        holder.setFixedWidth(300)
        self.left_holder = holder
        left.setContentsMargins(0, 0, 0, 0)
        chat = Panel(t, "Chat")
        self.chat = ChatView(ctx, compact=True, header=False)
        chat.box.addWidget(self.chat, 1)
        chat.setMinimumWidth(420)
        row.addWidget(holder)
        row.addStretch(1)
        row.addWidget(chat, 0)
        chat.setMaximumWidth(560)
        chat.setSizePolicy(chat.sizePolicy().horizontalPolicy(), chat.sizePolicy().verticalPolicy())
        self.root.addLayout(row, 1)
        self.chat_panel = chat

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self.orb.setGeometry(0, 0, self.width(), self.height())
        self.orb.lower()
        left, right = self.left_holder.geometry().right(), self.chat_panel.geometry().left()
        self.orb.box = QRectF(left, 0, max(200, right - left), self.height())

    def refresh(self):
        t = self.ctx.theme
        dim, acc = t.dim.name(), t.accent_text.name()
        self.cpu.set_value(psutil.cpu_percent(None))
        self.ram.set_value(psutil.virtual_memory().percent)
        self.disk.set_value(psutil.disk_usage("/").percent)
        self.up.setText(f"free memory {psutil.virtual_memory().available / 2 ** 30:.1f} GB")
        states = provider_states()
        if states[2][2] == "warn" and self.ctx.ollama:
            states[2] = ("Ollama", "running, not used yet", "ok", None)
        for card, (name, label, level, lat) in zip(self.cards, states):
            card.set(name, label, level, lat)
        self.brief.setText(privacy.show(self.brief_html(dim, acc)))
        lines = []
        for name, key in AGENTS:
            on = agent_running(key)
            colour = t.ok.name() if on else dim
            lines.append(f'<span style="color:{colour}">&#9679;</span> {pad(name, 10)}<span style="color:{colour}">{"running" if on else "idle"}</span>')
        self.agents.setText("<br>".join(lines))

    def brief_html(self, dim, acc):
        from html import escape
        from ...routines import load, maildigest, morning
        from ... import timetable
        got = morning.latest()
        if got:
            body = f'{escape(got["spoken"][:260])}'
        else:
            body = f'<span style="color:{dim}">No briefing yet today. Say "morning briefing".</span>'
        try:
            nxt = [r for r in load() if r["time"] > datetime.now().strftime("%H:%M")]
            nxt = nxt[0] if nxt else (load() or [None])[0]
        except OSError:
            nxt = None
        digest = maildigest.latest()
        if digest and digest["at"][:10] == datetime.now().date().isoformat():
            c = digest["counts"]
            top = [r for r in digest["groups"]["needs"][:2]]
            body += (f'<br><br><span style="color:{acc}">Email digest</span> {c["needs"]} need attention, {c["know"]} good to know, {c["promo"]} promotions'
                     + "".join(f'<br>&nbsp;&nbsp;{escape(r["name"])}: {escape(r["subject"] or "(text withheld)")[:50]}' for r in top))
        try:
            soon = [d for d in timetable.due_within(7) if d["date"] >= datetime.now().date()][:2]
            body += "".join(f'<br><span style="color:{dim}">due {escape(timetable.say_deadline(d))}</span>' for d in soon)
        except OSError:
            pass
        later = f'<br><span style="color:{dim}">next routine {nxt["time"]} {escape(nxt["name"])}</span>' if nxt else ""
        cmds = '<br><span style="color:%s">say: morning briefing, what is on my calendar, what is important in my email, list routines</span>' % dim
        return body + later + cmds


class Activity(Page):
    """What the system is doing: how each command was routed and answered, system messages, core facts and today's timeline. No conversation here."""
    FEED_ROWS = 12

    def __init__(self, ctx):
        super().__init__(ctx)
        t = ctx.theme
        row = QHBoxLayout()
        row.setSpacing(12)
        feed = Panel(t, "Routing")
        self.feed = value_label("")
        self.feed.setTextFormat(Qt.TextFormat.RichText)
        self.feed.setAlignment(Qt.AlignmentFlag.AlignTop)
        feed.box.addWidget(self.feed, 1)
        log = Panel(t, "Activity log")
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(mono(9))
        log.box.addWidget(self.log, 1)
        side = QVBoxLayout()
        side.setSpacing(10)
        core = Panel(t, "Core")
        self.core = value_label("")
        self.core.setTextFormat(Qt.TextFormat.RichText)
        core.box.addWidget(self.core)
        mem = Panel(t, "Memory")
        self.mem = value_label("")
        mem.box.addWidget(self.mem)
        mission = Panel(t, "Today")
        self.today = value_label("")
        self.today.setTextFormat(Qt.TextFormat.RichText)
        mission.box.addWidget(self.today)
        for w in (core, mem, mission):
            side.addWidget(w)
        side.addStretch(1)
        holder = QWidget()
        holder.setLayout(side)
        side.setContentsMargins(0, 0, 0, 0)
        row.addWidget(feed, 3)
        row.addWidget(log, 4)
        row.addWidget(holder, 3)
        self.root.addLayout(row, 1)

    def refresh(self):
        t = self.ctx.theme
        dim, acc = t.dim.name(), t.accent_text.name()
        count = rag.count()
        stamp = rag.last_indexed()
        self.mem.setText(f"{count} notes and documents indexed<br>" + (
            f'<span style="color:{dim}">last indexed {datetime.fromtimestamp(stamp):%d %b %H:%M}</span>' if stamp else
            f'<span style="color:{dim}">not indexed yet: say "reindex my notes"</span>'))
        from ...voice import voices
        brain_name = "offline (Ollama only)" if config.offline() else "Groq" if config.get("GROQ_API_KEY") else "offline only"
        info = (("BRAIN", brain_name), ("EARS", "Groq Whisper" if config.stt_cloud() else "this laptop"),
                ("WAKE", config.wake_label().title()), ("VOICE", voices.current_name()),
                ("OFFLINE", brain._ollama_name["name"] or "not checked yet"), ("FALLBACK", "Ollama only" if config.offline() else "OpenRouter, then Ollama"))
        self.core.setText("<br>".join(f'<span style="color:{dim}">{pad(k, 10)}</span>{escape(str(v))}' for k, v in info))
        rows = []
        for r in self.ctx.feed[-self.FEED_ROWS:][::-1]:
            rows.append(f'<span style="color:{dim}">{r["time"]}</span> {escape(privacy.show(r["heard"][:40]))}<br>'
                        f'&nbsp;&nbsp;<span style="color:{acc}">{r["route"] or "..."}</span> <span style="color:{dim}">{r["provider"]}</span> <span style="color:{acc}">{r.get("tier", "")}</span>')
        self.feed.setText("<br><br>".join(rows) or
                          f'<span style="color:{dim}">Nothing heard yet.<br><br>Every command shows up here with how it was routed and which brain answered.</span>')
        self.log.setPlainText(privacy.show("\n".join(self.ctx.activity[-80:])) or "No activity yet.")
        self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())
        now = datetime.now()
        todo = sorted((r for r in reminders.pending() if datetime.fromisoformat(r["due"]).date() == now.date()), key=lambda r: r["due"])
        out = [f'<span style="color:{acc}">&#9679;</span> {datetime.fromisoformat(r["due"]):%H:%M} {escape(r["text"][:30])}' for r in todo[:3]]
        out = out or [f'<span style="color:{dim}">&#9675; no reminders today: say "remind me to ... at 7 pm"</span>']
        cur = pomodoro.status()
        out.append(f'<span style="color:{acc}">&#9679;</span> focus {pomodoro.left() / 60:.0f} min left ({cur["kind"]})' if cur else
                   f'<span style="color:{dim}">&#9675; no focus timer: say "start focus 25"</span>')
        nxt = study.next_item()
        out.append(f'<span style="color:{acc}">&#9679;</span> next: {escape(nxt[:34])}' if nxt else
                   f'<span style="color:{dim}">&#9675; no roadmap yet: add data/roadmap.md</span>')
        self.today.setText("<br>".join(out))


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
        current = play.now()
        if current is None:
            self.title.setText("nothing playing")
            self.pos.setText("")
            index = -1
        else:
            item, index = current
            title = item.get("title") or (mpvctl.send("get_property", "media-title") or {}).get("data") or "playing"
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
        for i, item in enumerate(play._state.get("results") or []):
            mark = ">" if i == index else " "
            self.queue.addItem(f"{mark} {str(item.get('title', item))[:90]}")


class Code(Page):
    """Left: the projects and what to build. Right: the build log and the run controls."""

    def __init__(self, ctx):
        super().__init__(ctx)
        t = ctx.theme
        row = QHBoxLayout()
        row.setSpacing(12)
        left = QVBoxLayout()
        left.setSpacing(10)
        proj = Panel(t, "Projects")
        self.list = QListWidget()
        self.list.currentTextChanged.connect(self.pick)
        proj.box.addWidget(self.list, 1)
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
        left.addWidget(proj, 1)
        left.addWidget(build)
        right = Panel(t, "Build log")
        run = QHBoxLayout()
        for text, fn in (("Run", lambda: ctx.run("run it")), ("Stop", lambda: procs.stop(coder.PROJECT)),
                         ("Fix last error", lambda: ctx.run("fix the last error")), ("Git init", lambda: ctx.run("git init this project"))):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, f=fn: f())
            run.addWidget(b)
        right.box.addLayout(run)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(mono(9))
        right.box.addWidget(self.log, 1)
        holder = QWidget()
        holder.setLayout(left)
        left.setContentsMargins(0, 0, 0, 0)
        row.addWidget(holder, 2)
        row.addWidget(right, 3)
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
        folder = coder.last.get("dir")
        tail = procs.tail(folder / ".run.log", 12) if folder and (folder / ".run.log").exists() else ""
        text = "\n".join(self.ctx.build[-30:]) + (("\n--- run log ---\n" + tail) if tail else "")
        self.log.setPlainText(privacy.show(text) or "Nothing built yet. Type what to build on the left, for example: a flask app that shows the time.")
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
        self.count = cap("")
        top.addWidget(self.search, 1)
        top.addWidget(self.count)
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
        mp = Panel(t, "Memory")
        self.memory = QListWidget()
        self.memory.setMaximumHeight(130)
        forget = QPushButton("Forget selected")
        forget.clicked.connect(self.forget_selected)
        mp.box.addWidget(self.memory)
        mp.box.addWidget(forget)
        side.addWidget(rp)
        side.addWidget(vp, 1)
        side.addWidget(mp)
        side.addWidget(ip)
        row.addWidget(gp, 3)
        holder = QWidget()
        holder.setLayout(side)
        side.setContentsMargins(0, 0, 0, 0)
        row.addWidget(holder, 2)
        self.root.addLayout(row, 1)
        self._sig = None
        self.files = {}
        self._texts = {}

    def files_now(self):
        """Every .md, .txt and .pdf in NOTES_DIR and RAG_FOLDERS, keyed by a short display name."""
        found = {}
        names = {}
        for path in sorted(rag.scan()):
            p = Path(path)
            if len(found) >= 60:
                break
            key = p.name if p.name not in names else f"{p.parent.name}/{p.name}"
            names[p.name] = p
            found[key] = p
        return found

    def text_of(self, p):
        stamp = p.stat().st_mtime
        hit = self._texts.get(p)
        if hit is None or hit[0] != stamp:
            try:
                hit = (stamp, rag.read_text(p)[:4000])
            except Exception:
                hit = (stamp, "")
            self._texts[p] = hit
        return hit[1]

    def load_graph(self):
        self.files = self.files_now()
        sig = tuple((n, p.stat().st_mtime) for n, p in self.files.items())
        if sig != self._sig:
            self._sig = sig
            self.graph.load([(n, self.text_of(p)) for n, p in self.files.items()])
            self.graph.highlight(self.search.text())
        self.count.setText(f"{rag.count()} indexed / {len(self.files)} on disk, {len(rag.folders())} folders")

    def open_note(self, name):
        p = self.files.get(name)
        if p:
            self.viewer.setPlainText(self.text_of(p)[:6000])

    def do_search(self):
        q = self.search.text().strip()
        self.results.clear()
        for h in rag.search(q, 5) if q else []:
            self.results.addItem(f"{h['name']}: {h['text'][:80]}")
        if not self.results.count():
            self.results.addItem("nothing found")

    def load_memory(self):
        rows = facts.listing()
        sig = tuple(r["id"] for r in rows)
        if sig == getattr(self, "_mem_sig", None):
            return
        self._mem_sig = sig
        self.memory.clear()
        for r in rows[:100]:
            item = QListWidgetItem(f"{r['date']}  {r['kind']}: {r['text']}")
            item.setData(Qt.ItemDataRole.UserRole, r["id"])
            self.memory.addItem(item)
        if not rows:
            self.memory.addItem("nothing remembered yet")

    def forget_selected(self):
        for item in self.memory.selectedItems():
            fid = item.data(Qt.ItemDataRole.UserRole)
            if fid:
                facts.delete(fid)
        self._mem_sig = None
        self.load_memory()

    def refresh(self):
        self.load_graph()
        self.load_memory()
        inbox = notes_store.NOTES_DIR / "inbox.md"
        self.inbox.setPlainText("\n".join(inbox.read_text(errors="replace", encoding="utf-8").splitlines()[-8:]) if inbox.exists() else "no inbox yet")


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
        review = QPushButton("Review due questions")
        review.clicked.connect(lambda: ctx.run("review due questions"))
        sc.box.addWidget(review)
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
        today = Panel(t, "Today, 20 minutes")
        self.today_item = value_label("")
        self.today_item.setWordWrap(True)
        start = QPushButton("Start")
        start.clicked.connect(self.start_today)
        today.box.addWidget(self.today_item)
        today.box.addWidget(start)
        left.addWidget(today)
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

    def start_today(self):
        self.ctx.run("start focus 20")

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
            rows.append(f'{pad(topic, 16)}<span style="color:{colour}">{acc * 100:.0f}%</span> of {r["asked"]}')
        weak = study.weak_topics(data)
        from ...actions import notes_quiz
        cards = data.get("cards", [])
        if cards:
            due = len(notes_quiz.due_cards(data))
            rows.append(f'<br><span style="color:{t.dim.name()}">notes cards: {len(cards)}, {due} due</span>')
            rows += [f'weak: {name} <span style="color:{t.bad.name()}">{share * 100:.0f}%</span> right' for name, share in notes_quiz.weak_topics(data)]
        self.scores.setText("<br>".join(rows) or "no quizzes yet")
        self.streak.setText(f"streak {study.streak(data)} days" + (f"   weak: {', '.join(weak[:2])}" if weak else ""))
        lines, items = study.roadmap_items()
        nxt = study.next_item()
        self.today_item.setText(nxt if nxt else "no open item in data/roadmap.md" if lines is not None else "no data/roadmap.md yet")
        self.road.clear()
        for _, done, text in items:
            self.road.addItem(("x " if done else "o ") + text)
        if lines is None:
            self.road.addItem("no data/roadmap.md yet")


class Jobs(Page):
    COLUMNS = ("Company", "Role", "Resume", "Status", "Applied", "Follow up", "Location")

    def __init__(self, ctx):
        super().__init__(ctx)
        t = ctx.theme
        top = QHBoxLayout()
        top.addWidget(cap("Status"))
        self.filter = QComboBox()
        self.filter.addItems(["all", "saved", "applied", "interview", "offer", "rejected"])
        self.filter.currentTextChanged.connect(lambda _: self.refresh())
        self.summary = value_label("")
        top.addWidget(self.filter)
        top.addWidget(self.summary, 1)
        self.root.addLayout(top)
        tp = Panel(t, "Jobs")
        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        tp.box.addWidget(self.table, 1)
        self.root.addWidget(tp, 1)
        hint = value_label('Say "add job Acme as data analyst", "update Acme to interview", "analyse this job", "what needs a follow-up". '
                           "Nothing is applied for or sent for you.")
        hint.setWordWrap(True)
        self.root.addWidget(hint)

    def refresh(self):
        from ...jobs import tracker
        jobs = tracker.load()
        by_status, by_resume = tracker.counts(jobs)
        pick = self.filter.currentText()
        shown = [j for j in jobs if pick in ("all", j["status"])]
        self.table.setRowCount(len(shown))
        for row, j in enumerate(sorted(shown, key=lambda j: j.get("id", 0), reverse=True)):
            for col, key in enumerate(("company", "role", "resume", "status", "applied", "follow_up", "location")):
                self.table.setItem(row, col, QTableWidgetItem(str(j.get(key) or "")))
        self.summary.setText("   ".join(f"{s} {n}" for s, n in by_status.items()) + "      resume: " + "  ".join(f"{r} {n}" for r, n in by_resume.items()))


class Web(Page):
    def __init__(self, ctx):
        super().__init__(ctx)
        t = ctx.theme
        st = Panel(t, "Browser agent")
        self.state = value_label("")
        st.box.addWidget(self.state)
        row = QHBoxLayout()
        self.goal = QLineEdit()
        self.goal.setPlaceholderText("give the browser a task, for example: find the cheapest USB-C cable on amazon")
        self.goal.returnPressed.connect(self.go)
        go = QPushButton("Go")
        go.clicked.connect(self.go)
        self.stop = QPushButton("Stop")
        self.stop.setObjectName("stop")
        self.stop.clicked.connect(self.abort)
        row.addWidget(self.goal, 1)
        row.addWidget(go)
        row.addWidget(self.stop)
        st.box.addLayout(row)
        self.confirm = ConfirmBar(ctx)
        self.root.addWidget(st)
        self.root.addWidget(self.confirm)
        sp = Panel(t, "Steps")
        self.steps = QListWidget()
        self.head = value_label("")
        sp.box.addWidget(self.head)
        sp.box.addWidget(self.steps, 1)
        self.root.addWidget(sp, 1)
        rules = Panel(t, "Safety rules")
        rules.box.addWidget(value_label("Never types passwords, cards, codes or keys. Asks before submit, send, post, buy, delete and login clicks. "
                                        "Asks before any download. Stops at a captcha. Page text is data, never instructions. "
                                        "Ctrl+. , the Stop button, the word stop or AGENT_ABORT_KEY end a task. Own profile in data/browser-profile."))
        self.root.addWidget(rules)
        quick = QHBoxLayout()
        for text in ("close the browser", "new tab", "read this page"):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, c=text: ctx.run(c))
            quick.addWidget(b)
        self.root.addLayout(quick)
        self._seen = None

    def go(self):
        text = self.goal.text().strip()
        if text:
            self.goal.clear()
            self.ctx.run("use the browser to " + text)

    def abort(self):
        from ...actions import web_agent
        web_agent.abort()

    def refresh(self):
        from ...actions import browser, web_agent
        if not browser.playwright_ok():
            msg = "Playwright is not installed. Run: pip install playwright"
        elif not browser.ready():
            msg = "No browser found for Playwright. Install Google Chrome or run: playwright install chromium"
        else:
            msg = "browser open" if browser.active() else "browser closed, ready"
        self.state.setText(msg)
        run = web_agent.RUN
        self.stop.setEnabled(web_agent.running())
        self.head.setText((f"{run['status'].upper()}  step {len(run['steps'])} of {web_agent.max_steps()}  {run['goal'][:80]}" if run["goal"] else "no task yet")
                          + (f"\n{run['note'][:120]}" if run["note"] else ""))
        sig = (len(run["steps"]), run["status"], tuple(run["plan"]))
        if sig != self._seen:
            self._seen = sig
            self.steps.clear()
            for i, s in enumerate(run["plan"], 1):
                self.steps.addItem(f"plan {i}: {s}")
            for s in run["steps"]:
                self.steps.addItem(f"{s['n']}. {s['action']} {s['detail']} -> {s['result']}")
            self.steps.scrollToBottom()
        self.confirm.refresh()


def local_summary():
    """The Stats line for the local model: the average first-word time of the last 10 turns, from data/local-turns.json."""
    from ...brain import local
    rows = local.recent_turns()
    avg, n = local.average_first_word()
    if not rows:
        return "No local turns yet."
    if avg is None:
        return f"No first word in the last {len(rows)} local turns."
    slow = max((r["first"] for r in rows if r.get("first") is not None), default=0)
    return f"Average first word {avg:.1f} s over {n} of the last {len(rows)} local turns (slowest {slow:.1f} s)"


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
        bench_panel = Panel(t, "Benchmark")
        self.bench = value_label("")
        self.bench.setWordWrap(True)
        bench_panel.box.addWidget(self.bench)
        local_panel = Panel(t, "Local model")
        self.local = value_label("")
        local_panel.box.addWidget(self.local)
        sysp = Panel(t, "This process")
        self.sys = value_label("")
        sysp.box.addWidget(self.sys)
        for w in (self.eval, bench_panel, use, local_panel, sysp):
            self.root.addWidget(w)
        self.root.addStretch(1)

    def refresh(self):
        ev = stats.latest_eval()
        if ev:
            self.eval_text.setText(f"{ev['passed']}/{ev['total']} passed   {ev['avg_tokens']} tokens avg   {ev['date']}")
        else:
            self.eval_text.setText("no eval yet: python scripts/eval_phrases.py")
        core = stats.core_rate()
        if core:
            self.eval_text.setText(self.eval_text.text() + f"   core {core['passed']}/{core['total']}")
        from ... import bench
        latest = bench.latest()
        self.bench.setText(bench.describe(latest) if latest else "no benchmark yet: python -m jarvis.bench")
        week, today = stats.usage()
        rows = []
        for key, label in stats.PROVIDERS:
            r = week.get(key, {"calls": 0, "tokens": 0})
            t = today.get(key, {})
            rows.append(f"{label:<12} today {t.get('tokens', 0):>7} tokens, {t.get('calls', 0):>3} requests   week {r['tokens']:>7} tokens, {r['calls']:>4} requests")
        used, cap, sent = stats.advanced_today()
        setup = "" if (config.get("GROQ_API_KEY") or config.get("OPENROUTER_API_KEY")) else "   needs setup: no cloud key"
        rows.append(f"{'Advanced':<12} today {sent:>7} tokens, {used:>3} of {cap} calls{setup}")
        rows.append(f"rate limits hit this session: {brain.LIMITED['count']}")
        self.use.setText("<pre>" + "\n".join(rows) + "</pre>")
        self.local.setText(local_summary())
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
        self.reduced = QCheckBox("Reduced motion (no particles, drift or transitions)")
        self.reduced.toggled.connect(window.set_reduced_motion)
        self.tint = QCheckBox("State colours (accent follows listening, thinking, error)")
        self.tint.toggled.connect(lambda on: window.set_ui_flag("state_colours", on))
        self.cycle = QCheckBox("Slowly cycle the hue")
        self.cycle.toggled.connect(lambda on: window.set_ui_flag("cycle", on))
        self.mute = QCheckBox("Mute Jarvis's voice")
        self.mute.toggled.connect(lambda on: state.update(muted=bool(on)))
        self.crowd = QCheckBox("Crowd mode (wake word for every command, no follow-up window)")
        self.crowd.toggled.connect(listen.set_crowd)
        for w in (self.low, self.reduced, self.tint, self.cycle, self.mute, self.crowd):
            opt.box.addWidget(w)
        keys = Panel(t, "Keys")
        self.keys = value_label("")
        keys.box.addWidget(self.keys)
        doc = Panel(t, "Doctor")
        self.doctor_text = value_label("Press the button to check the microphone, wake word, keys, offline model, tools, voice and memory.")
        self.doctor_text.setTextFormat(Qt.TextFormat.RichText)
        self.doctor_text.setWordWrap(True)
        self.doctor_btn = QPushButton("Run diagnostics")
        self.doctor_btn.clicked.connect(self.run_doctor)
        doc.box.addWidget(self.doctor_btn)
        doc.box.addWidget(self.doctor_text)
        self._doctor = {"results": None, "running": False}
        for w in (tp, opt, keys, doc):
            self.root.addWidget(w)
        self.root.addStretch(1)

    def run_doctor(self):
        """The checks can take a few seconds (microphone, Ollama), so they run off the window thread and the next refresh shows them."""
        if self._doctor["running"]:
            return
        import threading
        from ... import doctor
        self._doctor["running"] = True
        self.doctor_btn.setEnabled(False)
        self.doctor_text.setText("checking ...")

        def go():
            try:
                self._doctor["results"] = doctor.run()
            finally:
                self._doctor["running"] = False
        threading.Thread(target=go, daemon=True).start()

    def doctor_html(self):
        from html import escape
        t = self.ctx.theme
        colours = {"pass": t.ok.name(), "warn": t.warn.name(), "fail": t.bad.name()}
        rows = []
        for r in self._doctor["results"]:
            fix = f' <span style="color:{t.dim.name()}">{escape(r["fix"])}</span>' if r["fix"] and r["status"] != "pass" else ""
            rows.append(f'<span style="color:{colours[r["status"]]}">{pad(r["status"].upper(), 7)}</span>{escape(r["name"])}: {escape(r["detail"])}{fix}')
        return "<br>".join(rows)

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
        for box, value in ((self.low, self.window.low_manual), (self.reduced, self.window.reduced), (self.tint, th.state_colours), (self.cycle, th.cycle), (self.mute, state.get("muted")), (self.crowd, listen.crowd())):
            box.blockSignals(True)
            box.setChecked(bool(value))
            box.blockSignals(False)
        self.hue.blockSignals(True)
        self.hue.setValue(int(th.hue) % 360)
        self.hue.blockSignals(False)

    def refresh(self):
        self.sync()
        if self._doctor["results"] is not None and not self._doctor["running"]:
            self.doctor_text.setText(self.doctor_html())
            self.doctor_btn.setEnabled(True)
        from ... import telegram
        lines = [f"{k}: {'set' if config.get(k) else 'not set'}" for k in KEYS]
        code = telegram.pairing_code()
        lines.append("telegram: " + telegram.status() + (f", pairing code {code}" if code else ""))
        self.keys.setText("\n".join(lines))
