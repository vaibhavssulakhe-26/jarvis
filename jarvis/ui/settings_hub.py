"""The Settings screen of the new window: General (the older page, unchanged), Profile, Memory, Customization, and Models and providers. Everything shown
comes from the real stores; nothing here ever reads or shows an API key."""
import threading
import time

from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QScrollArea, QSlider,
                             QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ..brain import registry
from ..core import config, lang, profile
from ..memory import controls, manager
from ..voice import voices
from . import design

SECTIONS = (("general", "General"), ("profile", "Profile"), ("memory", "Memory"), ("customize", "Customization"), ("models", "Models and providers"))
CARD_REFRESH_S = 4


def label(text="", dim=False, size=13, wrap=True):
    lab = QLabel(text)
    lab.setWordWrap(wrap)
    lab.setFont(design.font(size))
    if dim:
        lab.setObjectName("dim")
    lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return lab


def title(text):
    lab = QLabel(text)
    lab.setFont(design.font(18))
    return lab


def card():
    frame = QFrame()
    frame.setObjectName("card")
    frame.setStyleSheet(f"QFrame#card {{ background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.10); border-radius: {design.RADIUS['m']}px; }}")
    box = QVBoxLayout(frame)
    box.setContentsMargins(design.SPACE["m"], design.SPACE["m"], design.SPACE["m"], design.SPACE["m"])
    box.setSpacing(design.SPACE["s"])
    return frame, box


def row(*widgets, stretch=None):
    r = QHBoxLayout()
    r.setSpacing(design.SPACE["s"])
    for i, w in enumerate(widgets):
        r.addWidget(w, 1 if (stretch == i) else 0)
    return r


class Section(QWidget):
    """Base of the sub-pages: a column of cards, with refresh() called when it is shown."""

    def __init__(self):
        super().__init__()
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(0, 0, design.SPACE["m"], 0)
        self.root.setSpacing(design.SPACE["m"])

    def refresh(self):
        pass


# ---------------------------------------------------------------- profile
class ProfilePage(Section):
    saved = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.root.addWidget(title("Profile"))
        self.root.addWidget(label("How Jarvis addresses you. Saving applies at once to greetings, prompts, the self block and this window, and is kept across restarts. "
                                  "Nothing said in a conversation can change these.", dim=True))
        frame, box = card()
        self.full = QLineEdit()
        self.preferred = QLineEdit()
        self.nick = QLineEdit()
        for edit, name, hint in ((self.full, "Full name", "used in drafts and emails"), (self.preferred, "Preferred name", "what Jarvis calls you in writing"),
                                 (self.nick, "Nickname", "what Jarvis says out loud")):
            edit.setAccessibleName(name)
            edit.setPlaceholderText(hint)
            edit.setMaxLength(profile.NAME_MAX)
            box.addWidget(label(name, dim=True, size=12))
            box.addWidget(edit)
        self.prefs = QPlainTextEdit()
        self.prefs.setAccessibleName("Preferences")
        self.prefs.setPlaceholderText("for example: short answers, metric units, explain things step by step")
        self.prefs.setFixedHeight(90)
        box.addWidget(label("Preferences", dim=True, size=12))
        box.addWidget(self.prefs)
        self.save_btn = QPushButton("Save profile")
        self.save_btn.clicked.connect(self.save)
        self.note = label("", dim=True)
        box.addLayout(row(self.save_btn, self.note, stretch=1))
        self.root.addWidget(frame)
        self.preview = label("", dim=True)
        self.root.addWidget(self.preview)
        self.root.addStretch(1)
        self.load()

    def load(self):
        p = profile.load()
        self.full.setText(p["full_name"] or config.FULL_NAME)
        self.preferred.setText(p["preferred_name"] or config.SHORT_NAME)
        self.nick.setText(p["nickname"] or config.PET_NAME)
        self.prefs.setPlainText(p["preferences"])
        self.preview.setText(f"Jarvis will say: \"Good morning, {config.PET_NAME or config.SHORT_NAME or 'there'}.\"")

    def save(self):
        profile.save(full_name=self.full.text(), preferred_name=self.preferred.text(), nickname=self.nick.text(), preferences=self.prefs.toPlainText())
        self.load()
        self.note.setText("Saved. Greetings and prompts use it now.")
        self.saved.emit()

    def refresh(self):
        pass


