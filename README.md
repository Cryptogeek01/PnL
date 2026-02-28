# BetBot Pro — Setup Guide (Windows)

## What This Is
An automated live betting bot that:
- Monitors all live football matches globally in real time
- Detects matches at 85+ minutes with a 2+ goal lead
- Compares odds across SportyBet and BetKing
- Places bets automatically (or manually) on the leading team
- Tracks all bets, balances, and P&L in a live dashboard

---

## Step 1 — Install Python
1. Go to https://python.org/downloads
2. Download Python 3.11 or higher
3. During install, CHECK "Add Python to PATH"
4. Click Install Now

---

## Step 2 — Install Dependencies
Open **Command Prompt** (press Windows key, type `cmd`, press Enter):

```
cd path\to\betbot
pip install -r requirements.txt
playwright install chromium
```

---

## Step 3 — Get Your API-Football Key (Free)
1. Go to https://www.api-football.com
2. Click "Subscribe" → choose the **Free plan** (100 requests/day)
3. Copy your API key from the dashboard

---

## Step 4 — Configure Your Details
Open `config.py` in Notepad (right-click → Open With → Notepad):

Fill in:
```python
API_FOOTBALL_KEY = "paste_your_key_here"

SPORTYBET_USERNAME = "your_phone_or_email"
SPORTYBET_PASSWORD = "your_password"

BETKING_USERNAME = "your_phone_or_email"
BETKING_PASSWORD = "your_password"
```

Save the file.

---

## Step 5 — Run the Bot
In Command Prompt:
```
python app.py
```

You will see:
```
BetBot Pro starting on http://127.0.0.1:5000
```

---

## Step 6 — Open the Dashboard
Open your browser and go to:
```
http://127.0.0.1:5000
```

---

## Step 7 — Using the Dashboard

### First time:
1. Click **⚡ INITIALIZE** — this opens Chrome browsers and logs into SportyBet and BetKing
2. Wait for "Initialization complete" in the Activity Feed
3. Your **real balances** will appear automatically
4. Click **▶ START** to begin scanning

### Modes:
- **Auto-bet OFF** (default): Bot scans and highlights opportunities. You click "BET NOW" on each match to place manually.
- **Auto-bet ON**: Bot places bets automatically on all qualifying matches.

### Recording Results:
Since live bet results aren't fetched automatically (to keep the free API tier), each "PLACED" bet in the log shows WIN / LOSS buttons. Click the correct one after the match ends to update your P&L.

---

## Important Notes

### Account Safety
- Do not run both the bot and your normal browser logged into the same account simultaneously
- Start with small stakes (₦50-₦100) while validating the bot works correctly
- Bookmakers may flag accounts for automated betting — use responsibly

### API Limits
The free API-Football plan allows 100 requests/day.
- At 60-second scan intervals, that's about 100 scans per day (enough for testing)
- To scan more frequently, upgrade to a paid plan (~$10/month)

### If Login Fails
- Check your credentials in config.py
- If BetKing requires OTP: the browser window will stay open — enter the OTP manually when prompted
- Some accounts may require CAPTCHA on first login — complete it manually in the browser window

### Logs
All activity is saved to `betbot.log` in the same folder — useful for debugging.

---

## File Structure
```
betbot/
├── app.py          — Main server (run this)
├── bot.py          — Core betting logic
├── sportybet.py    — SportyBet browser automation
├── betking.py      — BetKing browser automation
├── scores.py       — Live score fetcher
├── config.py       — YOUR CREDENTIALS (keep private)
├── dashboard.html  — Web dashboard
├── requirements.txt
└── README.md
```

---

## Scaling Up
To add more bookmakers later, create a new file following the same pattern as `sportybet.py` and register it in `bot.py`.

To add automatic result detection (remove the manual WIN/LOSS buttons), the premium API-Football plan includes match result webhooks.
