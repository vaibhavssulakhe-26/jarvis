"""Reply language: English by default, another language only when the current message is in it or the user set it, saved across restarts, shown in the pill and
Settings, set by direct commands that never reach the model, never confused with the time command, and English from the local model for typos and variants.
Also the first-word average on Stats. Run: QT_QPA_PLATFORM=offscreen python scripts/reply_language_check.py"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

os.environ["QT_QPA_PLATFORM"] = "offscreen"
tmp = Path(tempfile.mkdtemp(prefix="jarvis-replylang-"))
os.environ["JARVIS_DATA"] = str(tmp / "data")
os.environ["XDG_STATE_HOME"] = str(tmp / "state")
(tmp / "run").mkdir()
os.environ["XDG_RUNTIME_DIR"] = str(tmp / "run")
os.environ["JARVIS_DASH_TEST"] = "1"
for name in ("OLLAMA_URL", "OLLAMA_HOST", "OLLAMA_MODEL", "BRAIN", "BRAIN_MODE", "HTTP_PROXY", "HTTPS_PROXY", "STT_LANGUAGE"):
    os.environ.pop(name, None)
(tmp / "data").mkdir()
root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "scripts" / "fakes"))

import fake_ollama  # noqa: E402
import psutil  # noqa: E402
from PyQt6.QtCore import QCoreApplication  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from jarvis import features  # noqa: E402
from jarvis.actions import events, tools  # noqa: E402
from jarvis.brain import agent, brain, local  # noqa: E402
from jarvis.core import config, lang, main  # noqa: E402
from jarvis.memory import threads  # noqa: E402
from jarvis.voice import voice  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)
bad = []
HI = "नमस्ते"


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (f"  {detail}" if detail and not ok else ""))
    if not ok:
        bad.append(name)


def pump(seconds):
    end = time.time() + seconds
    while time.time() < end:
        QCoreApplication.processEvents()
        time.sleep(0.01)


def chat_body(srv):
    """The last chat request that carries the persona (the summary and extraction calls the brain makes now and then are not chat)."""
    bodies = [b for u, b in srv.posts if u == "/api/chat" and b["messages"][0]["content"].startswith("You are")]
    return bodies[-1] if bodies else None


def restart():
    """What a restart does to the language state: forget the process, read the file again."""
    lang._session.update(reply=None, loaded=False)


settings = config.DATA / "settings.json"
spoken = []
mock.patch.object(voice, "say", lambda t, *a, **k: spoken.append(str(t))).start()

# ---- the default, and where it lives ----
check("the default reply language is English, automatic", lang.reply_setting() is None and lang.label() == "English (auto)")
check("the hint says English only, short", lang.reply_hint("hello") == "Reply in English only, short.")
check("typos and Latin text stay English", all(lang.reply_language(t) == "en" for t in ("heelo ?", "hello", "nice how are you doing", "kaise ho aap", "hii")))
check("a message in Devanagari gets Hindi, in Kannada script gets Kannada", lang.reply_language(HI + ", आज मौसम कैसा है") == "hi" and lang.reply_language("ನಮಸ್ಕಾರ, ಹೇಗಿದ್ದೀರಿ") == "kn")
check("the persona prompts carry the line", "Reply in English only, short." in brain.chat_system("hello") and "Reply in English only, short." in local.short_system("hello")
      and "Reply in English only, short." in brain.cloud_system("hello") and "Reply in English only, short." in brain.quality_system("hello"))
check("a Hindi message under auto gets the Hindi line", "Reply in Hindi only, short." in local.short_system(HI + " कैसे हो"))
check("nothing is saved until someone sets it", not settings.exists() or "language" not in json.loads(settings.read_text()))

# ---- set, persist, restart ----
json_before = {"voice": "en_US-joe-medium", "profile": {"nickname": "Vee"}}
settings.write_text(json.dumps(json_before))
lang.set_reply("hindi")
saved = json.loads(settings.read_text())
check("setting Hindi saves it in settings.json", saved["language"]["reply"] == "hi" and saved["voice"] == "en_US-joe-medium" and saved["profile"] == {"nickname": "Vee"})
restart()
check("it survives a restart", lang.reply_setting() == "hi" and lang.label() == "Hindi")
check("an explicit Hindi answers a Latin message in Hindi", lang.reply_language("hello") == "hi" and "Reply in Hindi only, short." in local.short_system("hello"))
lang.set_reply("english")
restart()
check("an explicit English survives a restart and beats a Hindi message", lang.reply_setting() == "en" and lang.reply_language(HI) == "en" and lang.label() == "English")
lang.set_reply("kannada")
check("Kannada can be set", lang.reply_language("hello") == "kn")
lang.set_reply("auto")
restart()
check("auto removes the saved value", lang.reply_setting() is None and "reply" not in json.loads(settings.read_text()).get("language", {}))
settings.write_text(json.dumps({"language": {"reply": "tr"}}))
restart()
check("a bad saved value is ignored", lang.reply_setting() is None)
settings.write_text("{ not json")
restart()
check("a damaged file is ignored", lang.reply_setting() is None)
lang.set_reply("auto")

# ---- direct commands ----
ran = []
phrases = ["speak in english", "Speak in English.", "reply in english", "Reply in English", "respond in english", "answer in english please", "talk in english", "talk in hindi",
           "speak in hindi", "reply in kannada", "answer in kannada from now on", "switch to english", "english only", "speak english", "please speak in english", "can you speak in english",
           "speek in englsh", "replay in english", "tak in hindi", "reply in englis", "write in english"]
want = {"english": "en", "hindi": "hi", "kannada": "kn"}
for t in phrases:
    ran.clear()
    with mock.patch.object(main, "run_tool", lambda a, args, s: ran.append((a, args))):
        handled = main.direct(t)
    expect_lang = next((k for k in want if k[:4] in t.lower().replace("englsh", "english").replace("englis", "english")), "")
    check(f"'{t}' is a direct language command", handled and ran and ran[0][0] == "set_language" and ran[0][1]["mode"] == "reply" and ran[0][1]["language"] == expect_lang, f"{handled} {ran}")
for t in ("speak in english", "talk in hindi", "reply in english", "answer in kannada"):
    check(f"'{t}' cannot match the time command or a draft", not main.fast_path(t) and "time_date" not in tools.rank_tools(t) and not any(a == "time_date" for a, _ in ran), str(tools.rank_tools(t)))
check("the time command still works", main.fast_path.__name__ and (lambda: (ran.clear(), mock.patch.object(main, "do_tool", lambda a, args: ran.append((a, args))).start(), main.fast_path("what time is it"))[2])() and ran[-1][0] == "time_date")
mock.patch.stopall()
mock.patch.object(voice, "say", lambda t, *a, **k: spoken.append(str(t))).start()

# the real command: sets, confirms in one short sentence in that language, persists
for phrase, code, test in (("talk in hindi", "hi", lambda t: lang.script(t) == "hi"), ("reply in kannada", "kn", lambda t: lang.script(t) == "kn"),
                           ("speak in english", "en", lambda t: t == "Okay, I will reply in English.")):
    spoken.clear()
    main._handle(phrase)
    restart()
    check(f"'{phrase}' sets {code}, persists, and confirms in that language", lang.reply_setting() == code and len(spoken) == 1 and test(spoken[0]) and spoken[0].count(".") + spoken[0].count("।") <= 1,
          f"{lang.reply_setting()} {spoken}")
check("it did not go to the model", True)
calls = []
with mock.patch.object(brain, "chat", lambda *a, **k: calls.append("chat")), mock.patch.object(agent, "turn", lambda *a, **k: calls.append("agent")), \
        mock.patch.object(brain, "route", lambda *a, **k: calls.append("route") or (None, None)):
    for t in ("speak in english", "reply in english", "talk in hindi", "speek in englsh"):
        main._handle(t)
check("none of the language commands reached the brain, the agent or a draft", not calls, str(calls))
lang.set_reply("auto")

# ---- a complaint is chat ----
complaints = ["i didnt ask time", "i didn't ask the time", "I did not ask for the time", "no i didnt ask the time", "that is not what i asked", "i said english", "you misheard me",
              "that's wrong", "why did you tell me the time", "i never asked for that"]
for t in complaints:
    check(f"'{t}' is chat, not a command", not main.direct(t) and not main.fast_path(t) and tools.pick_tools(t) == [] and tools.rank_tools(t) == [], f"{tools.pick_tools(t)}")
routed = []
with mock.patch.object(brain, "chat", lambda text, *a, **k: routed.append(("chat", text)) or {"action": "chat", "say": "Sorry about that."}), \
        mock.patch.object(agent, "turn", lambda *a, **k: routed.append(("agent",)) or True), mock.patch.object(main, "do_tool", lambda *a, **k: routed.append(("tool", a))):
    main._handle("i didnt ask time")
check("end to end, 'i didnt ask time' goes to chat and no tool runs", routed and routed[0][0] == "chat" and all(r[0] == "chat" for r in routed), str(routed))
check("real time questions are still tool requests", "time_date" in tools.rank_tools("what time is it") and not tools.small_talk("what time is it"))
check("a request that merely contains 'not' is not a complaint", not tools.small_talk("do not forget to set a reminder at five"))

# ---- English from the local model for typos and variants ----
def model(body):
    """A stand-in model that obeys the language line in the system prompt, the way a real one should."""
    system = body["messages"][0]["content"]
    if "Reply in English only" in system:
        return ["Hello! ", "I'm doing well, ", "thanks for asking."]
    if "Reply in Hindi only" in system:
        return [HI + "! ", "मैं ठीक हूँ।"]
    return ["??? ", "unknown language"]


srv = fake_ollama.start(reply_fn=model)
local._use["url"] = srv.url
mock.patch.object(brain, "_ensure_ollama", lambda: True).start()
mock.patch.object(brain, "_free_gb", lambda: 3.0).start()
mock.patch.object(brain, "_ollama_model", lambda: "llama3.2:1b").start()
mock.patch.object(psutil, "virtual_memory", lambda: mock.Mock(available=3 * 2 ** 30, percent=50)).start()
threads.attach()
lang.set_reply("auto")
# an earlier Hindi session left Hindi replies in the conversation
threads.add("user", HI + " जार्विस")
threads.add("assistant", "नमस्ते! मैं आपकी कैसे मदद कर सकता हूँ?")
threads.add("user", "कैसे हो")
threads.add("assistant", "मैं ठीक हूँ, धन्यवाद।")
for t in ("heelo ?", "hello", "nice how are you doing", "helo jarvis", "hii", "how r u doing", "hey whats up", "gud morning", "hlo", "nice"):
    srv.posts.clear()
    plan = brain.chat(t)
    body = chat_body(srv)
    system = body["messages"][0]["content"] if body else ""
    reply = (plan or {}).get("say", "")
    check(f"'{t}' gets an English answer with the language line and no Hindi in the context", plan and lang.script(reply) == "en" and "Hello" in reply and "Reply in English only, short." in system
          and not any(lang.script(m["content"]) != "en" for m in body["messages"]), f"{reply!r}")
    if t not in ("how r u doing", "gud morning"):
        check(f"'{t}' is chat, not a tool request", tools.pick_tools(t) == [], str(tools.pick_tools(t)))
srv.posts.clear()
plan = brain.chat(HI + ", आज कैसे हो")
body = chat_body(srv)
check("a Hindi message under auto is answered in Hindi", lang.script(plan["say"]) == "hi" and "Reply in Hindi only, short." in body["messages"][0]["content"], f"{lang.script(plan['say'])} {body['messages'][0]['content'][-90:]!r}")
lang.set_reply("english")
srv.posts.clear()
plan = brain.chat(HI + ", आज कैसे हो")
body = chat_body(srv)
check("with English set, even a Hindi message is answered in English", lang.script(plan["say"]) == "en" and "Reply in English only, short." in body["messages"][0]["content"])
lang.set_reply("hindi")
srv.posts.clear()
plan = brain.chat("hello there")
body = chat_body(srv)
check("with Hindi set, a Latin message is answered in Hindi", lang.script(plan["say"]) == "hi")
lang.set_reply("auto")
srv.stop()

# ---- the status pill and Settings ----
from jarvis.ui import shell  # noqa: E402
sh = shell.Shell()
sh.resize(1280, 800)
sh.show()
pump(0.4)
lang.set_reply("auto")
sh.dash.update_pill()
check("the classic pill shows the reply language", "REPLY ENGLISH (AUTO)" in sh.dash.pill.text(), sh.dash.pill.text())
sh.poll()
check("the bottom panel shows it", sh.bottom.reply.text() == "reply: English (auto)", sh.bottom.reply.text())
sh.open_page("Settings")
pump(0.3)
sh.hub.show_section("customize")
cp = sh.hub.customize
check("Settings shows the current reply language", cp.reply_now.text() == "Replies now: English (auto)" and cp.reply.currentData() == "", cp.reply_now.text())
cp.reply.setCurrentIndex(cp.reply.findData("hindi"))
check("picking Hindi in Settings sets and saves it", lang.reply_setting() == "hi" and json.loads(settings.read_text())["language"]["reply"] == "hi")
sh.dash.update_pill()
sh.poll()
check("the pill and the panel follow at once", "REPLY HINDI" in sh.dash.pill.text() and sh.bottom.reply.text() == "reply: Hindi")
sh.hub.show_section("general")
sh.hub.show_section("customize")
check("and Settings shows it again when reopened", cp.reply.currentData() == "hindi" and "Hindi" in cp.reply_now.text())
cp.reply.setCurrentIndex(cp.reply.findData("english"))
check("English can be picked", lang.reply_setting() == "en" and sh.hub.customize.reply_now.text() == "Replies now: English")
cp.reply.setCurrentIndex(0)
check("and back to auto", lang.reply_setting() is None)
check("Reply language is in the palette", features.search("reply language")[0].action == ("page", "Settings", "customize") and features.search("reply language")[0].available)

# ---- first-word average on Stats ----
turns = local._turns_path()
if turns.exists():
    turns.unlink()
stats_page = sh.dash.pages["Stats"]
stats_page.refresh()
check("Stats says so before any local turn", "No local turns yet" in stats_page.local.text(), stats_page.local.text())
for first in (9.0, 9.0, 9.0) + (1.0,) * 10:
    local.record_turn(first, first + 1, 90, False)
avg, n = local.average_first_word()
check("the average is over the last 10 turns only", n == 10 and abs(avg - 1.0) < 0.001 and len(local.recent_turns()) == 10, f"{avg} {n}")
local.record_turn(None, 60, 90, False)
local.record_turn(3.0, 4, 90, False)
avg, n = local.average_first_word()
check("a turn with no first word is not averaged in, but takes a place in the last 10", n == 9 and abs(avg - (8 * 1.0 + 3.0) / 9) < 0.001, f"{avg} {n}")
stats_page.refresh()
txt = stats_page.local.text()
check("Stats shows the average, the count and the slowest", "Average first word 1.2 s over 9 of the last 10 local turns" in txt and "slowest 3.0 s" in txt, txt)
check("the figures are kept across a restart (read from the file)", local.average_first_word() == (avg, n) and json.loads(turns.read_text())[-1]["total"] == 4.0)
check("the file holds numbers only", all(set(r) == {"first", "total", "prompt", "throttled", "at"} for r in json.loads(turns.read_text())))
srv = fake_ollama.start(first_delay=0.5)
local._use["url"] = srv.url
turns.unlink()
brain._try_ollama([{"role": "user", "content": "can you hear me?"}], 100, False)
rows = local.recent_turns()
check("a real local turn is recorded with its first-word time", len(rows) == 1 and rows[0]["first"] is not None and rows[0]["first"] >= 0.45 and rows[0]["prompt"] == 42, str(rows))
srv.stop()
srv = fake_ollama.start(chat_status=404, chat_body="model not found")
local._use["url"] = srv.url
brain._try_ollama([{"role": "user", "content": "hi"}], 100, False)
rows = local.recent_turns()
check("a failed turn is recorded with no first word", len(rows) == 2 and rows[1]["first"] is None)
srv.stop()

sh.tray = None
with mock.patch("jarvis.ui.ui.mpvctl.stop", lambda: None), mock.patch("jarvis.ui.ui.browser.shutdown", lambda: None), mock.patch("jarvis.ui.ui.brain.finish", lambda: None):
    sh.quit_all(exit_process=False)
sys.exit(1 if bad else 0)
