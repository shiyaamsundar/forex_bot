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

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import pandas as pd
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
today_events = []
last_fetched_date = None

HEADERS = {
    'Authorization': f'Bearer {OANDA_API_KEY}'
}

# --- The following functions must be defined or imported elsewhere ---
# fetch_investing_calendar
# convert_to_indian_time
# is_event_within_30_minutes
# send_telegram_alert
# check_engulfing
# check_cpr_engulfing
# get_next_interval
# clear_expired_alerts
# run_flask
# keep_server_alive
# poll_updates (already imported)

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

def is_alert_sent(instrument, timeframe, pattern_type, level_type=None):
    """Check if an alert was recently sent"""
    # Clear expired alerts first
    clear_expired_alerts()
    
    key = f"{instrument}_{timeframe}_{pattern_type}_{level_type if level_type else ''}"
    if key in sent_alerts:
        # Check if alert is still valid (within 30 minutes)
        if time.time() - sent_alerts[key] < ALERT_EXPIRY:
            return True
        # Remove expired alert
        del sent_alerts[key]
    return False

def mark_alert_sent(instrument, timeframe, pattern_type, level_type=None):
    """Mark an alert as sent"""
    key = f"{instrument}_{timeframe}_{pattern_type}_{level_type if level_type else ''}"
    sent_alerts[key] = time.time()

def send_telegram_alert(message):
    
    try:
        if not message or not message.strip():
            #logger.error("Cannot send empty message to Telegram")
            return
        print(message,'messagepassss!')        
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML"
        }
        
        response = requests.post(url, json=payload)
        response.raise_for_status()
        #logger.info(f"Telegram alert sent: {message}")
        print(response,'response')
    except requests.exceptions.RequestException as e:
        #logger.error(f"Failed to send Telegram alert: {str(e)}")
        if hasattr(e.response, 'json'):
            error_data = e.response.json()
            #logger.error(f"Telegram API error: {error_data}")
    except Exception as e:
        #logger.error(f"Unexpected error sending Telegram alert: {str(e)}")
        pass

def fetch_calendar_once_per_day():
    global last_fetched_date, today_events 

    while True:
        current_date = date.today()

        # Check if already fetched today
        if last_fetched_date != current_date:
            print(f"[{datetime.now()}] Fetching calendar for {current_date}...")
            try:
                df = fetch_investing_calendar()
                if not df.empty:
                    today_events = df.to_dict(orient='records')
                    last_fetched_date = current_date
                    print(f"Stored {len(today_events)} events for today.")
                else:
                    print("No events found.")
            except Exception as e:
                print(f"Error fetching calendar: {e}")

        # Wait 10 minutes before checking again (low load, avoids unnecessary fetch)
        time.sleep(600)

def check_cpr_engulfing(instrument, timeframe):
    """
    Detect bullish or bearish engulfing near CPR levels based on previous day's CPR.
    Only alert:
    - Bearish near TC
    - Bullish near BC
    """
    try:
        daily_candles = get_candles(instrument, "D", count=2)
        if len(daily_candles) < 2:
            print(f"Not enough daily candles for CPR on {instrument}")
            return False

        prev_day = daily_candles[-2]
        high = prev_day["high"]
        low = prev_day["low"]
        close = prev_day["close"]

        pivot = (high + low + close) / 3
        bc = (high + low) / 2
        tc = (pivot - bc) + pivot

        recent_candles = get_candles(instrument, timeframe, count=2)
        if len(recent_candles) < 2:
            print(f"Not enough candles for engulfing check on {instrument} {timeframe}")
            return False

        prev, curr = recent_candles[-2], recent_candles[-1]

        # Looser threshold for proximity (~10 pips for forex)
        threshold = max((high - low) * 0.01, 0.0010)

        near_tc = abs(curr["close"] - tc) <= threshold
        near_bc = abs(curr["close"] - bc) <= threshold

        if is_bearish_engulfing(prev, curr) and near_tc:
            pattern_type = "BEARISH"
            level_type = "TC"
            level_val = tc
            emoji = "🔻"
        elif is_bullish_engulfing(prev, curr) and near_bc:
            pattern_type = "BULLISH"
            level_type = "BC"
            level_val = bc
            emoji = "🚀"
        else:
            print(f"No CPR engulfing pattern detected for {instrument} on {timeframe}")
            return False

        if is_alert_sent(instrument, timeframe, pattern_type, level_type):
            return False

        message = f"{emoji} <b>{pattern_type} Engulfing near CPR {level_type}</b>\n\n" \
                  f"Pair: {instrument}\n" \
                  f"Timeframe: {timeframe}\n" \
                  f"Open: {curr['open']:.5f}\n" \
                  f"Close: {curr['close']:.5f}\n" \
                  f"CPR {level_type}: {level_val:.5f}\n" \
                  f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

        send_telegram_alert(message)
        mark_alert_sent(instrument, timeframe, pattern_type, level_type)
        return True

    except Exception as e:
        print(f"Error in CPR check for {instrument} {timeframe}: {str(e)}")
        return False



