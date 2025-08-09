import time
import pandas as pd
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

def fetch_forex_data():
    options = Options()
    options.headless = False  # Run the browser in non-headless mode for debugging
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    driver.get("https://www.forexfactory.com/calendar")

    # Increase the wait time
    try:
        WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.CLASS_NAME, "calendar__event"))
        )
    except Exception as e:
        print(f"Error: {e}")
        driver.quit()
        return pd.DataFrame()

    events = driver.find_elements(By.CLASS_NAME, "calendar__event")
    data = []

    print(f"Number of events found: {len(events)}")

    for event in events:
        try:
            title = event.find_element(By.CLASS_NAME, "calendar__event-title").text
            event_time = event.find_element(By.CLASS_NAME, "calendar__time").text
            impact = event.find_element(By.CLASS_NAME, "impact").get_attribute("title")
            data.append([title, event_time, impact])
        except Exception as e:
            print(f"Error extracting event data: {e}")
            continue

    driver.quit()
    return pd.DataFrame(data, columns=["Event", "Time", "Impact"])

df = fetch_forex_data()

# Print the dataframe to the console
print(df)
