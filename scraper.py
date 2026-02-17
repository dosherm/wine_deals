"""
Wine Deal Scraper
Checks WTSO, Last Bottle, and Wine.com for deals matching your taste profile.
Sends a free SMS via email-to-SMS gateway when a great deal is found.
"""

import requests
from bs4 import BeautifulSoup
import smtplib
from email.mime.text import MIMEText
import json
import os
import re
from datetime import datetime

# ─────────────────────────────────────────
# YOUR PREFERENCES — edit these
# ─────────────────────────────────────────
PREFERENCES = {
    "keywords": [
        "cabernet sauvignon", "cab sav", "cabernet",
        "chianti", "sangiovese",
        "syrah", "shiraz",
        "zinfandel", "zin",
        "malbec",                  # bonus — great value right now
        "petite sirah",
    ],
    "min_discount_pct": 30,        # only alert if 30%+ off
    "max_price": 55,               # max price after discount
    "min_score": 90,               # minimum wine score (if listed)
}

# ─────────────────────────────────────────
# SMS GATEWAY CONFIG
# Set these as GitHub Actions Secrets:
#   GMAIL_USER     → your gmail address
#   GMAIL_PASS     → your gmail app password (not regular password)
#   PHONE_SMS      → e.g. 3125551234@vtext.com
#
# Common SMS gateways:
#   Verizon:  @vtext.com
#   AT&T:     @txt.att.net
#   T-Mobile: @tmomail.net
#   Sprint:   @messaging.sprintpcs.com
# ─────────────────────────────────────────
GMAIL_USER = os.environ.get("GMAIL_USER", "")
GMAIL_PASS = os.environ.get("GMAIL_PASS", "")
PHONE_SMS  = os.environ.get("PHONE_SMS", "")   # e.g. 3125551234@vtext.com


def send_sms(deals):
    """Send deals via email-to-SMS gateway (free, no account needed)."""
    if not all([GMAIL_USER, GMAIL_PASS, PHONE_SMS]):
        print("⚠️  SMS credentials not set — printing deals only")
        for d in deals:
            print(f"  🍷 {d['name']} | ${d['price']} ({d['discount']}% off) | {d['url']}")
        return

    for deal in deals[:3]:  # SMS is short — limit to top 3
        body = (
            f"🍷 WINE DEAL\n"
            f"{deal['name']}\n"
            f"${deal['price']} ({deal['discount']}% off)\n"
            f"{deal['url']}"
        )
        msg = MIMEText(body)
        msg["From"] = GMAIL_USER
        msg["To"] = PHONE_SMS
        msg["Subject"] = ""

        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                server.login(GMAIL_USER, GMAIL_PASS)
                server.sendmail(GMAIL_USER, PHONE_SMS, msg.as_string())
            print(f"✅ SMS sent: {deal['name']}")
        except Exception as e:
            print(f"❌ SMS failed: {e}")


def matches_preferences(name, price, original_price, score=None):
    """Check if a wine matches your taste profile."""
    name_lower = name.lower()

    # Must match at least one keyword
    if not any(kw in name_lower for kw in PREFERENCES["keywords"]):
        return False

    # Price check
    if price > PREFERENCES["max_price"]:
        return False

    # Discount check
    if original_price and original_price > 0:
        discount = round((1 - price / original_price) * 100)
        if discount < PREFERENCES["min_discount_pct"]:
            return False
    
    # Score check (optional)
    if score and score < PREFERENCES["min_score"]:
        return False

    return True


