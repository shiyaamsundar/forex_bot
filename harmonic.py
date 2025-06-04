import requests
import time
import pandas as pd

# === Configurations ===



# Your list of NSE stocks (use .NSE suffix)
stocks = ['RELIANCE', 'TCS', 'INFY', 'TATAMOTORS', 'HDFCBANK']

# Timeframes to scan
timeframes = {
    "4h": "4h",
    "1d": "1day",
    "1w": "1week"
}

# === Telegram alert function ===
def send_telegram_alert(symbol, timeframe):
    message = f"✅ ABCD Pattern found in {symbol} on {timeframe} timeframe"
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    response = requests.post(url, data={"chat_id": CHAT_ID, "text": message})
    if response.status_code == 200:
        print(f"Alert sent: {message}")
    else:
        print(f"Failed to send alert: {response.text}")

# === Fetch stock data from Twelve Data ===
def fetch_stock_data(symbol, interval, outputsize=100):
    url = (
        f"https://api.twelvedata.com/time_series?symbol={symbol}"
        f"&interval={interval}&outputsize={outputsize}&apikey={API_KEY}"
    )
    resp = requests.get(url)
    data = resp.json()
    if "values" in data:
        df = pd.DataFrame(data["values"])
        # Convert columns to appropriate types and sort by datetime ascending
        df['datetime'] = pd.to_datetime(df['datetime'])
        df = df.sort_values(by='datetime')
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = pd.to_numeric(df[col])
        return df
    else:
        print(f"Failed to fetch {symbol} {interval}: {data.get('message', 'No data')}")
        return None

# === ABCD pattern detection function ===
def is_abcd_pattern(A, B, C, D, tolerance=0.05):
    AB = abs(B - A)
    CD = abs(D - C)
    if AB == 0:
        return False
    ratio = CD / AB
    return abs(ratio - 1.0) < tolerance

# === Main scanning loop ===
def scan_stocks():
    for symbol in stocks:
        for tf, interval in timeframes.items():
            print(f"Fetching {symbol} {tf} data...")
            df = fetch_stock_data(symbol, interval)
            if df is None or len(df) < 20:
                print(f"Not enough data for {symbol} {tf}")
                continue
            
            closes = df['close'].values
            # Naive pattern detection with sliding window
            for i in range(10, len(closes) - 1):
                A, B, C, D = closes[i - 10], closes[i - 7], closes[i - 3], closes[i]
                if is_abcd_pattern(A, B, C, D):
                    print(f"Pattern found: {symbol} on {tf} at index {i}")
                    send_telegram_alert(symbol, tf)
                    # You can break here to avoid multiple alerts or continue to find more
                    break
            time.sleep(7)  # Twelve Data limit: 8 calls/min, so wait ~7 sec

if __name__ == "__main__":
    scan_stocks()
