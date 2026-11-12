"""Nightly inbox triage: label the unread mail and save the table to data/triage/<date>.md. Read only."""
from datetime import date, datetime

from ..core import config


def run():
    from ..actions import mail
    if not mail.configured():
        return "skipped, email is not set up"
    items = mail.classify(mail.fetch("inbox", 50))
    folder = config.DATA / "triage"
    folder.mkdir(parents=True, exist_ok=True)
    important = sum(1 for m in items if m["label"] == "important")
    (folder / f"{date.today().isoformat()}.md").write_text(
        f"# Inbox triage {datetime.now():%Y-%m-%d %H:%M}\n\n{len(items)} unread, {important} important.\n\n```\n{mail.table(items) if items else 'No unread mail.'}\n```\n")
    return f"{len(items)} unread, {important} important"
