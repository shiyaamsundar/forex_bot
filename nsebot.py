import os
from dotenv import load_dotenv
import requests

# Load environment variables
load_dotenv()

# Get Telegram configuration
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID_2')


def send_telegram_alert(message):
    """Send message to Telegram"""
    try:
        if not message or not message.strip():
            print("Cannot send empty message to Telegram")
            return

        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
            print("Telegram configuration missing. Please check your .env file")
            return

        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML"
        }

        response = requests.post(url, json=payload)
        response.raise_for_status()
        print(f"✅ Message sent: {message}")
        return True

    except requests.exceptions.RequestException as e:
        print(f"❌ Failed to send Telegram alert: {e}")
        if e.response is not None:
            try:
                error_data = e.response.json()
                print(f"Telegram API error: {error_data}")
            except Exception:
                pass
    except Exception as e:
        print(f"❌ Unexpected error sending Telegram alert: {e}")
    return False


def get_chat_id():
    """Get chat ID from Telegram bot"""
    try:
        if not TELEGRAM_BOT_TOKEN:
            print("Telegram bot token not found. Please check your .env file")
            return None

        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()

        if not data.get("ok"):
            print("Telegram API error:", data.get("description", "Unknown error"))
            return None

        results = data.get("result", [])
        for item in reversed(results):
            if "message" in item:
                return item["message"]["chat"]["id"]

        print("No valid message found in updates")
    except Exception as e:
        print(f"❌ Error getting chat ID: {e}")
    return None


def test_telegram_bot():
    """Test Telegram bot configuration"""
    global TELEGRAM_CHAT_ID

    print("🔍 Testing Telegram bot...")

    test_message = "🤖 <b>Telegram Bot Test</b>\n\nThis is a test message to verify bot configuration."

    if TELEGRAM_CHAT_ID:
        print(f"Using TELEGRAM_CHAT_ID from .env: {TELEGRAM_CHAT_ID}")
        if send_telegram_alert(test_message):
            print("✅ Bot test successful!")
            return True
        else:
            print("⚠️ Test failed. Trying to fetch new chat ID...")

    chat_id = get_chat_id()
    if not chat_id:
        print("❌ Could not get chat ID. Make sure you've messaged the bot.")
        return False

    TELEGRAM_CHAT_ID = str(chat_id)

    # Update or append TELEGRAM_CHAT_ID in .env
    try:
        if os.path.exists('.env'):
            with open('.env', 'r') as f:
                lines = f.readlines()

            updated = False
            with open('.env', 'w') as f:
                for line in lines:
                    if line.startswith("TELEGRAM_CHAT_ID="):
                        f.write(f"TELEGRAM_CHAT_ID={chat_id}\n")
                        updated = True
                    else:
                        f.write(line)
                if not updated:
                    f.write(f"\nTELEGRAM_CHAT_ID={chat_id}\n")
        else:
            with open('.env', 'w') as f:
                f.write(f"TELEGRAM_CHAT_ID={chat_id}\n")
        print(f"✅ Chat ID saved to .env: {chat_id}")
    except Exception as e:
        print(f"⚠️ Could not save chat ID to .env: {e}")

    if send_telegram_alert(test_message):
        print("✅ Bot test successful with new chat ID!")
        return True

    print("❌ Bot test failed!")
    return False


if __name__ == "__main__":
    if test_telegram_bot():
        print("🚀 Bot is ready!")
    else:
        print("🛑 Bot setup failed. Please check your config.")
