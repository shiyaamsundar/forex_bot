#!/usr/bin/env python3
"""
Daily FF calendar -> Telegram alerts (IST only)

- At MORNING_HOUR (IST), fetches this week's JSON once, filters today's events.
- Immediately sends a morning digest listing all of today's events.
- Every minute, checks for events ~30 minutes away and sends a one-time alert.
"""

import os
import time
import argparse
from datetime import datetime, timezone, timedelta, date
from typing import Iterable, Optional, List, Dict

import requests

try:
    from zoneinfo import ZoneInfo  # Python 3.9+
except Exception:
    ZoneInfo = None

# ── Config ─────────────────────────────────────────────────────────────────────
IST = ZoneInfo("Asia/Kolkata") if ZoneInfo else None
FF_BASE = "https://nfs.faireconomy.media"
PERIOD_TO_PATH = {
    "thisweek": "ff_calendar_thisweek.json",
    "nextweek": "ff_calendar_nextweek.json",
    "lastweek": "ff_calendar_lastweek.json",
}
VALID_IMPACTS = {"Holiday", "Low", "Medium", "High"}

# Morning fetch hour in IST (00-23). Override with env MORNING_HOUR.
MORNING_HOUR = int(os.getenv("MORNING_HOUR", "7"))

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")

# ── Telegram ───────────────────────────────────────────────────────────────────
def send_telegram_alert(message: str):
    """Uses TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID env vars."""
    if not message or not message.strip():
        return
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[WARN] Telegram env missing; printing message:\n", message)
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
        r = requests.post(url, json=payload, timeout=15)
        r.raise_for_status()
    except Exception as e:
        print(f"[Telegram] send error: {e}")

# ── Fetch & filter ─────────────────────────────────────────────────────────────
def _get(url: str, max_retries: int = 5, timeout: int = 20) -> requests.Response:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; FFCalendarFetcher/1.0)",
        "Accept": "application/json, text/plain, */*",
        "Connection": "close",
    }
    for attempt in range(1, max_retries + 1):
        resp = requests.get(url, headers=headers, timeout=timeout)
        if resp.status_code < 400:
            return resp
        if resp.status_code in (429, 500, 502, 503, 504):
            time.sleep(min(2 ** attempt, 30))
            continue
        resp.raise_for_status()
    resp.raise_for_status()
    return resp

def fetch_events(
    period: str = "thisweek",
    currencies: Optional[Iterable[str]] = None,
    impacts: Optional[Iterable[str]] = None,
) -> List[Dict]:
    if period not in PERIOD_TO_PATH:
        raise ValueError(f"period must be one of {list(PERIOD_TO_PATH.keys())}")
    url = f"{FF_BASE}/{PERIOD_TO_PATH[period]}"
    data = _get(url).json()

    cur_set = {c.upper() for c in currencies} if currencies else None
    imp_set = {i.capitalize() for i in impacts} if impacts else None
    if imp_set and not imp_set.issubset(VALID_IMPACTS):
        raise ValueError(f"impacts must be subset of {VALID_IMPACTS}")

    out = []
    for ev in data:
        country = (ev.get("country") or ev.get("currency") or "").upper()
        impact = (ev.get("impact") or "").capitalize()
        if cur_set and country not in cur_set:
            continue
        if imp_set and impact not in imp_set:
            continue
        out.append(ev)
    return out

# ── Time helpers ───────────────────────────────────────────────────────────────
def to_ist_from_ts(ts: int) -> datetime:
    dt_utc = datetime.fromtimestamp(int(ts), tz=timezone.utc)
    return dt_utc.astimezone(IST) if IST else dt_utc

def parse_event_time_ist(ev: Dict) -> Optional[datetime]:
    ts = ev.get("timestamp")
    if ts is not None:
        return to_ist_from_ts(int(ts))
    date_s = ev.get("date")
    time_s = ev.get("time") or ""
    if not date_s or not time_s or ":" not in time_s:
        return None
    try:
        hh, mm = map(int, time_s.split(":"))
        return datetime.strptime(date_s, "%Y-%m-%d").replace(hour=hh, minute=mm, tzinfo=IST)
    except Exception:
        return None

def is_same_ist_day(ev: Dict, ref_date: date) -> bool:
    dt = parse_event_time_ist(ev)
    if not dt:
        return False
    return dt.date() == ref_date

