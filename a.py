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



# Load environment variables
load_dotenv()

# Initialize Flask app
app = Flask(__name__)

# Configure logging
#logging.basicConfig(
#    level=logging.INFO,
#    format='%(asctime)s - %(levelname)s - %(message)s'
#)
#logger = logging.getLogger(__name__)

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

HEADERS = {
    'Authorization': f'Bearer {OANDA_API_KEY}'
}

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

def get_chat_id():
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
    #print(chat_id,'chat_id')
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
    
    # Path to your matching ChromeDriver (v138)
    service = Service(r"C:\webdrivers\chromedriver-win64\chromedriver.exe")
    # Update this path as needed

    driver = webdriver.Chrome(service=service, options=options)

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


def check_cpr_engulfing1(instrument, timeframe):
    """
    Detect bullish or bearish engulfing near CPR levels based on previous day's CPR.
    Only alert:
    - Bearish near TC
    - Bullish near BC
    """
    try:
        # Get previous 2 daily candles for CPR calculation
        daily_candles = get_candles(instrument, "D", count=2)
        if len(daily_candles) < 2:
            print(f"Not enough daily candles for CPR on {instrument}")
            return False

        prev_day = daily_candles[-2]
        high = prev_day["high"]
        low = prev_day["low"]
        close = prev_day["close"]

        # CPR levels
        pivot = (high + low + close) / 3
        bc = (high + low) / 2
        tc = (pivot - bc) + pivot

        # Get last 2 candles on current timeframe
        recent_candles = get_candles(instrument, timeframe, count=2)
        if len(recent_candles) < 2:
            print(f"Not enough candles for engulfing check on {instrument} {timeframe}")
            return False

        prev, curr = recent_candles[-2], recent_candles[-1]

        # Proximity threshold (0.1% of price range)
        threshold = (high - low) * 0.001

        near_tc = abs(curr["close"] - tc) <= threshold
        near_bc = abs(curr["close"] - bc) <= threshold

        # Match logic
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
            return False  # Pattern not at the right CPR level

        # Check if we've already sent this alert recently
        if is_alert_sent(instrument, timeframe, pattern_type, level_type):
            return False

        message = f"{emoji} <b>{pattern_type} Engulfing near CPR {level_type}</b>\n\n" \
                  f"Pair: {instrument}\n" \
                  f"Timeframe: {timeframe}\n" \
                  f"Open: {curr['open']:.5f}\n" \
                  f"Close: {curr['close']:.5f}\n" \
                  f"CPR {level_type}: {level_val:.5f}\n" \
                  f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

        print(f"CPR {pattern_type} Engulfing detected for {instrument} on {timeframe}")
        send_telegram_alert(message)
        mark_alert_sent(instrument, timeframe, pattern_type, level_type)
        return True

    except Exception as e:
        print(f"Error in CPR check for {instrument} {timeframe}: {str(e)}")
        return False


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
def check_prev_day_breakout1(instrument, timeframe):
    try:
        # Get previous 2 daily candles
        daily_candles = get_candles(instrument, "D", count=2)
        if len(daily_candles) < 2:
            print(f"Not enough daily candles for {instrument}")
            return False

        prev_day = daily_candles[-2]
        prev_high = prev_day["high"]
        prev_low = prev_day["low"]

        # Get latest candle on current timeframe
        recent_candles = get_candles(instrument, timeframe, count=1)
        if not recent_candles:
            return False

        curr = recent_candles[-1]

        # Check breakout
        if curr["high"] > prev_high and not is_alert_sent(instrument, timeframe, "BREAKOUT", "HIGH"):
            message = f"📈 <b>Breakout Above Previous Day High</b>\n\n" \
                      f"Pair: {instrument}\nTimeframe: {timeframe}\n" \
                      f"Current High: {curr['high']:.5f}\nPrev High: {prev_high:.5f}\n" \
                      f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            send_telegram_alert(message)
            mark_alert_sent(instrument, timeframe, "BREAKOUT", "HIGH")
            return True

        elif curr["low"] < prev_low and not is_alert_sent(instrument, timeframe, "BREAKOUT", "LOW"):
            message = f"📉 <b>Breakdown Below Previous Day Low</b>\n\n" \
                      f"Pair: {instrument}\nTimeframe: {timeframe}\n" \
                      f"Current Low: {curr['low']:.5f}\nPrev Low: {prev_low:.5f}\n" \
                      f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            send_telegram_alert(message)
            mark_alert_sent(instrument, timeframe, "BREAKOUT", "LOW")
            return True

        return False
    except Exception as e:
        print(f"Error in prev day breakout check for {instrument} {timeframe}: {str(e)}")
        return False


