#!/usr/bin/env python3
import os
import time
import threading
import requests
from dotenv import load_dotenv
from flask import Flask, jsonify

import argparse
from datetime import datetime, timezone, timedelta, date
from typing import Iterable, Optional, List, Dict

import requests

# ── ENV ────────────────────────────────────────────────────────────────────────
load_dotenv()
OANDA_API_KEY     = os.getenv('OANDA_API_KEY')
OANDA_ACCOUNT_ID  = os.getenv('OANDA_ACCOUNT_ID')  # not used here but kept for future
OANDA_URL         = os.getenv('OANDA_URL')         # e.g. https://api-fxpractice.oanda.com/v3
TELEGRAM_BOT_TOKEN= os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID  = os.getenv('TELEGRAM_CHAT_ID')

HEADERS = {'Authorization': f'Bearer {OANDA_API_KEY}'}

# ── FLASK LIVENESS ─────────────────────────────────────────────────────────────
app = Flask(__name__)

@app.route('/')
def home():
    return jsonify({"status": "alive", "message": "Forex Bot is running"})

def run_flask():
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
    
def keep_server_alive():
    """Optional health ping (use your own Render URL)."""
    url = os.getenv("SELF_URL", "https://forex-bot-1-c7bj.onrender.com/")
    while True:
        try:
            r = requests.get(url, timeout=10)
            print(f"Server alive: {r.status_code} @ {datetime.now():%Y-%m-%d %H:%M:%S}", flush=True)
        except Exception as e:
            print(f"Alive check error: {e}", flush=True)
        time.sleep(60)

# ── TELEGRAM ───────────────────────────────────────────────────────────────────
def send_telegram_alert(message: str):
    try:
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

# ── DEDUP / RATE LIMIT ─────────────────────────────────────────────────────────
sent_alerts = {}         # key -> last_sent_epoch
ALERT_EXPIRY = 30 * 60   # 30 minutes
last_clear_time = time.time()

def clear_expired_alerts():
    global last_clear_time
    now = time.time()
    if now - last_clear_time >= ALERT_EXPIRY:
        sent_alerts.clear()
        last_clear_time = now
        print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Cleared expired alerts")

def is_alert_sent(instrument, timeframe, pattern_type, level_type=None):
    clear_expired_alerts()
    key = f"{instrument}_{timeframe}_{pattern_type}_{level_type or ''}"
    ts = sent_alerts.get(key)
    if ts and (time.time() - ts) < ALERT_EXPIRY:
        return True
    return False

def mark_alert_sent(instrument, timeframe, pattern_type, level_type=None):
    key = f"{instrument}_{timeframe}_{pattern_type}_{level_type or ''}"
    sent_alerts[key] = time.time()

# ── OANDA CANDLES ──────────────────────────────────────────────────────────────
def get_candles(instrument="EUR_USD", timeframe="H1", count=2):
    """
    Returns a list of the last `count` COMPLETED candles:
    [{open, high, low, close, time, complete}, ...]
    """
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
                "low": float(c["mid"]["l"]),
                "close": float(c["mid"]["c"]),
                "time": c["time"],
                "complete": c["complete"]
            })
        return out
    except Exception as e:
        print(f"get_candles error {instrument} {timeframe}: {e}")
        return []

# ── PATTERN LOGIC ──────────────────────────────────────────────────────────────
def is_bullish_engulfing(prev, curr):
    # Wide/simple definition: current body engulfs previous body and closes above prev open
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

    if is_bullish_engulfing(prev, curr):
        if not is_alert_sent(instrument, timeframe, "BULLISH"):
            msg = (f"🚀 <b>BULLISH Engulfing</b>\n\n"
                   f"Pair: {instrument}\nTF: {timeframe}\n"
                   f"Open: {curr['open']:.5f}\nClose: {curr['close']:.5f}\n"
                   f"Time: {datetime.now():%Y-%m-%d %H:%M:%S}")
            send_telegram_alert(msg)
            mark_alert_sent(instrument, timeframe, "BULLISH")

    elif is_bearish_engulfing(prev, curr):
        if not is_alert_sent(instrument, timeframe, "BEARISH"):
            msg = (f"🔻 <b>BEARISH Engulfing</b>\n\n"
                   f"Pair: {instrument}\nTF: {timeframe}\n"
                   f"Open: {curr['open']:.5f}\nClose: {curr['close']:.5f}\n"
                   f"Time: {datetime.now():%Y-%m-%d %H:%M:%S}")
            send_telegram_alert(msg)
            mark_alert_sent(instrument, timeframe, "BEARISH")

def check_cpr_engulfing(instrument, timeframe):
    """
    CPR from previous day: Pivot=(H+L+C)/3, BC=(H+L)/2, TC=2*Pivot-BC
    Alert when bullish/bearish engulfing happens near TC or BC (±1% of prev day's range, min 10 pips).
    """
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
        if ck["engulf"] and ck["near"]:
            if not is_alert_sent(instrument, timeframe, ck["pattern"], ck["level_type"]):
                msg = (f"{ck['emoji']} <b>{ck['pattern']} Engulfing near CPR {ck['level_type']}</b>\n\n"
                       f"Pair: {instrument}\nTF: {timeframe}\n"
                       f"Open: {curr['open']:.5f}\nClose: {curr['close']:.5f}\n"
                       f"CPR {ck['level_type']}: {ck['level_val']:.5f}\n"
                       f"Time: {datetime.now():%Y-%m-%d %H:%M:%S}")
                send_telegram_alert(msg)
                mark_alert_sent(instrument, timeframe, ck["pattern"], ck["level_type"])
            return

