import re
import time
import requests
from urllib.parse import urljoin
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from playwright.sync_api import sync_playwright

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

JUNK_EMAILS = (
    "user@domain.com",
    "example@email.com",
    "email@example.com",
    "info@mysite.com",
    "name@company.com",
    "sentry@wixpress.com"
)

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
        res = requests.get(url, headers=headers, timeout=5)
        emails = find_emails_in_html(res.text)
        if emails:
            return emails[0]

        for path in ["/contact", "/contact-us", "/about"]:
            c_res = requests.get(urljoin(url, path), headers=headers, timeout=4)
            if c_res.status_code == 200:
                c_emails = find_emails_in_html(c_res.text)
                if c_emails:
                    return c_emails[0]
    except Exception:
        pass
    return ""

def scrape_leads(search_query, skip=0, limit=20):
    leads = []
    seen_names = set()

    with sync_playwright() as p:
        # Render Free Tier (512MB RAM) crash prevention flags
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--single-process"
            ]
        )
        try:
            page = browser.new_page()
            page.goto(f"https://www.google.com/maps/search/{search_query.replace(' ', '+')}")
            page.wait_for_selector('div[role="feed"]', timeout=15000)

            # Jitne zyada skip karne hain, utna zyada scroll karein
            scroll_times = 4 + (skip // 10) * 2
            feed = page.locator('div[role="feed"]')
            for _ in range(scroll_times):
                feed.evaluate("el => el.scrollTop += 1500")
                time.sleep(1.5)

            listings = page.locator('a[href*="/maps/place/"]').all()
            all_urls = list(dict.fromkeys([l.get_attribute("href") for l in listings if l.get_attribute("href")]))
            
            # Purane results ko skip karke agla fresh batch uthana
            target_urls = all_urls[skip : skip + limit]

            for url in target_urls:
                try:
                    page.goto(url)
                    time.sleep(1.2)

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
                        "name": name,
                        "phone": phone,
                        "website": website,
                        "email": email
                    })
                except Exception:
                    continue
        finally:
            browser.close()

    return leads

@app.get("/")
def health_check():
    return {"status": "LocalLeadPro API is running"}

@app.get("/scrape")
def get_leads(query: str, skip: int = 0):
    results = scrape_leads(query, skip=skip, limit=20)
    return {"leads": results, "next_skip": skip + len(results)}