import requests
import time
import json
import logging
from datetime import datetime
import threading
from flask import Flask, jsonify
import os
from dotenv import load_dotenv

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

HEADERS = {
    'Authorization': f'Bearer {OANDA_API_KEY}'
}

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
    if not chat_id:
        #logger.error("Could not get chat ID. Please make sure you've sent a message to your bot.")
        return
        
    global TELEGRAM_CHAT_ID
    TELEGRAM_CHAT_ID = chat_id
    
    test_message = "🤖 <b>Forex Alert Bot Test</b>\n\n" \
                  "This is a test message to verify that the bot is working correctly.\n" \
                  "If you receive this message, the bot is properly configured!"
    send_telegram_alert(test_message)

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


def check_cpr_engulfing(instrument, timeframe):
    """
    Check engulfing pattern near CPR lines (TC or BC) and send combined alert.
    Returns True if pattern is found and alert is sent, False otherwise.
    """
    try:
        # Get more candles to ensure we have enough data for CPR calculation
        candles = get_candles(instrument, timeframe, count=10)
        if len(candles) < 10:
            print(f"Not enough candles for CPR calculation on {instrument} {timeframe}")
            return False

        # Calculate CPR levels
        high = max(candle["high"] for candle in candles)
        low = min(candle["low"] for candle in candles)
        close = candles[-1]["close"]
        
        # Calculate CPR levels
        pivot = (high + low + close) / 3
        bc = (high + low) / 2
        tc = (pivot - bc) + pivot

        # Get the last two candles for engulfing check
        prev, curr = candles[-2], candles[-1]
        
        # Define proximity threshold (0.1% of the price range)
        threshold = (high - low) * 0.001
        
        # Check if price is near CPR levels
        near_tc = abs(curr["close"] - tc) <= threshold
        near_bc = abs(curr["close"] - bc) <= threshold
        
        if not (near_tc or near_bc):
            return False

        # Check for engulfing patterns
        is_bullish = is_bullish_engulfing(prev, curr)
        is_bearish = is_bearish_engulfing(prev, curr)
        
        if not (is_bullish or is_bearish):
            return False

        # Prepare the alert message
        pattern_type = "BULLISH" if is_bullish else "BEARISH"
        level_type = "TC" if near_tc else "BC"
        emoji = "🚀" if is_bullish else "🔻"
        
        message = f"{emoji} <b>{pattern_type} Engulfing near {level_type}</b>\n\n" \
                 f"Pair: {instrument}\n" \
                 f"Timeframe: {timeframe}\n" \
                 f"Open: {curr['open']:.5f}\n" \
                 f"Close: {curr['close']:.5f}\n" \
                 f"CPR {level_type}: {tc if near_tc else bc:.5f}\n" \
                 f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
        print(f"CPR Engulfing detected for {instrument} on {timeframe}")
        send_telegram_alert(message)
        return True

    except Exception as e:
        print(f"Error in check_cpr_engulfing for {instrument} {timeframe}: {str(e)}")
        return False


def check_engulfing(instrument="EUR_GBP", timeframe="M1"):
    try:
        candles = get_candles(instrument, timeframe)
        if len(candles) < 2:
            return None

        prev, curr = candles[-2], candles[-1]

        if is_bullish_engulfing(prev, curr):
            message = f"🚀 <b>BULLISH Engulfing</b>\n\n" \
                     f"Pair: {instrument}\n" \
                     f"Timeframe: {timeframe}\n" \
                     f"Open: {curr['open']:.5f}\n" \
                     f"Close: {curr['close']:.5f}\n" \
                     f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            send_telegram_alert(message)
            return message
        elif is_bearish_engulfing(prev, curr):
            message = f"🔻 <b>BEARISH Engulfing</b>\n\n" \
                     f"Pair: {instrument}\n" \
                     f"Timeframe: {timeframe}\n" \
                     f"Open: {curr['open']:.5f}\n" \
                     f"Close: {curr['close']:.5f}\n" \
                     f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            send_telegram_alert(message)
            return message
        return None
    except Exception as e:
        #logger.error(f"Error checking engulfing pattern: {str(e)}")
        return None

def monitor_instrument(instrument, timeframes):
    """Continuously monitor an instrument for patterns"""
    while True:
        try:
            for tf in timeframes:
                signal = check_engulfing(instrument, tf)
                cpr_signal = check_cpr_engulfing(instrument, tf)
                if signal or cpr_signal:
                    #logger.info(signal)
                    pass
                time.sleep(1)  # Small delay to avoid hitting rate limits
            print(f"Waiting 15 minutes before next check for {instrument} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            time.sleep(900)  # 15 minutes = 900 seconds
        except Exception as e:
            #logger.error(f"Error in monitoring loop: {str(e)}")
            time.sleep(900)  # Wait 15 minutes before retrying

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
    #logger.info("Server alive checker started")

    test_telegram_bot()

    instruments = [
        "EUR_USD", "GBP_USD", "USD_JPY", "USD_CHF", "AUD_USD", "NZD_USD", "USD_CAD",
        "EUR_GBP", "EUR_JPY", "EUR_CHF", "EUR_AUD", "EUR_NZD", "EUR_CAD",
        "GBP_JPY", "GBP_CHF", "GBP_AUD", "GBP_NZD", "GBP_CAD",
        "AUD_JPY", "NZD_JPY", "CAD_JPY", "CHF_JPY",
        "AUD_CHF", "NZD_CHF", "CAD_CHF", "AUD_NZD", "AUD_CAD", "NZD_CAD",
        "XAU_USD", "XAG_USD",
        "WTICO_USD", "BCO_USD"
    ]

    #timeframes = ["M1", "M5", "M15", "M30", "H1", "H4", "D", "W", "M"]
    timeframes = ["M30"]

    threads = []
    for instrument in instruments:
        thread = threading.Thread(
            target=monitor_instrument,
            args=(instrument, timeframes),
            daemon=True
        )
        thread.start()
        threads.append(thread)
        #logger.info(f"Started monitoring {instrument}")

    try:
        while True:
            time.sleep(60)
            print(f"Bot is alive - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    except KeyboardInterrupt:
        #logger.info("Monitoring stopped by user")
        pass

if __name__ == "__main__":
    main()
