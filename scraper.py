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
        "syrah", "shiraz", "guidalberto",
        "zinfandel", "zin",
        "malbec",                  # bonus — great value right now
        "petite sirah",
    ],
    "min_discount_pct": 30,
    "max_price": 60,
    "min_score": 92,
    "trusted_sources": [           # only trust scores from these publications
        "wine spectator",
        "wine advocate",
        "robert parker",           # Wine Advocate founder
    ],
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

NOTIFIED_FILE = "notified.json"


def load_notified():
    """Load the set of wines already notified today."""
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        with open(NOTIFIED_FILE) as f:
            data = json.load(f)
        if data.get("date") == today:
            return data.get("wines", [])
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return []


def save_notified(wine_keys):
    """Save the set of wines notified today."""
    today = datetime.now().strftime("%Y-%m-%d")
    with open(NOTIFIED_FILE, "w") as f:
        json.dump({"date": today, "wines": wine_keys}, f)


def wine_key(deal):
    """Create a unique key for a wine deal (name + source)."""
    return f"{deal['name'].lower().strip()}|{deal['source'].lower()}"


def send_sms(deals):
    """Send deals via email-to-SMS gateway. Returns list of status dicts."""
    sms_results = []
    if not all([GMAIL_USER, GMAIL_PASS, PHONE_SMS]):
        print("⚠️  SMS credentials not set — printing deals only")
        for d in deals:
            print(f"  🍷 {d['name']} | ${d['price']} ({d['discount']}% off) | {d['url']}")
            sms_results.append({"name": d["name"], "status": "SKIPPED", "error": "credentials not set"})
        return sms_results

    for deal in deals[:3]:  # SMS is short — limit to top 3
        score_line = ""
        if deal.get("scores"):
            score_parts = [f"{s['source']} {s['score']}" for s in deal["scores"] if s["source"] != "unknown"]
            if score_parts:
                score_line = f"\n{' | '.join(score_parts)}"
        body = (
            f"🍷 WINE DEAL\n"
            f"{deal['name']}\n"
            f"${deal['price']} ({deal['discount']}% off)"
            f"{score_line}\n"
            f"{deal['url']}"
        )
        msg = MIMEText(body)
        msg["From"] = GMAIL_USER
        msg["To"] = PHONE_SMS
        msg["Subject"] = ""

        try:
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                server.login(GMAIL_USER, GMAIL_PASS)
                refused = server.sendmail(GMAIL_USER, PHONE_SMS, msg.as_string())
            if refused:
                error_msg = str(refused)
                print(f"❌ SMS rejected by gateway: {deal['name']} — {error_msg}")
                sms_results.append({"name": deal["name"], "status": "REJECTED", "error": error_msg})
            else:
                print(f"✅ SMS accepted by gateway: {deal['name']}")
                sms_results.append({"name": deal["name"], "status": "DELIVERED TO GATEWAY"})
        except smtplib.SMTPRecipientsRefused as e:
            print(f"❌ SMS recipient refused: {e}")
            sms_results.append({"name": deal["name"], "status": "RECIPIENT REFUSED", "error": str(e)})
        except smtplib.SMTPAuthenticationError as e:
            print(f"❌ Gmail auth failed: {e}")
            sms_results.append({"name": deal["name"], "status": "AUTH FAILED", "error": str(e)})
        except Exception as e:
            print(f"❌ SMS failed: {e}")
            sms_results.append({"name": deal["name"], "status": "SMTP ERROR", "error": str(e)})
    return sms_results


def matches_preferences(name, price, original_price, scores=None):
    """Check if a wine matches your taste profile.

    scores: list of dicts like [{"score": 94, "source": "Wine Spectator"}]
    """
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

    # Score check — any source with a high enough score counts
    if scores:
        has_good_score = any(
            s.get("score", 0) >= PREFERENCES["min_score"] for s in scores
        )
        if not has_good_score:
            return False

    return True