def get_chat_id():
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        
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

def get_next_interval():
    """Calculate seconds until next 30-minute interval"""
    now = datetime.now()
    # Calculate minutes until next 30-minute mark
    minutes_until_next = 30 - (now.minute % 30)
    # If we're at a 30-minute mark, wait for the next hour
    if minutes_until_next == 30:
        minutes_until_next = 0
    # Add seconds
    seconds_until_next = minutes_until_next * 60
    return seconds_until_next


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

def fetch_investing_calendar():
    # Set up headless Chrome options
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--user-agent=Mozilla/5.0")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    
    # Path to your matching ChromeDriver (v138)
    #service = Service(r"C:\webdrivers\chromedriver-win64\chromedriver.exe")
    service = Service("/usr/local/bin/chromedriver") 
    # Update this path as needed

    #driver = webdriver.Chrome(service=service, options=options)
    driver = webdriver.Chrome(service=Service("/usr/local/bin/chromedriver"), options=options)

    try:
        print("Opening Investing.com calendar...")
        driver.get("https://www.investing.com/economic-calendar/")

        # Wait until calendar table loads
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.ID, "economicCalendarData"))
        )
        
        # Optional scroll to load more rows
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)

        print("Extracting rows...")
        rows = driver.find_elements(By.XPATH, "//table[@id='economicCalendarData']//tr[contains(@id,'eventRowId')]")
        
        events = []
        for row in rows:
            try:
                time_ = row.find_element(By.CLASS_NAME, "first.left.time").text.strip()
                currency = row.find_element(By.CLASS_NAME, "left.flagCur.noWrap").text.strip()
                event = row.find_element(By.CLASS_NAME, "event").text.strip()
                importance = len(row.find_elements(By.CLASS_NAME, "grayFullBullishIcon"))

                events.append({
                    "time": time_,
                    "currency": currency,
                    "event": event,
                    "importance": importance
                })
            except Exception as e:
                continue

        df = pd.DataFrame(events)
        print(df)
        
        # Send events to Telegram immediately
        if not df.empty:
            print("Calling send_events_to_telegram function...")
            send_events_to_telegram(df)
        else:
            print("No events found in DataFrame")
        
        return df

    finally:
        driver.quit()


def convert_to_indian_time(time_str):
    """Convert time string to Indian time in 12-hour format"""
    try:
        # Parse the time string (assuming it's in GMT/UTC)
        from datetime import datetime, timedelta
        import pytz
        
        # Create a datetime object for today with the given time
        today = datetime.now().date()
        
        # Parse the time string (format: HH:MM)
        if ':' in time_str:
            hour, minute = map(int, time_str.split(':'))
        else:
            # Handle cases where time might be in different format
            hour, minute = 0, 0
            
        # Create datetime object in UTC
        utc_time = datetime.combine(today, datetime.min.time().replace(hour=hour, minute=minute))
        utc_time = pytz.utc.localize(utc_time)
        
        # Convert to Indian time (IST = UTC+5:30)
        ist_tz = pytz.timezone('Asia/Kolkata')
        ist_time = utc_time.astimezone(ist_tz)
        
        # Format in 12-hour format
        return ist_time.strftime('%I:%M %p')
        
    except Exception as e:
        print(f"Error converting time {time_str}: {e}")
        return time_str

def is_event_within_30_minutes(time_str):
    """Check if event is within 30 minutes from now"""
    try:
        from datetime import datetime, timedelta
        import pytz
        
        # Get current time in IST
        ist_tz = pytz.timezone('Asia/Kolkata')
        now = datetime.now(ist_tz)
        
        # Parse the event time
        today = now.date()
        if ':' in time_str:
            hour, minute = map(int, time_str.split(':'))
        else:
            return False
            
        # Create event time in IST
        event_time = datetime.combine(today, datetime.min.time().replace(hour=hour, minute=minute))
        event_time = ist_tz.localize(event_time)
        
        # Calculate time difference
        time_diff = event_time - now
        
        # Check if event is within 30 minutes and not in the past
        return timedelta(minutes=0) <= time_diff <= timedelta(minutes=30)
        
    except Exception as e:
        print(f"Error checking event time {time_str}: {e}")
        return False