# ---------------------------------------------------------------- memory
class MemoryPage(Section):
    def __init__(self):
        super().__init__()
        self.items = []
        self.root.addWidget(title("Memory"))
        frame, box = card()
        self.paused = QCheckBox("Pause remembering (nothing new is saved while this is on)")
        self.paused.toggled.connect(self.on_paused)
        box.addWidget(self.paused)
        box.addWidget(label("What may be remembered", dim=True, size=12))
        self.boxes = {}
        grid = QHBoxLayout()
        for group, names in (("Ordinary", controls.NORMAL), ("Sensitive, off by default", controls.SENSITIVE)):
            col = QVBoxLayout()
            col.addWidget(label(group, dim=True, size=12))
            for c in names:
                b = QCheckBox(controls.LABELS[c])
                b.toggled.connect(lambda on, c=c: self.on_category(c, on))
                self.boxes[c] = b
                col.addWidget(b)
            col.addStretch(1)
            grid.addLayout(col)
        box.addLayout(grid)
        box.addWidget(label(f"Never stored, whatever these say: {controls.NEVER}.", dim=True, size=12))
        self.root.addWidget(frame)

        frame2, box2 = card()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search memories")
        self.search.setAccessibleName("Search memories")
        self.search.textChanged.connect(self.reload)
        self.filter = QComboBox()
        self.filter.setAccessibleName("Category filter")
        self.filter.currentIndexChanged.connect(self.reload)
        self.count = label("", dim=True, size=12)
        box2.addLayout(row(self.search, self.filter, self.count, stretch=0))
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Date", "Category", "Memory"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setMinimumHeight(180)
        self.table.setAccessibleName("Memories")
        self.table.itemSelectionChanged.connect(self.open_selected)
        box2.addWidget(self.table)
        self.editor = QPlainTextEdit()
        self.editor.setAccessibleName("Selected memory")
        self.editor.setFixedHeight(70)
        self.category = QComboBox()
        self.category.setAccessibleName("Category of the selected memory")
        for c in manager.EDITABLE_CATEGORIES:
            self.category.addItem(controls.LABELS[c], c)
        self.save_btn = QPushButton("Save edit")
        self.save_btn.clicked.connect(self.save_edit)
        self.delete_btn = QPushButton("Delete selected")
        self.delete_btn.clicked.connect(self.delete_selected)
        self.clear_btn = QPushButton("Clear all")
        self.clear_btn.clicked.connect(self.clear_all)
        self._clear_until = 0.0
        box2.addWidget(self.editor)
        box2.addLayout(row(self.category, self.save_btn, self.delete_btn, self.clear_btn))
        self.note = label("", dim=True, size=12)
        box2.addWidget(self.note)
        self.root.addWidget(frame2)
        self.root.addStretch(1)
        self.sync_controls()
        self.reload()

    # controls
    def sync_controls(self):
        data = controls.load()
        for widget, value in [(self.paused, data["paused"])] + [(self.boxes[c], data["categories"][c]) for c in controls.CATEGORIES]:
            widget.blockSignals(True)
            widget.setChecked(value)
            widget.blockSignals(False)

    def on_paused(self, on):
        controls.set_paused(on)
        self.note.setText("Remembering is paused." if on else "Remembering is on.")

    def on_category(self, category, on):
        controls.set_category(category, on)
        self.note.setText(f"{controls.LABELS[category]}: {'may be remembered' if on else 'will not be remembered'}.")

    # list
    def reload(self, *_):
        every = manager.entries()
        present = manager.categories_present(every)
        chosen = self.filter.currentData() if self.filter.count() else ""
        self.filter.blockSignals(True)
        self.filter.clear()
        self.filter.addItem("All categories", "")
        for c in present:
            self.filter.addItem(controls.LABELS.get(c, c.capitalize()), c)
        idx = self.filter.findData(chosen)
        self.filter.setCurrentIndex(max(0, idx))
        self.filter.blockSignals(False)
        self.items = manager.search(self.search.text(), self.filter.currentData() or "", every)
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.items))
        for i, e in enumerate(self.items):
            for j, text in enumerate((e.date, controls.LABELS.get(e.category, e.category.capitalize()), e.text)):
                self.table.setItem(i, j, QTableWidgetItem(text))
        self.table.blockSignals(False)
        self.count.setText(f"{len(self.items)} of {len(every)}")
        self.editor.clear()

    def selected(self):
        return [self.items[i.row()] for i in self.table.selectionModel().selectedRows()] if self.table.selectionModel() else []

    def open_selected(self):
        sel = self.selected()
        if len(sel) == 1:
            e = sel[0]
            self.editor.setPlainText(e.text)
            idx = self.category.findData(e.category)
            self.category.setCurrentIndex(max(0, idx))
            self.category.setEnabled(e.store in ("facts", "memory"))
            self.editor.setEnabled(True)
        else:
            self.editor.clear()

    def save_edit(self):
        sel = self.selected()
        if len(sel) != 1:
            self.note.setText("Select one memory to edit.")
            return
        e = sel[0]
        cat = self.category.currentData() if e.store in ("facts", "memory") and self.category.currentData() != e.category else None
        ok, why = manager.update(e.ref, self.editor.toPlainText(), cat)
        self.note.setText("Saved." if ok else why)
        if ok:
            self.reload()

    def delete_selected(self):
        sel = self.selected()
        n = manager.delete([e.ref for e in sel]) if sel else 0
        self.note.setText(f"Deleted {n}." if sel else "Select what to delete first.")
        self.reload()

    def clear_all(self):
        """Two clicks inside five seconds: the first arms the button, the second wipes everything."""
        now = time.monotonic()
        if now > self._clear_until:
            self._clear_until = now + 5
            self.clear_btn.setText("Click again to clear all")
            self.note.setText("This forgets every saved memory, person and conversation summary.")
            QTimer.singleShot(5200, lambda: self.clear_btn.setText("Clear all"))
            return
        self._clear_until = 0.0
        n = manager.clear_all()
        self.clear_btn.setText("Clear all")
        self.note.setText(f"Cleared {n} memories.")
        self.reload()

    def refresh(self):
        self.sync_controls()


