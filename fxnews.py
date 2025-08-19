#!/usr/bin/env python3
import os
import time
import threading
import argparse
from datetime import datetime, timezone, date
from typing import Optional, List, Dict, Tuple
import collections
import requests

FF_BASE = "https://nfs.faireconomy.media"
PERIOD_TO_PATH = {
    "thisweek": "ff_calendar_thisweek.json",
    "nextweek": "ff_calendar_nextweek.json",
    "lastweek": "ff_calendar_lastweek.json",
}
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID")
LOCAL_TZ = datetime.now().astimezone().tzinfo
DEFAULT_REFRESH_MIN = int(os.getenv("REFRESH_MINUTES", "30"))

try:
    from zoneinfo import ZoneInfo
    NY_TZ = ZoneInfo("America/New_York")
except Exception:
    NY_TZ = None  # fallback

# ── Telegram ──────────────────────────────────────────────────────────────────
def send_telegram_alert(message: str):
    try:
        if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
            print("[TELEGRAM DISABLED]\n" + message)
            return
        if not message.strip():
            return
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
        resp = requests.post(url, json=payload, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        print(f"Telegram send error: {e}")

# ── Fetcher ───────────────────────────────────────────────────────────────────
def _get(url: str, max_retries: int = 5, timeout: int = 20) -> requests.Response:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; FFCalendarFetcher/1.0)",
        "Accept": "application/json, text/plain, */*",
        "Connection": "close",
    }
    for attempt in range(1, max_retries + 1):
        r = requests.get(url, headers=headers, timeout=timeout)
        if r.status_code < 400:
            return r
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(min(2 ** attempt, 30))
            continue
        r.raise_for_status()
    r.raise_for_status()
    return r

def fetch_events(period: str = "thisweek") -> List[Dict]:
    if period not in PERIOD_TO_PATH:
        raise ValueError(f"period must be one of {list(PERIOD_TO_PATH.keys())}")
    url = f"{FF_BASE}/{PERIOD_TO_PATH[period]}"
    return _get(url).json()

# ── Time parsing ──────────────────────────────────────────────────────────────
def parse_any_date(date_s: str) -> Optional[date]:
    if not date_s:
        return None
    fmts = ["%Y-%m-%d", "%d-%m-%Y", "%Y/%m/%d", "%b %d, %Y"]
    for f in fmts:
        try:
            return datetime.strptime(date_s, f).date()
        except Exception:
            continue
    return None

def parse_event_time_local(ev: Dict) -> Optional[datetime]:
    """
    Return a tz-aware datetime in LOCAL tz if event has a precise time.
    Handles in order:
      1) 'timestamp' (UTC seconds)
      2) ISO-8601 in 'date' (e.g., '2025-08-19T08:30:00-04:00' or ...Z)
      3) 'date' + 'time' (NY local clock like '8:30am', '08:30')
    """
    ts = ev.get("timestamp")
    if ts not in (None, "", "--"):
        try:
            dt_utc = datetime.fromtimestamp(int(float(ts)), tz=timezone.utc)
            return dt_utc.astimezone(LOCAL_TZ)
        except Exception:
            pass

    date_raw = (ev.get("date") or "").strip()
    if date_raw:
        if "T" in date_raw or date_raw.endswith("Z"):
            try:
                iso_s = date_raw.replace("Z", "+00:00")
                dt_iso = datetime.fromisoformat(iso_s)
                if dt_iso.tzinfo is None:
                    dt_iso = dt_iso.replace(tzinfo=(NY_TZ or timezone.utc))
                return dt_iso.astimezone(LOCAL_TZ)
            except Exception:
                pass

    time_s = (ev.get("time") or "").strip().lower()
    if not date_raw or time_s in ("", "all day", "tentative"):
        return None

    date_formats = ["%Y-%m-%d", "%d-%m-%Y", "%Y/%m/%d", "%b %d, %Y"]
    time_formats = ["%I:%M%p", "%I%p", "%H:%M", "%H"]
    for df in date_formats:
        for tf in time_formats:
            try:
                base = datetime.strptime(f"{date_raw} {time_s.upper()}", f"{df} {tf}")
                base = base.replace(tzinfo=(NY_TZ or timezone.utc))
                return base.astimezone(LOCAL_TZ)
            except Exception:
                continue
    return None

# ── “Today” logic ────────────────────────────────────────────────────────────
def calc_today_variants(now_local: datetime) -> Tuple[date, date, date]:
    today_local = now_local.date()
    today_ny = now_local.astimezone(NY_TZ or timezone.utc).date()
    today_utc = now_local.astimezone(timezone.utc).date()
    return today_local, today_ny, today_utc

def event_is_today_any(ev: Dict, now_local: datetime) -> bool:
    dt_local = parse_event_time_local(ev)
    if dt_local:
        return dt_local.date() == now_local.date()
    raw = (ev.get("date") or "").strip()
    if raw and not ("T" in raw or raw.endswith("Z")):
        ev_date = parse_any_date(raw)
        if ev_date:
            t_local, t_ny, t_utc = calc_today_variants(now_local)
            return ev_date in (t_local, t_ny, t_utc)
    return False

