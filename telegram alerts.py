"""
telegram_alerts.py — Telegram notification system
Sends real-time alerts to your phone for every key bot event.

SETUP:
1. Open Telegram, search @BotFather
2. Send /newbot and follow prompts → copy the token into config.py
3. Send any message to your new bot, then visit:
   https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates
4. Copy the chat "id" value → paste as TELEGRAM_CHAT_ID in config.py
5. Set TELEGRAM_ENABLED = True in config.py
"""

import requests
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


class TelegramAlerter:
    def __init__(self, token: str, chat_id: str, enabled: bool = False):
        self.token = token
        self.chat_id = chat_id
        self.enabled = enabled and bool(token) and token != "YOUR_TELEGRAM_BOT_TOKEN"

        if enabled and not self.enabled:
            logger.warning("Telegram enabled in config but token/chat_id not set.")

    def send(self, message: str, silent: bool = False):
        """Send a message to Telegram. Non-blocking — fails silently."""
        if not self.enabled:
            return
        try:
            requests.post(
                TELEGRAM_API.format(token=self.token),
                json={
                    "chat_id": self.chat_id,
                    "text": message,
                    "parse_mode": "HTML",
                    "disable_notification": silent,
                },
                timeout=8
            )
        except Exception as e:
            logger.warning(f"Telegram send failed: {e}")

    # ── Typed alert methods ──

    def bot_started(self, sporty_bal: float, betking_bal: float):
        total = sporty_bal + betking_bal
        self.send(
            f"🤖 <b>BetBot Pro STARTED</b>\n"
            f"SportyBet: ₦{sporty_bal:,.2f}\n"
            f"BetKing:   ₦{betking_bal:,.2f}\n"
            f"Total:     ₦{total:,.2f}"
        )

    def bot_paused(self, reason: str = ""):
        self.send(f"⏸ <b>BetBot PAUSED</b>\n{reason}")

    def bot_stopped(self, pnl: float, wins: int, losses: int):
        emoji = "📈" if pnl >= 0 else "📉"
        self.send(
            f"■ <b>BetBot STOPPED</b>\n"
            f"{emoji} Session P&L: {'+'if pnl>=0 else ''}₦{pnl:,.2f}\n"
            f"✅ Wins: {wins}   ❌ Losses: {losses}"
        )

    def bet_placed(self, home: str, away: str, score: str, minute: int,
                   bookmaker: str, odds: float, stake: float, leading_team: str):
        self.send(
            f"🎯 <b>BET PLACED</b>\n"
            f"{home} {score} {away}\n"
            f"⏱ {minute}'  |  Leading: <b>{leading_team}</b>\n"
            f"📊 Odds: {odds:.3f}  |  Stake: ₦{stake:,.0f}\n"
            f"📍 {bookmaker}"
        )

    def bet_won(self, match: str, odds: float, stake: float, profit: float, total_pnl: float):
        self.send(
            f"✅ <b>WIN</b>  +₦{profit:,.2f}\n"
            f"{match} @ {odds:.3f}\n"
            f"Stake: ₦{stake:,.0f}  |  Session P&L: {'+'if total_pnl>=0 else ''}₦{total_pnl:,.2f}"
        )

    def bet_lost(self, match: str, stake: float, total_pnl: float):
        self.send(
            f"❌ <b>LOSS</b>  -₦{stake:,.2f}\n"
            f"{match}\n"
            f"Session P&L: {'+'if total_pnl>=0 else ''}₦{total_pnl:,.2f}"
        )

    def opportunity_found(self, count: int, best_match: str, minute: int, goal_diff: int):
        self.send(
            f"🔍 <b>{count} opportunity{'s' if count>1 else ''} detected</b>\n"
            f"Best: {best_match}\n"
            f"⏱ {minute}'  |  Goal lead: {goal_diff}",
            silent=True   # Silent — informational only
        )

    def daily_limit_hit(self, lost: float, limit: float):
        self.send(
            f"🚨 <b>DAILY LOSS LIMIT HIT</b>\n"
            f"Lost today: ₦{lost:,.2f}\n"
            f"Limit: ₦{limit:,.2f}\n"
            f"Bot has been stopped for the day."
        )

    def loss_recovery_activated(self, bets_remaining: int):
        self.send(
            f"⚠️ <b>Loss Recovery Mode ON</b>\n"
            f"Filters tightened: 88+ min, 3+ goal lead\n"
            f"Recovers after {bets_remaining} successful bets",
            silent=True
        )

    def low_balance_warning(self, total_bal: float, stake: float):
        self.send(
            f"💸 <b>Low Balance Warning</b>\n"
            f"Balance: ₦{total_bal:,.2f}\n"
            f"Current stake: ₦{stake:,.2f}\n"
            f"Consider reducing stake or adding funds."
        )

    def odds_suspended(self, match: str, bookmaker: str):
        self.send(
            f"🚫 <b>Odds Suspended</b>\n"
            f"{match}\n"
            f"Bookmaker: {bookmaker}\n"
            f"Bet skipped — possible in-game incident.",
            silent=True
        )

    def compound_stake_updated(self, old_stake: float, new_stake: float, balance: float):
        self.send(
            f"📈 <b>Stake Auto-Updated</b>\n"
            f"₦{old_stake:,.0f} → ₦{new_stake:,.0f}\n"
            f"Balance: ₦{balance:,.2f}",
            silent=True
        )
