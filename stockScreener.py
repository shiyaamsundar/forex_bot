import time
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# === Setup ===
CHROME_DRIVER_PATH = r"C:\webdrivers\chromedriver-win64\chromedriver.exe"

def analyze_stock(stock_name):
    options = Options()
    # Uncomment headless if needed
    # options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-notifications")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64)")

    driver = webdriver.Chrome(service=Service(CHROME_DRIVER_PATH), options=options)

    try:
        driver.get("https://www.screener.in/")

        # Accept cookies if present
        try:
            cookie_btn = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.CLASS_NAME, "btn-accept-cookies"))
            )
            cookie_btn.click()
        except:
            pass

        # Search for stock
        search_input = WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.NAME, "q"))
        )
        search_input.clear()
        search_input.send_keys(stock_name)
        search_input.submit()

        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".company-header"))
        )

        def extract_metric(label):
            try:
                element = driver.find_element(By.XPATH, f"//li[strong[contains(text(), '{label}')]]")
                return element.text.split(":")[-1].strip().replace(",", "").replace("%", "")
            except:
                return "NA"

        pe = extract_metric("P/E")
        industry_pe = extract_metric("Industry P/E")
        pb = extract_metric("P/B")
        roe = extract_metric("ROE")
        eps = extract_metric("EPS")

        def safe_float(val):
            try:
                return float(val)
            except:
                return 0

        # Evaluation logic
        passes = (
            safe_float(pe) < safe_float(industry_pe)
            and 1 <= safe_float(pb) <= 5
            and safe_float(roe) > 10
            and safe_float(eps) > 10
        )

        # Output
        print(f"\n📈 {stock_name.upper()} Analysis:")
        print(f"PE: {pe}")
        print(f"Industry PE: {industry_pe}")
        print(f"PB: {pb}")
        print(f"ROE: {roe}")
        print(f"EPS: {eps}")
        print(f"\n✅ PASS: {passes}\n")

    finally:
        driver.quit()

# === 🔍 Run analysis on one stock
stock_to_check = "Infosys"  # <-- Change this to any stock name
analyze_stock(stock_to_check)
