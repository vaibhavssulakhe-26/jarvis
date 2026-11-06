"""Checks mail reading and triage against a mocked IMAP server. Run: python scripts/mail_check.py"""
import io
import os
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
tmp = Path(tempfile.mkdtemp(prefix="jarvis-mail-"))
os.environ["JARVIS_DATA"] = str(tmp)
os.environ["GMAIL_ADDRESS"] = "me@example.test"
os.environ["GMAIL_APP_PASSWORD"] = "app-password-for-test"
os.environ["MAIL_VIP"] = "dean@college.test"

from jarvis.actions import mail, tools  # noqa: E402
from jarvis.brain import brain  # noqa: E402
from jarvis.core import main as core  # noqa: E402

results = []


def check(name, ok):
    ok = bool(ok)
    results.append(ok)
    print(("PASS  " if ok else "FAIL  ") + name)


def raw(sender, subject, body, extra=""):
    return (f"From: {sender}\r\nTo: me@example.test\r\nSubject: {subject}\r\n{extra}"
            f"Content-Type: text/plain; charset=utf-8\r\n\r\n{body}\r\n").encode()


INBOX = [
    raw("Priya Rao <recruiter@acme.test>", "Interview invitation: Software Intern, tomorrow 10am",
        "Hello, we would like to invite you to an interview for the internship tomorrow. SECRETBODY"),
    raw("Shop Deals <newsletter@shop.test>", "Weekly newsletter: big sale this weekend",
        "Great deals and a huge sale. " * 800 + " click to unsubscribe", "List-Unsubscribe: <mailto:u@shop.test>\r\n"),
    raw("Registrar <registrar@college.test>", "Fee payment deadline today", "Pay the exam fee before 5 pm today."),
    raw("Arjun <arjun@friend.test>", "lunch?", "Are you free for lunch on Saturday?"),
    raw("Dean <dean@college.test>", "Re: project review", "Notes from the review.", "In-Reply-To: <abc@example.test>\r\n"),
]
SPAM = [
    raw("Lucky Draw <win@prize.test>", "You have won the lottery", "Claim your prize now, click here immediately."),
    raw("Recruiter <hr@acme.test>", "Re: internship offer letter", "Your internship offer is attached.", "In-Reply-To: <x@y>\r\n"),
    raw("Pills <p@pills.test>", "cheap watches", "buy now"),
]
log = {"commands": [], "readonly": None}


class FakeIMAP:
    def __init__(self, host, timeout=None):
        self.folder = None

    def login(self, user, password):
        log["commands"].append("login")

    def select(self, folder, readonly=False):
        log["readonly"] = readonly
        self.folder = SPAM if "Spam" in folder else INBOX
        return "OK", [b"1"]

    def uid(self, cmd, *args):
        log["commands"].append(cmd)
        if cmd == "SEARCH":
            return "OK", [b" ".join(str(i + 1).encode() for i in range(len(self.folder)))]
        if cmd == "FETCH":
            assert "PEEK" in args[1], "fetch must not mark mail as read"
            return "OK", [(b"1 (UID 1 BODY[] {1}", self.folder[int(args[0]) - 1]), b")"]
        raise AssertionError("unexpected IMAP command " + cmd)

    def logout(self):
        log["commands"].append("logout")

    def __getattr__(self, name):
        raise AssertionError("mail must stay read only, but " + name + " was called")


def fake_model(prompt, max_tokens=300, **kw):
    rules = (("interview", "important|interview invite"), ("newsletter", "ignorable|promotional newsletter"),
             ("fee", "important|fee deadline today"), ("lunch", "normal|friend asking lunch"))
    out = []
    for line in prompt.splitlines():
        parts = line.split("|")
        if len(parts) >= 4 and parts[0].isdigit():
            for word, label in rules:
                if word in parts[2].lower():
                    out.append(parts[0] + "|" + label)
    return "\n".join(out)


out = io.StringIO()
with mock.patch("imaplib.IMAP4_SSL", FakeIMAP), mock.patch.object(brain, "ask", side_effect=fake_model) as ask, redirect_stdout(out):
    spoken = tools.TOOLS["check_email"]["fn"]({})
    mails = list(mail.SESSION["items"])
