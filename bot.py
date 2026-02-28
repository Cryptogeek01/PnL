"""
bot.py — Core betting logic
Orchestrates score scanning, opportunity detection, and bet placement.
"""

import asyncio
import logging
import time
from datetime import datetime
from scores import get_live_matches, filter_opportunities
from sportybet import SportyBetBot
from betking import BetKingBot

logger = logging.getLogger(__name__)


class BettingBot:
    def __init__(self, config, broadcast_fn=None):
        """
        config: the config module
        broadcast_fn: async function to send updates to dashboard (WebSocket)
        """
        self.config = config
        self.broadcast = broadcast_fn or self._noop_broadcast

        self.sportybet = SportyBetBot(config.SPORTYBET_USERNAME, config.SPORTYBET_PASSWORD, config.HEADLESS)
        self.betking = BetKingBot(config.BETKING_USERNAME, config.BETKING_PASSWORD, config.HEADLESS)

        self.running = False
        self.paused = False

        # Runtime settings (adjustable from dashboard)
        self.stake = config.DEFAULT_STAKE
        self.min_minute = config.MIN_MINUTE
        self.min_goal_lead = config.MIN_GOAL_LEAD
        self.min_odds = config.MIN_ODDS
        self.auto_bet = config.AUTO_BET

        # State
        self.bets = []
        self.live_matches = []
        self.opportunities = []
        self.session_start = None
        self.bets_already_placed = set()  # Track fixture IDs to avoid double betting

        # Stats
        self.wins = 0
        self.losses = 0
        self.pending = 0
        self.pnl = 0.0
        self.win_pnl = 0.0
        self.loss_pnl = 0.0

    async def initialize(self):
        """Start browsers and log into bookmakers."""
        await self.broadcast({"type": "log", "msg": "Initializing browsers...", "color": "blue"})

        # Start both bots concurrently
        results = await asyncio.gather(
            self.sportybet.start(),
            self.betking.start(),
            return_exceptions=True
        )

        sporty_ok = not isinstance(results[0], Exception) and self.sportybet.logged_in
        betking_ok = not isinstance(results[1], Exception) and self.betking.logged_in

        if not sporty_ok:
            await self.broadcast({"type": "log", "msg": "SportyBet login FAILED — check credentials", "color": "red"})
        else:
            await self.broadcast({"type": "log", "msg": f"SportyBet logged in ✓ Balance: ₦{self.sportybet.balance:.2f}", "color": "green"})

        if not betking_ok:
            await self.broadcast({"type": "log", "msg": "BetKing login FAILED — check credentials", "color": "red"})
        else:
            await self.broadcast({"type": "log", "msg": f"BetKing logged in ✓ Balance: ₦{self.betking.balance:.2f}", "color": "green"})

        await self.push_balances()
        return sporty_ok or betking_ok

    async def start(self):
        """Start the scanning and betting loop."""
        if self.running and not self.paused:
            return

        self.running = True
        self.paused = False

        if not self.session_start:
            self.session_start = datetime.utcnow()

        await self.broadcast({"type": "status", "status": "running"})
        await self.broadcast({"type": "log", "msg": "Bot started. Scanning live matches...", "color": "green"})

        while self.running and not self.paused:
            await self.scan_tick()
            await asyncio.sleep(self.config.SCAN_INTERVAL)

    async def pause(self):
        """Pause scanning."""
        self.paused = True
        await self.broadcast({"type": "status", "status": "paused"})
        await self.broadcast({"type": "log", "msg": "Bot paused.", "color": "yellow"})

    async def stop(self):
        """Stop bot completely."""
        self.running = False
        self.paused = False
        await self.broadcast({"type": "status", "status": "stopped"})
        await self.broadcast({"type": "log", "msg": "Bot stopped.", "color": "red"})
        await self.sportybet.stop()
        await self.betking.stop()

    async def resume(self):
        """Resume from pause."""
        self.paused = False
        self.running = True
        await self.broadcast({"type": "status", "status": "running"})
        await self.broadcast({"type": "log", "msg": "Bot resumed.", "color": "green"})
        asyncio.create_task(self.start())

    async def scan_tick(self):
        """One scan cycle: fetch matches, find opportunities, place bets if auto."""
        try:
            # Refresh balances
            await self.sportybet.fetch_balance()
            await self.betking.fetch_balance()
            await self.push_balances()

            # Get live matches
            self.live_matches = get_live_matches(self.config.API_FOOTBALL_KEY)
            self.opportunities = filter_opportunities(self.live_matches, self.min_minute, self.min_goal_lead)

            await self.broadcast({
                "type": "matches",
                "matches": self.live_matches,
                "opportunities": self.opportunities,
                "live_count": len(self.live_matches),
                "opp_count": len(self.opportunities),
            })

            if self.opportunities:
                await self.broadcast({
                    "type": "log",
                    "msg": f"{len(self.opportunities)} betting opportunity/ies found across {len(self.live_matches)} live matches",
                    "color": "green"
                })

            # Auto-bet mode
            if self.auto_bet:
                for match in self.opportunities:
                    fixture_key = f"{match['fixture_id']}_{match['minute']//5}"  # Prevent re-betting same match every minute
                    if fixture_key not in self.bets_already_placed:
                        await self.execute_bet(match)
                        self.bets_already_placed.add(fixture_key)

        except Exception as e:
            logger.error(f"Scan tick error: {e}")
            await self.broadcast({"type": "log", "msg": f"Scan error: {str(e)}", "color": "red"})

    async def execute_bet(self, match: dict):
        """
        Place a bet on the best available odds across all active bookmakers.
        """
        home = match["home_team"]
        away = match["away_team"]
        leading_side = match["leading_side"]
        leading_team = match["leading_team"]
        score = f"{match['home_score']}-{match['away_score']}"

        await self.broadcast({
            "type": "log",
            "msg": f"Checking odds for {home} vs {away} ({score}) @ {match['minute']}'",
            "color": "blue"
        })

        # Check both bookmakers concurrently
        tasks = []
        bookmakers = []

        if self.sportybet.logged_in and self.sportybet.balance >= self.stake:
            tasks.append(self.sportybet.get_live_odds(home, away, leading_side))
            bookmakers.append("sportybet")

        if self.betking.logged_in and self.betking.balance >= self.stake:
            tasks.append(self.betking.get_live_odds(home, away, leading_side))
            bookmakers.append("betking")

        if not tasks:
            await self.broadcast({"type": "log", "msg": "No bookmakers available or insufficient balance", "color": "red"})
            return

        odds_results = await asyncio.gather(*tasks, return_exceptions=True)

        # Find best odds
        best_bm = None
        best_odds = 0

        for i, result in enumerate(odds_results):
            if isinstance(result, Exception) or result is None:
                continue
            if result["odds"] > best_odds and result["odds"] >= self.min_odds:
                best_odds = result["odds"]
                best_bm = bookmakers[i]

        if not best_bm:
            await self.broadcast({
                "type": "log",
                "msg": f"No valid odds found for {home} vs {away} (min: {self.min_odds})",
                "color": "yellow"
            })
            return

        await self.broadcast({
            "type": "log",
            "msg": f"Best odds: {best_odds:.3f} on {best_bm.title()} — placing ₦{self.stake} bet on {leading_team}",
            "color": "green"
        })

        # Place bet on best bookmaker
        if best_bm == "sportybet":
            result = await self.sportybet.place_bet(home, away, leading_side, self.stake, self.min_odds)
        else:
            result = await self.betking.place_bet(home, away, leading_side, self.stake, self.min_odds)

        # Record bet
        bet_record = {
            "id": int(time.time() * 1000),
            "time": datetime.now().strftime("%H:%M:%S"),
            "home_team": home,
            "away_team": away,
            "match": f"{home} vs {away}",
            "score": score,
            "minute": match["minute"],
            "league": match["league"],
            "bookmaker": result["bookmaker"],
            "odds": result["odds"] or best_odds,
            "stake": self.stake,
            "leading_team": leading_team,
            "status": "placed" if result["success"] else "failed",
            "pnl": None,
            "error": result.get("error"),
            "fixture_id": match["fixture_id"],
        }

        if result["success"]:
            self.pending += 1
            self.bets.insert(0, bet_record)
            await self.broadcast({"type": "bet_placed", "bet": bet_record})
            await self.broadcast({
                "type": "log",
                "msg": f"✓ Bet placed: {home} vs {away} @ {result['odds']:.3f} | ₦{self.stake} on {result['bookmaker']}",
                "color": "green"
            })
        else:
            await self.broadcast({
                "type": "log",
                "msg": f"✗ Bet failed: {result.get('error', 'Unknown error')}",
                "color": "red"
            })

        await self.push_balances()

    async def manual_bet(self, fixture_id: int):
        """
        Called from dashboard when user manually clicks a match to bet on.
        """
        match = next((m for m in self.opportunities if m["fixture_id"] == fixture_id), None)
        if not match:
            await self.broadcast({"type": "log", "msg": "Match no longer available or not an opportunity", "color": "yellow"})
            return
        await self.execute_bet(match)

    async def record_result(self, bet_id: int, won: bool):
        """
        Update a bet's result (called manually or via future result-checking module).
        """
        bet = next((b for b in self.bets if b["id"] == bet_id), None)
        if not bet:
            return

        stake = bet["stake"]
        odds = bet["odds"]

        if won:
            profit = round((stake * odds) - stake, 2)
            bet["status"] = "win"
            bet["pnl"] = profit
            self.wins += 1
            self.pnl += profit
            self.win_pnl += profit
            # Return winnings to bookmaker balance
            if bet["bookmaker"] == "SportyBet":
                self.sportybet.balance += stake * odds
            else:
                self.betking.balance += stake * odds
            await self.broadcast({"type": "log", "msg": f"✓ WIN: {bet['match']} | +₦{profit:.2f}", "color": "green"})
        else:
            bet["status"] = "loss"
            bet["pnl"] = -stake
            self.losses += 1
            self.pnl -= stake
            self.loss_pnl += stake
            await self.broadcast({"type": "log", "msg": f"✗ LOSS: {bet['match']} | -₦{stake:.2f}", "color": "red"})

        self.pending = max(0, self.pending - 1)

        # Stop-loss check
        if self.config.STOP_ON_LOW_BALANCE:
            total_bal = self.sportybet.balance + self.betking.balance
            if total_bal < self.stake:
                await self.pause()
                await self.broadcast({"type": "log", "msg": "⚠ STOP-LOSS: Balance too low to continue. Bot paused.", "color": "red"})

        await self.push_stats()
        await self.push_balances()

    async def push_balances(self):
        """Send balance update to dashboard."""
        total = self.sportybet.balance + self.betking.balance
        await self.broadcast({
            "type": "balances",
            "sportybet": round(self.sportybet.balance, 2),
            "betking": round(self.betking.balance, 2),
            "total": round(total, 2),
            "pnl": round(self.pnl, 2),
        })

    async def push_stats(self):
        """Send stats update to dashboard."""
        total_bets = self.wins + self.losses
        win_rate = round((self.wins / total_bets) * 100, 1) if total_bets > 0 else None
        await self.broadcast({
            "type": "stats",
            "wins": self.wins,
            "losses": self.losses,
            "pending": self.pending,
            "win_rate": win_rate,
            "pnl": round(self.pnl, 2),
            "win_pnl": round(self.win_pnl, 2),
            "loss_pnl": round(self.loss_pnl, 2),
            "total_bets": len(self.bets),
        })

    def update_settings(self, settings: dict):
        """Update bot settings from dashboard."""
        if "stake" in settings:
            self.stake = max(self.config.MIN_STAKE, float(settings["stake"]))
        if "min_minute" in settings:
            self.min_minute = int(settings["min_minute"])
        if "min_goal_lead" in settings:
            self.min_goal_lead = int(settings["min_goal_lead"])
        if "min_odds" in settings:
            self.min_odds = float(settings["min_odds"])
        if "auto_bet" in settings:
            self.auto_bet = bool(settings["auto_bet"])

    async def _noop_broadcast(self, msg):
        pass
