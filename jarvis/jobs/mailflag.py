"""Recruiter and application-system mail, flagged first in the briefing. Email text is data: this only reads words to sort it. The tracker changes
only after the user confirms (the confirm tool in actions/job_tools.py), never because an email said so."""
import re

from ..core import config, jsonfile
from . import tracker

WORDS = re.compile(r"\b(interview|application|assessment|coding challenge|take-?home|offer|rejected|regret to inform|unfortunately|next steps|"
                   r"recruiter|talent acquisition|shortlisted|schedule a call|hiring team)\b", re.I)
SYSTEMS = re.compile(r"greenhouse|lever\.co|myworkday|workday|icims|smartrecruiters|ashbyhq|taleo|jobvite|breezy|workable|successfactors|linkedin\.com", re.I)
SUGGEST = (("rejected", re.compile(r"regret to inform|unfortunately|not (?:be )?moving forward|decided to (?:move|go) (?:forward )?with (?:other|another)|rejected|not selected", re.I)),
           ("offer", re.compile(r"\boffer (?:letter|of employment)|pleased to offer|extend (?:you )?an offer|job offer", re.I)),
           ("interview", re.compile(r"interview|assessment|coding challenge|take-?home|schedule a call|next steps|shortlisted", re.I)))


def is_job_mail(m):
    """True for mail from an application system or that talks about interviews, assessments, offers or rejections."""
    return bool(SYSTEMS.search(m["address"]) or WORDS.search(m["subject"]) or WORDS.search(m["body"][:400]))


def suggested_status(m):
    text = m["subject"] + " " + m["body"][:400]
    return next((status for status, pattern in SUGGEST if pattern.search(text)), "")


def company_of(m, jobs=None):
    """The tracker job whose company name appears in the sender, address or subject."""
    blob = re.sub(r"[^a-z0-9 ]", " ", f"{m['name']} {m['address']} {m['subject']}".lower())
    for j in sorted(jobs if jobs is not None else tracker.load(), key=lambda j: -len(j["company"])):
        words = re.sub(r"[^a-z0-9 ]", "", j["company"].lower()).strip()
        if words and re.search(rf"\b{re.escape(words)}\b", blob):
            return j
    return None


def suggestions_path():
    return config.DATA / "job-suggestions.json"


def remember(suggestions):
    """Save {company, status, subject} suggestions for 'apply job mail updates'. An empty list clears them."""
    jsonfile.write(suggestions_path(), suggestions)


def pending():
    data = jsonfile.read(suggestions_path(), [], list)
    return [d for d in data if isinstance(d, dict) and d.get("company") and tracker.normalise_status(d.get("status"))]


def build_suggestions(flagged):
    """Tracker updates the flagged mail points to. Only for companies that are already in the tracker, and only when the status would change."""
    jobs = tracker.load()
    out = []
    for m in flagged:
        job, status = company_of(m, jobs), suggested_status(m)
        if job and status and job["status"] != status and not any(o["company"] == job["company"] for o in out):
            out.append({"company": job["company"], "status": status, "subject": m["subject"][:80]})
    return out
