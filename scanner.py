"""
scanner.py — Live Match Scanner + Telegram Alerter
No browser automation. No logins. Just pure opportunity detection.

Monitors live football matches via API-Football and sends
Telegram alerts the moment a qualifying match is found.

Run with: py -3.11 scanner.py
"""

import requests
import time
import logging
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)

# ── YOUR SETTINGS ─────────────────────────────────────
API_KEY       = "YOUR_API_FOOTBALL_KEY_HERE"
TG_TOKEN      = "YOUR_TELEGRAM_BOT_TOKEN"
TG_CHAT_ID    = "YOUR_TELEGRAM_CHAT_ID"

MIN_MINUTE    = 65     # Alert from this minute onwards
MIN_GOAL_LEAD = 2      # Minimum goal difference
SCAN_INTERVAL = 60     # Seconds between scans (60 = 1 minute)
# ──────────────────────────────────────────────────────

API_BASE   = "https://v3.football.api-sports.io"
TG_API     = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"

# Track already-alerted matches so we don't spam
# Key: fixture_id, Value: minute bracket (rounded to 5) when alerted
alerted: dict = {}


def fetch_live_matches() -> list:
    """Fetch all currently live matches from API-Football."""
    try:
        resp = requests.get(
            f"{API_BASE}/fixtures",
            headers={"x-apisports-key": API_KEY},
            params={"live": "all"},
            timeout=15
        )
        resp.raise_for_status()
        data = resp.json()

        if data.get("errors"):
            logger.error(f"API error: {data['errors']}")
            return []

        matches = []
        for f in data.get("response", []):
            try:
                status     = f["fixture"]["status"]
                short      = status.get("short", "")
                minute     = status.get("elapsed") or 0
                goals      = f["goals"]
                teams      = f["teams"]
                league     = f["league"]
                home_score = goals.get("home") or 0
                away_score = goals.get("away") or 0

                # Only 2nd half live matches
                if short not in ("2H", "ET"):
                    continue

                goal_diff = home_score - away_score

                if goal_diff > 0:
                    leading_team  = teams["home"]["name"]
                    trailing_team = teams["away"]["name"]
                elif goal_diff < 0:
                    leading_team  = teams["away"]["name"]
                    trailing_team = teams["home"]["name"]
                else:
                    continue  # Draw — skip

                matches.append({
                    "fixture_id":   f["fixture"]["id"],
                    "league":       league["name"],
                    "country":      league["country"],
                    "home":         teams["home"]["name"],
                    "away":         teams["away"]["name"],
                    "home_score":   home_score,
                    "away_score":   away_score,
                    "minute":       minute,
                    "goal_diff":    abs(goal_diff),
                    "leading_team": leading_team,
                    "trailing_team":trailing_team,
                })
            except Exception:
                continue

        return matches

    except Exception as e:
        logger.error(f"Fetch error: {e}")
        return []


def send_telegram(message: str, silent: bool = False):
    """Send a Telegram message."""
    try:
        requests.post(
            TG_API,
            json={
                "chat_id":              TG_CHAT_ID,
                "text":                 message,
                "parse_mode":           "HTML",
                "disable_notification": silent,
            },
            timeout=8
        )
    except Exception as e:
        logger.warning(f"Telegram failed: {e}")


def build_alert(match: dict) -> str:
    """Build a clean Telegram alert message."""
    score    = f"{match['home_score']}-{match['away_score']}"
    minute   = match['minute']
    lead     = match['goal_diff']

    # Risk assessment
    if minute >= 80 and lead >= 3:
        risk = "🟢 VERY SAFE"
    elif minute >= 75 and lead >= 2:
        risk = "🟡 FAIRLY SAFE"
    elif minute >= 65 and lead >= 3:
        risk = "🟡 FAIRLY SAFE"
    else:
        risk = "🟠 MODERATE RISK"

    # Time remaining estimate
    time_left = max(0, 90 - minute)

    return (
        f"⚽ <b>BETTING OPPORTUNITY</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🏆 {match['league']} ({match['country']})\n"
        f"📋 {match['home']} <b>{score}</b> {match['away']}\n"
        f"⏱ Minute: <b>{minute}'</b>  (~{time_left} mins left)\n"
        f"🎯 Bet on: <b>{match['leading_team']}</b> to win\n"
        f"📊 Goal lead: <b>+{lead}</b>\n"
        f"{risk}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👉 Open SportyBet → Live Betting → Find this match → Bet on <b>{match['leading_team']}</b>\n"
        f"🕐 {datetime.now().strftime('%H:%M:%S')}"
    )


def scan():
    """One scan cycle."""
    matches = fetch_live_matches()

    if not matches:
        logger.info("No live matches found or API error")
        return

    # Filter opportunities
    opportunities = [
        m for m in matches
        if m["minute"] >= MIN_MINUTE
        and m["goal_diff"] >= MIN_GOAL_LEAD
    ]

    logger.info(f"Scanned {len(matches)} live matches — {len(opportunities)} opportunities")

    for match in opportunities:
        fid          = match["fixture_id"]
        minute_key   = (match["minute"] // 10) * 10  # Re-alert every 10 mins

        # Skip if already alerted in this minute bracket
        if alerted.get(fid) == minute_key:
            continue

        alerted[fid] = minute_key

        alert_msg = build_alert(match)
        send_telegram(alert_msg)

        logger.info(
            f"ALERT SENT: {match['home']} {match['home_score']}-{match['away_score']} "
            f"{match['away']} @ {match['minute']}' — {match['leading_team']} leading"
        )

    # Clean up old fixture IDs from memory (keep last 200)
    if len(alerted) > 200:
        oldest_keys = list(alerted.keys())[:100]
        for k in oldest_keys:
            del alerted[k]


def startup_message():
    """Send a startup confirmation to Telegram."""
    send_telegram(
        f"🤖 <b>BetBot Scanner STARTED</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"⏱ Scanning from: <b>{MIN_MINUTE}th minute</b>\n"
        f"⚽ Min goal lead: <b>{MIN_GOAL_LEAD} goals</b>\n"
        f"🔄 Scan interval: <b>every {SCAN_INTERVAL}s</b>\n"
        f"📡 Watching ALL live matches globally\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"You'll be alerted the moment an opportunity appears.\n"
        f"Press Ctrl+C to stop."
    )


def main():
    print("=" * 50)
    print("  BetBot Scanner — Live Opportunity Detector")
    print("=" * 50)
    print(f"  Scanning from: {MIN_MINUTE}th minute")
    print(f"  Min goal lead: {MIN_GOAL_LEAD} goals")
    print(f"  Scan interval: every {SCAN_INTERVAL} seconds")
    print(f"  Telegram alerts: ON")
    print("=" * 50)
    print("  Press Ctrl+C to stop\n")

    # Validate config
    if API_KEY == "YOUR_API_FOOTBALL_KEY_HERE":
        print("ERROR: Please set your API_KEY in scanner.py")
        return

    if TG_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN":
        print("ERROR: Please set your TG_TOKEN in scanner.py")
        return

    startup_message()
    print("Startup message sent to Telegram!\n")

    scan_count = 0
    while True:
        try:
            scan_count += 1
            print(f"[Scan #{scan_count}] {datetime.now().strftime('%H:%M:%S')} — scanning...")
            scan()
            print(f"  Next scan in {SCAN_INTERVAL} seconds...\n")
            time.sleep(SCAN_INTERVAL)

        except KeyboardInterrupt:
            print("\nScanner stopped.")
            send_telegram("⏹ BetBot Scanner stopped.")
            break
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            time.sleep(10)


if __name__ == "__main__":
    main()
