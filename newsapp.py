from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager
import time

def fetch_forex_news():
    """Fetch news events from Forex Factory"""
    driver = None
    try:
        # Setup headless browser
        options = Options()
        options.add_argument("--headless=new")              # Run in headless mode
        options.add_argument("--disable-gpu")               # Prevent GPU fallback
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-logging")
        options.add_argument("--log-level=3")               # Suppress info and warnings
        options.add_argument("--silent")
        options.add_argument("--disable-software-rasterizer")
        options.add_argument("--disable-webgl")             # Disables WebGL
        options.add_argument("--disable-3d-apis")  

        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
        driver.get("https://www.forexfactory.com/calendar")
        driver.implicitly_wait(10)  # Increased wait time
        
        # Save page source for debugging (optional)
        try:
            with open("forex_factory_debug.html", "w", encoding="utf-8") as f:
                f.write(driver.page_source)
            print("Saved page source to forex_factory_debug.html")
        except Exception as e:
            print(f"Could not save page source: {str(e)}")

        # Wait for page to fully load
        time.sleep(3)
        
        # Try different selectors to find news rows
        selectors = [
            "tr.calendar__row",
            "tr[data-event-id]",
            ".calendar__row",
            "table.calendar__table tbody tr"
        ]
        
        rows = []
        for selector in selectors:
            try:
                rows = driver.find_elements(By.CSS_SELECTOR, selector)
                if rows:
                    print(f"Found {len(rows)} rows using selector: {selector}")
                    break
            except Exception as e:
                print(f"Selector {selector} failed: {str(e)}")
                continue
        
        data = []
        print(f"Total rows found: {len(rows)}")

        for i, row in enumerate(rows):
            try:
                print(f"Processing row {i+1}/{len(rows)}")
                
                # Try different selectors for each field
                time_selectors = ["td.calendar__time", ".calendar__time", "td:nth-child(1)"]
                currency_selectors = ["td.calendar__currency", ".calendar__currency", "td:nth-child(2)"]
                title_selectors = ["td.calendar__event", ".calendar__event", "td:nth-child(3)"]
                impact_selectors = ["td.calendar__impact", ".calendar__impact", "td:nth-child(4)"]
                actual_selectors = ["td.calendar__actual", ".calendar__actual", "td:nth-child(5)"]
                forecast_selectors = ["td.calendar__forecast", ".calendar__forecast", "td:nth-child(6)"]
                previous_selectors = ["td.calendar__previous", ".calendar__previous", "td:nth-child(7)"]
                
                # Helper function to find element with multiple selectors
                def find_element_text(row, selectors):
                    for selector in selectors:
                        try:
                            element = row.find_element(By.CSS_SELECTOR, selector)
                            return element.text.strip()
                        except:
                            continue
                    return "N/A"
                
                def find_element_attribute(row, selectors, attribute):
                    for selector in selectors:
                        try:
                            element = row.find_element(By.CSS_SELECTOR, selector)
                            return element.get_attribute(attribute).strip()
                        except:
                            continue
                    return "N/A"
                
                time_str = find_element_text(row, time_selectors)
                currency = find_element_text(row, currency_selectors)
                title = find_element_text(row, title_selectors)
                impact = find_element_attribute(row, impact_selectors, "title")
                actual = find_element_text(row, actual_selectors)
                forecast = find_element_text(row, forecast_selectors)
                previous = find_element_text(row, previous_selectors)
                
                # Only add if we have at least time and title
                if time_str != "N/A" and title != "N/A":
                    data.append({
                        "time": time_str,
                        "currency": currency,
                        "title": title,
                        "impact": impact,
                        "actual": actual,
                        "forecast": forecast,
                        "previous": previous
                    })
                    print(f"✓ Added event: {time_str} - {title}")
                else:
                    print(f"✗ Skipped row {i+1}: Missing time or title")
                    
            except Exception as e:
                print(f"Error parsing row {i+1}: {str(e)}")
                continue

        print(f"Successfully fetched {len(data)} news events")
        return data
        
    except Exception as e:
        print(f"Error fetching news: {str(e)}")
        return []
    finally:
        if driver:
            try:
                driver.quit()
            except Exception as e:
                print(f"Error closing driver: {str(e)}")

