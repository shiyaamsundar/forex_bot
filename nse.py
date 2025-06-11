import datetime
import requests
import zipfile
import io
import pandas as pd
import os

# === Step 1: Download Bhavcopy for a Given Date ===
def fetch_bhavcopy(date):
    url = f"https://www1.nseindia.com/content/historical/EQUITIES/{date.strftime('%Y')}/{date.strftime('%b').upper()}/cm{date.strftime('%d%b%Y').upper()}bhav.csv.zip"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code != 200:
            return None
        z = zipfile.ZipFile(io.BytesIO(r.content))
        csv_name = z.namelist()[0]
        df = pd.read_csv(z.open(csv_name))
        df = df[['SYMBOL', 'OPEN', 'HIGH', 'LOW', 'CLOSE']].rename(columns=str.lower)
        df['date'] = date
        return df
    except Exception as e:
        print(f"{date}: Failed to fetch Bhavcopy - {e}")
        return None

# === Step 2: Get Last 5 Trading Days' Bhavcopies ===
def get_last_n_bhavcopies(n=5):
    today = datetime.date.today()
    results = []
    attempts = 0

    while len(results) < n and attempts < 10:
        if today.weekday() < 5:  # Skip weekends
            df = fetch_bhavcopy(today)
            if df is not None:
                results.append(df)
        today -= datetime.timedelta(days=1)
        attempts += 1

    if results:
        return pd.concat(results, ignore_index=True)
    return None

# === Step 3: Screener Logic (Your 6 Conditions) ===
def apply_weekly_screener(df):
    df.columns = df.columns.str.lower()
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
            print(f"{symbol}: Error in logic - {e}")

    return pd.DataFrame(results)

# === Step 4: Run Entire Process ===
def run_screener():
    print("📥 Downloading last 5 Bhavcopies...")
    bhav_data = get_last_n_bhavcopies(5)

    if bhav_data is None:
        print("❌ Failed to get sufficient Bhavcopy data.")
        return

    print("✅ Applying screener...")
    results = apply_weekly_screener(bhav_data)

    print("💾 Saving to 'nse_200_screener_results.xlsx'...")
    results.to_excel("nse_200_screener_results.xlsx", index=False)

    passed = results[results['PASS']]
    print(f"\n🏆 {len(passed)} stocks passed the screener:")
    print(passed[['symbol'] + [f'C{i}' for i in range(1,7)]])

# === Run it ===
if __name__ == "__main__":
    run_screener()