def send_events_to_telegram(df):
    """Send economic events to Telegram with Indian time and 30-minute filter"""
    print('hellohello')
    if df.empty:
        print("No economic events found.")
        return

    print(f"Total events found: {len(df)}")
    
    # Filter events that are within 30 minutes
    upcoming_events = []
    for _, row in df.iterrows():
        indian_time = convert_to_indian_time(row['time'])
        is_within_30 = is_event_within_30_minutes(row['time'])
        print(f"Event: {row['time']} -> {indian_time} (IST), Within 30min: {is_within_30}")
        
        if is_event_within_30_minutes(row['time']):
            upcoming_events.append({
                'time': indian_time,
                'currency': row['currency'],
                'event': row['event'],
                'importance': row['importance']
            })
    
    print(f"Events within 30 minutes: {len(upcoming_events)}")
    
    if not upcoming_events:
        print("No events within 30 minutes.")
        return

    # Create message with Indian time
    message = "🚨 <b>Upcoming Economic Events (Next 30 mins)</b>\n\n"
    
    # Group events by importance
    high_impact = [e for e in upcoming_events if e['importance'] == 3]
    medium_impact = [e for e in upcoming_events if e['importance'] == 2]
    low_impact = [e for e in upcoming_events if e['importance'] == 1]
    
    if high_impact:
        message += "🔴 <b>High Impact Events:</b>\n"
        for event in high_impact:
            message += f"• {event['time']} | {event['currency']} | {event['event']}\n"
        message += "\n"
    
    if medium_impact:
        message += "🟡 <b>Medium Impact Events:</b>\n"
        for event in medium_impact:
            message += f"• {event['time']} | {event['currency']} | {event['event']}\n"
        message += "\n"
    
    if low_impact:
        message += "🟢 <b>Low Impact Events:</b>\n"
        for event in low_impact:
            message += f"• {event['time']} | {event['currency']} | {event['event']}\n"
    
    # Send the message
    print(f"Sending message to Telegram: {message}")
    send_telegram_alert(message)

def is_event_n_minutes_ahead(time_str, minutes):
    """Return True if event is ~`minutes` ahead (±60 seconds margin)"""
    try:
        from datetime import datetime, timedelta
        import pytz

        ist_tz = pytz.timezone('Asia/Kolkata')
        now = datetime.now(ist_tz)

        if ':' not in time_str:
            return False

        hour, minute = map(int, time_str.split(':'))
        today = now.date()
        event_time = datetime.combine(today, datetime.min.time().replace(hour=hour, minute=minute))
        event_time = ist_tz.localize(event_time)

        delta_seconds = (event_time - now).total_seconds()
        return (minutes * 60 - 60) <= delta_seconds <= (minutes * 60 + 60)

    except Exception as e:
        print(f"Error checking {minutes}-minute alert: {e}")
        return False


def send_today_economic_events():
    df = fetch_investing_calendar()
    if df.empty:
        print("No economic events found.")
        return

    high_impact_events = df[df['importance'] == 3]
    if high_impact_events.empty:
        print("No high-impact events for today.")
        return

    for _, row in high_impact_events.iterrows():
        indian_time = convert_to_indian_time(row['time'])
        msg = f"📊 <b>Upcoming Economic Event</b>\n\n" \
              f"🕒 Time: {indian_time} (IST)\n" \
              f"💱 Currency: {row['currency']}\n" \
              f"📌 Event: {row['event']}\n" \
              f"⚠️ Impact: High"
        send_telegram_alert(msg)
        time.sleep(1)

