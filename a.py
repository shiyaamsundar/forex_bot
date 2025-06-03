import requests
import time
import json
import logging
from datetime import datetime
import threading
from flask import Flask, jsonify

# Initialize Flask app
app = Flask(__name__)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
OANDA_API_KEY = '816bb6859c55c695017b323717644166-261bfdb5340bf2254dea6ff908474fd5'
OANDA_ACCOUNT_ID = '101-001-31847433-001'
OANDA_URL = 'https://api-fxpractice.oanda.com/v3'  # use api-fxtrade.oanda.com for live
TELEGRAM_BOT_TOKEN = '8138331040:AAH_1S50R0_fHGbedJExuzIizoQ6I6fr5iw'
TELEGRAM_CHAT_ID = '1002403985994'  # Replace with your Telegram chat ID

HEADERS = {
    'Authorization': f'Bearer {OANDA_API_KEY}'
}

def send_telegram_alert(message):
    """Send alert to Telegram channel"""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML"
        }
        
        response = requests.post(url, json=payload)
        response.raise_for_status()
        logger.info(f"Telegram alert sent: {message}")
    except Exception as e:
        logger.error(f"Failed to send Telegram alert: {str(e)}")

def get_chat_id():
    """Get the chat ID from the bot's updates"""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        
        if data["ok"] and data["result"]:
            # Get the most recent message
            latest_message = data["result"][-1]
            chat_id = latest_message["message"]["chat"]["id"]
            logger.info(f"Found chat ID: {chat_id}")
            return chat_id
        else:
            logger.error("No messages found. Please send a message to your bot first.")
            return None
    except Exception as e:
        logger.error(f"Error getting chat ID: {str(e)}")
        return None

def test_telegram_bot():
    """Send a test message to verify Telegram bot functionality"""
    # Get chat ID first
    chat_id = get_chat_id()
    if not chat_id:
        logger.error("Could not get chat ID. Please make sure you've sent a message to your bot.")
        return
        
    # Update the global chat ID
    global TELEGRAM_CHAT_ID
    TELEGRAM_CHAT_ID = chat_id
    
    test_message = "🤖 <b>Forex Alert Bot Test</b>\n\n" \
                  "This is a test message to verify that the bot is working correctly.\n" \
                  "If you receive this message, the bot is properly configured!"
    send_telegram_alert(test_message)
    logger.info("Test message sent to Telegram")

def get_candles(instrument="EUR_GBP", timeframe="H1", count=2):
    """Get candle data from OANDA API"""
    try:
        url = f"{OANDA_URL}/instruments/{instrument}/candles"
        params = {
            "count": count,
            "granularity": timeframe,
            "price": "M"  # Midpoint prices
        }
        response = requests.get(url, headers=HEADERS, params=params)
        response.raise_for_status()
        data = response.json()
        #print(data)
        candles = data["candles"]
        return [{
            "open": float(c["mid"]["o"]),
            "high": float(c["mid"]["h"]),
            "low": float(c["mid"]["l"]),
            "close": float(c["mid"]["c"]),
            "complete": c["complete"]
        } for c in candles if c["complete"]]
    except Exception as e:
        logger.error(f"Error fetching candles: {str(e)}")
        return []

def is_bullish_engulfing(prev, curr):
    """
    Bullish Engulfing:
    - Previous candle is bearish (close < open)
    - Current candle is bullish (close > open)
    - Current candle's body engulfs previous candle's body
    """
    return (
        prev['close'] < prev['open'] and      # prev bearish
        curr['close'] > curr['open'] and      # curr bullish
        curr['open'] <= prev['close'] and     # engulfing start
        curr['close'] >= prev['open']         # engulfing end
    )


def is_bearish_engulfing(prev, curr):
    """
    Bearish Engulfing:
    - Previous candle is bullish (close > open)
    - Current candle is bearish (close < open)
    - Current candle's body engulfs previous candle's body
    """
    return (
        prev['close'] > prev['open'] and      # prev bullish
        curr['close'] < curr['open'] and      # curr bearish
        curr['open'] >= prev['close'] and     # engulfing start
        curr['close'] <= prev['open']         # engulfing end
    )
    
def check_engulfing(instrument="EUR_GBP", timeframe="1M"):
    """Check for engulfing patterns and send alerts"""
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
        logger.error(f"Error checking engulfing pattern: {str(e)}")
        return None

def monitor_instrument(instrument, timeframes):
    """Continuously monitor an instrument for patterns"""
    while True:
        try:
            for tf in timeframes:
                signal = check_engulfing(instrument, tf)
                if signal:
                    logger.info(signal)
            time.sleep(60)  # Check every minute
        except Exception as e:
            logger.error(f"Error in monitoring loop: {str(e)}")
            time.sleep(60)  # Wait before retrying

@app.route('/')
def home():
    return jsonify({"status": "alive", "message": "Forex Bot is running"})

def run_flask():
    """Run the Flask server"""
    app.run(host='0.0.0.0', port=10000)

def main():
    """Main function to start monitoring"""
    # Start Flask server in a separate thread
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    logger.info("Flask server started")
    
    # Test Telegram bot first
    #test_telegram_bot()
    
    # List of instruments to monitor
    instruments = [
    # Major Forex pairs
    "EUR_USD", "GBP_USD", "USD_JPY", "USD_CHF", "AUD_USD", "NZD_USD", "USD_CAD",

    # EUR crosses
    "EUR_GBP", "EUR_JPY", "EUR_CHF", "EUR_AUD", "EUR_NZD", "EUR_CAD",

    # GBP crosses
    "GBP_JPY", "GBP_CHF", "GBP_AUD", "GBP_NZD", "GBP_CAD",

    # JPY crosses
    "AUD_JPY", "NZD_JPY", "CAD_JPY", "CHF_JPY",

    # Other crosses
    "AUD_CHF", "NZD_CHF", "CAD_CHF", "AUD_NZD", "AUD_CAD", "NZD_CAD",

    # Metals
    "XAU_USD",  # Gold
    "XAG_USD",  # Silver

    # Oil
    "WTICO_USD",  # WTI Crude
    "BCO_USD"     # Brent Crude
    ]

    timeframes = ["M1","M15", "M5", "M30", "H1", "H4"]
    
    # Start monitoring threads for each instrument
    threads = []
    for instrument in instruments:
        thread = threading.Thread(
            target=monitor_instrument,
            args=(instrument, timeframes),
            daemon=True
        )
        thread.start()
        threads.append(thread)
        logger.info(f"Started monitoring {instrument}")
    
    # Keep the main thread alive
    try:
        while True:
            time.sleep(60)  # Check every minute
            print(f"Bot is alive - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    except KeyboardInterrupt:
        logger.info("Monitoring stopped by user")

if __name__ == "__main__":
    main()
