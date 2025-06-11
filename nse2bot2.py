import os
import time
import pandas as pd
import requests
from dotenv import load_dotenv
from tabulate import tabulate
from nsepython import nse_eq


# Load Telegram Bot credentials
load_dotenv()
BOT_TOKEN = os.getenv("TELEGRAM_NSE_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID_2")

API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)


def fetch_pe_ratios(df):
    df["Company PE"] = None
    df["Industry PE"] = None
    for idx, row in df.iterrows():
        symbol = str(row["Symbol"]).strip().upper()
        try:
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
    file_info = requests.get(f"{API_URL}/getFile", params={"file_id": file_id}).json()
    file_path = file_info["result"]["file_path"]
    file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
    local_path = os.path.join(DOWNLOAD_DIR, os.path.basename(file_path))
    with open(local_path, "wb") as f:
        f.write(requests.get(file_url).content)
    return local_path

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

            # Clean up and round for display
            display_df = filtered[["Symbol", "Company PE", "Industry PE", "ROE", "EPS", "PB Ratio"]].round(2)
            table = tabulate(display_df, headers="keys", tablefmt="grid", showindex=False)

            # Break into chunks (Telegram max is 4096 chars)
            chunks = [table[i:i+4000] for i in range(0, len(table), 4000)]
            for chunk in chunks:
                send_message(f"<pre>{chunk}</pre>", chat_id)

    except Exception as e:
        send_message(f"❌ Failed to process file:\n<pre>{e}</pre>", chat_id)

def get_latest_chat_id():
    try:
        response = requests.get(f"{API_URL}/getUpdates").json()
        results = response.get("result", [])
        if not results:
            print("⚠️ No messages received yet. Send a message to the bot first.")
            return None

        last_message = results[-1]
        chat = last_message.get("message", {}).get("chat", {})
        chat_id = chat.get("id")
        username = chat.get("username", "N/A")
        print(f"✅ Latest Chat ID: {chat_id} (Username: @{username})")
        return chat_id

    except Exception as e:
        print(f"❌ Failed to fetch chat ID: {e}")
        return None

def poll_updates():
    print("🤖 Bot is running... waiting for Excel uploads.")
    last_update_id = None
    while True:
        try:
            params = {"timeout": 60, "offset": last_update_id + 1 if last_update_id else None}
            res = requests.get(f"{API_URL}/getUpdates", params=params).json()
            for update in res.get("result", []):
                last_update_id = update["update_id"]
                message = update.get("message", {})
                chat_id = message.get("chat", {}).get("id")

                if "document" in message:
                    doc = message["document"]
                    if doc["mime_type"] in ["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "application/vnd.ms-excel"]:
                        file_id = doc["file_id"]
                        local_file = download_excel(file_id)
                        send_message("📥 File received. Processing...", chat_id)
                        process_excel(local_file, chat_id)
                    else:
                        send_message("⚠️ Only Excel files are supported (.xlsx or .xls)", chat_id)
                elif "text" in message and message["text"].lower() in ["/start", "hi", "hello"]:
                    send_message("👋 Send me an Excel file with a 'Symbol' column. I will return filtered stock results as a table.", chat_id)
        except Exception as e:
            print(f"❌ Polling error: {e}")
        time.sleep(2)

if __name__ == "__main__":
    poll_updates()
    #get_latest_chat_id()
