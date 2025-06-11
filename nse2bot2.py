import os
import time
import pandas as pd
import requests
from dotenv import load_dotenv
from tabulate import tabulate
from nsepython import nse_fno, nse_eq

# Load Telegram Bot credentials
load_dotenv()
BOT_TOKEN = os.getenv("TELEGRAM_NSE_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID_2")

API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Track which chat is waiting for Excel
waiting_for_excel = set()

def fetch_pe_ratios(df):
    df["Company PE"] = None
    df["Industry PE"] = None
    for idx, row in df.iterrows():
        symbol = str(row["Symbol"]).strip().upper()
        try:
            data = nse_fno(symbol)
            pe = data.get("metadata", {}).get("pdSymbolPe")
            ind_pe = data.get("metadata", {}).get("pdSectorPe")

            if pe is None or ind_pe is None:
                # fallback to nse_eq
                data = nse_eq(symbol)
                pe = data.get("metadata", {}).get("pdSymbolPe")
                ind_pe = data.get("metadata", {}).get("pdSectorPe")

            df.at[idx, "Company PE"] = float(pe) if pe else None
            df.at[idx, "Industry PE"] = float(ind_pe) if ind_pe else None
            print(f"✅ {symbol}: PE = {pe}, Industry PE = {ind_pe}")
        except Exception as e:
            print(f"❌ {symbol} failed: {e}")
        time.sleep(1)
    return df

def apply_filter(df):
    df["Company PE"] = pd.to_numeric(df["Company PE"], errors="coerce")
    df["Industry PE"] = pd.to_numeric(df["Industry PE"], errors="coerce")
    df["ROE"] = 12
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
        print(f"❌ Download error: {e}")
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
            chunks = [table[i:i+4000] for i in range(0, len(table), 4000)]
            for chunk in chunks:
                send_message(f"<pre>{chunk}</pre>", chat_id)
    except Exception as e:
        send_message(f"❌ Failed to process file:\n<pre>{e}</pre>", chat_id)

def poll_updates():
    print("🤖 Bot is live. Send /start to begin.")

    try:
        res = requests.get(f"{API_URL}/getUpdates", params={"timeout": 5}).json()
        updates = res.get("result", [])
        last_update_id = updates[-1]["update_id"] if updates else None
    except Exception as e:
        print(f"❌ Could not initialize polling: {e}")
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
                    send_message("👋 Welcome! Please upload an Excel file (.xlsx or .xls) with a 'Symbol' column.", chat_id)
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
                    send_message("ℹ️ Please first send /start before uploading a file.", chat_id)

        except Exception as e:
            print(f"❌ Polling error: {e}")
            time.sleep(3)

if __name__ == "__main__":
    poll_updates()
