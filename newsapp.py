from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import pandas as pd
import time

def fetch_investing_calendar():
    # Set up headless Chrome options
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--user-agent=Mozilla/5.0")
    
    # Path to your matching ChromeDriver (v138)
    service = Service(r"C:\webdrivers\chromedriver-win64\chromedriver.exe")
    # Update this path as needed

    driver = webdriver.Chrome(service=service, options=options)

    try:
        print("Opening Investing.com calendar...")
        driver.get("https://www.investing.com/economic-calendar/")

        # Wait until calendar table loads
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.ID, "economicCalendarData"))
        )
        
        # Optional scroll to load more rows
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)

        print("Extracting rows...")
        rows = driver.find_elements(By.XPATH, "//table[@id='economicCalendarData']//tr[contains(@id,'eventRowId')]")
        
        events = []
        for row in rows:
            try:
                time_ = row.find_element(By.CLASS_NAME, "first.left.time").text.strip()
                currency = row.find_element(By.CLASS_NAME, "left.flagCur.noWrap").text.strip()
                event = row.find_element(By.CLASS_NAME, "event").text.strip()
                importance = len(row.find_elements(By.CLASS_NAME, "grayFullBullishIcon"))

                events.append({
                    "time": time_,
                    "currency": currency,
                    "event": event,
                    "importance": importance
                })
            except Exception as e:
                continue

        df = pd.DataFrame(events)
        print(df)
        return df

    finally:
        driver.quit()

# Run the scraper
if __name__ == "__main__":
    fetch_investing_calendar()
