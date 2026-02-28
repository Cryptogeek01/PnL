"""
bot.py — Core betting logic (v2)
New in this version:
  1. Compound reinvestment — stake scales automatically with balance
  2. Loss recovery mode   — tighter filters after a loss
  3. Daily loss limit     — hard stop if daily losses exceed threshold
  4. Odds suspension detector — skip bets when odds disappear mid-scan
  5. Analytics integration — every resolved bet saved to disk
  6. Telegram alerts       — phone notifications for all key events
"""

import asyncio
import logging
import time
from datetime import datetime, date
from scores import get_live_matches, filter_opportunities
from sportybet import SportyBetBot
from betking import BetKingBot
from telegram_alerts import TelegramAlerter
from analytics import Analytics

logger = logging.getLogger(__name__)


class BettingBot:
    def __init__(self, config, broadcast_fn=None):
        self.config    = config
        self.broadcast = broadcast_fn or self._noop_broadcast

        self.sportybet = SportyBetBot(config.SPORTYBET_USERNAME, config.SPORTYBET_PASSWORD, config.HEADLESS)
        self.betking   = BetKingBot(config.BETKING_USERNAME,     config.BETKING_PASSWORD,   config.HEADLESS)
        self.telegram  = TelegramAlerter(config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID, config.TELEGRAM_ENABLED)
        self.analytics = Analytics(config.ANALYTICS_FILE)

        self.running = False
        self.paused  = False

        self.stake         = config.DEFAULT_STAKE
        self.min_minute    = config.MIN_MINUTE
        self.min_goal_lead = config.MIN_GOAL_LEAD
        self.min_odds      = config.MIN_ODDS
        self.auto_bet      = config.AUTO_BET

        self.bets                = []
        self.live_matches        = []
        self.opportunities       = []
        self.session_start       = None
        self.bets_already_placed = set()

        self.wins     = 0
        self.losses   = 0
        self.pending  = 0
        self.pnl      = 0.0
        self.win_pnl  = 0.0
        self.loss_pnl = 0.0

        # Loss recovery
        self.in_recovery_mode        = False
        self.recovery_bets_remaining = 0

        # Suspension detection — stores {fixture_id: goal_diff} from last scan
        self._prev_scan_opps: dict = {}

        # Daily loss limit
        self._daily_limit_triggered = False
        self._daily_limit_date      = date.today()

    # ── INIT ──────────────────────────────────────────

    async def initialize(self):
        await self.broadcast({"type": "log", "msg": "Initializing browsers...", "color": "blue"})

        results = await asyncio.gather(
            self.sportybet.start(),
            self.betking.start(),
            return_exceptions=True
        )

        sporty_ok  = not isinstance(results[0], Exception) and self.sportybet.logged_in
        betking_ok = not isinstance(results[1], Exception) and self.betking.logged_in

        if sporty_ok:
            await self.broadcast({"type": "log", "msg": f"SportyBet logged in ✓  Balance: N{self.sportybet.balance:.2f}", "color": "green"})
        else:
            await self.broadcast({"type": "log", "msg": "SportyBet login FAILED — check credentials in config.py", "color": "red"})

        if betking_ok:
            await self.broadcast({"type": "log", "msg": f"BetKing logged in ✓  Balance: N{self.betking.balance:.2f}", "color": "green"})
        else:
            await self.broadcast({"type": "log", "msg": "BetKing login FAILED — check credentials in config.py", "color": "red"})

        if sporty_ok or betking_ok:
            self.telegram.bot_started(self.sportybet.balance, self.betking.balance)
            await self.push_analytics()

        await self.push_balances()
        return sporty_ok or betking_ok

    # ── LIFECYCLE ─────────────────────────────────────

    async def start(self):
        if self.running and not self.paused:
            return

        if date.today() != self._daily_limit_date:
            self._daily_limit_triggered = False
            self._daily_limit_date = date.today()
            await self.broadcast({"type": "log", "msg": "New day — daily loss limit reset.", "color": "blue"})

        if self._daily_limit_triggered:
            await self.broadcast({"type": "log", "msg": "Daily loss limit was hit today. Bot will resume tomorrow.", "color": "red"})
            return

        self.running = True
        self.paused  = False
        if not self.session_start:
            self.session_start = datetime.utcnow()

        await self.broadcast({"type": "status", "status": "running"})
        await self.broadcast({"type": "log",    "msg":    "Bot started. Scanning live matches...", "color": "green"})

        while self.running and not self.paused:
            await self.scan_tick()
            await asyncio.sleep(self.config.SCAN_INTERVAL)

    async def pause(self, reason="Manual pause"):
        self.paused = True
        await self.broadcast({"type": "status", "status": "paused"})
        await self.broadcast({"type": "log",    "msg":    f"Bot paused — {reason}", "color": "yellow"})
        self.telegram.bot_paused(reason)

    async def stop(self):
        self.running = False
        self.paused  = False
        await self.broadcast({"type": "status", "status": "stopped"})
        await self.broadcast({"type": "log",    "msg":    "Bot stopped.", "color": "red"})
        self.telegram.bot_stopped(self.pnl, self.wins, self.losses)
        await self.sportybet.stop()
        await self.betking.stop()

    async def resume(self):
        self.paused  = False
        self.running = True
        await self.broadcast({"type": "status", "status": "running"})
        await self.broadcast({"type": "log",    "msg":    "Bot resumed.", "color": "green"})
        asyncio.create_task(self.start())

    # ── SCAN TICK ─────────────────────────────────────

    async def scan_tick(self):
        try:
            await self.sportybet.fetch_balance()
            await self.betking.fetch_balance()
            await self.push_balances()
            await self._recalculate_stake()

            self.live_matches = get_live_matches(self.config.API_FOOTBALL_KEY)

            active_minute    = self.config.LOSS_RECOVERY_MIN_MINUTE    if self.in_recovery_mode and self.config.LOSS_RECOVERY_ENABLED else self.min_minute
            active_goal_lead = self.config.LOSS_RECOVERY_MIN_GOAL_LEAD if self.in_recovery_mode and self.config.LOSS_RECOVERY_ENABLED else self.min_goal_lead

            self.opportunities = filter_opportunities(self.live_matches, active_minute, active_goal_lead)

            # Suspension check
            suspended = self._detect_suspensions()
            if suspended:
                for fid in suspended:
                    await self.broadcast({"type": "log", "msg": f"Odds suspended on fixture #{fid} — bet skipped", "color": "yellow"})
                    self.telegram.odds_suspended(f"Fixture #{fid}", "Bookmaker")
                self.opportunities = [o for o in self.opportunities if o["fixture_id"] not in suspended]

            self._update_odds_snapshot()

            await self.broadcast({
                "type":          "matches",
                "matches":       self.live_matches,
                "opportunities": self.opportunities,
                "live_count":    len(self.live_matches),
                "opp_count":     len(self.opportunities),
                "recovery_mode": self.in_recovery_mode,
            })

            if self.opportunities:
                best = max(self.opportunities, key=lambda m: m["goal_diff"] * 10 + m["minute"])
                mode_prefix = "[RECOVERY] " if self.in_recovery_mode else ""
                await self.broadcast({
                    "type":  "log",
                    "msg":   f"{mode_prefix}{len(self.opportunities)} opp(s) — best: {best['home_team']} {best['home_score']}-{best['away_score']} {best['away_team']} @ {best['minute']}'",
                    "color": "green"
                })
                self.telegram.opportunity_found(len(self.opportunities), f"{best['home_team']} vs {best['away_team']}", best["minute"], best["goal_diff"])

            if self.auto_bet:
                for match in self.opportunities:
                    fkey = f"{match['fixture_id']}_{match['minute'] // 5}"
                    if fkey not in self.bets_already_placed:
                        await self.execute_bet(match)
                        self.bets_already_placed.add(fkey)

        except Exception as e:
            logger.error(f"Scan tick error: {e}")
            await self.broadcast({"type": "log", "msg": f"Scan error: {str(e)}", "color": "red"})

    # ── COMPOUND STAKE ────────────────────────────────

    async def _recalculate_stake(self):
        if not self.config.COMPOUND_ENABLED:
            return
        total = self.sportybet.balance + self.betking.balance
        if total <= 0:
            return
        raw       = total * self.config.COMPOUND_PERCENT / 100
        rounded   = round(raw / 50) * 50
        new_stake = max(self.config.MIN_STAKE, min(rounded, self.config.MAX_STAKE))
        if new_stake != self.stake:
            old = self.stake
            self.stake = new_stake
            await self.broadcast({"type": "log",           "msg":   f"Stake auto-updated: N{old:,.0f} -> N{new_stake:,.0f}  (balance: N{total:,.2f})", "color": "blue"})
            await self.broadcast({"type": "stake_updated", "stake": self.stake})
            self.telegram.compound_stake_updated(old, new_stake, total)

    # ── SUSPENSION DETECTION ──────────────────────────

    def _detect_suspensions(self) -> set:
        if not self.config.SUSPENSION_DETECTOR_ENABLED:
            return set()
        current_ids = {m["fixture_id"] for m in self.live_matches}
        return set(self._prev_scan_opps.keys()) - current_ids

    def _update_odds_snapshot(self):
        self._prev_scan_opps = {m["fixture_id"]: m.get("goal_diff", 0) for m in self.opportunities}

    # ── EXECUTE BET ───────────────────────────────────

    async def execute_bet(self, match: dict):
        home         = match["home_team"]
        away         = match["away_team"]
        leading_side = match["leading_side"]
        leading_team = match["leading_team"]
        score        = f"{match['home_score']}-{match['away_score']}"

        await self.broadcast({"type": "log", "msg": f"Checking odds: {home} {score} {away} @ {match['minute']}'", "color": "blue"})

        tasks      = []
        bookmakers = []

        if self.sportybet.logged_in and self.sportybet.balance >= self.stake:
            tasks.append(self.sportybet.get_live_odds(home, away, leading_side))
            bookmakers.append("sportybet")

        if self.betking.logged_in and self.betking.balance >= self.stake:
            tasks.append(self.betking.get_live_odds(home, away, leading_side))
            bookmakers.append("betking")

        if not tasks:
            total = self.sportybet.balance + self.betking.balance
            await self.broadcast({"type": "log", "msg": f"Insufficient balance — total: N{total:.2f}, stake: N{self.stake:.0f}", "color": "red"})
            self.telegram.low_balance_warning(total, self.stake)
            return

        odds_results = await asyncio.gather(*tasks, return_exceptions=True)

        best_bm   = None
        best_odds = 0.0

        for i, res in enumerate(odds_results):
            if isinstance(res, Exception) or res is None:
                continue
            if res["odds"] > best_odds and res["odds"] >= self.min_odds:
                best_odds = res["odds"]
                best_bm   = bookmakers[i]

        if not best_bm:
            await self.broadcast({"type": "log", "msg": f"No valid odds >= {self.min_odds} for {home} vs {away}", "color": "yellow"})
            return

        await self.broadcast({"type": "log", "msg": f"Placing N{self.stake:,.0f} @ {best_odds:.3f} on {leading_team} ({best_bm.title()})", "color": "green"})

        result = await (self.sportybet if best_bm == "sportybet" else self.betking).place_bet(home, away, leading_side, self.stake, self.min_odds)

        bet_record = {
            "id":           int(time.time() * 1000),
            "time":         datetime.now().strftime("%H:%M:%S"),
            "date":         date.today().isoformat(),
            "home_team":    home,
            "away_team":    away,
            "match":        f"{home} vs {away}",
            "score":        score,
            "minute":       match["minute"],
            "goal_diff":    match["goal_diff"],
            "league":       match["league"],
            "bookmaker":    result["bookmaker"],
            "odds":         result["odds"] or best_odds,
            "stake":        self.stake,
            "leading_team": leading_team,
            "status":       "placed" if result["success"] else "failed",
            "pnl":          None,
            "error":        result.get("error"),
            "fixture_id":   match["fixture_id"],
            "recovery_bet": self.in_recovery_mode,
        }

        if result["success"]:
            self.pending += 1
            self.bets.insert(0, bet_record)
            await self.broadcast({"type": "bet_placed", "bet": bet_record})
            await self.broadcast({"type": "log", "msg": f"BET PLACED: {home} vs {away} @ {result['odds']:.3f} | N{self.stake:,.0f} | {result['bookmaker']}", "color": "green"})
            self.telegram.bet_placed(home, away, score, match["minute"], result["bookmaker"], result["odds"], self.stake, leading_team)
        else:
            await self.broadcast({"type": "log", "msg": f"Bet failed: {result.get('error', 'Unknown')}", "color": "red"})

        await self.push_balances()

    # ── MANUAL BET ────────────────────────────────────

    async def manual_bet(self, fixture_id: int):
        match = next((m for m in self.opportunities if m["fixture_id"] == fixture_id), None)
        if not match:
            await self.broadcast({"type": "log", "msg": "Match no longer available or not qualifying", "color": "yellow"})
            return
        await self.execute_bet(match)

    # ── RECORD RESULT ─────────────────────────────────

    async def record_result(self, bet_id: int, won: bool):
        bet = next((b for b in self.bets if b["id"] == bet_id), None)
        if not bet:
            return

        stake = bet["stake"]
        odds  = bet["odds"]

        if won:
            profit         = round((stake * odds) - stake, 2)
            bet["status"]  = "win"
            bet["pnl"]     = profit
            self.wins     += 1
            self.pnl      += profit
            self.win_pnl  += profit

            if bet["bookmaker"] == "SportyBet":
                self.sportybet.balance += stake * odds
            else:
                self.betking.balance += stake * odds

            await self.broadcast({"type": "log", "msg": f"WIN: {bet['match']} | +N{profit:.2f}", "color": "green"})
            self.telegram.bet_won(bet["match"], odds, stake, profit, self.pnl)

            if self.in_recovery_mode and self.config.LOSS_RECOVERY_ENABLED:
                self.recovery_bets_remaining -= 1
                if self.recovery_bets_remaining <= 0:
                    self.in_recovery_mode = False
                    await self.broadcast({"type": "log",           "msg":    "Recovery complete — back to normal filters", "color": "green"})
                    await self.broadcast({"type": "recovery_mode", "active": False})
                else:
                    await self.broadcast({"type": "log", "msg": f"Recovery mode: {self.recovery_bets_remaining} more win(s) needed", "color": "yellow"})

        else:
            bet["status"]   = "loss"
            bet["pnl"]      = -stake
            self.losses    += 1
            self.pnl       -= stake
            self.loss_pnl  += stake

            await self.broadcast({"type": "log", "msg": f"LOSS: {bet['match']} | -N{stake:.2f}", "color": "red"})
            self.telegram.bet_lost(bet["match"], stake, self.pnl)

            # Activate loss recovery
            if self.config.LOSS_RECOVERY_ENABLED and not self.in_recovery_mode:
                self.in_recovery_mode        = True
                self.recovery_bets_remaining = self.config.LOSS_RECOVERY_BETS
                await self.broadcast({"type": "log",           "msg":    f"Loss recovery mode ON — tighter filters for next {self.config.LOSS_RECOVERY_BETS} bets", "color": "yellow"})
                await self.broadcast({"type": "recovery_mode", "active": True})
                self.telegram.loss_recovery_activated(self.config.LOSS_RECOVERY_BETS)

            # Daily loss limit
            if self.config.DAILY_LOSS_LIMIT_ENABLED:
                daily_lost = self.analytics.today_losses() + stake
                if daily_lost >= self.config.DAILY_LOSS_LIMIT:
                    self._daily_limit_triggered = True
                    await self.pause(reason="Daily loss limit reached")
                    await self.broadcast({"type": "log", "msg": f"DAILY LIMIT: N{daily_lost:.2f} lost today (limit: N{self.config.DAILY_LOSS_LIMIT:.2f}). Stopping for the day.", "color": "red"})
                    self.telegram.daily_limit_hit(daily_lost, self.config.DAILY_LOSS_LIMIT)

        self.pending = max(0, self.pending - 1)
        self.analytics.record_bet(bet)

        if self.config.STOP_ON_LOW_BALANCE:
            total = self.sportybet.balance + self.betking.balance
            if total < self.stake:
                await self.pause(reason="Balance too low for next bet")
                self.telegram.low_balance_warning(total, self.stake)

        await self.push_stats()
        await self.push_balances()
        await self.push_analytics()

    # ── PUSH METHODS ──────────────────────────────────

    async def push_balances(self):
        total = self.sportybet.balance + self.betking.balance
        await self.broadcast({"type": "balances", "sportybet": round(self.sportybet.balance, 2), "betking": round(self.betking.balance, 2), "total": round(total, 2), "pnl": round(self.pnl, 2)})

    async def push_stats(self):
        total_bets = self.wins + self.losses
        win_rate   = round((self.wins / total_bets) * 100, 1) if total_bets > 0 else None
        await self.broadcast({"type": "stats", "wins": self.wins, "losses": self.losses, "pending": self.pending, "win_rate": win_rate, "pnl": round(self.pnl, 2), "win_pnl": round(self.win_pnl, 2), "loss_pnl": round(self.loss_pnl, 2), "total_bets": len(self.bets), "stake": self.stake, "recovery": self.in_recovery_mode})

    async def push_analytics(self):
        data = self.analytics.get_dashboard_data()
        await self.broadcast({"type": "analytics", "data": data})

    # ── SETTINGS ──────────────────────────────────────

    def update_settings(self, settings: dict):
        if "stake"            in settings: self.stake             = max(self.config.MIN_STAKE, float(settings["stake"]))
        if "min_minute"       in settings: self.min_minute        = int(settings["min_minute"])
        if "min_goal_lead"    in settings: self.min_goal_lead     = int(settings["min_goal_lead"])
        if "min_odds"         in settings: self.min_odds          = float(settings["min_odds"])
        if "auto_bet"         in settings: self.auto_bet          = bool(settings["auto_bet"])
        if "compound_enabled" in settings: self.config.COMPOUND_ENABLED  = bool(settings["compound_enabled"])
        if "compound_percent" in settings: self.config.COMPOUND_PERCENT  = max(1, min(25, int(settings["compound_percent"])))

    async def _noop_broadcast(self, msg):
        pass