def scrape_wtso():
    """Scrape Wines Till Sold Out (wtso.com) — single daily deal site."""
    deals = []
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
        r = requests.get("https://www.wtso.com/", headers=headers, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")

        # WTSO has one main deal in #current-offer
        offer = soup.select_one("#current-offer")
        if not offer:
            return deals

        # Wine name from h2 inside current-offer
        name_el = offer.select_one("h2")
        price_el = soup.select_one("span#price")
        orig_el = soup.select_one("#comparable-price .price-words span")

        if not name_el or not price_el:
            return deals

        name = name_el.get_text(strip=True)
        price = float(re.sub(r"[^\d.]", "", price_el.get_text(strip=True)) or 0)
        orig_price = 0
        if orig_el:
            orig_price = float(re.sub(r"[^\d.]", "", orig_el.get_text(strip=True)) or 0)

        discount = round((1 - price / orig_price) * 100) if orig_price > 0 else 0
        url = "https://www.wtso.com"

        # Extract critic scores from .show_description divs
        # These contain abbreviations like "WA95-97", "WS95", "JD97", "AG92"
        scores = []
        score_abbrevs = {"WA": "Wine Advocate", "WS": "Wine Spectator",
                         "JD": "Jeb Dunnuck", "AG": "Antonio Galloni",
                         "RP": "Wine Advocate", "JS": "James Suckling",
                         "JH": "James Halliday", "V": "Vinous"}
        for score_el in soup.select(".show_description"):
            text = score_el.get_text(strip=True)
            # Match patterns like "WA95-97", "WS95", "JD97"
            m = re.match(r'([A-Z]{1,2})(\d{2,3})(?:-(\d{2,3}))?', text)
            if m:
                abbrev, score_low = m.group(1), int(m.group(2))
                score_high = int(m.group(3)) if m.group(3) else score_low
                score_val = score_high  # use the high end of range
                if 80 <= score_val <= 100:
                    source = score_abbrevs.get(abbrev, "unknown")
                    scores.append({"score": score_val, "source": source})

        if matches_preferences(name, price, orig_price, scores=scores if scores else None):
            deals.append({"name": name, "price": price, "original": orig_price,
                           "discount": discount, "url": url, "source": "WTSO",
                           "scores": scores})
    except Exception as e:
        print(f"WTSO scrape error: {e}")
    return deals


def scrape_lastbottle():
    """Scrape Last Bottle Wines (lastbottlewines.com) — Shopify single-deal site."""
    deals = []
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
        r = requests.get("https://lastbottlewines.com/", headers=headers, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")

        # Get wine name from product title or ProductJSON
        name = ""
        name_el = soup.select_one("h1.product__title")
        if name_el:
            name = name_el.get_text(strip=True)

        # Try ProductJSON for reliable name and deal price
        price = 0
        pjson_el = soup.select_one("#ProductJSON")
        if pjson_el:
            try:
                pdata = json.loads(pjson_el.string)
                if not name:
                    name = pdata.get("title", "")
                variants = pdata.get("variants", [])
                if variants:
                    price = variants[0].get("price", 0) / 100.0  # cents to dollars
            except (json.JSONDecodeError, TypeError):
                pass

        if not name:
            return deals

        # Get retail price from the price divs
        # Price divs show: "$25 RETAIL", "$25 BEST WEB", "$15 LAST BOTTLE"
        orig_price = 0
        for price_div in soup.select(".product__price"):
            text = price_div.get_text(strip=True)
            if "RETAIL" in text:
                val = re.sub(r"[^\d.]", "", text.split("RETAIL")[0])
                if val:
                    orig_price = float(val)
                break

        # Fallback: if price wasn't in JSON, try to find "LAST BOTTLE" price
        if price == 0:
            for price_div in soup.select(".product__price"):
                text = price_div.get_text(strip=True)
                if "LAST BOTTLE" in text:
                    val = re.sub(r"[^\d.]", "", text.split("LAST BOTTLE")[0])
                    if val:
                        price = float(val)
                    break

        discount = round((1 - price / orig_price) * 100) if orig_price > 0 and price > 0 else 0
        url = "https://lastbottlewines.com"

        # Extract critic scores from .product__reivew-score (note: typo in their class)
        # and look for source in the surrounding review text
        scores = []
        for review_el in soup.select(".product__review"):
            score_el = review_el.select_one(".product__reivew-score")
            if not score_el:
                continue
            score_text = score_el.get_text(strip=True)
            m = re.search(r"(\d{2,3})", score_text)
            if not m:
                continue
            score_val = int(m.group(1))
            if not (80 <= score_val <= 100):
                continue
            # Try to identify source from review text
            review_text = review_el.get_text().lower()
            source = "unknown"
            if "wine spectator" in review_text or "ws " in review_text:
                source = "Wine Spectator"
            elif "wine advocate" in review_text or "robert parker" in review_text:
                source = "Wine Advocate"
            elif "vinous" in review_text or "galloni" in review_text:
                source = "Vinous"
            elif "jeb dunnuck" in review_text:
                source = "Jeb Dunnuck"
            elif "james suckling" in review_text:
                source = "James Suckling"
            elif "wine enthusiast" in review_text:
                source = "Wine Enthusiast"
            scores.append({"score": score_val, "source": source})

        if matches_preferences(name, price, orig_price, scores=scores if scores else None):
            deals.append({"name": name, "price": price, "original": orig_price,
                           "discount": discount, "url": url, "source": "Last Bottle",
                           "scores": scores})
    except Exception as e:
        print(f"Last Bottle scrape error: {e}")
    return deals


def scrape_winespies():
    """Scrape Wine Spies (winespies.com) — daily flash deal site."""
    deals = []
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
        r = requests.get("https://www.winespies.com/", headers=headers, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")

        # Wine name from offer heading
        name_el = soup.select_one("h1.offer-heading")
        if not name_el:
            return deals

        name = name_el.get_text(strip=True)

        # Sale price from .pricing .price .amount
        price = 0
        price_el = soup.select_one(".pricing .price .amount")
        if price_el:
            price = float(re.sub(r"[^\d.]", "", price_el.get_text(strip=True)) or 0)

        # Original/retail price from .pricing .avg-price .amount
        orig_price = 0
        orig_el = soup.select_one(".pricing .avg-price .amount")
        if orig_el:
            orig_price = float(re.sub(r"[^\d.]", "", orig_el.get_text(strip=True)) or 0)

        discount = round((1 - price / orig_price) * 100) if orig_price > 0 and price > 0 else 0
        url = "https://www.winespies.com"

        # Extract critic scores from feedback items
        # Structure: .feedback-item contains .feedback-name (abbrev) + .feedback-body (score)
        # Also: .feedback-body.award contains "Source · NN Points"
        scores = []
        seen_sources = set()
        source_map = {"WE": "Wine Enthusiast", "WS": "Wine Spectator",
                       "WA": "Wine Advocate", "RP": "Wine Advocate",
                       "JD": "Jeb Dunnuck", "JS": "James Suckling",
                       "AG": "Antonio Galloni", "V": "Vinous"}

        # Method 1: feedback-items-list has compact items with abbrev + score
        for item in soup.select(".feedback-items-list .feedback-item"):
            fname = item.select_one(".feedback-name")
            fbody = item.select_one(".feedback-body")
            if fname and fbody:
                abbrev = fname.get_text(strip=True)
                score_text = fbody.get_text(strip=True)
                m = re.search(r"(\d{2,3})", score_text)
                if m:
                    score_val = int(m.group(1))
                    if 80 <= score_val <= 100:
                        source = source_map.get(abbrev, "unknown")
                        if source not in seen_sources:
                            scores.append({"score": score_val, "source": source})
                            seen_sources.add(source)

        # Method 2: feedback-body.award has full text like "Wine Enthusiast · 94 Points"
        if not scores:
            for award in soup.select(".feedback-body.award"):
                text = award.get_text(strip=True)
                m = re.search(r"(\d{2,3})\s*Points?", text, re.I)
                if m:
                    score_val = int(m.group(1))
                    if 80 <= score_val <= 100:
                        source = "unknown"
                        text_lower = text.lower()
                        if "spectator" in text_lower:
                            source = "Wine Spectator"
                        elif "advocate" in text_lower or "parker" in text_lower:
                            source = "Wine Advocate"
                        elif "enthusiast" in text_lower:
                            source = "Wine Enthusiast"
                        elif "vinous" in text_lower or "galloni" in text_lower:
                            source = "Vinous"
                        elif "suckling" in text_lower:
                            source = "James Suckling"
                        elif "dunnuck" in text_lower:
                            source = "Jeb Dunnuck"
                        if source not in seen_sources:
                            scores.append({"score": score_val, "source": source})
                            seen_sources.add(source)

        if matches_preferences(name, price, orig_price, scores=scores if scores else None):
            deals.append({"name": name, "price": price, "original": orig_price,
                           "discount": discount, "url": url, "source": "Wine Spies",
                           "scores": scores})
    except Exception as e:
        print(f"Wine Spies scrape error: {e}")
    return deals


def write_run_log(timestamp, site_results, new_deals, sms_target, sms_results=None):
    """Write a log of the last run to last_run.txt (overwritten each run)."""
    lines = []
    lines.append(f"Last Run: {timestamp}")
    lines.append("=" * 50)
    lines.append("")
    lines.append("Sites Checked:")
    for site, result in site_results.items():
        status = f"{result['matches']} match(es)" if result["matches"] > 0 else "no matches"
        if result.get("error"):
            status = f"ERROR: {result['error']}"
        lines.append(f"  {site}: {status}")
    lines.append("")
    if new_deals:
        lines.append(f"Deals Notified ({len(new_deals)}):")
        for d in new_deals:
            lines.append(f"  [{d['source']}] {d['name']}")
            lines.append(f"    ${d['price']} ({d['discount']}% off)")
        lines.append("")
        lines.append(f"SMS Gateway: {sms_target}")
        if sms_results:
            for sr in sms_results:
                error_info = f" — {sr['error']}" if sr.get("error") else ""
                lines.append(f"  {sr['status']}: {sr['name']}{error_info}")
        else:
            lines.append("  (no SMS results recorded)")
    else:
        lines.append("No new deals to notify.")
        lines.append(f"SMS Gateway: (none this run)")
    lines.append("")
    with open("last_run.txt", "w") as f:
        f.write("\n".join(lines))


def main():
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M UTC')
    print(f"\n🍷 Wine Deal Scanner — {timestamp}")
    print("=" * 50)

    site_results = {
        "WTSO": {"matches": 0},
        "Last Bottle": {"matches": 0},
        "Wine Spies": {"matches": 0},
    }

    all_deals = []
    for name, scraper in [("WTSO", scrape_wtso), ("Last Bottle", scrape_lastbottle), ("Wine Spies", scrape_winespies)]:
        try:
            deals = scraper()
            site_results[name]["matches"] = len(deals)
            all_deals += deals
            print(f"  {name}: found {len(deals)} matching deal(s)")
        except Exception as e:
            site_results[name]["error"] = str(e)
            print(f"  {name}: ERROR - {e}")

    # Sort by discount percentage
    all_deals.sort(key=lambda x: x.get("discount", 0), reverse=True)

    # Filter out wines already notified today
    already_notified = load_notified()
    new_deals = [d for d in all_deals if wine_key(d) not in already_notified]

    sms_results = []
    if new_deals:
        print(f"\n🎉 Found {len(new_deals)} new deal(s)! ({len(all_deals) - len(new_deals)} already notified today)")
        for d in new_deals:
            print(f"  [{d['source']}] {d['name']}")
            print(f"    ${d['price']} (was ${d['original']}, {d['discount']}% off)")
            print(f"    {d['url']}\n")
        sms_results = send_sms(new_deals)

        # Mark these wines as notified
        already_notified.extend(wine_key(d) for d in new_deals)
        save_notified(already_notified)
    elif all_deals:
        print(f"📋 {len(all_deals)} matching deal(s) found, but all already notified today.")
    else:
        print("😴 No deals matching your preferences right now. Will check again in 30 min.")

    # Write run log
    write_run_log(timestamp, site_results, new_deals, PHONE_SMS, sms_results)


if __name__ == "__main__":
    main()