def fetch_investing_news():
    """Fetch news events from Investing.com Economic Calendar"""
    driver = None
    try:
        # Setup headless browser
        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-logging")
        options.add_argument("--log-level=3")
        options.add_argument("--silent")
        options.add_argument("--disable-software-rasterizer")
        options.add_argument("--disable-webgl")
        options.add_argument("--disable-3d-apis")
        # Add user agent to avoid detection
        options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
        driver.get("https://www.investing.com/economic-calendar/")
        driver.implicitly_wait(15)  # Longer wait for Investing.com
        
        # Save page source for debugging
        try:
            with open("investing_debug.html", "w", encoding="utf-8") as f:
                f.write(driver.page_source)
            print("Saved page source to investing_debug.html")
        except Exception as e:
            print(f"Could not save page source: {str(e)}")

        # Wait for page to fully load
        time.sleep(5)
        
        # Try different selectors for Investing.com
        selectors = [
            "tr.js-event-item",
            "tr[data-event-id]",
            ".eventRow",
            "table.genTbl tr",
            ".economicCalendarRow"
        ]
        
        rows = []
        for selector in selectors:
            try:
                rows = driver.find_elements(By.CSS_SELECTOR, selector)
                if rows:
                    print(f"Found {len(rows)} rows using selector: {selector}")
                    break
            except Exception as e:
                print(f"Selector {selector} failed: {str(e)}")
                continue
        
        data = []
        print(f"Total rows found: {len(rows)}")

        for i, row in enumerate(rows):
            try:
                print(f"Processing row {i+1}/{len(rows)}")
                
                # Investing.com specific selectors
                time_selectors = [
                    "td.time",
                    ".time",
                    "td:nth-child(1)",
                    ".eventTime"
                ]
                currency_selectors = [
                    "td.flagCur",
                    ".flagCur",
                    "td:nth-child(2)",
                    ".currency"
                ]
                title_selectors = [
                    "td.event",
                    ".event",
                    "td:nth-child(3)",
                    ".eventName"
                ]
                impact_selectors = [
                    "td.impact",
                    ".impact",
                    "td:nth-child(4)",
                    ".importance"
                ]
                actual_selectors = [
                    "td.act",
                    ".act",
                    "td:nth-child(5)",
                    ".actual"
                ]
                forecast_selectors = [
                    "td.forecast",
                    ".forecast",
                    "td:nth-child(6)",
                    ".consensus"
                ]
                previous_selectors = [
                    "td.prev",
                    ".prev",
                    "td:nth-child(7)",
                    ".previous"
                ]
                
                # Helper function to find element with multiple selectors
                def find_element_text(row, selectors):
                    for selector in selectors:
                        try:
                            element = row.find_element(By.CSS_SELECTOR, selector)
                            return element.text.strip()
                        except:
                            continue
                    return "N/A"
                
                def find_element_attribute(row, selectors, attribute):
                    for selector in selectors:
                        try:
                            element = row.find_element(By.CSS_SELECTOR, selector)
                            return element.get_attribute(attribute).strip()
                        except:
                            continue
                    return "N/A"
                
                time_str = find_element_text(row, time_selectors)
                currency = find_element_text(row, currency_selectors)
                title = find_element_text(row, title_selectors)
                impact = find_element_attribute(row, impact_selectors, "title")
                actual = find_element_text(row, actual_selectors)
                forecast = find_element_text(row, forecast_selectors)
                previous = find_element_text(row, previous_selectors)
                
                # Only add if we have at least time and title
                if time_str != "N/A" and title != "N/A":
                    data.append({
                        "time": time_str,
                        "currency": currency,
                        "title": title,
                        "impact": impact,
                        "actual": actual,
                        "forecast": forecast,
                        "previous": previous,
                        "source": "Investing.com"
                    })
                    print(f"✓ Added event: {time_str} - {title}")
                else:
                    print(f"✗ Skipped row {i+1}: Missing time or title")
                    
            except Exception as e:
                print(f"Error parsing row {i+1}: {str(e)}")
                continue

        print(f"Successfully fetched {len(data)} news events from Investing.com")
        return data
        
    except Exception as e:
        print(f"Error fetching news from Investing.com: {str(e)}")
        return []
    finally:
        if driver:
            try:
                driver.quit()
            except Exception as e:
                print(f"Error closing driver: {str(e)}")

def main():
    """Main function to run the news scraper"""
    print("🟢 Starting News Scraper...")
    
    # Fetch from both sources
    print("\n📊 Fetching from Forex Factory...")
    forex_data = fetch_forex_news()
    
    print("\n📊 Fetching from Investing.com...")
    investing_data = fetch_investing_news()
    
    # Combine data
    all_data = forex_data + investing_data
    
    if all_data:
        print(f"\n📊 Total News Events Found: {len(all_data)}")
        print(f"Forex Factory: {len(forex_data)} events")
        print(f"Investing.com: {len(investing_data)} events")
        
        print("\n" + "="*60)
        for event in all_data:
            source = event.get('source', 'Forex Factory')
            print(f"Source: {source}")
            print(f"Time: {event['time']}")
            print(f"Currency: {event['currency']}")
            print(f"Title: {event['title']}")
            print(f"Impact: {event['impact']}")
            print(f"Actual: {event['actual']}")
            print(f"Forecast: {event['forecast']}")
            print(f"Previous: {event['previous']}")
            print("-" * 50)
    else:
        print("❌ No news events found from either source")

if __name__ == "__main__":
    main()
