#!/usr/bin/env python3
import os
import time
import threading
import argparse
from datetime import datetime, timezone, date, timedelta
from typing import Iterable, Optional, List, Dict, Tuple
import collections
from urllib.parse import urljoin
import random

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify

# ──────────────────────────────────────────────────────────────────────────────
# Env & globals
# ──────────────────────────────────────────────────────────────────────────────
load_dotenv()
OANDA_API_KEY      = os.getenv('OANDA_API_KEY')
OANDA_ACCOUNT_ID   = os.getenv('OANDA_ACCOUNT_ID')   # unused here, kept for future
OANDA_URL          = os.getenv('OANDA_URL')          # e.g. https://api-fxpractice.oanda.com/v3
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN_15')
TELEGRAM_CHAT_ID   = os.getenv('TELEGRAM_CHAT_ID_15')
API_URL =   os.getenv('API_URL_15')

# News refresh/alert config
REFRESH_MINUTES = int(os.getenv("REFRESH_MINUTES", "30"))  # refetch feed every N minutes
ALERT_LEAD_MIN  = int(os.getenv("ALERT_LEAD_MIN", "30"))   # alert N minutes before event start

HEADERS = {'Authorization': f'Bearer {OANDA_API_KEY}'}

try:
    from zoneinfo import ZoneInfo  # Py3.9+
except Exception:
    ZoneInfo = None

IST   = ZoneInfo("Asia/Kolkata") if ZoneInfo else None
NY_TZ = ZoneInfo("America/New_York") if ZoneInfo else None

# App timezone: prefer IST; fall back to server local tz (always aware)
APP_TZ = IST or datetime.now().astimezone().tzinfo
FAR_FUTURE = datetime.max.replace(tzinfo=APP_TZ)

FF_BASE = "https://nfs.faireconomy.media"
PERIOD_TO_PATH = {
    "thisweek": "ff_calendar_thisweek.json",
    "nextweek": "ff_calendar_nextweek.json",
    "lastweek": "ff_calendar_lastweek.json",
}
VALID_IMPACTS = {"Holiday", "Low", "Medium", "High"}

# ──────────────────────────────────────────────────────────────────────────────
# Flask liveness (Render)
# ──────────────────────────────────────────────────────────────────────────────
app = Flask(__name__)

@app.route('/')
def home():
    # Keep the root simple but informative
    return jsonify({
        "status": "alive",
        "message": "Forex Bot is running",
        "now": datetime.now(APP_TZ).strftime("%Y-%m-%d %H:%M:%S %Z")
    })
@app.route('/healthz')
def healthz():
    # Lightweight probe endpoint for uptime monitors
    return jsonify({
        "ok": True,
        "service": "forex-bot",
        "tz": str(APP_TZ),
        "epoch": time.time(),
        "now": datetime.now(APP_TZ).strftime("%Y-%m-%d %H:%M:%S %Z")
    })


def run_flask():
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)

def get_chat_id():
    print(TELEGRAM_BOT_TOKEN,'TELEGRAM_BOT_TOKEN')
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        # print(data,'data')
        if data["ok"] and data["result"]:
            latest_message = data["result"][-1]
            chat_id = latest_message["message"]["chat"]["id"]

            #logger.info(f"Found chat ID: {chat_id}")
            return chat_id
        else:
            #logger.error("No messages found. Please send a message to your bot first.")
            return None
    except Exception as e:
        #logger.error(f"Error getting chat ID: {str(e)}")
        return None


def test_telegram_bot():
    chat_id = get_chat_id()
    print(chat_id,'chat_id')
    if not chat_id:
        #logger.error("Could not get chat ID. Please make sure you've sent a message to your bot.")
        return
        
    global TELEGRAM_CHAT_ID
    TELEGRAM_CHAT_ID = chat_id
    
    test_message = "🤖 <b>Forex Alert Bot Test</b>\n\n" \
                  "This is a test message to verify that the bot is working correctly.\n" \
                  "If you receive this message, the bot is properly configured!"
    send_telegram_alert(test_message)

