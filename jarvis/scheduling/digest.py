"""The morning briefing: greeting, date, weather, today's reminders and notes, mail, headlines."""
import re
import threading
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime

import requests

from ..core import config
from ..memory import notes, store
from . import reminders

MAX_WORDS = 105
WEATHER_TTL = 600
GEOCODE = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST = "https://api.open-meteo.com/v1/forecast"
DEFAULT_FEEDS = ("https://feeds.bbci.co.uk/news/world/rss.xml,"
                 "https://www.thehindu.com/news/national/feeder/default.rss,"
                 "https://feeds.npr.org/1001/rss.xml")
CODES = {0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "overcast", 45: "foggy", 48: "foggy",
         51: "light drizzle", 53: "drizzle", 55: "heavy drizzle", 61: "light rain", 63: "rain", 65: "heavy rain",
         71: "light snow", 73: "snow", 75: "heavy snow", 80: "rain showers", 81: "rain showers",
         82: "heavy showers", 95: "thunderstorms", 96: "thunderstorms", 99: "thunderstorms"}
DEADLINE = re.compile(r"\b(deadline|submit|submission|due|exam|assignment|viva|fee)\b", re.I)
RUNNING = threading.Event()
_weather = {"t": 0.0, "city": "", "text": ""}


def weather_line():
    """One sentence about today's weather, cached for ten minutes. Empty when anything goes wrong."""
    city = config.get("WEATHER_CITY")
    if not city:
        return ""
    if _weather["city"] == city and time.time() - _weather["t"] < WEATHER_TTL:
        return _weather["text"]
    text = ""
    try:
        geo = requests.get(GEOCODE, params={"name": city, "count": 1}, timeout=10).json()
        place = (geo.get("results") or [None])[0]
        if place:
            r = requests.get(FORECAST, timeout=10, params={
                "latitude": place["latitude"], "longitude": place["longitude"], "timezone": "auto",
                "current": "temperature_2m,weather_code", "forecast_days": 1,
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max"}).json()
            now, day = r["current"], r["daily"]
            text = (f"In {city} it is {CODES.get(now['weather_code'], 'fine')} and {now['temperature_2m']:.0f} degrees, "
                    f"with a high of {day['temperature_2m_max'][0]:.0f}")
            rain = day["precipitation_probability_max"][0]
            text += f" and a {rain:.0f} percent chance of rain." if rain and rain >= 30 else "."
    except (requests.RequestException, ValueError, KeyError, IndexError, TypeError):
        text = ""
    _weather.update(t=time.time(), city=city, text=text)
    return text


def headlines(n=3):
    feeds = [f.strip() for f in config.get("NEWS_FEEDS", DEFAULT_FEEDS).split(",") if f.strip()]
    found = []
    for url in feeds[:n]:
        try:
            r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"})
            title = ET.fromstring(r.content).find(".//item/title")
            if title is not None and title.text:
                found.append(" ".join(title.text.split())[:110])
        except (requests.RequestException, ET.ParseError):
            continue
    return found[:n]


def today_reminders():
    today = date.today()
    out = []
    for r in reminders.pending():
        due = datetime.fromisoformat(r["due"])
        if due.date() == today:
            kind = "deadline: " if DEADLINE.search(r["text"]) else ""
            out.append(f"{kind}{r['text']} at {due.strftime('%I:%M %p').lstrip('0')}")
    return out


def mail_line():
    try:
        from ..actions import mail
        return mail.digest_line() if mail.enabled() else ""
    except Exception:
        return ""


def build():
    now = datetime.now()
    pet = config.PET_NAME or "there"
    part = "morning" if now.hour < 12 else "afternoon" if now.hour < 17 else "evening"
    parts = [(0, f"Good {part}, {pet}. It is {now:%A}, {now.day} {now:%B}.")]
    parts.append((3, weather_line()))
    mine = today_reminders()
    if mine:
        parts.append((1, f"Today you have {len(mine)} reminder{'s' if len(mine) > 1 else ''}: " + "; ".join(mine[:3]) + "."))
    else:
        parts.append((1, "You have no reminders today."))
    tagged = notes.for_today()
    if tagged:
        parts.append((2, "Notes for today: " + "; ".join(tagged[:2]) + "."))
    parts.append((2, mail_line()))
    news = headlines()
    if news:
        parts.append((4, "In the news: " + "; ".join(news) + "."))
    parts = [p for p in parts if p[1]]
    # drop the least important parts until it fits in about 45 seconds of speech
    while len(" ".join(t for _, t in parts).split()) > MAX_WORDS and len(parts) > 2:
        parts.remove(max(parts, key=lambda p: p[0]))
    return " ".join(t for _, t in parts)


def due_now(now=None):
    now = now or datetime.now()
    raw = config.get("DIGEST_TIME", "07:30")
    start = reminders._hm(raw)
    start = 450 if start is None else start
    return start <= now.hour * 60 + now.minute and now.hour < 11


def run(speak):
    """Say the briefing once per day. Two processes cannot both do it."""
    if not store.claim("digest_last", date.today().isoformat()):
        return False
    RUNNING.set()
    try:
        speak(build())
    finally:
        RUNNING.clear()
    return True


def watch(speak):
    """Check every 30 seconds. After a sleep it runs on the first wake before 11:00."""
    if config.get("DIGEST_TIME", "07:30").lower() in ("off", "none"):
        return

    def loop():
        time.sleep(20)
        while True:
            try:
                if due_now():
                    run(speak)
            except Exception as e:
                print(f"  (morning briefing failed: {type(e).__name__})")
            time.sleep(30)
    threading.Thread(target=loop, daemon=True).start()
