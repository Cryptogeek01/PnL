"""
analytics.py — Bet history persistence and performance analytics
Saves every bet to disk, survives restarts, powers the dashboard charts.
"""

import json
import os
import logging
from datetime import datetime, date
from collections import defaultdict

logger = logging.getLogger(__name__)


class Analytics:
    def __init__(self, filepath: str = "analytics.json"):
        self.filepath = filepath
        self.history = []   # All resolved bets ever
        self._load()

    # ── Persistence ──

    def _load(self):
        """Load bet history from disk."""
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r") as f:
                    self.history = json.load(f)
                logger.info(f"Analytics: loaded {len(self.history)} historical bets")
            except Exception as e:
                logger.warning(f"Analytics load failed: {e}")
                self.history = []

    def _save(self):
        """Save bet history to disk."""
        try:
            with open(self.filepath, "w") as f:
                json.dump(self.history, f, indent=2)
        except Exception as e:
            logger.warning(f"Analytics save failed: {e}")

    def record_bet(self, bet: dict):
        """
        Save a resolved bet to history.
        bet must have: id, time, match, league, bookmaker, odds, stake,
                       status ('win'|'loss'), pnl, minute, goal_diff (optional)
        """
        record = {
            "id":         bet.get("id"),
            "date":       date.today().isoformat(),
            "time":       bet.get("time"),
            "match":      bet.get("match"),
            "league":     bet.get("league", "Unknown"),
            "bookmaker":  bet.get("bookmaker"),
            "odds":       bet.get("odds"),
            "stake":      bet.get("stake"),
            "status":     bet.get("status"),
            "pnl":        bet.get("pnl"),
            "minute":     bet.get("minute"),
            "goal_diff":  bet.get("goal_diff", 0),
        }
        self.history.append(record)
        self._save()

    # ── Daily stats ──

    def today_losses(self) -> float:
        """Total losses recorded today."""
        today = date.today().isoformat()
        return sum(
            abs(b["pnl"]) for b in self.history
            if b["date"] == today and b["status"] == "loss" and b["pnl"] is not None
        )

    def today_summary(self) -> dict:
        today = date.today().isoformat()
        today_bets = [b for b in self.history if b["date"] == today]
        wins   = [b for b in today_bets if b["status"] == "win"]
        losses = [b for b in today_bets if b["status"] == "loss"]
        pnl    = sum(b["pnl"] for b in today_bets if b["pnl"] is not None)
        return {
            "date":      today,
            "total":     len(today_bets),
            "wins":      len(wins),
            "losses":    len(losses),
            "pnl":       round(pnl, 2),
            "win_rate":  round(len(wins)/len(today_bets)*100, 1) if today_bets else 0,
        }

    # ── Full analytics payload for dashboard ──

    def get_dashboard_data(self) -> dict:
        """
        Returns all analytics data needed for the dashboard charts.
        """
        if not self.history:
            return self._empty_payload()

        resolved = [b for b in self.history if b["pnl"] is not None]
        wins   = [b for b in resolved if b["status"] == "win"]
        losses = [b for b in resolved if b["status"] == "loss"]

        total_pnl    = sum(b["pnl"] for b in resolved)
        total_staked = sum(b["stake"] for b in resolved)
        roi          = round((total_pnl / total_staked) * 100, 2) if total_staked > 0 else 0
        win_rate     = round(len(wins) / len(resolved) * 100, 1) if resolved else 0
        avg_odds     = round(sum(b["odds"] for b in resolved) / len(resolved), 3) if resolved else 0

        return {
            "total_bets":   len(resolved),
            "wins":         len(wins),
            "losses":       len(losses),
            "total_pnl":    round(total_pnl, 2),
            "total_staked": round(total_staked, 2),
            "roi":          roi,
            "win_rate":     win_rate,
            "avg_odds":     avg_odds,

            # Daily P&L chart (last 14 days)
            "daily_pnl":    self._daily_pnl(14),

            # Win rate by league
            "league_stats": self._league_stats(),

            # Win rate by goal difference
            "goal_diff_stats": self._goal_diff_stats(),

            # Win rate by minute bracket
            "minute_stats": self._minute_stats(),

            # Win rate by bookmaker
            "bookmaker_stats": self._bookmaker_stats(),

            # P&L running total (last 50 bets)
            "pnl_curve":    self._pnl_curve(50),

            # Today
            "today":        self.today_summary(),
        }

    def _daily_pnl(self, days: int) -> list:
        """P&L grouped by date for the last N days."""
        by_date = defaultdict(float)
        for b in self.history:
            if b["pnl"] is not None:
                by_date[b["date"]] += b["pnl"]
        # Sort last N days
        sorted_days = sorted(by_date.items())[-days:]
        return [{"date": d, "pnl": round(p, 2)} for d, p in sorted_days]

    def _league_stats(self) -> list:
        """Win rate and P&L per league, sorted by total bets desc."""
        leagues = defaultdict(lambda: {"wins": 0, "total": 0, "pnl": 0.0})
        for b in self.history:
            if b["pnl"] is None:
                continue
            lg = b.get("league", "Unknown")
            leagues[lg]["total"] += 1
            leagues[lg]["pnl"]   += b["pnl"]
            if b["status"] == "win":
                leagues[lg]["wins"] += 1

        result = []
        for lg, s in leagues.items():
            result.append({
                "league":   lg,
                "total":    s["total"],
                "wins":     s["wins"],
                "win_rate": round(s["wins"] / s["total"] * 100, 1) if s["total"] else 0,
                "pnl":      round(s["pnl"], 2),
            })
        return sorted(result, key=lambda x: x["total"], reverse=True)[:10]

    def _goal_diff_stats(self) -> list:
        """Win rate by goal difference (1, 2, 3, 4+)."""
        buckets = defaultdict(lambda: {"wins": 0, "total": 0})
        for b in self.history:
            if b["pnl"] is None:
                continue
            gd = min(b.get("goal_diff", 1), 4)  # Cap at 4+
            label = f"{gd}+" if gd == 4 else str(gd)
            buckets[label]["total"] += 1
            if b["status"] == "win":
                buckets[label]["wins"] += 1

        return [
            {
                "goal_diff": k,
                "total":     v["total"],
                "win_rate":  round(v["wins"] / v["total"] * 100, 1) if v["total"] else 0,
            }
            for k, v in sorted(buckets.items())
        ]

    def _minute_stats(self) -> list:
        """Win rate by minute bracket: 80-84, 85-87, 88-89, 90+."""
        def bracket(m):
            if m < 85:   return "80-84'"
            if m < 88:   return "85-87'"
            if m < 90:   return "88-89'"
            return "90+'"

        buckets = defaultdict(lambda: {"wins": 0, "total": 0})
        for b in self.history:
            if b["pnl"] is None:
                continue
            bkt = bracket(b.get("minute", 85))
            buckets[bkt]["total"] += 1
            if b["status"] == "win":
                buckets[bkt]["wins"] += 1

        order = ["80-84'", "85-87'", "88-89'", "90+'"]
        return [
            {
                "minute":   k,
                "total":    buckets[k]["total"],
                "win_rate": round(buckets[k]["wins"] / buckets[k]["total"] * 100, 1) if buckets[k]["total"] else 0,
            }
            for k in order if k in buckets
        ]

    def _bookmaker_stats(self) -> list:
        """Win rate and P&L per bookmaker."""
        bms = defaultdict(lambda: {"wins": 0, "total": 0, "pnl": 0.0})
        for b in self.history:
            if b["pnl"] is None:
                continue
            bm = b.get("bookmaker", "Unknown")
            bms[bm]["total"] += 1
            bms[bm]["pnl"]   += b["pnl"]
            if b["status"] == "win":
                bms[bm]["wins"] += 1

        return [
            {
                "bookmaker": bm,
                "total":     s["total"],
                "win_rate":  round(s["wins"] / s["total"] * 100, 1) if s["total"] else 0,
                "pnl":       round(s["pnl"], 2),
            }
            for bm, s in bms.items()
        ]

    def _pnl_curve(self, n: int) -> list:
        """Running cumulative P&L for last N resolved bets."""
        resolved = [b for b in self.history if b["pnl"] is not None][-n:]
        cumulative = 0.0
        curve = []
        for i, b in enumerate(resolved):
            cumulative += b["pnl"]
            curve.append({"bet": i + 1, "pnl": round(cumulative, 2)})
        return curve

    def _empty_payload(self) -> dict:
        return {
            "total_bets": 0, "wins": 0, "losses": 0,
            "total_pnl": 0, "total_staked": 0, "roi": 0,
            "win_rate": 0, "avg_odds": 0,
            "daily_pnl": [], "league_stats": [],
            "goal_diff_stats": [], "minute_stats": [],
            "bookmaker_stats": [], "pnl_curve": [],
            "today": self.today_summary(),
        }