def _session_with_retries(total=3, backoff_factor=0.5, status_forcelist=(429, 500, 502, 503, 504)):
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry

    sess = requests.Session()
    retry = Retry(
        total=total,
        read=total,
        connect=total,
        status=total,
        backoff_factor=backoff_factor,
        status_forcelist=status_forcelist,
        allowed_methods=frozenset(['HEAD', 'GET', 'OPTIONS'])
    )
    adapter = HTTPAdapter(max_retries=retry)
    sess.mount("http://", adapter)
    sess.mount("https://", adapter)
    return sess

def keep_server_alive():
    """Self-ping the service every minute to keep it warm."""
    while True:
        try:
            r = requests.get(API_URL, timeout=10)
            if r.status_code == 200:
                print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Self-ping OK", flush=True)
            else:
                print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Self-ping non-200: {r.status_code}", flush=True)
        except Exception as e:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Self-ping error: {e}", flush=True)
        time.sleep(60)

# ──────────────────────────────────────────────────────────────────────────────
# Telegram
# ──────────────────────────────────────────────────────────────────────────────
def send_telegram_alert(message: str):
    try:
        # NOTE: Time-window restriction temporarily disabled; will reintroduce later
        # # allow alerts only between 05:30 and 13:30 IST, regardless of server timezone
        # ist_tz = IST or timezone(timedelta(hours=5, minutes=30))
        # now_ist = datetime.now(ist_tz)
        # start_window = now_ist.replace(hour=5, minute=30, second=0, microsecond=0)
        # end_window = now_ist.replace(hour=13, minute=30, second=0, microsecond=0)
        # if not (start_window <= now_ist <= end_window):
        #     print(f"[{now_ist:%Y-%m-%d %H:%M:%S %Z}] Alert suppressed (outside 05:30-13:30 IST window)")
        #     return
        if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
            print("Telegram env not set; printing message:\n", message)
            return
        if not message.strip():
            return
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
        resp = requests.post(url, json=payload, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        print(f"Telegram send error: {e}")

# ──────────────────────────────────────────────────────────────────────────────
# Alert de-dupe (pattern monitors)
# ──────────────────────────────────────────────────────────────────────────────
sent_alerts = {}         # key -> last_sent_epoch
ALERT_EXPIRY = 30 * 60   # 30 minutes
last_clear_time = time.time()

def clear_expired_alerts():
    global last_clear_time
    now = time.time()
    if now - last_clear_time >= ALERT_EXPIRY:
        sent_alerts.clear()
        last_clear_time = now
        print(f"[{datetime.now(APP_TZ):%Y-%m-%d %H:%M:%S}] Cleared expired alerts")

def is_alert_sent(instrument, timeframe, pattern_type, level_type=None):
    clear_expired_alerts()
    key = f"{instrument}_{timeframe}_{pattern_type}_{level_type or ''}"
    ts = sent_alerts.get(key)
    return bool(ts and (time.time() - ts) < ALERT_EXPIRY)

def mark_alert_sent(instrument, timeframe, pattern_type, level_type=None):
    key = f"{instrument}_{timeframe}_{pattern_type}_{level_type or ''}"
    sent_alerts[key] = time.time()

# ──────────────────────────────────────────────────────────────────────────────
# OANDA candles
# ──────────────────────────────────────────────────────────────────────────────
def get_candles(instrument="EUR_USD", timeframe="H1", count=2):
    """Return last `count` completed candles as dicts."""
    try:
        url = f"{OANDA_URL}/instruments/{instrument}/candles"
        params = {"count": max(count * 3, 10), "granularity": timeframe, "price": "M"}
        r = requests.get(url, headers=HEADERS, params=params, timeout=20)
        r.raise_for_status()
        data = r.json()
        candles = [c for c in data.get("candles", []) if c.get("complete")]
        final = candles[-count:]
        out = []
        for c in final:
            out.append({
                "open": float(c["mid"]["o"]),
                "high": float(c["mid"]["h"]),
                "low":  float(c["mid"]["l"]),
                "close":float(c["mid"]["c"]),
                "time": c["time"],
                "complete": c["complete"]
            })
        return out
    except Exception as e:
        print(f"get_candles error {instrument} {timeframe}: {e}")
        return []

# ──────────────────────────────────────────────────────────────────────────────
# Pattern logic (engulfing / CPR / body breakout)
# ──────────────────────────────────────────────────────────────────────────────
def is_bullish_engulfing(prev, curr):
    return (curr['open'] <= prev['close'] and
            curr['open'] <  prev['open']  and
            curr['close'] > prev['open'])

def is_bearish_engulfing(prev, curr):
    return (curr['open'] >= prev['close'] and
            curr['open'] >  prev['open']  and
            curr['close'] < prev['open'])

def check_engulfing(instrument="EUR_USD", timeframe="M30"):
    candles = get_candles(instrument, timeframe, count=2)
    if len(candles) < 2:
        return
    prev, curr = candles[-2], candles[-1]

    if is_bullish_engulfing(prev, curr) and not is_alert_sent(instrument, timeframe, "BULLISH"):
        msg = (f"🚀 <b>BULLISH Engulfing</b>\n\n"
               f"Pair: {instrument}\nTF: {timeframe}\n"
               f"Open: {curr['open']:.5f}\nClose: {curr['close']:.5f}\n"
               f"Time: {datetime.now(APP_TZ):%Y-%m-%d %H:%M:%S}")
        send_telegram_alert(msg)
        mark_alert_sent(instrument, timeframe, "BULLISH")

    elif is_bearish_engulfing(prev, curr) and not is_alert_sent(instrument, timeframe, "BEARISH"):
        msg = (f"🔻 <b>BEARISH Engulfing</b>\n\n"
               f"Pair: {instrument}\nTF: {timeframe}\n"
               f"Open: {curr['open']:.5f}\nClose: {curr['close']:.5f}\n"
               f"Time: {datetime.now(APP_TZ):%Y-%m-%d %H:%M:%S}")
        send_telegram_alert(msg)
        mark_alert_sent(instrument, timeframe, "BEARISH")

def check_cpr_engulfing(instrument, timeframe):
    daily = get_candles(instrument, "D", count=2)
    if len(daily) < 2:
        print(f"[{instrument}] Not enough daily candles for CPR.")
        return

    prev_day = daily[-2]
    H, L, C = prev_day["high"], prev_day["low"], prev_day["close"]
    pivot = (H + L + C) / 3.0
    bc = (H + L) / 2.0
    tc = 2 * pivot - bc

    rec = get_candles(instrument, timeframe, count=2)
    if len(rec) < 2:
        print(f"[{instrument} - {timeframe}] Not enough recent candles.")
        return

    prev, curr = rec[-2], rec[-1]
    threshold = max((H - L) * 0.01, 0.0010)  # ~1% of range or 10 pips fallback

    checks = [
        {"pattern": "BEARISH", "emoji": "🔻", "engulf": is_bearish_engulfing(prev, curr),
         "level_type": "TC", "level_val": tc, "near": abs(curr["close"] - tc) <= threshold},
        {"pattern": "BULLISH", "emoji": "🚀", "engulf": is_bullish_engulfing(prev, curr),
         "level_type": "BC", "level_val": bc, "near": abs(curr["close"] - bc) <= threshold},
    ]

    for ck in checks:
        if ck["engulf"] and ck["near"] and not is_alert_sent(instrument, timeframe, ck["pattern"], ck["level_type"]):
            msg = (f"{ck['emoji']} <b>{ck['pattern']} Engulfing near CPR {ck['level_type']}</b>\n\n"
                   f"Pair: {instrument}\nTF: {timeframe}\n"
                   f"Open: {curr['open']:.5f}\nClose: {curr['close']:.5f}\n"
                   f"CPR {ck['level_type']}: {ck['level_val']:.5f}\n"
                   f"Time: {datetime.now(APP_TZ):%Y-%m-%d %H:%M:%S}")
            send_telegram_alert(msg)
            mark_alert_sent(instrument, timeframe, ck["pattern"], ck["level_type"])
            return

# Track daily H/L + one-time alert per day
breakout_state = {}  # instrument -> {prev_high, prev_low, date, alert_sent}

def check_body_breakout(instrument, timeframe="M30"):
    today = datetime.now(APP_TZ).date()
    if instrument not in breakout_state or breakout_state[instrument]["date"] != today:
        daily = get_candles(instrument, "D", count=2)
        if len(daily) < 2:
            print(f"[{instrument}] Not enough daily candles for breakout init")
            return
        prev = daily[-2]
        breakout_state[instrument] = {
            "prev_high": prev["high"],
            "prev_low":  prev["low"],
            "date": today,
            "alert_sent": False
        }

    st = breakout_state[instrument]
    if st["alert_sent"]:
        return

    last = get_candles(instrument, timeframe, count=1)
    if not last:
        return
    c = last[0]
    body_high = max(c["open"], c["close"])
    body_low  = min(c["open"], c["close"])

    if body_low > st["prev_high"]:
        msg = (f"🚀 <b>{instrument} Bullish Body Breakout</b>\n\n"
               f"TF: {timeframe}\nOpen: {c['open']:.5f}\nClose: {c['close']:.5f}\n"
               f"Prev Day High: {st['prev_high']:.5f}\nTime: {datetime.now(APP_TZ):%Y-%m-%d %H:%M:%S}")
        send_telegram_alert(msg)
        st["alert_sent"] = True

    elif body_high < st['prev_low']:
        msg = (f"🔻 <b>{instrument} Bearish Body Breakdown</b>\n\n"
               f"TF: {timeframe}\nOpen: {c['open']:.5f}\nClose: {c['close']:.5f}\n"
               f"Prev Day Low: {st['prev_low']:.5f}\nTime: {datetime.now(APP_TZ):%Y-%m-%d %H:%M:%S}")
        send_telegram_alert(msg)
        st["alert_sent"] = True

# ──────────────────────────────────────────────────────────────────────────────
# FF calendar (ISO-aware fetch + IST/APP_TZ digest + T-LEAD alerts)
# ──────────────────────────────────────────────────────────────────────────────
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

def parse_event_time_ist(ev: Dict) -> Optional[datetime]:
    """
    Return tz-aware datetime in APP_TZ (IST preferred) if event has a precise time.
    Order:
      1) 'timestamp' (UTC seconds)
      2) ISO-8601 in 'date' (e.g., '2025-08-19T08:30:00-04:00' or ...Z)
      3) 'date' + 'time' (NY local clock like '8:30am', '08:30')
    """
    # 1) timestamp
    ts = ev.get("timestamp")
    if ts not in (None, "", "--"):
        try:
            dt_utc = datetime.fromtimestamp(int(float(ts)), tz=timezone.utc)
            return dt_utc.astimezone(APP_TZ)
        except Exception:
            pass

    # 2) ISO-8601 in 'date'
    date_raw = (ev.get("date") or "").strip()
    if date_raw:
        if "T" in date_raw or date_raw.endswith("Z"):
            try:
                iso_s = date_raw.replace("Z", "+00:00")
                dt_iso = datetime.fromisoformat(iso_s)
                if dt_iso.tzinfo is None:
                    dt_iso = dt_iso.replace(tzinfo=(NY_TZ or timezone.utc))
                return dt_iso.astimezone(APP_TZ)
            except Exception:
                pass

    # 3) 'date' + 'time'
    time_s = (ev.get("time") or "").strip().lower()
    if not date_raw or time_s in ("", "all day", "tentative"):
        return None  # no precise time

    date_formats = ["%Y-%m-%d", "%d-%m-%Y", "%Y/%m/%d", "%b %d, %Y"]
    time_formats = ["%I:%M%p", "%I%p", "%H:%M", "%H"]
    for df in date_formats:
        for tf in time_formats:
            try:
                base = datetime.strptime(f"{date_raw} {time_s.upper()}", f"{df} {tf}")
                base = base.replace(tzinfo=(NY_TZ or timezone.utc))
                return base.astimezone(APP_TZ)
            except Exception:
                continue
    return None

def calc_today_variants_app(now_app: datetime) -> Tuple[date, date, date]:
    today_app = now_app.date()
    today_ny  = now_app.astimezone(NY_TZ or timezone.utc).date()
    today_utc = now_app.astimezone(timezone.utc).date()
    return today_app, today_ny, today_utc

def event_is_today_any_app(ev: Dict, now_app: datetime) -> bool:
    """Timed events by parsed APP_TZ dt; otherwise raw-date match vs APP/NY/UTC 'today'."""
    dt_app = parse_event_time_ist(ev)
    if dt_app:
        return dt_app.date() == now_app.date()

    raw = (ev.get("date") or "").strip()
    if raw and not ("T" in raw or raw.endswith("Z")):
        ev_date = parse_any_date(raw)
        if ev_date:
            t_app, t_ny, t_utc = calc_today_variants_app(now_app)
            return ev_date in (t_app, t_ny, t_utc)
    return False

def fmt_line(ev: Dict) -> str:
    title   = ev.get("title") or ev.get("event") or ""
    country = (ev.get("country") or ev.get("currency") or "").upper()
    impact  = (ev.get("impact") or "").capitalize()

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
    if not events:
        return "ℹ️ <b>No events found for today.</b>"
    lines = ["📅 <b>Today's Economic Calendar</b>"]
    by_imp_order = ["High", "Medium", "Low", "Holiday"]
    icons = {"High":"🔴","Medium":"🟡","Low":"🟢","Holiday":"⚪"}
    for imp in by_imp_order:
        bucket = [e for e in events if (e.get("impact") or "").capitalize() == imp]
        if not bucket:
            continue
        lines.append(f"{icons.get(imp,'⚪')} <b>{imp} Impact</b>")
        # aware sort key so we never compare naive vs aware
        bucket.sort(key=lambda ev: (parse_event_time_ist(ev) is None,
                                    parse_event_time_ist(ev) or FAR_FUTURE))
        for ev in bucket:
            lines.append("• " + fmt_line(ev))
        lines.append("")
    return "\n".join(lines).strip()

def is_about_n_minutes_ahead_app(ev_dt: datetime, n: int) -> bool:
    now = datetime.now(APP_TZ)
    delta = (ev_dt - now).total_seconds()
    return (n*60 - 60) <= delta <= (n*60 + 60)

def summarize_feed_dates(events: List[Dict]):
    counter = collections.Counter()
    for ev in events:
        d = (ev.get("date") or "").strip()
        counter[d] += 1
    print("[NEWS] Raw 'date' values (top 12):")
    for i, (k, v) in enumerate(counter.most_common(12), 1):
        print(f"  {i:2d}. {k or '<empty>'}: {v}")

def news_loop(period="thisweek", currencies=None, impacts=None, refresh_minutes=30, alert_lead=30):
    today_events: List[Dict] = []
    last_digest_date: Optional[date] = None
    alerted_keys = set()
    last_fetch_ts = 0.0

    print(f"[NEWS] TZ={APP_TZ}, refresh={refresh_minutes} min, lead={alert_lead} min, period={period}, "
          f"curr={currencies or 'ALL'}, impact={impacts or 'ALL'}")

    while True:
        try:
            now_app = datetime.now(APP_TZ)
            t_app, t_ny, t_utc = calc_today_variants_app(now_app)

            # Fetch immediately then every refresh interval
            if (time.time() - last_fetch_ts) >= (refresh_minutes * 60):
                weekly = fetch_events(period, currencies, impacts)
                print(f"[NEWS] fetched weekly: {len(weekly)} @ {now_app:%Y-%m-%d %H:%M:%S}")
                print(f"[NEWS] Today APP={t_app}, NY={t_ny}, UTC={t_utc}")
                summarize_feed_dates(weekly)

                todays = [ev for ev in weekly if event_is_today_any_app(ev, now_app)]
                # aware, stable sort key
                todays.sort(key=lambda ev: (parse_event_time_ist(ev) is None,
                                            parse_event_time_ist(ev) or FAR_FUTURE))
                print(f"[NEWS] Picked for today: {len(todays)} events")

                today_events = todays
                last_fetch_ts = time.time()

                if last_digest_date != t_app:
                    digest = build_morning_digest(today_events)
                    send_telegram_alert(digest)
                    last_digest_date = t_app
                    alerted_keys.clear()
                    print(f"[NEWS] Digest sent: {len(today_events)} events")

            # T-LEAD alerts for timed events
            if today_events:
                now_app = datetime.now(APP_TZ)
                for ev in today_events:
                    ev_dt = parse_event_time_ist(ev)
                    if not ev_dt:
                        continue  # All Day, etc.
                    if ev_dt < now_app:
                        continue
                    key = f"{int(ev_dt.timestamp())}-{ev.get('title') or ev.get('event')}"
                    if key in alerted_keys:
                        continue
                    if is_about_n_minutes_ahead_app(ev_dt, alert_lead):
                        send_telegram_alert(f"⏳ <b>Event in {alert_lead} minutes</b>\n\n• " + fmt_line(ev))
                        alerted_keys.add(key)

            time.sleep(60)

        except Exception as e:
            print(f"[NEWS] loop error: {e}")
            time.sleep(30)

# ──────────────────────────────────────────────────────────────────────────────
# Scheduling loop for chart patterns
# ──────────────────────────────────────────────────────────────────────────────
def get_next_interval():
    """Seconds until next :00/:30 boundary (to check after candle closes)."""
    now = datetime.now(APP_TZ)
    mins = now.minute
    secs = now.second
    mod = mins % 30
    wait_min = (30 - mod) if mod != 0 else 30
    wait_sec = wait_min * 60 - secs
    if wait_sec <= 0:
        wait_sec = 30 * 60
    return wait_sec

def pattern_monitor(instrument, timeframes):
    while True:
        try:
            wait_seconds = get_next_interval()
            print(f"[{instrument}] waiting {wait_seconds//60}m for next check @ {datetime.now(APP_TZ):%H:%M:%S}")
            time.sleep(wait_seconds)
            clear_expired_alerts()
            for tf in timeframes:
                check_engulfing(instrument, tf)
                check_cpr_engulfing(instrument, tf)
                check_body_breakout(instrument, tf)
                time.sleep(1)  # light rate limit
        except Exception as e:
            print(f"pattern_monitor error {instrument}: {e}")
            time.sleep(60)

# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────
def main():
    test_telegram_bot()
    ap = argparse.ArgumentParser(description="Bot runner (FF news ISO-aware + pattern monitors + liveness)")
    ap.add_argument("--period", default="thisweek", choices=list(PERIOD_TO_PATH.keys()))
    ap.add_argument("--curr", dest="currencies", default="", help="Comma list, e.g. USD,EUR,INR")
    # ap.add_argument("--impact", dest="impacts", default="", help="Comma list: High,Medium,Low,Holiday")
    ap.add_argument("--refresh", type=int, default=REFRESH_MINUTES, help="Minutes between news feed refreshes (ENV REFRESH_MINUTES)")
    ap.add_argument("--lead", type=int, default=ALERT_LEAD_MIN, help="Minutes before event to alert (ENV ALERT_LEAD_MIN)")
    args = ap.parse_args()

    currencies = [c.strip() for c in args.currencies.split(",") if c.strip()]
    #impacts    = [i.strip() for i in args.impacts.split(",") if i.strip()]

    # liveness
    threading.Thread(target=run_flask, daemon=True).start()
    threading.Thread(target=keep_server_alive, daemon=True).start()

    # FF news (digest + T-LEAD alerts)
    # threading.Thread(
    #     target=news_loop,
    #     args=(args.period, currencies or None, impacts or None, args.refresh, args.lead),
    #     daemon=True,
    # ).start()

    # Pattern monitors (engulfing, CPR, body breakout)
    instrument_timeframes = {
        "CAD_JPY": ["M15"],
        "XAU_USD": ["M15"],
    }
    for inst, tfs in instrument_timeframes.items():
        threading.Thread(target=pattern_monitor, args=(inst, tfs), daemon=True).start()
        print(f"Started monitoring {inst}: {', '.join(tfs)}")

    # keep main alive
    try:
        while True:
            print(f"Bot alive @ {datetime.now(APP_TZ):%Y-%m-%d %H:%M:%S} ({APP_TZ})")
            time.sleep(600)
    except KeyboardInterrupt:
        print("Stopped by user.")

if __name__ == "__main__":
    test_telegram_bot()
    main()
