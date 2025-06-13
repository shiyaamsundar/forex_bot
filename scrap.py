import os
import time
import requests
import pandas as pd
from tabulate import tabulate
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

DOWNLOAD_DIR = "downloads"

# Step 1: Get Tickertape URL using slug search API
def get_tickertape_slug(symbol):
    url = f"https://api.tickertape.in/search?text={symbol.upper()}"
    headers = {"User-Agent": "Mozilla/5.0"}

    try:
        res = requests.get(url, headers=headers, timeout=5)
        res.raise_for_status()
        data = res.json()
        slug = data["data"]["stocks"][0]["slug"]
        ticker = data["data"]["stocks"][0]["ticker"]
        return f"https://www.tickertape.in/stocks/{slug}-{ticker}"
    except Exception as e:
        print(f"❌ Failed to get Tickertape slug for {symbol}: {e}")
        return None

# Step 2: Launch Selenium and extract PE data from Tickertape page
def fetch_pe_from_tickertape(symbol, driver):
    url = get_tickertape_slug(symbol)
    if not url:
        return None, None

    try:
        driver.get(url)
        time.sleep(5)

        elements = driver.find_elements("css selector", "div[class*='key-metrics'] span")
        text_values = [e.text.strip() for e in elements if e.text.strip()]

        pe = next((float(v) for v in text_values if v.replace('.', '', 1).replace('-', '', 1).isdigit()), None)
        sector_pe = None
        for i, v in enumerate(text_values):
            if "Sector PE" in v:
                sector_pe = float(text_values[i + 1]) if i + 1 < len(text_values) else None

        return pe, sector_pe
    except Exception as e:
        print(f"❌ {symbol} Tickertape fetch failed: {e}")
        return None, None

# Step 3: Setup Selenium driver once
def setup_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    return webdriver.Chrome(options=chrome_options)

# Step 4: Fetch PE ratios for all symbols
def fetch_pe_ratios(df, driver):
    df["Company PE"] = None
    df["Industry PE"] = None

    for idx, row in df.iterrows():
        symbol = str(row["Symbol"]).strip().upper()
        if not symbol:
            continue

        pe, ind_pe = fetch_pe_from_tickertape(symbol, driver)
        df.at[idx, "Company PE"] = pe
        df.at[idx, "Industry PE"] = ind_pe

        if pe is not None and ind_pe is not None:
            print(f"✅ {symbol}: PE = {pe}, Industry PE = {ind_pe}")
        else:
            print(f"⚠️ {symbol}: PE or Industry PE not found")

    return df

# Step 5: Filter the stocks
def apply_filter(df):
    df["Company PE"] = pd.to_numeric(df["Company PE"], errors="coerce")
    df["Industry PE"] = pd.to_numeric(df["Industry PE"], errors="coerce")

    if "ROE" not in df.columns:
        df["ROE"] = 12
    if "EPS" not in df.columns:
        df["EPS"] = 12
    if "PB Ratio" not in df.columns:
        df["PB Ratio"] = 3

    return df[
        (df["Company PE"] < df["Industry PE"]) &
        (df["ROE"].between(10, 15)) &
        (df["EPS"].between(10, 15)) &
        (df["PB Ratio"].between(1, 5))
    ]

# Step 6: Process each Excel file
def process_excel(file_path, driver):
    print(f"\n📁 Processing: {file_path}")
    try:
        df = pd.read_excel(file_path, skiprows=1)
        df.columns = df.columns.str.strip()

        if "Symbol" not in df.columns:
            print("❌ 'Symbol' column not found. Skipping this file.")
            return

        df = fetch_pe_ratios(df, driver)
        filtered = apply_filter(df)

        if filtered.empty:
            print("⚠️ No stocks matched the filter criteria.")
        else:
            print("\n📊 Filtered Stocks:")
            display_df = filtered[["Symbol", "Company PE", "Industry PE", "ROE", "EPS", "PB Ratio"]].round(2)
            print(tabulate(display_df, headers="keys", tablefmt="grid", showindex=False))

            result_path = os.path.join(DOWNLOAD_DIR, "filtered_results.xlsx")
            display_df.to_excel(result_path, index=False)
            print(f"✅ Results saved to: {result_path}")

    except Exception as e:
        print(f"❌ Failed to process {file_path}: {e}")

# Step 7: Main logic
if __name__ == "__main__":
    if not os.path.exists(DOWNLOAD_DIR):
        print(f"❌ Folder not found: {DOWNLOAD_DIR}")
        exit()

    print("🌐 Launching Selenium to extract data from Tickertape...")
    driver = setup_driver()

    excel_files = [f for f in os.listdir(DOWNLOAD_DIR) if f.endswith((".xlsx", ".xls"))]
    if not excel_files:
        print("📂 No Excel files found in the downloads folder.")
    else:
        for excel_file in excel_files:
            full_path = os.path.join(DOWNLOAD_DIR, excel_file)
            process_excel(full_path, driver)

    driver.quit()