def is_about_n_minutes_ahead(ev_dt: datetime, n: int) -> bool:
    now = datetime.now(IST)
    delta = (ev_dt - now).total_seconds()
    return (n*60 - 60) <= delta <= (n*60 + 60)

# ── Formatting ─────────────────────────────────────────────────────────────────
def fmt_line(ev: Dict) -> str:
    title = ev.get("title") or ev.get("event") or ""
    country = (ev.get("country") or ev.get("currency") or "").upper()
    impact = (ev.get("impact") or "").capitalize()
    when_local = parse_event_time_ist(ev)
    when_str = when_local.strftime("%H:%M") if when_local else (ev.get("time") or "All Day")

    extras = []
    for k in ("actual", "forecast", "previous"):
        v = ev.get(k)
        if v not in (None, "", "--"):
            extras.append(f"{k.capitalize()}: {v}")
    extras_s = " | ".join(extras) if extras else ""
    base = f"{when_str} | {country} {impact:<6} | {title}"
    return base + (f"  ({extras_s})" if extras_s else "")

def build_morning_digest(events: List[Dict]) -> str:
    lines = []
    by_imp_order = ["High", "Medium", "Low", "Holiday"]
    for imp in by_imp_order:
        bucket = [e for e in events if (e.get("impact") or "").capitalize() == imp]
        if not bucket:
            continue
        lines.append({"High":"🔴","Medium":"🟡","Low":"🟢","Holiday":"⚪"}.get(imp,"⚪") +
                     f" <b>{imp} Impact</b>")
        bucket.sort(key=lambda ev: parse_event_time_ist(ev) or datetime.max)
        for ev in bucket:
            lines.append("• " + fmt_line(ev))
        lines.append("")
    if not lines:
        return "ℹ️ <b>No events found for today.</b>"
    return "📅 <b>Today's Economic Calendar</b>\n" + "\n".join(lines).strip()

# ── Main loop ──────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="Daily FF calendar alerts in IST.")
    ap.add_argument("--period", default="thisweek", choices=list(PERIOD_TO_PATH.keys()))
    ap.add_argument("--curr", dest="currencies", default="", help="Comma list, e.g. USD,EUR,INR")
    ap.add_argument("--impact", dest="impacts", default="", help="Comma list: High,Medium,Low,Holiday")
    args = ap.parse_args()

    currencies = [c.strip() for c in args.currencies.split(",") if c.strip()]
    impacts = [i.strip() for i in args.impacts.split(",") if i.strip()]

    today_events: List[Dict] = []
    last_fetch_date: Optional[date] = None
    alerted_keys_30m = set()

    print(f"[START] IST MorningHour={MORNING_HOUR}, filters: curr={currencies or 'ALL'}, impact={impacts or 'ALL'}")

    while True:
        try:
            now_ist = datetime.now(IST)
            today_ist = now_ist.date()

            need_fetch = (last_fetch_date != today_ist) and (now_ist.hour >= MORNING_HOUR)
            if need_fetch:
                weekly = fetch_events(args.period, currencies or None, impacts or None)
                todays = [ev for ev in weekly if is_same_ist_day(ev, today_ist)]
                todays.sort(key=lambda ev: parse_event_time_ist(ev) or datetime.max)
                today_events = todays
                last_fetch_date = today_ist
                alerted_keys_30m.clear()
                send_telegram_alert(build_morning_digest(today_events))
                print(f"[{now_ist:%Y-%m-%d %H:%M}] Morning fetch: {len(today_events)} events")

            if today_events:
                for ev in today_events:
                    ev_dt = parse_event_time_ist(ev)
                    if not ev_dt or ev_dt < now_ist:
                        continue
                    key = f"{int(ev.get('timestamp') or ev_dt.timestamp())}-{ev.get('title') or ev.get('event')}"
                    if key in alerted_keys_30m:
                        continue
                    if is_about_n_minutes_ahead(ev_dt, 30):
                        send_telegram_alert("⏳ <b>Event in 30 minutes</b>\n\n• " + fmt_line(ev))
                        alerted_keys_30m.add(key)

            time.sleep(60)

        except Exception as e:
            print(f"[LOOP] error: {e}")
            time.sleep(30)

if __name__ == "__main__":
    main()
