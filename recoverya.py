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

# Load environment variables
load_dotenv()

# Initialize Flask app
app = Flask(__name__)

# Configuration from environment variables
OANDA_API_KEY = os.getenv('OANDA_API_KEY')
OANDA_ACCOUNT_ID = os.getenv('OANDA_ACCOUNT_ID')
OANDA_URL = os.getenv('OANDA_URL')
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

# Track sent alerts to prevent duplicates
sent_alerts = {}
ALERT_EXPIRY = 1800  # 30 minutes in seconds
last_clear_time = time.time()
breakout_alerts = {}

HEADERS = {
    'Authorization': f'Bearer {OANDA_API_KEY}'
}

def clear_expired_alerts():
    global last_clear_time
    current_time = time.time()
    now = datetime.now()
    if current_time - last_clear_time >= ALERT_EXPIRY or now.strftime('%H:%M') == "00:01":
        sent_alerts.clear()
        last_clear_time = current_time
        print(f"[{now.strftime('%Y-%m-%d %H:%M:%S')}] Cleared expired/daily alerts")

def is_alert_sent(instrument, timeframe, pattern_type, level_type=None):
    clear_expired_alerts()
    key = f"{instrument}_{timeframe}_{pattern_type}_{level_type if level_type else ''}"
    if key in sent_alerts:
        if time.time() - sent_alerts[key] < ALERT_EXPIRY:
            return True
        del sent_alerts[key]
    return False

def mark_alert_sent(instrument, timeframe, pattern_type, level_type=None):
    key = f"{instrument}_{timeframe}_{pattern_type}_{level_type if level_type else ''}"
    sent_alerts[key] = time.time()

def send_telegram_alert(message):
    try:
        if not message or not message.strip():
            return
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML"
        }
        response = requests.post(url, json=payload)
        response.raise_for_status()
        print("Telegram alert sent")
    except Exception as e:
        print(f"Telegram send error: {e}")

def check_body_breakout(instrument, timeframe="M30"):
    global breakout_alerts
    if instrument not in breakout_alerts:
        daily_candles = get_candles(instrument, "D", count=2)
        if len(daily_candles) < 2:
            return
        prev = daily_candles[-2]
        breakout_alerts[instrument] = {
            "prev_high": prev["high"],
            "prev_low": prev["low"],
            "alert_sent": False,
            "date": datetime.now().date()
        }

    today = datetime.now().date()
    if breakout_alerts[instrument]["date"] != today:
        breakout_alerts[instrument]["alert_sent"] = False
        breakout_alerts[instrument]["date"] = today
        daily_candles = get_candles(instrument, "D", count=2)
        if len(daily_candles) >= 2:
            prev = daily_candles[-2]
            breakout_alerts[instrument]["prev_high"] = prev["high"]
            breakout_alerts[instrument]["prev_low"] = prev["low"]

    if breakout_alerts[instrument]["alert_sent"]:
        return

    candles = get_candles(instrument, timeframe, count=1)
    if not candles:
        return

    candle = candles[0]
    body_high = max(candle["open"], candle["close"])
    body_low = min(candle["open"], candle["close"])
    prev_high = breakout_alerts[instrument]["prev_high"]
    prev_low = breakout_alerts[instrument]["prev_low"]

    if body_low > prev_high:
        msg = f"🚀 <b>{instrument} Bullish Breakout</b>\n\n"
        msg += f"🕒 Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        msg += f"Open: {candle['open']:.5f}\nClose: {candle['close']:.5f}\nPrev Day High: {prev_high:.5f}"
        send_telegram_alert(msg)
        breakout_alerts[instrument]["alert_sent"] = True

    elif body_high < prev_low:
        msg = f"🔻 <b>{instrument} Bearish Breakdown</b>\n\n"
        msg += f"🕒 Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        msg += f"Open: {candle['open']:.5f}\nClose: {candle['close']:.5f}\nPrev Day Low: {prev_low:.5f}"
        send_telegram_alert(msg)
        breakout_alerts[instrument]["alert_sent"] = True

def check_cpr_engulfing(instrument, timeframe):
    try:
        daily_candles = get_candles(instrument, "D", count=2)
        if len(daily_candles) < 2:
            return False

        prev_day = daily_candles[-2]
        high, low, close = prev_day["high"], prev_day["low"], prev_day["close"]

        pivot = (high + low + close) / 3
        bc = (high + low) / 2
        tc = (2 * pivot) - bc

        recent_candles = get_candles(instrument, timeframe, count=2)
        if len(recent_candles) < 2:
            return False

        prev, curr = recent_candles[-2], recent_candles[-1]
        threshold = max((high - low) * 0.01, 0.0010)

        checks = [
            {"pattern": "BEARISH", "emoji": "🔻", "engulf_check": is_bearish_engulfing(prev, curr),
             "level_type": "TC", "level_val": tc, "near": abs(curr["close"] - tc) <= threshold},

            {"pattern": "BULLISH", "emoji": "🚀", "engulf_check": is_bullish_engulfing(prev, curr),
             "level_type": "TC", "level_val": tc, "near": abs(curr["close"] - tc) <= threshold},

            {"pattern": "BULLISH", "emoji": "🚀", "engulf_check": is_bullish_engulfing(prev, curr),
             "level_type": "BC", "level_val": bc, "near": abs(curr["close"] - bc) <= threshold},

            {"pattern": "BEARISH", "emoji": "🔻", "engulf_check": is_bearish_engulfing(prev, curr),
             "level_type": "BC", "level_val": bc, "near": abs(curr["close"] - bc) <= threshold},
        ]

        for check in checks:
            if check["engulf_check"] and check["near"]:
                msg = (
                    f"{check['emoji']} <b>{check['pattern']} Engulfing near CPR {check['level_type']}</b>\n\n"
                    f"Pair: {instrument}\n"
                    f"Timeframe: {timeframe}\n"
                    f"Open: {curr['open']:.5f}\n"
                    f"Close: {curr['close']:.5f}\n"
                    f"CPR {check['level_type']}: {check['level_val']:.5f}\n"
                    f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                )
                send_telegram_alert(msg)
                mark_alert_sent(instrument, timeframe, check["pattern"], check["level_type"])
                return True
        return False

    except Exception as e:
        print(f"[{instrument} - {timeframe}] CPR engulfing error: {str(e)}")
        return False