def check_prev_day_breakout(instrument, timeframe):
    try:
        if 'D' in timeframe or 'W' in timeframe or 'M' in timeframe:
            print(f"Skipping non-intraday timeframe: {timeframe}")
            return False

        daily_candles = get_candles(instrument, "D", count=2)
        if len(daily_candles) < 2:
            print(f"Not enough daily candles for {instrument}")
            return False

        prev_day = daily_candles[-2]
        prev_high = prev_day["high"]
        prev_low = prev_day["low"]

        recent_candles = get_candles(instrument, timeframe, count=2)
        if len(recent_candles) < 2:
            print(f"Not enough intraday candles for {instrument} on {timeframe}")
            return False

        curr = recent_candles[-1]
        if not curr["complete"]:
            print(f"Skipping incomplete candle for {instrument} {timeframe}")
            return False

        current_date = datetime.now().strftime('%Y-%m-%d')
        open_price = curr["open"]
        close_price = curr["close"]

        # Bullish breakout: full body above previous day high
        if open_price > prev_high and close_price > prev_high:
            alert_key = f"HIGH_{current_date}"
            if is_alert_sent(instrument, timeframe, "BREAKOUT", alert_key):
                return False

            message = f"📈 <b>Body Breakout Above Previous Day High</b>\n\n" \
                      f"Pair: {instrument}\nTimeframe: {timeframe}\n" \
                      f"Open: {open_price:.5f}\nClose: {close_price:.5f}\n" \
                      f"Prev High: {prev_high:.5f}\n" \
                      f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            send_telegram_alert(message)
            mark_alert_sent(instrument, timeframe, "BREAKOUT", alert_key)
            return True

        # Bearish breakdown: full body below previous day low
        elif open_price < prev_low and close_price < prev_low:
            alert_key = f"LOW_{current_date}"
            if is_alert_sent(instrument, timeframe, "BREAKOUT", alert_key):
                return False

            message = f"📉 <b>Body Breakdown Below Previous Day Low</b>\n\n" \
                      f"Pair: {instrument}\nTimeframe: {timeframe}\n" \
                      f"Open: {open_price:.5f}\nClose: {close_price:.5f}\n" \
                      f"Prev Low: {prev_low:.5f}\n" \
                      f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            send_telegram_alert(message)
            mark_alert_sent(instrument, timeframe, "BREAKOUT", alert_key)
            return True

        print(f"No body breakout for {instrument} on {timeframe}")
        return False

    except Exception as e:
        print(f"Error in prev day breakout check for {instrument} {timeframe}: {str(e)}")
        return False


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

def monitor_instrument(instrument, timeframes):
    """Continuously monitor an instrument for patterns"""
    while True:
        try:
            # Wait until next 30-minute interval
            wait_seconds = get_next_interval()
            print(f"Waiting {wait_seconds//60} minutes until next check for {instrument} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            time.sleep(wait_seconds)
            
            # Clear expired alerts at the start of each monitoring cycle
            clear_expired_alerts()
            
            for tf in timeframes:
                signal = check_engulfing(instrument, tf)
                # cpr_signal = check_cpr_engulfing(instrument, tf)
                # breakout_signal = check_prev_day_breakout(instrument, tf)
                if signal or cpr_signal:
                    #logger.info(signal)
                    pass
                time.sleep(1)  # Small delay to avoid hitting rate limits
            
        except Exception as e:
            #logger.error(f"Error in monitoring loop: {str(e)}")
            print(f"Error occurred, retrying in 5 minutes - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            time.sleep(300)  # Wait 5 minutes before retrying

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
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    #logger.info("Flask server started")

    alive_thread = threading.Thread(target=keep_server_alive, daemon=True)
    alive_thread.start()
    
    telegram_thread = threading.Thread(target=poll_updates, daemon=True)
    telegram_thread.start()
    #logger.info("Server alive checker started")

    test_telegram_bot()
    
    # Send economic events at startup
    send_today_economic_events()

    instruments = [
        "EUR_USD", "GBP_USD", "USD_JPY", "USD_CHF", "AUD_USD", "NZD_USD", "USD_CAD",
        "EUR_GBP", "EUR_JPY", "EUR_CHF", "EUR_AUD", "EUR_NZD", "EUR_CAD",
        "GBP_JPY", "GBP_CHF", "GBP_AUD", "GBP_NZD", "GBP_CAD",
        "AUD_JPY", "NZD_JPY", "CAD_JPY", "CHF_JPY",
        "AUD_CHF", "NZD_CHF", "CAD_CHF", "AUD_NZD", "AUD_CAD", "NZD_CAD",
        "XAU_USD", "XAG_USD",
        "WTICO_USD", "BCO_USD"
    ]

    # Define instruments and their specific timeframes
    instrument_timeframes = {
        "EUR_USD": ["M30"],      # EURUSD 30mins
        "XAU_USD": ["H1"],       # XAUUSD 1HR
        "NZD_USD": ["M30"],     # NZDUSD 30mins
        "ETH_USDT": ["H1"]      # ETHUSDT 1HR
    }

    threads = []
    for instrument, timeframes in instrument_timeframes.items():
        thread = threading.Thread(
            target=monitor_instrument,
            args=(instrument, timeframes),
            daemon=True
        )
        thread.start()
        threads.append(thread)
        print(f"Started monitoring {instrument} on timeframes: {', '.join(timeframes)}")

    try:
        while True:
            wait_seconds = get_next_interval()
            time.sleep(wait_seconds)
            print(f"Bot is alive - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    except KeyboardInterrupt:
        #logger.info("Monitoring stopped by user")
        pass

if __name__ == "__main__":
    main()
    #test_telegram_bot()
    #poll_updates()


