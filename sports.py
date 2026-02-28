"""
scores.py — Live match data from API-Football
Fetches all currently live matches globally, returns structured data.
"""

import requests
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

API_BASE = "https://v3.football.api-sports.io"


def get_live_matches(api_key: str) -> list[dict]:
    """
    Fetch all live matches from API-Football.
    Returns a list of match dicts with score, minute, teams, and league.
    """
    if not api_key or api_key == "YOUR_API_FOOTBALL_KEY_HERE":
        logger.error("API-Football key not configured.")
        return []

    headers = {
        "x-apisports-key": api_key
    }

    try:
        resp = requests.get(
            f"{API_BASE}/fixtures",
            headers=headers,
            params={"live": "all"},
            timeout=15
        )
        resp.raise_for_status()
        data = resp.json()

        if data.get("errors"):
            logger.error(f"API-Football error: {data['errors']}")
            return []

        matches = []
        for fixture in data.get("response", []):
            try:
                match = parse_fixture(fixture)
                if match:
                    matches.append(match)
            except Exception as e:
                logger.warning(f"Failed to parse fixture: {e}")
                continue

        logger.info(f"Fetched {len(matches)} live matches")
        return matches

    except requests.RequestException as e:
        logger.error(f"Failed to fetch live matches: {e}")
        return []


def parse_fixture(fixture: dict) -> dict | None:
    """Parse a raw API-Football fixture into our standard format."""
    try:
        teams = fixture["teams"]
        goals = fixture["goals"]
        status = fixture["fixture"]["status"]
        league = fixture["league"]

        home_score = goals.get("home") or 0
        away_score = goals.get("away") or 0
        minute = status.get("elapsed") or 0

        # Only include matches that are actually live (not HT, not finished)
        short_status = status.get("short", "")
        if short_status not in ("1H", "2H", "ET", "P"):
            return None

        # Goal difference (positive = home winning, negative = away winning)
        goal_diff = home_score - away_score

        # Who is leading?
        if goal_diff > 0:
            leading_team = teams["home"]["name"]
            leading_score = home_score
            trailing_score = away_score
        elif goal_diff < 0:
            leading_team = teams["away"]["name"]
            leading_score = away_score
            trailing_score = home_score
        else:
            leading_team = None  # Draw
            leading_score = home_score
            trailing_score = away_score

        return {
            "fixture_id": fixture["fixture"]["id"],
            "league": league["name"],
            "country": league["country"],
            "home_team": teams["home"]["name"],
            "away_team": teams["away"]["name"],
            "home_score": home_score,
            "away_score": away_score,
            "minute": minute,
            "status": short_status,
            "goal_diff": abs(goal_diff),
            "leading_team": leading_team,
            "leading_side": "home" if goal_diff > 0 else ("away" if goal_diff < 0 else None),
            "leading_score": leading_score,
            "trailing_score": trailing_score,
            "fetched_at": datetime.utcnow().isoformat(),
        }

    except (KeyError, TypeError) as e:
        logger.warning(f"Fixture parse error: {e}")
        return None


def filter_opportunities(matches: list[dict], min_minute: int, min_goal_lead: int) -> list[dict]:
    """
    Filter matches to only those meeting betting criteria:
    - Minute >= min_minute
    - Goal difference >= min_goal_lead
    - A team is actually leading (not a draw)
    """
    opportunities = []
    for m in matches:
        if (
            m["minute"] >= min_minute
            and m["goal_diff"] >= min_goal_lead
            and m["leading_team"] is not None
        ):
            opportunities.append(m)

    logger.info(f"{len(opportunities)} opportunities found from {len(matches)} live matches")
    return opportunities
