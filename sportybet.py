"""
sportybet.py — SportyBet browser automation
Handles login, balance reading, odds fetching, and bet placement.
"""

import asyncio
import logging
import re
from playwright.async_api import async_playwright, Page, Browser, BrowserContext

logger = logging.getLogger(__name__)

SPORTYBET_URL = "https://www.sportybet.com/ng/"
LOGIN_URL = "https://www.sportybet.com/ng/user/login"


class SportyBetBot:
    def __init__(self, username: str, password: str, headless: bool = False):
        self.username = username
        self.password = password
        self.headless = headless
        self.playwright = None
        self.browser: Browser = None
        self.context: BrowserContext = None
        self.page: Page = None
        self.logged_in = False
        self.balance = 0.0

    async def start(self):
        """Launch browser and log in."""
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=self.headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ]
        )
        self.context = await self.browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
        )
        self.page = await self.context.new_page()

        # Mask automation detection
        await self.page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        """)

        await self.login()

    async def login(self) -> bool:
        """Log into SportyBet account."""
        try:
            logger.info("SportyBet: Navigating to login page...")
            await self.page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
            await self.page.wait_for_timeout(2000)

            # Accept cookies if prompted
            try:
                await self.page.click("button:has-text('Accept')", timeout=3000)
            except Exception:
                pass

            # Fill username
            await self.page.fill("input[name='username'], input[type='tel'], input[placeholder*='hone'], input[placeholder*='mail']", self.username)
            await self.page.wait_for_timeout(500)

            # Fill password
            await self.page.fill("input[type='password']", self.password)
            await self.page.wait_for_timeout(500)

            # Click login button
            await self.page.click("button[type='submit'], button:has-text('Login'), button:has-text('Sign in')")
            await self.page.wait_for_timeout(3000)

            # Verify login by checking for balance element
            try:
                await self.page.wait_for_selector(".balance, [class*='balance'], [class*='Balance']", timeout=10000)
                self.logged_in = True
                logger.info("SportyBet: Login successful")
                await self.fetch_balance()
                return True
            except Exception:
                logger.error("SportyBet: Login may have failed — could not find balance element")
                self.logged_in = False
                return False

        except Exception as e:
            logger.error(f"SportyBet login error: {e}")
            self.logged_in = False
            return False

    async def fetch_balance(self) -> float:
        """Read current balance from page."""
        try:
            await self.page.goto(SPORTYBET_URL, wait_until="domcontentloaded", timeout=20000)
            await self.page.wait_for_timeout(2000)

            # Try multiple balance selectors
            selectors = [
                ".m-balance__amount",
                "[class*='balance'] span",
                "[data-balance]",
                ".user-balance",
                "span[class*='Balance']",
            ]

            for selector in selectors:
                try:
                    el = await self.page.query_selector(selector)
                    if el:
                        text = await el.inner_text()
                        amount = self._parse_amount(text)
                        if amount is not None:
                            self.balance = amount
                            logger.info(f"SportyBet balance: ₦{self.balance:.2f}")
                            return self.balance
                except Exception:
                    continue

            logger.warning("SportyBet: Could not read balance")
            return self.balance

        except Exception as e:
            logger.error(f"SportyBet fetch_balance error: {e}")
            return self.balance

    async def get_live_odds(self, home_team: str, away_team: str, leading_side: str) -> dict | None:
        """
        Search for a live match on SportyBet and return odds for the leading team.
        Returns dict with odds and match_url, or None if not found.
        """
        try:
            live_url = "https://www.sportybet.com/ng/sport/football?source=in-play"
            await self.page.goto(live_url, wait_until="domcontentloaded", timeout=20000)
            await self.page.wait_for_timeout(2000)

            # Search for match by team name
            search_term = home_team.split()[0]  # Use first word of home team

            # Try to find the match in the live list
            match_elements = await self.page.query_selector_all("[class*='match'], [class*='event'], [class*='game']")

            for el in match_elements:
                text = await el.inner_text()
                if home_team.lower()[:5] in text.lower() or away_team.lower()[:5] in text.lower():
                    # Found the match - get the odds
                    odds_els = await el.query_selector_all("[class*='odd'], [class*='price'], [class*='rate']")
                    if len(odds_els) >= 3:
                        try:
                            # Odds order: home win, draw, away win
                            if leading_side == "home":
                                odds_text = await odds_els[0].inner_text()
                            else:
                                odds_text = await odds_els[2].inner_text()

                            odds = float(odds_text.strip())
                            if 1.01 <= odds <= 1.50:  # Sanity check
                                logger.info(f"SportyBet odds for {home_team} vs {away_team}: {odds}")
                                return {"odds": odds, "element": el, "odds_index": 0 if leading_side == "home" else 2}
                        except (ValueError, AttributeError):
                            continue

            logger.info(f"SportyBet: Match not found in live section — {home_team} vs {away_team}")
            return None

        except Exception as e:
            logger.error(f"SportyBet get_live_odds error: {e}")
            return None

    async def place_bet(self, home_team: str, away_team: str, leading_side: str, stake: float, min_odds: float) -> dict:
        """
        Place a real bet on the leading team.
        Returns result dict with success status and details.
        """
        result = {
            "success": False,
            "bookmaker": "SportyBet",
            "odds": None,
            "stake": stake,
            "error": None,
        }

        try:
            if not self.logged_in:
                result["error"] = "Not logged in"
                return result

            if self.balance < stake:
                result["error"] = f"Insufficient balance: ₦{self.balance:.2f}"
                return result

            # Get odds
            odds_data = await self.get_live_odds(home_team, away_team, leading_side)
            if not odds_data:
                result["error"] = "Match not found on SportyBet"
                return result

            current_odds = odds_data["odds"]
            result["odds"] = current_odds

            # Check if still profitable
            if current_odds < min_odds:
                result["error"] = f"Odds {current_odds} below minimum {min_odds}"
                return result

            # Click on the odds to add to betslip
            odds_el = odds_data["element"]
            odds_buttons = await odds_el.query_selector_all("[class*='odd'], [class*='price']")
            if odds_buttons:
                target_btn = odds_buttons[odds_data["odds_index"]]
                await target_btn.click()
                await self.page.wait_for_timeout(1500)

            # Fill in stake amount
            stake_selectors = [
                "input[placeholder*='Stake']",
                "input[placeholder*='stake']",
                "input[class*='stake']",
                ".betslip input[type='number']",
                "[class*='betslip'] input",
            ]

            stake_filled = False
            for selector in stake_selectors:
                try:
                    stake_input = await self.page.query_selector(selector)
                    if stake_input:
                        await stake_input.triple_click()
                        await stake_input.type(str(int(stake)))
                        stake_filled = True
                        break
                except Exception:
                    continue

            if not stake_filled:
                result["error"] = "Could not find stake input"
                return result

            await self.page.wait_for_timeout(1000)

            # Click Place Bet button
            bet_btn_selectors = [
                "button:has-text('Place Bet')",
                "button:has-text('PLACE BET')",
                "button:has-text('Bet Now')",
                "[class*='place-bet']",
                "[class*='placeBet']",
            ]

            bet_placed = False
            for selector in bet_btn_selectors:
                try:
                    btn = await self.page.query_selector(selector)
                    if btn:
                        await btn.click()
                        await self.page.wait_for_timeout(2000)
                        bet_placed = True
                        break
                except Exception:
                    continue

            if not bet_placed:
                result["error"] = "Could not find Place Bet button"
                return result

            # Check for success confirmation
            try:
                await self.page.wait_for_selector(
                    "[class*='success'], [class*='confirmed'], :has-text('Bet placed'), :has-text('successful')",
                    timeout=5000
                )
                result["success"] = True
                self.balance -= stake
                logger.info(f"SportyBet: Bet placed! {home_team} vs {away_team} @ {current_odds} | ₦{stake}")
            except Exception:
                result["error"] = "Bet confirmation not detected — check SportyBet manually"

            return result

        except Exception as e:
            result["error"] = str(e)
            logger.error(f"SportyBet place_bet error: {e}")
            return result

    async def stop(self):
        """Close browser."""
        try:
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()
        except Exception as e:
            logger.error(f"SportyBet stop error: {e}")

    def _parse_amount(self, text: str) -> float | None:
        """Extract numeric amount from balance text like '₦1,234.56'."""
        try:
            cleaned = re.sub(r"[^\d.]", "", text.replace(",", ""))
            return float(cleaned) if cleaned else None
        except ValueError:
            return None