def check_engulfing(instrument="EUR_GBP", timeframe="M1"):
    try:
        candles = get_candles(instrument, timeframe)
        if len(candles) < 2:
            return None

        prev, curr = candles[-2], candles[-1]

        if is_bullish_engulfing(prev, curr):
            # Check if we've already sent this alert recently
            if is_alert_sent(instrument, timeframe, "BULLISH"):
                return None
                
            message = f"🚀 <b>BULLISH Engulfing</b>\n\n" \
                     f"Pair: {instrument}\n" \
                     f"Timeframe: {timeframe}\n" \
                     f"Open: {curr['open']:.5f}\n" \
                     f"Close: {curr['close']:.5f}\n" \
                     f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            send_telegram_alert(message)
            mark_alert_sent(instrument, timeframe, "BULLISH")
            return message
        elif is_bearish_engulfing(prev, curr):
            # Check if we've already sent this alert recently
            if is_alert_sent(instrument, timeframe, "BEARISH"):
                return None
                
            message = f"🔻 <b>BEARISH Engulfing</b>\n\n" \
                     f"Pair: {instrument}\n" \
                     f"Timeframe: {timeframe}\n" \
                     f"Open: {curr['open']:.5f}\n" \
                     f"Close: {curr['close']:.5f}\n" \
                     f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            send_telegram_alert(message)
            mark_alert_sent(instrument, timeframe, "BEARISH")
            return message
        return None
    except Exception as e:
        #logger.error(f"Error checking engulfing pattern: {str(e)}")
        return None

def get_candles(instrument="EUR_GBP", timeframe="H1", count=2):
    try:
        url = f"{OANDA_URL}/instruments/{instrument}/candles"
        params = {
            "count": max(count * 3, 10),
            "granularity": timeframe,
            "price": "M"
        }
        response = requests.get(url, headers=HEADERS, params=params)
        response.raise_for_status()
        data = response.json()
        candles = data.get("candles", [])
        completed = [c for c in candles if c["complete"]]

        if len(completed) < count:
            #logger.warning(f"Only {len(completed)} complete candles found for {instrument} on {timeframe}")
            return []

        final = completed[-count:]
        return [{
            "open": float(c["mid"]["o"]),
            "high": float(c["mid"]["h"]),
            "low": float(c["mid"]["l"]),
            "close": float(c["mid"]["c"]),
            "time": c["time"],
            "complete": c["complete"]
        } for c in final]
    except Exception as e:
        #logger.error(f"Error fetching candles: {str(e)}")
        return []

def is_bullish_engulfing(prev, curr):
    return (
        curr['open'] <= prev['close'] and
        curr['open'] < prev['open'] and
        curr['close'] > prev['open']
    )

def is_bearish_engulfing(prev, curr):
    return (
        curr['open'] >= prev['close'] and
        curr['open'] > prev['open'] and
        curr['close'] < prev['open']
    )




# Global variable to store today's events

def monitor_today_events():
    already_alerted_30min = set()
    already_alerted_5min = set()

    while True:
        if not today_events:
            time.sleep(60)
            continue

        for event in today_events:
            key = f"{event['time']}_{event['event']}"
            ist_time = convert_to_indian_time(event['time'])
            impact_label = {3: "High", 2: "Medium", 1: "Low"}.get(event['importance'], "Unknown")
            impact_emoji = {3: "⚠️", 2: "🔸", 1: "🔹"}.get(event['importance'], "ℹ️")

            # Alert 30 minutes before
            if key not in already_alerted_30min and is_event_n_minutes_ahead(event['time'], 30):
                msg = (
                    "📊 <b>Upcoming Economic Event</b>\n\n"
                    f"🕒 Time: {ist_time} (IST)\n"
                    f"💱 Currency: {event['currency']}\n"
                    f"📌 Event: {event['event']}\n"
                    f"{impact_emoji} Impact: {impact_label} (in 30 mins)"
                )
                send_telegram_alert(msg)
                already_alerted_30min.add(key)

            # Alert 5 minutes before
            if key not in already_alerted_5min and is_event_n_minutes_ahead(event['time'], 5):
                msg = (
                    "⏳ <b>Reminder: Event in 5 Minutes</b>\n\n"
                    f"🕒 Time: {ist_time} (IST)\n"
                    f"💱 Currency: {event['currency']}\n"
                    f"📌 Event: {event['event']}\n"
                    f"{impact_emoji} Impact: {impact_label} (in 5 mins)"
                )
                send_telegram_alert(msg)
                already_alerted_5min.add(key)

        time.sleep(60)

    already_alerted_30min = set()
    already_alerted_5min = set()

    while True:
        if not today_events:
            time.sleep(60)
            continue

        upcoming_30min = []
        upcoming_5min = []

        for event in today_events:
            key = f"{event['time']}_{event['event']}"
            ist_time = convert_to_indian_time(event['time'])

            # Alert 30 mins before
            if key not in already_alerted_30min and is_event_n_minutes_ahead(event['time'], 30):
                upcoming_30min.append((key, event, ist_time))
                already_alerted_30min.add(key)

            # Alert 5 mins before
            if key not in already_alerted_5min and is_event_n_minutes_ahead(event['time'], 5):
                upcoming_5min.append((key, event, ist_time))
                already_alerted_5min.add(key)

        if upcoming_30min:
            msg = "\U0001F6A8 <b>Upcoming Economic Events (In 30 mins)</b>\n\n"
            for key, ev, ist in upcoming_30min:
                impact_emoji = {3: "\U0001F534", 2: "🟡", 1: "🟢"}.get(ev['importance'], "⚪")
                msg += f"{impact_emoji} {ist} | {ev['currency']} | {ev['event']}\n"
            send_telegram_alert(msg)

        if upcoming_5min:
            msg = "\U0001F504 <b>Reminder: Event in 5 mins</b>\n\n"
            for key, ev, ist in upcoming_5min:
                impact_emoji = {3: "\U0001F534", 2: "🟡", 1: "🟢"}.get(ev['importance'], "⚪")
                msg += f"{impact_emoji} {ist} | {ev['currency']} | {ev['event']}\n"
            send_telegram_alert(msg)

        time.sleep(60)

