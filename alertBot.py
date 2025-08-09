import requests
import time
import json
import logging
from datetime import datetime
import threading
from flask import Flask, jsonify
import os
from dotenv import load_dotenv
from nse2bot2 import poll_updates

from datetime import date

app = Flask(__name__)
last_clear_time = time.time()


# ---------- NEW / UPDATED HELPERS ----------

def get_next_interval():
    """Seconds until the next 30-minute boundary (e.g., :00 or :30)."""
    now = datetime.now()
    mins_mod = now.minute % 30
    minutes_until_next = 30 - mins_mod if mins_mod != 0 else 30
    seconds_until_next = minutes_until_next * 60 - now.second
    if seconds_until_next <= 0:
        seconds_until_next = 30 * 60
    return seconds_until_next

def clear_expired_alerts():
    """Clear expired alerts every 30 mins and reset daily breakouts at midnight"""
    global last_clear_time
    current_time = time.time()
    now = datetime.now()

    # Clear if 30 mins passed or it's just after midnight
    if current_time - last_clear_time >= ALERT_EXPIRY or now.strftime('%H:%M') == "00:01":
        sent_alerts.clear()
        last_clear_time = current_time
        print(f"[{now.strftime('%Y-%m-%d %H:%M:%S')}] Cleared expired/daily alerts")


def heartbeat():
    """Emit a log every minute so we can track liveness in Render."""
    i = 0
    while True:
        i += 1
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Heartbeat #{i} | uptime OK", flush=True)
        time.sleep(60)


def keep_server_alive():
    """Self-ping the service every minute to keep it warm."""
    url = os.getenv("HEALTH_URL", "https://forex-bot-5o8q.onrender.com")
    while True:
        try:
            r = requests.get(url, timeout=10)
            if r.status_code == 200:
                print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Self-ping OK", flush=True)
            else:
                print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Self-ping non-200: {r.status_code}", flush=True)
        except Exception as e:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Self-ping error: {e}", flush=True)
        time.sleep(60)


# ---------- UPDATED monitor_instrument ----------

def monitor_instrument(instrument, timeframes):
    """Continuously monitor an instrument for patterns, aligned to 30-min boundaries."""
    while True:
        try:
            wait_seconds = get_next_interval()
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
                  f"[{instrument}] Next pattern scan in ~{wait_seconds//60} minute(s)", flush=True)

            # Sleep in small chunks so logs still appear frequently
            slept = 0
            while slept < wait_seconds:
                chunk = min(10, wait_seconds - slept)
                time.sleep(chunk)
                slept += chunk

            clear_expired_alerts()

            for tf in timeframes:
                # Each check wrapped so one failure doesn’t kill the loop
                try:
                    if 'check_engulfing' in globals():
                        check_engulfing(instrument, tf)
                except Exception as e:
                    print(f"[{instrument} {tf}] check_engulfing error: {e}", flush=True)

                try:
                    if 'check_cpr_engulfing' in globals():
                        check_cpr_engulfing(instrument, tf)
                except Exception as e:
                    print(f"[{instrument} {tf}] check_cpr_engulfing error: {e}", flush=True)

                try:
                    if 'check_body_breakout' in globals():
                        check_body_breakout(instrument, tf)
                except Exception as e:
                    print(f"[{instrument} {tf}] check_body_breakout error: {e}", flush=True)

                time.sleep(1)  # polite rate limit

            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
                  f"[{instrument}] Pattern scan complete", flush=True)

        except Exception as e:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
                  f"[{instrument}] Monitor loop error: {e}. Retrying in 5 minutes.", flush=True)
            time.sleep(300)


# ---------- UNCHANGED ----------
def run_flask():
    app.run(host='0.0.0.0', port=10000)


# ---------- UPDATED main() TO START HEARTBEAT TOO ----------

def main():
    # Start Flask web server
    threading.Thread(target=run_flask, daemon=True).start()

    # Keep-alive pinger for Render
    threading.Thread(target=keep_server_alive, daemon=True).start()

    # Heartbeat (per-minute console log)
    threading.Thread(target=heartbeat, daemon=True).start()

    # Step 3: Monitor instruments for patterns
    instrument_timeframes = {
        "EUR_USD": ["M30"],
        "XAU_USD": ["H1"],
        "NZD_USD": ["M30"],
        "ETH_USDT": ["H1"]
    }

    for instrument, tfs in instrument_timeframes.items():
        threading.Thread(
            target=monitor_instrument,
            args=(instrument, tfs),
            daemon=True
        ).start()
        print(f"Started monitoring {instrument} on timeframes: {', '.join(tfs)}", flush=True)

    try:
        while True:
            print(f"Bot is alive - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
            time.sleep(60)
    except KeyboardInterrupt:
        print("Stopped by user.", flush=True)


if __name__ == "__main__":
    main()
