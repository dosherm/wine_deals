# 🍷 Wine Deal Scanner

Automatically checks WTSO, Last Bottle, and Wine.com every 30 minutes for deals
matching your taste profile (Cab, Chianti, Syrah, Zinfandel) and texts you for free.

---

## Setup — Takes About 10 Minutes

### Step 1: Create a GitHub repo

1. Go to https://github.com/new
2. Name it `wine-deals` (or anything you like)
3. Make it **Private**
4. Click **Create repository**

### Step 2: Push this code to your repo

From your terminal, in this folder:

```bash
git init
git add .
git commit -m "wine deal scanner"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/wine-deals.git
git push -u origin main
```

---

### Step 3: Set up Gmail App Password (free)

GitHub Actions needs to send email on your behalf via Gmail.

1. Go to https://myaccount.google.com/security
2. Enable **2-Step Verification** if not already on
3. Search for **"App passwords"** in the search bar
4. Create a new app password → name it "wine scanner"
5. Copy the 16-character password (looks like: `abcd efgh ijkl mnop`)

---

### Step 4: Find your SMS gateway address

This lets GitHub email your phone for free — no account, no cost.

| Carrier   | SMS Gateway                        |
|-----------|------------------------------------|
| Verizon   | `yournumber@vtext.com`             |
| AT&T      | `yournumber@txt.att.net`           |
| T-Mobile  | `yournumber@tmomail.net`           |
| Sprint    | `yournumber@messaging.sprintpcs.com` |

Example: if you're on Verizon with number 312-555-1234, use: `3125551234@vtext.com`

---

### Step 5: Add GitHub Secrets

1. Go to your repo on GitHub
2. Click **Settings** → **Secrets and variables** → **Actions**
3. Click **New repository secret** and add these three:

| Secret Name  | Value                              |
|--------------|------------------------------------|
| `GMAIL_USER` | your.email@gmail.com               |
| `GMAIL_PASS` | your 16-char app password          |
| `PHONE_SMS`  | 3125551234@vtext.com               |

---

### Step 6: Test it manually

1. Go to your repo → **Actions** tab
2. Click **Wine Deal Scanner** in the left sidebar
3. Click **Run workflow** → **Run workflow**
4. Watch the logs — you should see it scan and either find deals or report none

---

## Customizing Your Preferences

Edit the `PREFERENCES` section at the top of `scraper.py`:

```python
PREFERENCES = {
    "keywords": ["cabernet sauvignon", "chianti", "syrah", "zinfandel", ...],
    "min_discount_pct": 30,    # only alert if 30%+ off
    "max_price": 55,           # max price after discount
    "min_score": 90,           # minimum critic score (if listed)
}
```

After editing, just `git add . && git commit -m "update prefs" && git push`

---

## How It Works

```
Every 30 min → GitHub Actions wakes up
             → runs scraper.py
             → checks WTSO + Last Bottle + Wine.com
             → filters by your keywords, price, discount %
             → if match found → emails your phone's SMS gateway
             → you get a text with name, price, and buy link
```

## Cost

**$0.00** — GitHub Actions free tier gives you 2,000 minutes/month.
This job takes ~30 seconds × 48 runs/day × 30 days = ~720 minutes/month. Well within the free tier.

---

## Troubleshooting

**Not getting texts?**
- Double-check your SMS gateway address (carrier-specific)
- Make sure Gmail App Password is correct (not your regular password)
- Check the Actions log for errors

**Too many/few alerts?**
- Lower `min_discount_pct` to 20 to get more alerts
- Raise `max_price` to 70 to include pricier bottles
- Add more keywords like `"barbera"`, `"tempranillo"`, `"merlot"`

**GitHub Actions stopped running?**
- GitHub pauses scheduled workflows after 60 days of repo inactivity
- Just push any small change to reactivate: `git commit --allow-empty -m "keep alive" && git push`