# ---------------------------------------------------------------- customization
class CustomizePage(Section):
    changed = pyqtSignal()

    def __init__(self, dash):
        super().__init__()
        self.dash = dash
        self.root.addWidget(title("Customization"))
        self.root.addWidget(label("Everything here applies live and is kept across restarts. Accent colours that would be hard to read are lightened to keep a 4.5:1 contrast.", dim=True))
        s = design.settings()

        f, b = card()
        b.addWidget(label("Theme and colours", dim=True, size=12))
        self.theme = QComboBox()
        self.theme.setAccessibleName("Theme")
        self.theme.addItem("Choose a theme", "")
        for key, spec in design.THEMES.items():
            self.theme.addItem(spec["label"], key)
        self.theme.currentIndexChanged.connect(self.on_theme)
        self.swatches = []
        sw = QHBoxLayout()
        for name, hexv in design.ACCENT_PRESETS.items():
            btn = QPushButton(name)
            btn.setAccessibleName("Accent " + name)
            btn.setStyleSheet(f"QPushButton {{ border-left: 12px solid {hexv}; }}")
            btn.clicked.connect(lambda _=False, h=hexv: self.set_accent(h))
            sw.addWidget(btn)
            self.swatches.append(btn)
        self.hex = QLineEdit(s["accent"])
        self.hex.setAccessibleName("Accent colour as hex")
        self.hex.setMaxLength(7)
        self.hex.setFixedWidth(110)
        self.apply_hex = QPushButton("Apply colour")
        self.apply_hex.clicked.connect(lambda: self.set_accent(self.hex.text()))
        self.accent_note = label("", dim=True, size=12)
        b.addLayout(row(self.theme))
        b.addLayout(sw)
        b.addLayout(row(label("Accent", dim=True, size=12), self.hex, self.apply_hex, self.accent_note, stretch=3))
        self.background = QComboBox()
        self.background.setAccessibleName("Background")
        for key, spec in design.BACKGROUNDS.items():
            self.background.addItem(spec["label"], key)
        self.background.currentIndexChanged.connect(lambda: design.update(background=self.background.currentData()))
        b.addLayout(row(label("Background", dim=True, size=12), self.background, stretch=1))
        self.root.addWidget(f)

        f, b = card()
        b.addWidget(label("Globe and motion", dim=True, size=12))
        self.globe = {}
        for key, name in (("density", "Dots"), ("size", "Size"), ("glow", "Glow")):
            combo = QComboBox()
            combo.setAccessibleName("Globe " + name.lower())
            for opt in design.GLOBE_OPTIONS[key]:
                combo.addItem(opt.capitalize(), opt)
            combo.currentIndexChanged.connect(lambda _=0, k=key, c=combo: design.update(globe={k: c.currentData()}))
            self.globe[key] = combo
            b.addLayout(row(label(name, dim=True, size=12), combo, stretch=1))
        self.intensity = QSlider(Qt.Orientation.Horizontal)
        self.intensity.setRange(0, 100)
        self.intensity.setAccessibleName("Animation intensity")
        self.intensity.valueChanged.connect(lambda v: design.update(intensity=v))
        b.addLayout(row(label("Animation intensity", dim=True, size=12), self.intensity, stretch=1))
        self.root.addWidget(f)

        f, b = card()
        b.addWidget(label("Chat appearance", dim=True, size=12))
        self.chat_size = QComboBox()
        self.chat_size.setAccessibleName("Chat text size")
        for pt in design.CHAT_SIZES:
            self.chat_size.addItem(f"{pt} pt", pt)
        self.chat_size.currentIndexChanged.connect(lambda: design.update(chat={"size": self.chat_size.currentData()}))
        self.chat_density = QComboBox()
        self.chat_density.setAccessibleName("Chat spacing")
        for opt in design.CHAT_DENSITY:
            self.chat_density.addItem(opt.capitalize(), opt)
        self.chat_density.currentIndexChanged.connect(lambda: design.update(chat={"density": self.chat_density.currentData()}))
        b.addLayout(row(label("Text size", dim=True, size=12), self.chat_size, label("Spacing", dim=True, size=12), self.chat_density, stretch=1))
        self.root.addWidget(f)

        f, b = card()
        b.addWidget(label("Reply language", dim=True, size=12))
        self.reply = QComboBox()
        self.reply.setAccessibleName("Reply language")
        for name, key in (("Auto: English, or the language you write in", ""), ("English", "english"), ("Hindi", "hindi"), ("Kannada", "kannada")):
            self.reply.addItem(name, key)
        self.reply.currentIndexChanged.connect(self.on_reply)
        self.reply_now = label("", dim=True, size=12)
        b.addLayout(row(self.reply, self.reply_now, stretch=1))
        b.addWidget(label("You can also say: reply in English, talk in Hindi.", dim=True, size=12))
        self.root.addWidget(f)

        f, b = card()
        b.addWidget(label("Assistant personality", dim=True, size=12))
        self.personality = QComboBox()
        self.personality.setAccessibleName("Personality")
        for key, (name, _) in profile.PERSONALITIES.items():
            self.personality.addItem(name, key)
        self.personality.currentIndexChanged.connect(lambda: profile.save(personality=self.personality.currentData()))
        b.addLayout(row(self.personality, stretch=0))
        self.root.addWidget(f)

        f, b = card()
        b.addWidget(label("Voice", dim=True, size=12))
        self.voice = QComboBox()
        self.voice.setAccessibleName("Voice")
        self.voice.currentIndexChanged.connect(self.on_voice)
        self.speed = QSlider(Qt.Orientation.Horizontal)
        self.speed.setRange(70, 140)
        self.speed.setAccessibleName("Speaking speed")
        self.speed.valueChanged.connect(lambda v: voices.set_speed(v / 100))
        self.speed_label = label("", dim=True, size=12)
        self.test = QPushButton("Test voice")
        self.test.clicked.connect(self.test_voice)
        b.addLayout(row(self.voice, self.test, stretch=0))
        b.addLayout(row(label("Speed", dim=True, size=12), self.speed, self.speed_label, stretch=1))
        self.root.addWidget(f)
        self.root.addStretch(1)
        self.load()

    def load(self):
        """Put the saved values into the controls without triggering a save."""
        s = design.settings()
        widgets = [self.theme, self.background, self.intensity, self.chat_size, self.chat_density, self.personality, self.voice, self.speed] + list(self.globe.values())
        for w in widgets:
            w.blockSignals(True)
        self.background.setCurrentIndex(max(0, self.background.findData(s["background"])))
        for key, combo in self.globe.items():
            combo.setCurrentIndex(max(0, combo.findData(s["globe"][key])))
        self.intensity.setValue(int(s["intensity"]))
        self.chat_size.setCurrentIndex(max(0, self.chat_size.findData(s["chat"]["size"])))
        self.chat_density.setCurrentIndex(max(0, self.chat_density.findData(s["chat"]["density"])))
        self.personality.setCurrentIndex(max(0, self.personality.findData(profile.load()["personality"])))
        self.reply.blockSignals(True)
        self.reply.setCurrentIndex(max(0, self.reply.findData({"en": "english", "hi": "hindi", "kn": "kannada"}.get(lang.reply_setting(), ""))))
        self.reply.blockSignals(False)
        self.reply_now.setText("Replies now: " + lang.label())
        self.voice.clear()
        for name in voices.installed():
            self.voice.addItem(voices.label(name), name)
        self.voice.setCurrentIndex(max(0, self.voice.findData(voices.current_name())))
        self.speed.setValue(int(round(voices.speed() * 100)))
        self.speed_label.setText(f"{voices.speed():.2f}x")
        for w in widgets:
            w.blockSignals(False)
        self.hex.setText(s["accent"])
        self.show_accent()

    def show_accent(self):
        raw, used = design.settings()["accent"], design.ACCENT
        self.accent_note.setText(f"In use: {used}" + (" (lightened for contrast)" if used.lower() != raw.lower() else ""))

    def set_accent(self, text):
        text = str(text).strip()
        if not QColor(text).isValid() or not text.startswith("#"):
            self.accent_note.setText("Use a colour like #4cc2ff.")
            return
        design.update(accent=text)
        self.dash.set_hue(max(0, QColor(design.ACCENT).hueF()) * 360)
        self.show_accent()

    def on_reply(self):
        lang.set_reply(self.reply.currentData() or "auto")
        self.reply_now.setText("Replies now: " + lang.label())

    def on_theme(self):
        key = self.theme.currentData()
        if key:
            design.apply_theme(key)
            self.dash.set_theme(design.THEMES[key]["classic"])
            self.load()

    def on_voice(self):
        name = self.voice.currentData()
        if name:
            voices.choose(name)

    def test_voice(self):
        from ..voice import voice
        threading.Thread(target=lambda: voice.say("This is how I sound now."), daemon=True).start()

    def refresh(self):
        self.reply_now.setText("Replies now: " + lang.label())


