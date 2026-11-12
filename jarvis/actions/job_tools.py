"""Voice tools for the job helper. They are registered only when JOBS=on, so a setup without it never sees them."""
import re

from ..core import config
from ..jobs import analyse, drafts, interview, mailflag, tracker
from . import events, screen
from .tools import ToolError, tool

ENABLED = config.flag("JOBS", False)
LINK = re.compile(r"https?://\S+")


def register(*args, **kwargs):
    """Like @tool, but a no-op unless JOBS=on."""
    return tool(*args, **kwargs) if ENABLED else (lambda fn: fn)


def parse_add(text):
    """(company, role, resume, status, link) from 'Google as data analyst with the DA resume applied'. Companies with several words need
    ' as ', a comma or a dash before the role."""
    t = " ".join(str(text).split())
    link = (LINK.search(t) or [""])[0] if LINK.search(t) else ""
    t = LINK.sub("", t)
    resume = ""
    m = re.search(r"\b(?:with |using |on )?(?:the )?\b(BA|DA|OA|PA)\b(?: resume| cv)?", t, re.I)
    if m:
        resume, t = m.group(1).upper(), (t[:m.start()] + t[m.end():])
    status = "saved"
    m = re.search(r"\b(applied|saved)\b", t, re.I)
    if m:
        status, t = m.group(1).lower(), (t[:m.start()] + t[m.end():])
    t = re.sub(r"^(?:at|for)\s+", "", t.strip(" ,.-"), flags=re.I)
    parts = re.split(r"\s+as\s+|\s*,\s*|\s+-\s+", t, maxsplit=1)
    if len(parts) == 2:
        company, role = parts
    else:
        words = t.split()
        company, role = (words[0], " ".join(words[1:])) if words else ("", "")
    return company.strip(" ,.-"), role.strip(" ,.-"), resume, status, link


@register("add_job", 'args {"text": "<company as role>", "company": "...", "role": "...", "resume": "BA, DA, OA or PA", "status": "saved or applied", "link": "...", "notes": "..."} - add a job to the job tracker; for "add job Acme as data analyst", "add this job" (uses the last analysis)')
def add_job(args):
    company, role, resume = str(args.get("company") or ""), str(args.get("role") or ""), str(args.get("resume") or "")
    status, link = str(args.get("status") or "saved"), str(args.get("link") or "")
    text = str(args.get("text") or "")
    if text.strip() and not company:
        company, role2, resume2, status2, link2 = parse_add(text)
        role, resume, status, link = role or role2, resume or resume2, status2 if status == "saved" else status, link or link2
    if not company and analyse.LAST:
        company, role, resume = analyse.LAST.get("company", ""), analyse.LAST.get("title", ""), resume or analyse.LAST.get("resume", "")
    if not company:
        raise ToolError("Which company? Say for example: add job Acme as data analyst.")
    try:
        job = tracker.add(company, role, resume, analyse.LAST.get("location", "") if analyse.LAST.get("company") == company else "", link,
                          args.get("notes", ""), status)
    except ValueError as e:
        raise ToolError(str(e))
    extra = f", resume {job['resume']}" if job["resume"] else ""
    return f"Added {job['company']}, {job['role']}, as {job['status']}{extra}."


@register("update_job", 'args {"company": "<company as said>", "status": "saved, applied, interview, offer or rejected", "note": "optional"} - change a job in the tracker; for "update Acme to interview"')
def update_job(args):
    status = str(args.get("status") or "")
    if status and tracker.normalise_status(status) is None:
        raise ToolError("The status can be saved, applied, interview, offer or rejected.")
    try:
        job = tracker.update(str(args.get("company") or ""), status or None, str(args.get("note") or ""), str(args.get("resume") or ""))
    except KeyError:
        raise ToolError(f"I do not have {args.get('company') or 'that company'} in your job tracker.")
    return f"{job['company']} is now {job['status']}."


@register("jobs_this_week", 'args {} - say which jobs were applied to this week; for "what did I apply to this week"')
def jobs_this_week(args):
    rows = tracker.applied_this_week()
    if not rows:
        return "You have not applied to anything yet this week."
    print("\n".join(f"{j['applied']}  {j['company']}  {j['role']}  [{j['resume'] or '-'}]  {j['status']}" for j in rows))
    return f"You applied to {len(rows)} this week: {tracker.spoken_list(rows)}."


@register("jobs_follow_up", 'args {} - say which jobs need a follow-up; for "what needs a follow-up"')
def jobs_follow_up(args):
    rows = tracker.needs_follow_up()
    if not rows:
        return "Nothing needs a follow-up today."
    print("\n".join(f"{j['company']}  {j['role']}  {j['status']}  follow up since {j['follow_up']}" for j in rows))
    return f"{len(rows)} need a follow-up: {tracker.spoken_list(rows)}."


@register("analyse_job", 'args {"text": "<job description, or empty to use the clipboard>"} - compare a job description with the resume text in data/profile.md; for "analyse this job"')
def analyse_job(args):
    text = str(args.get("text") or "").strip()
    if len(text) < 40:
        text = screen.read_clip()
    try:
        result = analyse.analyse(text)
    except ValueError as e:
        raise ToolError(str(e))
    full = analyse.report(result)
    print("\n" + full + "\n")
    events.emit("sys", full)
    return analyse.spoken(result)


@register("draft_followup", 'args {"company": "<company as said>"} - write a follow-up email for a tracked job into the clipboard and Gmail Drafts; never sends; for "draft a follow-up email to Acme"')
def draft_followup(args):
    return drafts.follow_up(str(args.get("company") or ""))


@register("draft_cover_letter", 'args {} - write a cover letter for the job last analysed into the clipboard and Gmail Drafts; never sends; for "draft a cover letter for this job"')
def draft_cover_letter(args):
    return drafts.cover_letter()


def _describe_updates(args):
    rows = mailflag.pending()
    if not rows:
        raise ToolError("There are no job updates waiting from your email.")
    return "Update the tracker from your email: " + "; ".join(f"{r['company']} to {r['status']}" for r in rows[:4]) + "?"


@register("job_mail_updates", "args {} - apply the tracker updates that job emails suggested, after the user confirms; for \"apply the job updates\"",
          risk="confirm", describe=_describe_updates)
def job_mail_updates(args):
    done = []
    for row in mailflag.pending():
        try:
            tracker.update(row["company"], row["status"])
            done.append(f"{row['company']} to {row['status']}")
        except (KeyError, ValueError):
            continue
    mailflag.remember([])
    return ("Updated " + ", ".join(done) + ".") if done else "Nothing to update."


@register("practice_interview", 'args {"role": "<job role>"} - start a spoken mock interview, one question at a time; for "practice interview for data analyst"')
def practice_interview(args):
    return interview.start(args.get("role") or analyse.LAST.get("title") or "")


@register("interview_weak_areas", 'args {} - say the weak areas logged in mock interviews; for "what are my weak interview areas"')
def interview_weak_areas(args):
    weak = interview.weak_areas()
    return ("Your most common weak areas are " + ", ".join(weak) + ".") if weak else "No weak areas logged yet. Say practice interview for a role."
