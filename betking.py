"""
betking.py — BetKing browser automation
Handles login, balance reading, odds fetching, and bet placement.
"""

import asyncio
import logging
import re
from playwright.async_api import async_playwright, Page, Browser, BrowserContext

logger = logging.getLogger(__name__)

BETKING_URL = "https://www.betking.com/"
LOGIN_URL = "https://www.betking.com/login"


class BetKingBot:
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
        """Log into BetKing account."""
        try:
            logger.info("BetKing: Navigating to login page...")
            await self.page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
            await self.page.wait_for_timeout(2000)

            # Accept cookies if prompted
            try:
                await self.page.click("button:has-text('Accept'), button:has-text('OK')", timeout=3000)
            except Exception:
                pass

            # Fill username/phone
            await self.page.fill(
                "input[name='username'], input[type='tel'], input[type='email'], input[placeholder*='hone'], input[placeholder*='mail'], input[placeholder*='sername']",
                self.username
            )
            await self.page.wait_for_timeout(500)

            # Fill password
            await self.page.fill("input[type='password']", self.password)
            await self.page.wait_for_timeout(500)

            # Submit
            await self.page.click("button[type='submit'], button:has-text('Login'), button:has-text('Sign In'), input[type='submit']")
            await self.page.wait_for_timeout(3000)

            # Check for OTP page
            try:
                otp_el = await self.page.query_selector("input[placeholder*='OTP'], input[placeholder*='code'], input[name*='otp']")
                if otp_el:
                    logger.warning("BetKing: OTP required — waiting up to 60 seconds for you to enter it manually in the browser window")
                    # Wait for user to enter OTP manually
                    await self.page.wait_for_url("**/home**", timeout=60000)
            except Exception:
                pass

            # Verify login
            try:
                await self.page.wait_for_selector(
                    "[class*='balance'], [class*='Balance'], [class*='wallet'], .user-info",
                    timeout=10000
                )
                self.logged_in = True
                logger.info("BetKing: Login successful")
                await self.fetch_balance()
                return True
            except Exception:
                logger.error("BetKing: Login may have failed")
                self.logged_in = False
                return False

        except Exception as e:
            logger.error(f"BetKing login error: {e}")
            self.logged_in = False
            return False

    async def fetch_balance(self) -> float:
        """Read current balance from page."""
        try:
            await self.page.goto(BETKING_URL, wait_until="domcontentloaded", timeout=20000)
            await self.page.wait_for_timeout(2000)

            selectors = [
                "[class*='balance']",
                "[class*='wallet-amount']",
                ".account-balance",
                "[data-balance]",
                "span[class*='Balance']",
                ".header-balance",
            ]

            for selector in selectors:
                try:
                    el = await self.page.query_selector(selector)
                    if el:
                        text = await el.inner_text()
                        amount = self._parse_amount(text)
                        if amount is not None:
                            self.balance = amount
                            logger.info(f"BetKing balance: ₦{self.balance:.2f}")
                            return self.balance
                except Exception:
                    continue

            logger.warning("BetKing: Could not read balance")
            return self.balance

        except Exception as e:
            logger.error(f"BetKing fetch_balance error: {e}")
            return self.balance

    async def get_live_odds(self, home_team: str, away_team: str, leading_side: str) -> dict | None:
        """
        Search for a live match on BetKing and return odds for the leading team.
        """
        try:
            live_url = "https://www.betking.com/sports/live"
            await self.page.goto(live_url, wait_until="domcontentloaded", timeout=20000)
            await self.page.wait_for_timeout(2000)

            # Look for the match
            match_elements = await self.page.query_selector_all("[class*='match'], [class*='event'], [class*='fixture']")

            for el in match_elements:
                text = await el.inner_text()
                if home_team.lower()[:5] in text.lower() or away_team.lower()[:5] in text.lower():
                    # Get odds buttons (1X2: home, draw, away)
                    odds_els = await el.query_selector_all("[class*='odd'], [class*='price'], [class*='selection'], button[class*='bet']")
                    if len(odds_els) >= 3:
                        try:
                            if leading_side == "home":
                                odds_text = await odds_els[0].inner_text()
                                odds_index = 0
                            else:
                                odds_text = await odds_els[2].inner_text()
                                odds_index = 2

                            odds = float(odds_text.strip())
                            if 1.01 <= odds <= 1.50:
                                logger.info(f"BetKing odds for {home_team} vs {away_team}: {odds}")
                                return {"odds": odds, "element": el, "odds_index": odds_index}
                        except (ValueError, AttributeError):
                            continue

            logger.info(f"BetKing: Match not found — {home_team} vs {away_team}")
            return None

        except Exception as e:
            logger.error(f"BetKing get_live_odds error: {e}")
            return None

    async def place_bet(self, home_team: str, away_team: str, leading_side: str, stake: float, min_odds: float) -> dict:
        """
        Place a real bet on the leading team.
        """
        result = {
            "success": False,
            "bookmaker": "BetKing",
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
                result["error"] = "Match not found on BetKing"
                return result

            current_odds = odds_data["odds"]
            result["odds"] = current_odds

            if current_odds < min_odds:
                result["error"] = f"Odds {current_odds} below minimum {min_odds}"
                return result

            # Add to betslip
            odds_el = odds_data["element"]
            odds_buttons = await odds_el.query_selector_all("[class*='odd'], [class*='price'], [class*='selection'], button")
            if odds_buttons:
                await odds_buttons[odds_data["odds_index"]].click()
                await self.page.wait_for_timeout(1500)

            # Enter stake
            stake_selectors = [
                "input[placeholder*='Stake']",
                "input[placeholder*='stake']",
                "input[placeholder*='Amount']",
                "input[class*='stake']",
                ".betslip input[type='number']",
                "[class*='betslip'] input[type='number']",
            ]

            stake_filled = False
            for selector in stake_selectors:
                try:
                    el = await self.page.query_selector(selector)
                    if el:
                        await el.triple_click()
                        await el.type(str(int(stake)))
                        stake_filled = True
                        break
                except Exception:
                    continue

            if not stake_filled:
                result["error"] = "Could not find stake input on BetKing"
                return result

            await self.page.wait_for_timeout(1000)

            # Place bet
            btn_selectors = [
                "button:has-text('Place Bet')",
                "button:has-text('PLACE BET')",
                "button:has-text('Confirm')",
                "[class*='place-bet']",
                "[class*='confirm-bet']",
            ]

            bet_placed = False
            for selector in btn_selectors:
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
                result["error"] = "Could not click Place Bet on BetKing"
                return result

            # Check confirmation
            try:
                await self.page.wait_for_selector(
                    "[class*='success'], [class*='confirmed'], :has-text('successful'), :has-text('placed')",
                    timeout=5000
                )
                result["success"] = True
                self.balance -= stake
                logger.info(f"BetKing: Bet placed! {home_team} vs {away_team} @ {current_odds} | ₦{stake}")
            except Exception:
                result["error"] = "Bet confirmation not detected — check BetKing manually"

            return result

        except Exception as e:
            result["error"] = str(e)
            logger.error(f"BetKing place_bet error: {e}")
            return result

    async def stop(self):
        """Close browser."""
        try:
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()
        except Exception as e:
            logger.error(f"BetKing stop error: {e}")

    def _parse_amount(self, text: str) -> float | None:
        try:
            cleaned = re.sub(r"[^\d.]", "", text.replace(",", ""))
            return float(cleaned) if cleaned else None
        except ValueError:
            return None
