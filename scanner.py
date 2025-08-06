import os
import time
import pandas as pd
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# === Config ===
CHROME_DRIVER_PATH = r"C:\webdrivers\chromedriver-win64\chromedriver.exe"  # Update if needed
DOWNLOAD_DIR = r"C:\chartink_downloads"  # Make sure this folder exists

# === Setup Chrome for automatic downloads ===
options = Options()
options.add_experimental_option("prefs", {
    "download.default_directory": DOWNLOAD_DIR,
    "download.prompt_for_download": False,
    "download.directory_upgrade": True,
    "safebrowsing.enabled": True
})
options.add_argument("--headless=new")  # Use --headless=new for Chrome v109+
options.add_argument("--disable-gpu")
options.add_argument("--window-size=1920,1080")

driver = webdriver.Chrome(service=Service(CHROME_DRIVER_PATH), options=options)

try:
    print("[INFO] Opening Chartink screener page...")
    driver.get("https://chartink.com/screener/hhv-scanner")

    print("[INFO] Waiting for 'Download CSV' button...")
    download_button = WebDriverWait(driver, 20).until(
        EC.element_to_be_clickable((By.LINK_TEXT, "Download csv"))
    )

    print("[INFO] Clicking the download button...")
    download_button.click()

    # Wait for download to complete
    time.sleep(5)

    print("[INFO] Looking for downloaded CSV file...")
    csv_files = [f for f in os.listdir(DOWNLOAD_DIR) if f.endswith(".csv")]
    if not csv_files:
        raise FileNotFoundError("CSV download failed or not found.")

    # Get the most recent CSV file
    latest_file = max(
        [os.path.join(DOWNLOAD_DIR, f) for f in csv_files],
        key=os.path.getctime
    )

    print(f"[SUCCESS] Downloaded file: {latest_file}")

    # Read and print the CSV
    df = pd.read_csv(latest_file)
    print(f"\n✅ Total Records: {len(df)}\n")
    print(df.to_string(index=False))

except Exception as e:
    print(f"[ERROR] {e}")
finally:
    driver.quit()
