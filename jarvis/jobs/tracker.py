"""data/jobs.json: company, role, resume type, location, link, date applied, status, notes and a follow-up date for each job."""
import re
import threading
from datetime import date, datetime, timedelta

from ..core import config, jsonfile
from . import RESUME_TYPES, STATUSES

FOLLOW_UP_DAYS = 7
SYNONYMS = {"saved": "saved", "save": "saved", "bookmarked": "saved", "applied": "applied", "apply": "applied", "submitted": "applied",
            "interview": "interview", "interviewing": "interview", "interviews": "interview", "screening": "interview",
            "offer": "offer", "offered": "offer", "rejected": "rejected", "rejection": "rejected", "declined": "rejected", "turned down": "rejected"}
_lock = threading.RLock()


def path():
    return config.DATA / "jobs.json"


def load():
    with _lock:
        data = jsonfile.read(path(), {}, dict)
    return [j for j in data.get("jobs", []) if isinstance(j, dict)]


def save(jobs):
    with _lock:
        jsonfile.write(path(), {"jobs": jobs}, indent=1)


def normalise_status(word):
    w = re.sub(r"[^a-z ]", "", str(word).lower()).strip()
    return SYNONYMS.get(w) or next((v for k, v in SYNONYMS.items() if k in w.split()), None)


def normalise_resume(word):
    w = re.sub(r"[^A-Za-z]", "", str(word or "")).upper()
    return w if w in RESUME_TYPES else ""


def add(company, role, resume="", location="", link="", notes="", status="saved", contact="", today=None):
    company, role = " ".join(str(company).split())[:60], " ".join(str(role).split())[:80]
    if not company:
        raise ValueError("A job needs a company name.")
    status = normalise_status(status) or "saved"
    today = today or date.today()
    job = {"id": int(datetime.now().timestamp() * 1000), "company": company, "role": role or "role not given", "resume": normalise_resume(resume),
           "location": " ".join(str(location).split())[:60], "link": str(link).strip()[:300] if str(link).startswith(("http://", "https://")) else "",
           "applied": today.isoformat() if status == "applied" else "", "status": status, "notes": " ".join(str(notes).split())[:300],
           "follow_up": (today + timedelta(days=FOLLOW_UP_DAYS)).isoformat() if status == "applied" else "", "contact": str(contact).strip()[:80]}
    jobs = load()
    jobs.append(job)
    save(jobs)
    return job


def find(company, jobs=None):
    """The best match for a spoken company name (newest first among equals), or None."""
    want = re.sub(r"[^a-z0-9 ]", "", str(company).lower()).strip()
    if not want:
        return None
    jobs = sorted(jobs if jobs is not None else load(), key=lambda j: -j.get("id", 0))
    for j in jobs:
        if re.sub(r"[^a-z0-9 ]", "", j["company"].lower()) == want:
            return j
    return next((j for j in jobs if want in j["company"].lower() or j["company"].lower() in want), None)


def update(company, status=None, note="", resume="", today=None, contact=""):
    jobs = load()
    job = find(company, jobs)
    if job is None:
        raise KeyError(company)
    today = today or date.today()
    if status:
        new = normalise_status(status)
        if new is None:
            raise ValueError(f"Status must be one of {', '.join(STATUSES)}.")
        job["status"] = new
        if new == "applied" and not job["applied"]:
            job["applied"] = today.isoformat()
        job["follow_up"] = (today + timedelta(days=FOLLOW_UP_DAYS)).isoformat() if new in ("applied", "interview") else ""
    if note:
        job["notes"] = (job["notes"] + "; " if job["notes"] else "") + " ".join(note.split())[:200]
    if resume:
        job["resume"] = normalise_resume(resume) or job["resume"]
    if contact:
        job["contact"] = str(contact).strip()[:80]
    save(jobs)
    return job


def week_start(today=None):
    today = today or date.today()
    return today - timedelta(days=today.weekday())


def applied_this_week(today=None, jobs=None):
    start = week_start(today).isoformat()
    return [j for j in (jobs if jobs is not None else load()) if j.get("applied") and j["applied"] >= start]


def needs_follow_up(today=None, jobs=None):
    """Applied or interviewing jobs whose follow-up date has come."""
    today = (today or date.today()).isoformat()
    return [j for j in (jobs if jobs is not None else load()) if j.get("status") in ("applied", "interview") and j.get("follow_up") and j["follow_up"] <= today]


def counts(jobs=None):
    """({status: n}, {resume type: n}) over the tracker."""
    jobs = load() if jobs is None else jobs
    by_status = {s: sum(1 for j in jobs if j["status"] == s) for s in STATUSES}
    by_resume = {r: sum(1 for j in jobs if j.get("resume") == r) for r in RESUME_TYPES}
    return by_status, by_resume


def spoken_list(jobs, limit=4):
    names = [f"{j['company']} {j['role']}" for j in jobs[:limit]]
    return ", ".join(names) + (f" and {len(jobs) - limit} more" if len(jobs) > limit else "")
