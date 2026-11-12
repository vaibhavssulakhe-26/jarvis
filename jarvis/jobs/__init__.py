"""The optional job-search helper (JOBS=on). A tracker in data/jobs.json, job analysis against data/profile.md, reply and cover letter drafts,
recruiter mail flags in the briefing, and a mock interview. It never applies, sends or scrapes anything: all of it is local files plus the
brain for wording."""
from ..core import config

RESUME_TYPES = ("BA", "DA", "OA", "PA")
STATUSES = ("saved", "applied", "interview", "offer", "rejected")


def enabled():
    return config.flag("JOBS", False)