# ── Formatting ────────────────────────────────────────────────────────────────
def fmt_event_line(ev: Dict) -> str:
    title   = ev.get("title") or ev.get("event") or ""
    country = (ev.get("country") or ev.get("currency") or "").upper()
    impact  = (ev.get("impact") or "").capitalize()
    dt_local = parse_event_time_local(ev)
    when_str = dt_local.strftime("%H:%M") if dt_local else (ev.get("time") or "All Day")
    extras = []
    for k in ("actual", "forecast", "previous"):
        v = ev.get(k)
        if v not in (None, "", "--"):
            extras.append(f"{k.capitalize()}: {v}")
    extras_s = " | ".join(extras) if extras else ""
    base = f"{when_str} | {country} {impact:<6} | {title}"
    return base + (f"  ({extras_s})" if extras_s else "")

def build_morning_digest(events: List[Dict]) -> str:
    if not events:
        return "ℹ️ <b>No events found for today.</b>"
    lines = ["📅 <b>Today's Economic Calendar</b>"]
    by_imp_order = ["High", "Medium", "Low", "Holiday"]
    icons = {"High": "🔴", "Medium": "🟡", "Low": "🟢", "Holiday": "⚪"}
    for imp in by_imp_order:
        bucket = [e for e in events if (e.get("impact") or "").capitalize() == imp]
        if not bucket:
            continue
        lines.append(f"{icons.get(imp, '⚪')} <b>{imp} Impact</b>")
        bucket.sort(key=lambda ev: parse_event_time_local(ev) or datetime.max)
        for ev in bucket:
            lines.append("• " + fmt_event_line(ev))
        lines.append("")
    return "\n".join(lines).strip()

# ── Alerts & loop ────────────────────────────────────────────────────────────
def is_about_n_minutes_ahead(dt_local: datetime, n: int) -> bool:
    now = datetime.now(LOCAL_TZ)
    delta = (dt_local - now).total_seconds()
    return (n*60 - 60) <= delta <= (n*60 + 60)

def summarize_feed_dates(events: List[Dict]):
    counter = collections.Counter()
    for ev in events:
        d = (ev.get("date") or "").strip()
        counter[d] += 1
    print("[NEWS LOOP] Raw 'date' values (top 12):")
    for i, (k, v) in enumerate(counter.most_common(12), 1):
        print(f"  {i:2d}. {k or '<empty>'}: {v}")

def news_loop(period="thisweek", refresh_minutes=30):
    today_events: List[Dict] = []
    last_digest_date: Optional[date] = None
    alerted_keys_30m = set()
    last_fetch_ts = 0.0

    print(f"[NEWS LOOP] LocalTZ={LOCAL_TZ}, refresh={refresh_minutes} min, period={period}")

    while True:
        try:
            now_local = datetime.now(LOCAL_TZ)
            t_local, t_ny, t_utc = calc_today_variants(now_local)

            # Fetch immediately, then by interval
            if (time.time() - last_fetch_ts) >= (refresh_minutes * 60):
                weekly = fetch_events(period)
                print(f"[NEWS LOOP] fetched weekly: {len(weekly)} events @ {now_local:%Y-%m-%d %H:%M:%S}")
                print(f"[NEWS LOOP] Today Local={t_local}, NY={t_ny}, UTC={t_utc}")
                summarize_feed_dates(weekly)

                todays = [ev for ev in weekly if event_is_today_any(ev, now_local)]
                todays.sort(key=lambda ev: (parse_event_time_local(ev) or datetime.max))

                print(f"[NEWS LOOP] Picked for today: {len(todays)} events")
                if len(todays) == 0:
                    print("[NEWS LOOP] No matches; 10 samples with parsed local dt:")
                    for ev in weekly[:10]:
                        dt_local = parse_event_time_local(ev)
                        print("   -", (ev.get("title") or ev.get("event")),
                              "| raw_date:", (ev.get("date") or "").strip(),
                              "| time:", ev.get("time"),
                              "| parsed_local_dt:", dt_local)

                today_events = todays
                last_fetch_ts = time.time()

                if last_digest_date != t_local:
                    digest = build_morning_digest(today_events)
                    send_telegram_alert(digest)
                    last_digest_date = t_local
                    alerted_keys_30m.clear()
                    print(f"[{now_local:%Y-%m-%d %H:%M}] Digest sent: {len(today_events)} events")

            # 30-minute alerts for timed events
            if today_events:
                now_local = datetime.now(LOCAL_TZ)
                for ev in today_events:
                    dt_local = parse_event_time_local(ev)
                    if not dt_local:
                        continue  # All Day / no precise time
                    if dt_local < now_local:
                        continue
                    key = f"{int(dt_local.timestamp())}-{ev.get('title') or ev.get('event')}"
                    if key in alerted_keys_30m:
                        continue
                    if is_about_n_minutes_ahead(dt_local, 30):
                        send_telegram_alert("⏳ <b>Event in 30 minutes (Local)</b>\n\n• " + fmt_event_line(ev))
                        alerted_keys_30m.add(key)

            time.sleep(60)

        except Exception as e:
            print(f"[NEWS LOOP] error: {e}")
            time.sleep(30)

# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="FF News fetch + Local T-30 alerts (ISO-aware)")
    ap.add_argument("--period", default="thisweek", choices=list(PERIOD_TO_PATH.keys()))
    ap.add_argument("--refresh", type=int, default=DEFAULT_REFRESH_MIN,
                    help="Minutes between feed refreshes (env REFRESH_MINUTES, default 30)")
    args = ap.parse_args()

    threading.Thread(target=news_loop, args=(args.period, args.refresh), daemon=True).start()

    try:
        while True:
            print(f"Runner alive @ {datetime.now(LOCAL_TZ):%Y-%m-%d %H:%M:%S} (Local TZ)")
            time.sleep(600)
    except KeyboardInterrupt:
        print("Stopped by user.")

if __name__ == "__main__":
    main()
