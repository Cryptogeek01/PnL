# ─────────────────────────────────────────────
#  BetBot Pro — Configuration
#  Fill in your details below before running
# ─────────────────────────────────────────────

# ── API-FOOTBALL (free at api-football.com) ──
API_FOOTBALL_KEY = "YOUR_API_FOOTBALL_KEY_HERE"

# ── SPORTYBET CREDENTIALS ──
SPORTYBET_USERNAME = "YOUR_SPORTYBET_PHONE_OR_EMAIL"
SPORTYBET_PASSWORD = "YOUR_SPORTYBET_PASSWORD"

# ── BETKING CREDENTIALS ──
BETKING_USERNAME = "YOUR_BETKING_PHONE_OR_EMAIL"
BETKING_PASSWORD = "YOUR_BETKING_PASSWORD"

# ── BOT SETTINGS (defaults, all adjustable from dashboard) ──
DEFAULT_STAKE = 100           # Naira per bet
MIN_STAKE = 50                # Minimum allowed stake
MIN_MINUTE = 85               # Only bet from this minute onwards
MIN_GOAL_LEAD = 2             # Minimum goal difference to consider
MIN_ODDS = 1.02               # Minimum odds to accept
AUTO_BET = False              # Start in manual mode (toggle in dashboard)
STOP_ON_LOW_BALANCE = True    # Pause bot if balance too low for a bet

# ── SERVER SETTINGS ──
HOST = "127.0.0.1"
PORT = 5000

# ── SCAN INTERVAL (seconds between live score checks) ──
SCAN_INTERVAL = 60

# ── BROWSER SETTINGS ──
HEADLESS = False   # Set True to hide browser windows (not recommended at first)
