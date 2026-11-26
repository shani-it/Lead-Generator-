import re
import time
import requests
import pandas as pd
from urllib.parse import urljoin
from playwright.sync_api import sync_playwright

JUNK_EMAILS = ("user@domain.com", "example@email.com", "email@example.com", "info@mysite.com", "name@company.com")

def find_emails_in_html(html_text):
    emails = re.findall(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", html_text)
    clean = []
    for e in emails:
        e_low = e.lower()
        if not e_low.endswith(('.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.js', '.css')) and e_low not in JUNK_EMAILS:
            clean.append(e)
    return list(dict.fromkeys(clean))

def extract_email_from_website(url):
    if not url:
        return ""
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        # 1. Pehle Homepage check karein
        res = requests.get(url, headers=headers, timeout=8)
        emails = find_emails_in_html(res.text)
        if emails:
            return emails[0]

        # 2. Agar homepage par na mile to /contact aur /contact-us check karein
        for path in ["/contact", "/contact-us", "/about", "/about-us"]:
            contact_url = urljoin(url, path)
            c_res = requests.get(contact_url, headers=headers, timeout=6)
            if c_res.status_code == 200:
                c_emails = find_emails_in_html(c_res.text)
                if c_emails:
                    return c_emails[0]
    except Exception:
        pass
    return ""

def run_scraper(search_query, max_results=15):
    leads = []
    seen_names = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()

        print(f"Google Maps par search ho rahi hai: {search_query}...")
        page.goto(f"https://www.google.com/maps/search/{search_query.replace(' ', '+')}")
        page.wait_for_selector('div[role="feed"]', timeout=15000)

        feed = page.locator('div[role="feed"]')
        for _ in range(4):
            feed.evaluate("el => el.scrollTop += 1000")
            time.sleep(2)

        listings = page.locator('a[href*="/maps/place/"]').all()
        urls = list(dict.fromkeys([l.get_attribute("href") for l in listings if l.get_attribute("href")]))[:max_results]

        for url in urls:
            try:
                page.goto(url)
                time.sleep(2)

                name = page.locator("h1").inner_text().strip() if page.locator("h1").count() > 0 else "N/A"
                if name in seen_names or name == "N/A":
                    continue
                seen_names.add(name)

                phone_loc = page.locator('button[data-item-id^="phone:tel:"]')
                phone = phone_loc.get_attribute("aria-label").replace("Phone:", "").strip() if phone_loc.count() > 0 else ""

                web_loc = page.locator('a[data-item-id="authority"]')
                website = web_loc.get_attribute("href") if web_loc.count() > 0 else ""

                email = extract_email_from_website(website)

                leads.append({
                    "Business Name": name,
                    "Phone": phone,
                    "Website": website,
                    "Email": email
                })
                print(f"✔ {name} | {phone} | {email if email else 'No Email'}")
            except Exception:
                continue

        browser.close()

    df = pd.DataFrame(leads)
    df.to_csv("leads.csv", index=False)
    print("\nMukammal! Clean data 'leads.csv' mein save ho gaya hai.")

if __name__ == "__main__":
    run_scraper("Property Management Companies in Dallas TX", max_results=15)