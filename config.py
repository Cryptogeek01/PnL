# ─────────────────────────────────────────────
#  BetBot Pro — Configuration
#  Fill in your details below before running
# ─────────────────────────────────────────────

# ── API-FOOTBALL (free at api-football.com) ──
API_FOOTBALL_KEY = "44e824e2fe678d3fabfa60f10c9f2c42"

# ── SPORTYBET CREDENTIALS ──
SPORTYBET_USERNAME = "+2349153269357"
SPORTYBET_PASSWORD = "PEJStar123"

# ── BETKING CREDENTIALS ──
BETKING_USERNAME = "+2349153269357"
BETKING_PASSWORD = "PEJStar123"

# ── TELEGRAM ALERTS ──
# 1. Message @BotFather on Telegram → /newbot → copy the token below
# 2. Message your new bot once, then visit:
#    https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates
#    Copy the "id" number from "chat" — that's your CHAT_ID
TELEGRAM_BOT_TOKEN = "8413961592:AAHqYIIkw6SvPoFE22eACeaeujuazA8VKiY"
TELEGRAM_CHAT_ID   = "6397640917"
TELEGRAM_ENABLED   = True   # Set True once token and chat_id are filled in

# ── BOT SETTINGS (defaults — all adjustable from dashboard) ──
DEFAULT_STAKE    = 100    # Naira per bet
MIN_STAKE        = 50     # Hard minimum stake
MIN_MINUTE       = 85     # Only bet from this minute onwards
MIN_GOAL_LEAD    = 2      # Minimum goal difference
MIN_ODDS         = 1.02   # Minimum odds to accept
AUTO_BET         = False  # Start in manual mode

# ── COMPOUND REINVESTMENT ──
# Bot automatically scales stake as balance grows.
# Stake = COMPOUND_PERCENT % of current total balance, capped between MIN_STAKE and MAX_STAKE.
COMPOUND_ENABLED  = True
COMPOUND_PERCENT  = 10    # Bet 10% of current balance each time
MAX_STAKE         = 5000  # Hard cap so one bet never risks too much

# ── LOSS RECOVERY MODE ──
# After a loss, temporarily tighten filters to protect remaining capital.
LOSS_RECOVERY_ENABLED       = True
LOSS_RECOVERY_MIN_MINUTE    = 88   # Require later minute after a loss
LOSS_RECOVERY_MIN_GOAL_LEAD = 3    # Require bigger lead after a loss
LOSS_RECOVERY_BETS          = 5    # Successful bets before returning to normal filters

# ── DAILY LOSS LIMIT ──
# Bot hard-stops for the day if total losses exceed this amount.
DAILY_LOSS_LIMIT_ENABLED = True
DAILY_LOSS_LIMIT         = 500    # Naira

# ── ODDS SUSPENSION DETECTOR ──
# If odds on a match vanish between scans, treat as a danger signal.
SUSPENSION_DETECTOR_ENABLED = True

# ── STOP ON LOW BALANCE ──
STOP_ON_LOW_BALANCE = True

# ── SERVER SETTINGS ──
HOST = "127.0.0.1"
PORT = 5000

# ── SCAN INTERVAL (seconds between live score checks) ──
SCAN_INTERVAL = 60

# ── BROWSER SETTINGS ──
HEADLESS = False

# ── ANALYTICS ──
ANALYTICS_FILE = "analytics.json"