# Track daily H/L + one-time alert per day
breakout_state = {}  # instrument -> {prev_high, prev_low, date, alert_sent}

def check_body_breakout(instrument, timeframe="M30"):
    """
    First candle BODY breakout above previous day's HIGH (bullish) or below LOW (bearish).
    Fires once per day per instrument.
    """
    # Ensure state
    today = datetime.now().date()
    if instrument not in breakout_state or breakout_state[instrument]["date"] != today:
        daily = get_candles(instrument, "D", count=2)
        if len(daily) < 2:
            print(f"[{instrument}] Not enough daily candles for breakout init")
            return
        prev = daily[-2]
        breakout_state[instrument] = {
            "prev_high": prev["high"],
            "prev_low": prev["low"],
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
               f"Prev Day High: {st['prev_high']:.5f}\nTime: {datetime.now():%Y-%m-%d %H:%M:%S}")
        send_telegram_alert(msg)
        st["alert_sent"] = True

    elif body_high < st["prev_low"]:
        msg = (f"🔻 <b>{instrument} Bearish Body Breakdown</b>\n\n"
               f"TF: {timeframe}\nOpen: {c['open']:.5f}\nClose: {c['close']:.5f}\n"
               f"Prev Day Low: {st['prev_low']:.5f}\nTime: {datetime.now():%Y-%m-%d %H:%M:%S}")
        send_telegram_alert(msg)
        st["alert_sent"] = True

# ── SCHEDULING LOOP ────────────────────────────────────────────────────────────
def get_next_interval():
    """
    Seconds until the next 30-min boundary (:00 or :30).
    If we're exactly on boundary, wait full 30 mins to ensure next candle completes.
    """
    now = datetime.now()
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
            print(f"[{instrument}] waiting {wait_seconds//60}m for next check @ {datetime.now():%H:%M:%S}")
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


# --- NEW: put the FF alert loop into its own function ---
def ff_alert_loop(period: str, currencies: List[str], impacts: List[str]):
    today_events: List[Dict] = []
    last_fetch_date: Optional[date] = None
    alerted_keys_30m = set()

    print(f"[FF LOOP] IST MorningHour={MORNING_HOUR}, filters: curr={currencies or 'ALL'}, impact={impacts or 'ALL'}")
    while True:
        try:
            now_ist = datetime.now(IST)
            today_ist = now_ist.date()

            # fetch once each morning (IST)
            need_fetch = (last_fetch_date != today_ist) and (now_ist.hour >= MORNING_HOUR)
            if need_fetch:
                weekly = fetch_events(period, currencies or None, impacts or None)
                todays = [ev for ev in weekly if is_same_ist_day(ev, today_ist)]
                todays.sort(key=lambda ev: parse_event_time_ist(ev) or datetime.max)
                today_events = todays
                last_fetch_date = today_ist
                alerted_keys_30m.clear()

                # morning digest
                send_telegram_alert(build_morning_digest(today_events))
                print(f"[{now_ist:%Y-%m-%d %H:%M}] Morning fetch: {len(today_events)} events")

            # 30-min alerts
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
            print(f"[FF LOOP] error: {e}")
            time.sleep(30)



# ── MAIN ───────────────────────────────────────────────────────────────────────
def main():
    # argparse just for FF filters/period
    ap = argparse.ArgumentParser(description="Bot runner (FF alerts + pattern monitors + liveness)")
    ap.add_argument("--period", default="thisweek", choices=list(PERIOD_TO_PATH.keys()))
    ap.add_argument("--curr", dest="currencies", default="", help="Comma list, e.g. USD,EUR,INR")
    ap.add_argument("--impact", dest="impacts", default="", help="Comma list: High,Medium,Low,Holiday")
    args = ap.parse_args()

    currencies = [c.strip() for c in args.currencies.split(",") if c.strip()]
    impacts = [i.strip() for i in args.impacts.split(",") if i.strip()]

    # 1) liveness
    threading.Thread(target=run_flask, daemon=True).start()
    threading.Thread(target=keep_server_alive, daemon=True).start()

    # 2) FF alerts (morning digest + T-30)
    threading.Thread(
        target=ff_alert_loop,
        args=(args.period, currencies, impacts),
        daemon=True,
    ).start()

    # 3) Pattern monitors (engulfing, CPR, body breakout)
    instrument_timeframes = {
        "EUR_USD": ["M30"],
        "XAU_USD": ["H1"],
        "NZD_USD": ["M30"],
        "ETH_USD": ["H1"],  # adjust if your OANDA symbol differs
    }
    for inst, tfs in instrument_timeframes.items():
        threading.Thread(target=pattern_monitor, args=(inst, tfs), daemon=True).start()
        print(f"Started monitoring {inst}: {', '.join(tfs)}")

    # 4) keep the main thread alive
    try:
        while True:
            print(f"Bot alive @ {datetime.now():%Y-%m-%d %H:%M:%S}")
            time.sleep(600)
    except KeyboardInterrupt:
        print("Stopped by user.")

if __name__ == "__main__":
    main()