check("mailbox opened read only", log["readonly"] is True)
check("only search and fetch were used", set(log["commands"]) <= {"login", "SEARCH", "FETCH", "logout"})
check("five unread were read", len(mails) == 5)
check("newsletter body is cut to 1500 characters", all(len(m["body"]) <= 1500 for m in mails))
by_subject = {m["subject"][:10]: m for m in mails}
check("interview invite is important", by_subject["Interview "]["label"] == "important")
check("newsletter is ignorable", by_subject["Weekly new"]["label"] == "ignorable")
check("VIP sender scores high", by_subject["Re: projec"]["score"] >= 5)
prompt = ask.call_args[0][0]
check("one small batch call", ask.call_count == 1 and len(prompt) < 4500)
check("no body longer than 300 characters is sent", all(len(line.split("|")[3]) <= 300 for line in prompt.splitlines()[1:] if line.count("|") >= 3))
check("untrusted-text warning is in the prompt", "untrusted" in prompt)
check("cloud is allowed by default", ask.call_args[1].get("local") is False)
check("spoken report counts unread", spoken.startswith("You have 5 unread."))
check("report names important senders", "Priya Rao" in spoken)
check("report counts ignorable mail", "look ignorable" in spoken)
check("time-sensitive mail is called out", "Time sensitive" in spoken)
check("table is printed", "important" in out.getvalue() and "Priya Rao" in out.getvalue())
check("message bodies are never printed", "SECRETBODY" not in out.getvalue() and "Great deals" not in out.getvalue())

with mock.patch("imaplib.IMAP4_SSL", FakeIMAP), mock.patch.object(brain, "ask", return_value="") as ask, redirect_stdout(io.StringIO()), \
        mock.patch.dict(os.environ, {"EMAIL_USE_CLOUD": "false"}):
    tools.TOOLS["check_email"]["fn"]({})
check("EMAIL_USE_CLOUD=false keeps the model local", ask.call_args[1].get("local") is True)
check("rules alone still sort the mail", {m["label"] for m in mail.SESSION["items"]} >= {"important", "ignorable"})

# learning from the user
mail.SESSION["items"] = mails
mail.SESSION["focus"] = 1
before = mail.score(by_subject["lunch?"])
check("'that one is not important' is recognised", any(p[0].match("that one's not important") for p in core.DIRECT if p[1] == "rate_sender"))
tools.TOOLS["rate_sender"]["fn"]({"which": "the second one", "important": False})
check("a sender marked unimportant scores lower", mail.score(by_subject["lunch?"]) < before)
tools.TOOLS["rate_sender"]["fn"]({"which": "the second one", "important": True})
tools.TOOLS["rate_sender"]["fn"]({"which": "the second one", "important": True})
check("a sender marked important scores higher", mail.score(by_subject["lunch?"]) > before)

# spam
with mock.patch("imaplib.IMAP4_SSL", FakeIMAP), redirect_stdout(io.StringIO()):
    line = tools.TOOLS["check_spam"]["fn"]({})
check("spam: 3 messages counted", line.startswith("3 messages in spam"))
check("spam: a real offer is flagged", "might be real" in line and "internship offer" in line)
check("spam: scam is warned about", "look like scams" in line and "do not open" in line)

# opening Gmail
opened = []
with mock.patch.object(mail, "_browser", opened.append):
    mail.SESSION["items"] = mails
    tools.TOOLS["open_email"]["fn"]({"which": "inbox"})
    tools.TOOLS["open_email"]["fn"]({"which": "the first one"})
check("inbox opens at Gmail", opened[0] == mail.INBOX_URL)
check("'open that one' opens a search for it", opened[1].startswith(mail.SEARCH_URL) and "dean%40college.test" in opened[1])

# missing credentials
with mock.patch.dict(os.environ, {"GMAIL_APP_PASSWORD": ""}):
    try:
        mail.fetch("inbox")
        msg = ""
    except tools.ToolError as e:
        msg = str(e)
check("missing credentials give a clear message", "GMAIL_APP_PASSWORD" in msg)
check("the password is never shown", "app-password-for-test" not in msg and "app-password-for-test" not in out.getvalue())

print(f"\n{sum(results)} of {len(results)} passed")
sys.exit(0 if all(results) else 1)
