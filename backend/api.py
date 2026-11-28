import re
import time
import requests
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from playwright.sync_api import sync_playwright
from mangum import Mangum

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
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
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        res = requests.get(url, headers=headers, timeout=3)
        emails = find_emails_in_html(res.text)
        if emails:
            return emails[0]

        for path in ["/contact", "/contact-us"]:
            c_res = requests.get(urljoin(url, path), headers=headers, timeout=2.5)
            if c_res.status_code == 200:
                c_emails = find_emails_in_html(c_res.text)
                if c_emails:
                    return c_emails[0]
    except Exception:
        pass
    return ""

def scrape_leads(search_query, skip=0, limit=20):
    start_time = time.time()
    leads = []
    seen_names = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--no-zygote",
                "--disable-extensions"
            ]
        )
        try:
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                locale="en-US"
            )
            page = context.new_page()
            page.set_default_timeout(10000)

            page.route(
                "**/*",
                lambda route: route.abort()
                if route.request.resource_type in ["image", "font", "media", "stylesheet"]
                else route.continue_()
            )

            page.goto(
                f"https://www.google.com/maps/search/{search_query.replace(' ', '+')}?hl=en",
                wait_until="domcontentloaded",
                timeout=20000
            )

            # Agar Google consent page aaye to accept karein
            try:
                consent_btn = page.locator('button:has-text("Accept all"), button:has-text("I agree")').first
                if consent_btn.is_visible(timeout=2000):
                    consent_btn.click()
                    time.sleep(1)
            except Exception:
                pass

            page.wait_for_selector('div[role="feed"]', timeout=15000)

            scroll_times = 3 + (skip // 10) * 2
            feed = page.locator('div[role="feed"]')
            for _ in range(scroll_times):
                feed.evaluate("el => el.scrollTop += 2000")
                time.sleep(1.0)

            listings = page.locator('a[href*="/maps/place/"]').all()
            all_urls = list(dict.fromkeys([l.get_attribute("href") for l in listings if l.get_attribute("href")]))
            target_urls = all_urls[skip : skip + limit]

            for url in target_urls:
                # 110 second se zyada ho jaye to loop rok dein taake Lambda kabhi timeout na kare
                if time.time() - start_time > 110:
                    break
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=8000)
                    page.wait_for_selector("h1", timeout=4000)

                    name = page.locator("h1").first.inner_text().strip()
                    if not name or name in seen_names or name == "Results":
                        continue
                    seen_names.add(name)

                    phone_loc = page.locator('button[data-item-id^="phone:tel:"]')
                    phone = phone_loc.first.get_attribute("aria-label").replace("Phone:", "").strip() if phone_loc.count() > 0 else ""

                    web_loc = page.locator('a[data-item-id="authority"]')
                    website = web_loc.first.get_attribute("href") if web_loc.count() > 0 else ""

                    leads.append({
                        "name": name,
                        "phone": phone,
                        "website": website,
                        "email": ""
                    })
                except Exception:
                    continue
        finally:
            browser.close()

    # Saari websites se emails ek hi waqt (parallel) mein nikalein
    if leads:
        websites = [lead["website"] for lead in leads]
        with ThreadPoolExecutor(max_workers=10) as executor:
            emails = list(executor.map(extract_email_from_website, websites))
        for lead, email in zip(leads, emails):
            lead["email"] = email

    return leads

@app.get("/")
def health_check():
    return {"status": "LocalLeadPro API is running"}

@app.get("/scrape")
def get_leads(query: str, skip: int = 0):
    results = scrape_leads(query, skip=skip, limit=20)
    return {"leads": results, "next_skip": skip + len(results)}

handler = Mangum(app)