# ---------------------------------------------------------------- models and providers
class _Bridge(QObject):
    done = pyqtSignal(str, object)


class ModelsPage(Section):
    def __init__(self):
        super().__init__()
        self.bridge = _Bridge()
        self.bridge.done.connect(self.on_done)
        self.cards = {}
        self.root.addWidget(title("Models and providers"))
        self.mode = label("", dim=True)
        self.root.addWidget(self.mode)
        self.keys = label(registry.where_keys(), dim=True, size=12)
        self.root.addWidget(self.keys)
        self.holder = QVBoxLayout()
        self.holder.setSpacing(design.SPACE["m"])
        self.root.addLayout(self.holder)
        self.root.addStretch(1)
        self._at = 0.0
        self.refresh(force=True)

    def _build(self, pid):
        frame, box = card()
        head = QHBoxLayout()
        name = QLabel("")
        name.setFont(design.font(16))
        badge = label("", dim=True, size=12, wrap=False)
        head.addWidget(name)
        head.addWidget(badge)
        head.addStretch(1)
        check = QPushButton("Check now")
        check.setAccessibleName(f"Check {pid}")
        check.clicked.connect(lambda: self.run_probe(pid))
        head.addWidget(check)
        box.addLayout(head)
        body = label("", size=12)
        box.addWidget(body)
        model = QComboBox()
        model.setEditable(True)
        model.setAccessibleName(f"{pid} model")
        model.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        apply_btn = QPushButton("Use this model")
        apply_btn.clicked.connect(lambda: self.choose(pid))
        reset = QPushButton("Default")
        reset.clicked.connect(lambda: self.choose(pid, ""))
        pick = [label("Model", dim=True, size=12, wrap=False), model, apply_btn, reset]
        extra = None
        if pid in ("ollama", "openrouter"):
            extra = QPushButton("Load installed models" if pid == "ollama" else "Load OpenRouter models")
            extra.clicked.connect(lambda: self.load_models(pid))
            pick.append(extra)
        box.addLayout(row(*pick, stretch=1))
        self.holder.addWidget(frame)
        self.cards[pid] = {"frame": frame, "name": name, "badge": badge, "body": body, "model": model, "check": check, "extra": extra}

    def refresh(self, force=False):
        if not force and time.monotonic() - self._at < CARD_REFRESH_S:
            return
        self._at = time.monotonic()
        data = registry.providers()
        order = registry.order()
        primary = next((p for p, r in order if r == "primary"), "")
        backups = [registry.LABELS.get(p, p.capitalize()) for p, r in order if r in ("fallback", "advanced")]
        self.mode.setText(f"Mode {config.brain_mode().replace('_', ' ')}. Primary: {registry.LABELS.get(primary, primary)}. "
                          + ("Fallback: " if config.brain_mode() == "hybrid" else "Advanced and backup: ") + (", ".join(backups) or "none") + ".")
        for d in data:
            if d["id"] not in self.cards:
                self._build(d["id"])
            c = self.cards[d["id"]]
            c["name"].setText(d["label"])
            c["badge"].setText({"primary": "PRIMARY", "fallback": "FALLBACK", "advanced": "ADVANCED / BACKUP", "off": "NOT IN USE"}[d["role"]])
            u = d["usage"]
            lines = [f"Configured: {'yes' if d['configured'] else 'no'}" + ("" if d["key_set"] is None else f"   key {d['key_var']}: {'set' if d['key_set'] else 'not set'} (in .env)"),
                     f"Last real call: {d['last_call']}", f"Reachable: {d['reachable']}   (only checked when you press Check now)", f"Address: {d['url'] or 'not set'}",
                     "Can do: " + ", ".join(d["capabilities"]),
                     f"Usage, last 7 days: {u['calls']} answers, about {u['tokens']} tokens; today {u['today_calls']}. Traces: {u['ok']} worked, {u['failed']} failed"
                     + (f", {u['avg_ms']} ms on average." if u["avg_ms"] else ".")]
            lines.append("Recent errors: " + ("; ".join(d["errors"]) if d["errors"] else "none"))
            c["body"].setText("\n".join(lines))
            combo = c["model"]
            if not combo.hasFocus() and combo.count() == 0:
                combo.setEditText(d["model"])

    def run_probe(self, pid):
        self.cards[pid]["check"].setEnabled(False)
        threading.Thread(target=lambda: self.bridge.done.emit("probe:" + pid, registry.probe(pid)), daemon=True).start()

    def load_models(self, pid):
        card_ = self.cards[pid]
        card_["extra"].setEnabled(False)
        fn = registry.installed_models if pid == "ollama" else (lambda: [m["id"] for m in registry.openrouter_models(refresh=True)])
        threading.Thread(target=lambda: self.bridge.done.emit("models:" + pid, fn()), daemon=True).start()

    def on_done(self, key, value):
        kind, pid = key.split(":", 1)
        c = self.cards.get(pid)
        if not c:
            return
        if kind == "probe":
            c["check"].setEnabled(True)
        else:
            c["extra"].setEnabled(True)
            current = c["model"].currentText()
            c["model"].clear()
            c["model"].addItems([str(v) for v in value])
            c["model"].setEditText(current)
        self.refresh(force=True)

    def choose(self, pid, model=None):
        text = self.cards[pid]["model"].currentText() if model is None else model
        registry.select_model(pid, text)
        self.cards[pid]["model"].setEditText(registry.selected_model(pid))
        self.refresh(force=True)


