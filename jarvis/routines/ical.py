"""A small read-only iCal reader for the private link in CALENDAR_ICS_URL. Plain GET only: no login, no write access.
The link is a secret, so it is never printed or logged."""
import re
import time
from datetime import date, datetime, timedelta, timezone

import requests

from ..core import config

CACHE_SECONDS = 900
MAX_BYTES = 3_000_000
DAYS = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}
_cache = {"at": 0.0, "text": ""}


def configured():
    return config.get("CALENDAR_ICS_URL").lower().startswith("https://")


def fetch():
    """The calendar text, cached for fifteen minutes. Empty when there is no link or the download failed."""
    if not configured():
        return ""
    if time.time() - _cache["at"] < CACHE_SECONDS:
        return _cache["text"]
    try:
        r = requests.get(config.get("CALENDAR_ICS_URL"), timeout=15, stream=True, headers={"User-Agent": "jarvis-calendar"})
        raw = r.raw.read(MAX_BYTES, decode_content=True)
        text = raw.decode(r.encoding or "utf-8", errors="replace") if r.status_code == 200 else ""
    except requests.RequestException:
        return _cache["text"]
    _cache.update(at=time.time(), text=text)
    return text


def unfold(text):
    return re.sub(r"\r?\n[ \t]", "", text).splitlines()


def _stamp(value, params):
    """A date or date-time as a local naive datetime, plus whether it was an all-day value."""
    value = value.strip()
    if re.fullmatch(r"\d{8}", value):
        return datetime.strptime(value, "%Y%m%d"), True
    m = re.fullmatch(r"(\d{8}T\d{6})(Z?)", value)
    if not m:
        return None, False
    dt = datetime.strptime(m.group(1), "%Y%m%dT%H%M%S")
    if m.group(2):
        return dt.replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None), False
    tzid = params.get("TZID")
    if tzid:
        try:
            from zoneinfo import ZoneInfo
            return dt.replace(tzinfo=ZoneInfo(tzid)).astimezone().replace(tzinfo=None), False
        except Exception:
            pass
    return dt, False


def _line(raw):
    head, _, value = raw.partition(":")
    name, *rest = head.split(";")
    params = dict(p.split("=", 1) for p in rest if "=" in p)
    return name.upper(), params, value


def parse(text):
    """[{start, end, all_day, title, place, rrule, exdates}] for every VEVENT."""
    events, cur = [], None
    for raw in unfold(text):
        if raw == "BEGIN:VEVENT":
            cur = {"title": "", "place": "", "rrule": "", "exdates": set(), "start": None, "end": None, "all_day": False}
        elif raw == "END:VEVENT" and cur is not None:
            if cur["start"]:
                cur["end"] = cur["end"] or cur["start"] + (timedelta(days=1) if cur["all_day"] else timedelta())
                events.append(cur)
            cur = None
        elif cur is not None and ":" in raw:
            name, params, value = _line(raw)
            if name == "DTSTART":
                cur["start"], cur["all_day"] = _stamp(value, params)
            elif name == "DTEND":
                cur["end"], _ = _stamp(value, params)
            elif name == "SUMMARY":
                cur["title"] = _unescape(value)[:120]
            elif name == "LOCATION":
                cur["place"] = _unescape(value)[:80]
            elif name == "RRULE":
                cur["rrule"] = value
            elif name == "EXDATE":
                for v in value.split(","):
                    d, _ = _stamp(v, params)
                    if d:
                        cur["exdates"].add(d.date())
    return events


def _unescape(value):
    return value.replace("\\n", " ").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\").strip()


def _occurs(ev, day):
    """True if the event, with its simple repeat rule, has an occurrence starting on this date."""
    start = ev["start"]
    if start.date() == day:
        return True
    if not ev["rrule"] or day < start.date() or day in ev["exdates"]:
        return False
    rule = dict(p.split("=", 1) for p in ev["rrule"].split(";") if "=" in p)
    interval = max(1, int(rule.get("INTERVAL", "1") or 1))
    until = rule.get("UNTIL")
    if until:
        end, _ = _stamp(until if "T" in until else until, {})
        if end and day > end.date():
            return False
    gap = (day - start.date()).days
    freq = rule.get("FREQ")
    if freq == "DAILY":
        hit = gap % interval == 0
        count = gap // interval + 1
    elif freq == "WEEKLY":
        wanted = [DAYS[d[-2:]] for d in rule.get("BYDAY", "").split(",") if d[-2:] in DAYS] or [start.weekday()]
        weeks = (day - timedelta(days=day.weekday()) - (start.date() - timedelta(days=start.weekday()))).days // 7
        hit = weeks % interval == 0 and day.weekday() in wanted
        count = weeks // interval * len(wanted) + 1
    elif freq == "MONTHLY":
        months = (day.year - start.year) * 12 + day.month - start.month
        hit = months % interval == 0 and day.day == start.day
        count = months // interval + 1
    elif freq == "YEARLY":
        hit = (day.year - start.year) % interval == 0 and (day.month, day.day) == (start.month, start.day)
        count = (day.year - start.year) // interval + 1
    else:
        return False
    return hit and (not rule.get("COUNT") or count <= int(rule["COUNT"]))


def on_day(events, day):
    """The events that happen on this date, earliest first, as {time, title, place, all_day}."""
    out = []
    for ev in events:
        if _occurs(ev, day):
            moved = datetime.combine(day, ev["start"].time())
            out.append({"at": moved, "title": ev["title"] or "(no title)", "place": ev["place"], "all_day": ev["all_day"],
                        "time": "all day" if ev["all_day"] else moved.strftime("%H:%M")})
    return sorted(out, key=lambda e: (not e["all_day"], e["at"]))


def day_events(day=None, text=None):
    day = day or date.today()
    text = fetch() if text is None else text
    return on_day(parse(text), day) if text else []


def describe(items):
    return "; ".join(f"{e['time']} {e['title']}" + (f" at {e['place']}" if e["place"] else "") for e in items)