def monitor_today_events12():
    # global today_events
    already_alerted = set()  # Track alerted events to avoid duplicates

    while True:
        if not today_events:
            time.sleep(60)
            continue

        upcoming = []

        for event in today_events:
            key = f"{event['time']}_{event['event']}"
            if key not in already_alerted:
                ist_time = convert_to_indian_time(event['time'])
                upcoming.append((key, event, ist_time))
                already_alerted.add(key)

        if upcoming:
            msg = "\U0001F4C5 <b>All Economic Events (Test Mode)</b>\n\n"
            for key, ev, ist in upcoming:
                impact_emoji = {3: "\U0001F534", 2: "🟡", 1: "🟢"}.get(ev['importance'], "⚪")
                msg += f"{impact_emoji} {ist} | {ev['currency']} | {ev['event']}\n"

            send_telegram_alert(msg)

        time.sleep(600)  # Run again every 10 minutes to avoid spamming


def pattern_monitor(instrument, timeframes):
    while True:
        try:
            wait_seconds = get_next_interval()
            print(f"Waiting {wait_seconds//60} mins for next check on {instrument}")
            time.sleep(wait_seconds)
            clear_expired_alerts()

            for tf in timeframes:
                check_engulfing(instrument, tf)
                check_cpr_engulfing(instrument, tf)
                time.sleep(1)  # rate limit
        except Exception as e:
            print(f"Error in pattern monitor for {instrument}: {str(e)}")
            time.sleep(300)

@app.route('/')
def home():
    return jsonify({"status": "alive", "message": "Forex Bot is running"})

def run_flask():
    app.run(host='0.0.0.0', port=10000)

def keep_server_alive():
    while True:
        try:
            response = requests.get('https://forex-bot-5o8q.onrender.com')
            if response.status_code == 200:
                #logger.info(f"Server alive check successful - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                pass
            else:
                #logger.error(f"Server alive check failed with status code: {response.status_code}")
                pass
        except Exception as e:
            #logger.error(f"Error keeping server alive: {str(e)}")
            pass
        time.sleep(60)

def main():

    test_telegram_bot()

    threading.Thread(target=run_flask, daemon=True).start()
    threading.Thread(target=keep_server_alive, daemon=True).start()
    threading.Thread(target=poll_updates, daemon=True).start()

    threading.Thread(target=monitor_today_events, daemon=True).start()
    threading.Thread(target=fetch_calendar_once_per_day, daemon=True).start()


    # Step 3: Monitor instruments for patterns
    instrument_timeframes = {
        "EUR_USD": ["M30"],
        "XAU_USD": ["H1"],
        "NZD_USD": ["M30"],
        "ETH_USDT": ["H1"]
    }

    for instrument, timeframes in instrument_timeframes.items():
        threading.Thread(
            target=pattern_monitor,
            args=(instrument, timeframes),
            daemon=True
        ).start()
        print(f"Started monitoring {instrument} on timeframes: {', '.join(timeframes)}")

    try:
        while True:
            print(f"Bot is alive - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            time.sleep(600)
    except KeyboardInterrupt:
        print("Stopped by user.")

if __name__ == "__main__":
    main()