# ---------------------------------------------------------------- the hub
class SettingsHub(QWidget):
    """The Settings destination: a short list of sections on the left, the chosen one on the right."""

    def __init__(self, ctx, dash, general):
        super().__init__()
        self.ctx, self.dash = ctx, dash
        self.pages = {}
        box = QHBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(design.SPACE["m"])
        side = QVBoxLayout()
        side.setSpacing(design.SPACE["xs"])
        self.buttons = {}
        for key, name in SECTIONS:
            b = QPushButton(name)
            b.setCheckable(True)
            b.setAccessibleName(name)
            b.setStyleSheet("QPushButton { text-align: left; padding: 8px 14px; } QPushButton:checked { background: rgba(140,157,255,0.22); border: 1px solid rgba(140,157,255,0.6); }")
            b.clicked.connect(lambda _=False, k=key: self.show_section(k))
            side.addWidget(b)
            self.buttons[key] = b
        side.addStretch(1)
        sidebar = QWidget()
        sidebar.setLayout(side)
        sidebar.setFixedWidth(210)
        box.addWidget(sidebar)
        self.stack = QStackedWidget()
        box.addWidget(self.stack, 1)
        self.profile = ProfilePage()
        self.memory = MemoryPage()
        self.customize = CustomizePage(dash)
        self.models = ModelsPage()
        for key, page in (("general", general), ("profile", self.profile), ("memory", self.memory), ("customize", self.customize), ("models", self.models)):
            if key != "general":
                holder = QScrollArea()
                holder.setWidgetResizable(True)
                holder.setFrameShape(QFrame.Shape.NoFrame)
                holder.setWidget(page)
                holder.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }")
                widget = holder
            else:
                widget = general
            self.pages[key] = page
            self.stack.addWidget(widget)
        self._widgets = {k: self.stack.widget(i) for i, (k, _) in enumerate(SECTIONS)}
        self.show_section("general")

    @property
    def current(self):
        return next((k for k, w in self._widgets.items() if w is self.stack.currentWidget()), "general")

    def show_section(self, key):
        if key not in self.pages:
            return
        for k, b in self.buttons.items():
            b.setChecked(k == key)
        self.stack.setCurrentWidget(self._widgets[key])
        if key == "memory":
            self.memory.reload()
        elif key == "profile":
            self.profile.load()
        elif key == "customize":
            self.customize.load()
        self.refresh()

    def refresh(self):
        page = self.pages[self.current]
        try:
            page.refresh()
        except Exception:
            import traceback
            traceback.print_exc()

    def strings(self):
        """Every piece of text on the screen, for the checks that look for keys."""
        out = []
        for w in self.findChildren(QLabel):
            out.append(w.text())
        for w in self.findChildren((QLineEdit, QPushButton, QComboBox)):
            out.append(w.text() if hasattr(w, "text") else w.currentText())
        for w in self.findChildren(QPlainTextEdit):
            out.append(w.toPlainText())
        return out
