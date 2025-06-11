import os
import time
import requests
import pandas as pd
from tabulate import tabulate
from dotenv import load_dotenv
from nsepython import nse_eq, nse_fno

# Load environment variables
load_dotenv()

# Input directory
DOWNLOAD_DIR = "downloads"

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

            # Fallback to EQ if missing
            if not pe or not ind_pe:
                data = nse_eq(symbol)
                pe = data.get("metadata", {}).get("pdSymbolPe")
                ind_pe = data.get("metadata", {}).get("pdSectorPe")

            df.at[idx, "Company PE"] = float(pe) if pe else None
            df.at[idx, "Industry PE"] = float(ind_pe) if ind_pe else None

            print(f"✅ {symbol}: PE = {pe}, Industry PE = {ind_pe}")
        except Exception as e:
            print(f"❌ {symbol} fetch failed: {e}")

        time.sleep(1)  # Avoid being blocked

    return df

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

def process_excel(file_path):
    print(f"\n📁 Processing: {file_path}")
    try:
        df = pd.read_excel(file_path, skiprows=1)
        df.columns = df.columns.str.strip()

        if "Symbol" not in df.columns:
            print("❌ 'Symbol' column not found. Skipping this file.")
            return

        df = fetch_pe_ratios(df)
        filtered = apply_filter(df)

        if filtered.empty:
            print("⚠️ No stocks matched the filter criteria.")
        else:
            print("\n📊 Filtered Stocks:")
            display_df = filtered[["Symbol", "Company PE", "Industry PE", "ROE", "EPS", "PB Ratio"]].round(2)
            table = tabulate(display_df, headers="keys", tablefmt="grid", showindex=False)
            print(table)

    except Exception as e:
        print(f"❌ Failed to process {file_path}: {e}")

if __name__ == "__main__":
    if not os.path.exists(DOWNLOAD_DIR):
        print(f"❌ Folder not found: {DOWNLOAD_DIR}")
        exit()

    excel_files = [f for f in os.listdir(DOWNLOAD_DIR) if f.endswith((".xlsx", ".xls"))]

    if not excel_files:
        print("📂 No Excel files found in the downloads folder.")
    else:
        for excel_file in excel_files:
            full_path = os.path.join(DOWNLOAD_DIR, excel_file)
            process_excel(full_path)
