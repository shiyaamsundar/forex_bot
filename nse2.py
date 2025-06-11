import os
import time
import pandas as pd
from nsepython import nse_eq

# Ensure 'downloads/' folder exists
os.makedirs("downloads", exist_ok=True)

def find_latest_excel(folder="downloads"):
    """Find the latest Excel file in the downloads folder"""
    excel_files = [f for f in os.listdir(folder) if f.endswith(('.xlsx', '.xls'))]
    if not excel_files:
        raise FileNotFoundError("No Excel files found in the 'downloads/' folder.")
    latest_file = max(excel_files, key=lambda f: os.path.getctime(os.path.join(folder, f)))
    return os.path.join(folder, latest_file)

def fetch_pe_ratios(df):
    """Fetch Company PE and Industry PE for each symbol"""
    df["Company PE"] = None
    df["Industry PE"] = None

    for idx, row in df.iterrows():
        symbol = str(row["Symbol"]).strip().upper()
        try:
            data = nse_eq(symbol)
            company_pe = data.get("metadata", {}).get("pdSymbolPe")
            industry_pe = data.get("metadata", {}).get("pdSectorPe")
            df.at[idx, "Company PE"] = float(company_pe) if company_pe else None
            df.at[idx, "Industry PE"] = float(industry_pe) if industry_pe else None
            print(f"✅ {symbol}: Company PE = {company_pe}, Industry PE = {industry_pe}")
        except Exception as e:
            print(f"❌ {symbol}: Failed to fetch data - {e}")
        time.sleep(1)  # Respect NSE servers
    return df

def apply_filter(df):
    """Apply checklist filters on PE, ROE, EPS, PB Ratio"""
    df["Company PE"] = pd.to_numeric(df["Company PE"], errors="coerce")
    df["Industry PE"] = pd.to_numeric(df["Industry PE"], errors="coerce")

    # Use mock values for ROE, EPS, PB Ratio
    df["ROE"] = 12
    df["EPS"] = 12
    df["PB Ratio"] = 3

    filtered = df[
        (df["Company PE"] > df["Industry PE"]) &
        (df["ROE"].between(10, 15)) &
        (df["EPS"].between(10, 15)) &
        (df["PB Ratio"].between(1, 5))
    ]
    return filtered

def main():
    try:
        input_file = find_latest_excel()
        print(f"\n📂 Found file: {input_file}")
        df = pd.read_excel(input_file, skiprows=1)
        df.columns = df.columns.str.strip()

        df = fetch_pe_ratios(df)
        filtered_df = apply_filter(df)

        if not filtered_df.empty:
            output_path = "filtered_nse_results.xlsx"
            filtered_df.to_excel(output_path, index=False)
            print(f"\n✅ Filtered results saved to: {output_path}")
            print(filtered_df[["Symbol", "Company PE", "Industry PE", "ROE", "EPS", "PB Ratio"]])
        else:
            print("\n⚠️ No stocks matched the criteria.")

    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    main()
