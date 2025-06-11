import os
import time
import zipfile
import datetime
import pandas as pd
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

# === CONFIG ===
DOWNLOAD_DIR = os.path.join(os.getcwd(), "bhavcopies")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# === 1. Selenium Downloader ===
def download_bhavcopy_selenium(download_dir, date):
    day = date.strftime('%d')
    month = date.strftime('%b').upper()
    year = date.strftime('%Y')
    filename = f"cm{day}{month}{year}bhav.csv.zip"
    url = f"https://www1.nseindia.com/content/historical/EQUITIES/{year}/{month}/{filename}"

    options = Options()
    prefs = {
        "download.default_directory": os.path.abspath(download_dir),
        "download.prompt_for_download": False,
        "safebrowsing.enabled": True
    }
    options.add_experimental_option("prefs", prefs)
    options.add_argument("--headless=new")  # Remove for visible browser

    driver = webdriver.Chrome(options=options)
    driver.get(url)
    time.sleep(7)
    driver.quit()

    path = os.path.join(download_dir, filename)
    return path if os.path.exists(path) else None

# === 2. Download Last 5 Trading Days ===
def get_last_n_bhavcopies(n=5):
    today = datetime.date.today()
    bhav_files = []
    attempts = 0

    while len(bhav_files) < n and attempts < 10:
        if today.weekday() < 5:
            print(f"⬇️ Downloading: {today}")
            file_path = download_bhavcopy_selenium(DOWNLOAD_DIR, today)
            if file_path:
                bhav_files.append((today, file_path))
            else:
                print(f"❌ Failed for {today}")
        today -= datetime.timedelta(days=1)
        attempts += 1

    return bhav_files

# === 3. Extract CSV from ZIPs ===
def extract_ohlc_from_zip(zip_path, date):
    try:
        with zipfile.ZipFile(zip_path, 'r') as z:
            csv_file = z.namelist()[0]
            df = pd.read_csv(z.open(csv_file))
            df = df[['SYMBOL', 'OPEN', 'HIGH', 'LOW', 'CLOSE']].rename(columns=str.lower)
            df['date'] = date
            return df
    except Exception as e:
        print(f"❌ Error reading {zip_path}: {e}")
        return None

# === 4. Apply Screener Conditions ===
def apply_screener(df):
    df = df.sort_values(by=['symbol', 'date'])
    results = []

    for symbol, group in df.groupby('symbol'):
        if len(group) < 5:
            continue
        group = group.tail(5).reset_index(drop=True)
        today = group.iloc[-1]
        yesterday = group.iloc[-2]
        closes = group['close'].tolist()
        opens = group['open'].tolist()

        try:
            c1 = today['close'] >= yesterday['high']
            c2 = today['close'] > today['high'] * 0.75
            c3 = max(closes) < today['close'] * 1.03
            c4 = min(opens) > today['close'] * 0.95
            c5 = min(closes) > today['close'] * 0.95
            c6 = max(opens) < today['close'] * 1.03

            results.append({
                'symbol': symbol,
                'C1': c1, 'C2': c2, 'C3': c3,
                'C4': c4, 'C5': c5, 'C6': c6,
                'PASS': all([c1, c2, c3, c4, c5, c6])
            })
        except Exception as e:
            print(f"{symbol}: Error - {e}")

    return pd.DataFrame(results)

# === 5. Main Runner ===
def run_screener():
    print("📥 Downloading Bhavcopy ZIPs...")
    zip_files = get_last_n_bhavcopies(5)

    if not zip_files:
        print("❌ Could not get any Bhavcopy ZIPs.")
        return

    print("🧾 Extracting OHLC data...")
    combined = []
    for date, path in zip_files:
        df = extract_ohlc_from_zip(path, date)
        if df is not None:
            combined.append(df)

    all_data = pd.concat(combined) if combined else None
    if all_data is None:
        print("❌ No data extracted.")
        return

    print("🔎 Running Screener...")
    result = apply_screener(all_data)
    result.to_excel("nse_screener_output.xlsx", index=False)
    print("✅ Saved results to nse_screener_output.xlsx")

    passed = result[result['PASS']]
    print(f"\n🏆 {len(passed)} stocks passed the screener:")
    print(passed[['symbol'] + [f'C{i}' for i in range(1, 7)]])

# === Entry Point ===
if __name__ == "__main__":
    run_screener()