def scrape_wtso():
    """Scrape Wines Till Sold Out (wtso.com)"""
    deals = []
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; WineBot/1.0)"}
        r = requests.get("https://www.wtso.com/", headers=headers, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")

        # WTSO shows one featured deal prominently
        for item in soup.select(".wine-item, .deal-item, [class*='product']")[:10]:
            name_el = item.select_one("[class*='name'], [class*='title'], h2, h3")
            price_el = item.select_one("[class*='sale'], [class*='price-sale'], [class*='current']")
            orig_el  = item.select_one("[class*='original'], [class*='retail'], [class*='was'], s")
            link_el  = item.select_one("a[href]")

            if not name_el or not price_el:
                continue

            name = name_el.get_text(strip=True)
            price_text = price_el.get_text(strip=True)
            price = float(re.sub(r"[^\d.]", "", price_text) or 0)

            orig_price = 0
            if orig_el:
                orig_price = float(re.sub(r"[^\d.]", "", orig_el.get_text(strip=True)) or 0)

            discount = round((1 - price / orig_price) * 100) if orig_price > 0 else 0
            url = "https://www.wtso.com" + link_el["href"] if link_el else "https://www.wtso.com"

            if matches_preferences(name, price, orig_price):
                deals.append({"name": name, "price": price, "original": orig_price,
                               "discount": discount, "url": url, "source": "WTSO"})
    except Exception as e:
        print(f"WTSO scrape error: {e}")
    return deals


def scrape_lastbottle():
    """Scrape Last Bottle Wines (lastbottlewines.com)"""
    deals = []
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; WineBot/1.0)"}
        r = requests.get("https://lastbottlewines.com/", headers=headers, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")

        for item in soup.select(".offer, .wine-offer, [class*='offer']")[:5]:
            name_el  = item.select_one("[class*='name'], h1, h2, h3")
            price_el = item.select_one("[class*='price'], [class*='sale']")
            orig_el  = item.select_one("[class*='retail'], [class*='original'], s, strike")
            link_el  = item.select_one("a[href]")

            if not name_el or not price_el:
                continue

            name  = name_el.get_text(strip=True)
            price = float(re.sub(r"[^\d.]", "", price_el.get_text(strip=True)) or 0)
            orig  = float(re.sub(r"[^\d.]", "", orig_el.get_text(strip=True)) or 0) if orig_el else 0
            discount = round((1 - price / orig) * 100) if orig > 0 else 0
            url = link_el["href"] if link_el else "https://lastbottlewines.com"
            if not url.startswith("http"):
                url = "https://lastbottlewines.com" + url

            if matches_preferences(name, price, orig):
                deals.append({"name": name, "price": price, "original": orig,
                               "discount": discount, "url": url, "source": "Last Bottle"})
    except Exception as e:
        print(f"Last Bottle scrape error: {e}")
    return deals


def scrape_wine_dot_com():
    """Scrape Wine.com sale section via their public API endpoint"""
    deals = []
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; WineBot/1.0)"}
        # Wine.com has a public catalog endpoint
        url = ("https://www.wine.com/list/wine/7155?"
               "sortBy=savings&pricemax=60&pricemin=20&pct_off=25")
        r = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")

        for item in soup.select(".prodItem, [class*='productCard'], [class*='product-item']")[:15]:
            name_el  = item.select_one("[class*='name'], [class*='title']")
            price_el = item.select_one("[class*='salePrice'], [class*='sale-price']")
            orig_el  = item.select_one("[class*='regPrice'], [class*='reg-price'], s")
            link_el  = item.select_one("a[href]")

            if not name_el or not price_el:
                continue

            name  = name_el.get_text(strip=True)
            price = float(re.sub(r"[^\d.]", "", price_el.get_text(strip=True)) or 0)
            orig  = float(re.sub(r"[^\d.]", "", orig_el.get_text(strip=True)) or 0) if orig_el else 0
            discount = round((1 - price / orig) * 100) if orig > 0 else 0
            url = "https://www.wine.com" + link_el["href"] if link_el and not link_el["href"].startswith("http") else (link_el["href"] if link_el else "https://www.wine.com")

            if matches_preferences(name, price, orig):
                deals.append({"name": name, "price": price, "original": orig,
                               "discount": discount, "url": url, "source": "Wine.com"})
    except Exception as e:
        print(f"Wine.com scrape error: {e}")
    return deals


def main():
    print(f"\n🍷 Wine Deal Scanner — {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 50)

    all_deals = []
    all_deals += scrape_wtso()
    all_deals += scrape_lastbottle()
    all_deals += scrape_wine_dot_com()

    # Sort by discount percentage
    all_deals.sort(key=lambda x: x.get("discount", 0), reverse=True)

    if all_deals:
        print(f"\n🎉 Found {len(all_deals)} matching deal(s)!")
        for d in all_deals:
            print(f"  [{d['source']}] {d['name']}")
            print(f"    ${d['price']} (was ${d['original']}, {d['discount']}% off)")
            print(f"    {d['url']}\n")
        send_sms(all_deals)
    else:
        print("😴 No deals matching your preferences right now. Will check again in 30 min.")


if __name__ == "__main__":
    main()
