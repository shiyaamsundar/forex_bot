import os
import time
import requests
import pandas as pd
from dotenv import load_dotenv
from tabulate import tabulate
import nsepython
from nsepython import nse_eq, nse_fno

# Load environment variables
load_dotenv()
BOT_TOKEN = os.getenv("TELEGRAM_NSE_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID_2")
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

# Set headers to avoid blocks on Render
nsepython.requests = requests.Session()
nsepython.requests.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br"
})

# Setup download directory
DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Track chats awaiting uploads
waiting_for_excel = set()

def fetch_pe_ratios(df):
    df["Company PE"] = None
    df["Industry PE"] = None

    for idx, row in df.iterrows():
        symbol = str(row["Symbol"]).strip().upper()
        if not symbol:
            continue

        try:
            data = nse_fno(symbol)
            pe = data.get("metadata", {}).get("pdSymbolPe")
            ind_pe = data.get("metadata", {}).get("pdSectorPe")

            # Fallback if not found in FNO
            if not pe or not ind_pe:
                data = nse_eq(symbol)
                pe = data.get("metadata", {}).get("pdSymbolPe")
                ind_pe = data.get("metadata", {}).get("pdSectorPe")

            df.at[idx, "Company PE"] = float(pe) if pe else None
            df.at[idx, "Industry PE"] = float(ind_pe) if ind_pe else None
            print(f"✅ {symbol}: PE = {pe}, Industry PE = {ind_pe}")
        except Exception as e:
            print(f"❌ {symbol} fetch failed: {e}")
        time.sleep(1)
    
    return df

def apply_filter(df):
    df["Company PE"] = pd.to_numeric(df["Company PE"], errors="coerce")
    df["Industry PE"] = pd.to_numeric(df["Industry PE"], errors="coerce")
    df["ROE"] = 12  # Default values; replace if Excel provides
    df["EPS"] = 12
    df["PB Ratio"] = 3
    return df[
        (df["Company PE"] < df["Industry PE"]) &
        (df["ROE"].between(10, 15)) &
        (df["EPS"].between(10, 15)) &
        (df["PB Ratio"].between(1, 5))
    ]

def send_message(text, chat_id):
    requests.post(f"{API_URL}/sendMessage", json={
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    })

def download_excel(file_id):
    try:
        file_info = requests.get(f"{API_URL}/getFile", params={"file_id": file_id}).json()
        file_path = file_info["result"]["file_path"]
        file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
        local_path = os.path.join(DOWNLOAD_DIR, os.path.basename(file_path))
        with open(local_path, "wb") as f:
            f.write(requests.get(file_url).content)
        return local_path
    except Exception as e:
        print(f"❌ Download failed: {e}")
        return None

def process_excel(file_path, chat_id):
    try:
        df = pd.read_excel(file_path, skiprows=1)
        df.columns = df.columns.str.strip()

        df = fetch_pe_ratios(df)
        filtered = apply_filter(df)

        if filtered.empty:
            send_message("⚠️ No stocks matched the criteria.", chat_id)
        else:
            send_message("📊 <b>Filtered Stocks</b>", chat_id)

            display_df = filtered[["Symbol", "Company PE", "Industry PE", "ROE", "EPS", "PB Ratio"]].round(2)
            table = tabulate(display_df, headers="keys", tablefmt="grid", showindex=False)

            # Telegram has a message limit (~4096 chars), split if needed
            chunks = [table[i:i+4000] for i in range(0, len(table), 4000)]
            for chunk in chunks:
                send_message(f"<pre>{chunk}</pre>", chat_id)
    except Exception as e:
        send_message(f"❌ Failed to process Excel:\n<pre>{e}</pre>", chat_id)

def poll_updates():
    print("🤖 Bot is live. Waiting for /start and Excel uploads...")
    last_update_id = None

    while True:
        try:
            params = {"timeout": 60}
            if last_update_id:
                params["offset"] = last_update_id + 1

            res = requests.get(f"{API_URL}/getUpdates", params=params).json()
            for update in res.get("result", []):
                last_update_id = update["update_id"]
                message = update.get("message", {})
                chat_id = message.get("chat", {}).get("id")

                if "text" in message and message["text"].lower() in ["/start", "hi", "hello"]:
                    send_message("👋 Welcome! Upload an Excel file (.xlsx/.xls) with a 'Symbol' column to begin.", chat_id)
                    waiting_for_excel.add(chat_id)

                elif chat_id in waiting_for_excel and "document" in message:
                    doc = message["document"]
                    mime_type = doc.get("mime_type", "")
                    if mime_type in [
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        "application/vnd.ms-excel"
                    ]:
                        file_id = doc["file_id"]
                        send_message("📥 File received. Processing...", chat_id)
                        local_path = download_excel(file_id)
                        if local_path:
                            process_excel(local_path, chat_id)
                        else:
                            send_message("❌ File download failed.", chat_id)
                        waiting_for_excel.discard(chat_id)
                    else:
                        send_message("⚠️ Only Excel files (.xlsx or .xls) are supported.", chat_id)

                elif "document" in message:
                    send_message("ℹ️ Please send /start before uploading a file.", chat_id)

        except Exception as e:
            print(f"❌ Polling error: {e}")
            time.sleep(3)

if __name__ == "__main__":
    poll_updates()
