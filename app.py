"""
app.py — Flask + WebSocket server
Runs the backend, serves the dashboard, and bridges bot <-> frontend.
"""

import asyncio
import json
import logging
import threading
import os
from flask import Flask, render_template_string, send_from_directory
from flask_sock import Sock
import config
from bot import BettingBot

# ── Logging setup ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("betbot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ── Flask app ──
app = Flask(__name__)
sock = Sock(app)

# ── Global bot instance ──
bot: BettingBot = None
connected_clients: list = []
bot_loop: asyncio.AbstractEventLoop = None


# ── WebSocket broadcast (sends to all connected dashboards) ──
def broadcast_sync(message: dict):
    """Send a message to all connected WebSocket clients (thread-safe)."""
    payload = json.dumps(message)
    dead = []
    for ws in connected_clients:
        try:
            ws.send(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        connected_clients.remove(ws)


async def broadcast_async(message: dict):
    """Async-friendly broadcast called from bot."""
    broadcast_sync(message)


# ── Bot thread ──
def run_bot_loop():
    """Run the asyncio event loop for the bot in a background thread."""
    global bot_loop
    bot_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(bot_loop)
    bot_loop.run_forever()


def run_coroutine(coro):
    """Schedule a coroutine on the bot's event loop from any thread."""
    if bot_loop and bot_loop.is_running():
        return asyncio.run_coroutine_threadsafe(coro, bot_loop)
    return None


# ── Routes ──
@app.route("/")
def index():
    """Serve the dashboard."""
    dashboard_path = os.path.join(os.path.dirname(__file__), "dashboard.html")
    with open(dashboard_path, "r", encoding="utf-8") as f:
        return f.read()


@sock.route("/ws")
def websocket(ws):
    """Handle WebSocket connection from dashboard."""
    connected_clients.append(ws)
    logger.info(f"Dashboard connected. Total clients: {len(connected_clients)}")

    # Send current state to newly connected client
    if bot:
        run_coroutine(bot.push_balances())
        run_coroutine(bot.push_stats())

    try:
        while True:
            data = ws.receive(timeout=30)
            if data is None:
                break

            try:
                msg = json.loads(data)
                handle_message(msg)
            except json.JSONDecodeError:
                pass

    except Exception as e:
        logger.info(f"WebSocket disconnected: {e}")
    finally:
        if ws in connected_clients:
            connected_clients.remove(ws)


def handle_message(msg: dict):
    """Handle incoming messages from the dashboard."""
    action = msg.get("action")

    if action == "init":
        # Initialize bot (login to bookmakers)
        run_coroutine(initialize_bot())

    elif action == "start":
        if bot:
            run_coroutine(bot.start())

    elif action == "pause":
        if bot:
            run_coroutine(bot.pause())

    elif action == "stop":
        if bot:
            run_coroutine(bot.stop())

    elif action == "resume":
        if bot:
            run_coroutine(bot.resume())

    elif action == "settings":
        if bot:
            bot.update_settings(msg.get("settings", {}))
            broadcast_sync({"type": "log", "msg": f"Settings updated: stake=₦{bot.stake}, min_minute={bot.min_minute}', min_goal_lead={bot.min_goal_lead}, min_odds={bot.min_odds}", "color": "blue"})

    elif action == "manual_bet":
        if bot:
            fixture_id = msg.get("fixture_id")
            if fixture_id:
                run_coroutine(bot.manual_bet(fixture_id))

    elif action == "record_result":
        if bot:
            run_coroutine(bot.record_result(msg["bet_id"], msg["won"]))

    elif action == "refresh_balance":
        if bot:
            run_coroutine(refresh_balances())


async def initialize_bot():
    """Create and initialize the bot."""
    global bot

    broadcast_async_wrapper({"type": "log", "msg": "Starting up BetBot Pro...", "color": "blue"})
    broadcast_async_wrapper({"type": "status", "status": "initializing"})

    bot = BettingBot(config, broadcast_fn=broadcast_async)
    success = await bot.initialize()

    if success:
        broadcast_async_wrapper({"type": "log", "msg": "Initialization complete. Ready to bet.", "color": "green"})
        broadcast_async_wrapper({"type": "status", "status": "ready"})
    else:
        broadcast_async_wrapper({"type": "log", "msg": "Initialization failed. Check credentials in config.py", "color": "red"})
        broadcast_async_wrapper({"type": "status", "status": "error"})


async def refresh_balances():
    if bot:
        await bot.sportybet.fetch_balance()
        await bot.betking.fetch_balance()
        await bot.push_balances()


def broadcast_async_wrapper(msg):
    """Wrapper to call broadcast from sync context."""
    broadcast_sync(msg)


# ── Main entry ──
if __name__ == "__main__":
    # Start bot event loop in background thread
    bot_thread = threading.Thread(target=run_bot_loop, daemon=True)
    bot_thread.start()

    logger.info(f"BetBot Pro starting on http://{config.HOST}:{config.PORT}")
    logger.info("Open your browser and navigate to http://127.0.0.1:5000")

    app.run(
        host=config.HOST,
        port=config.PORT,
        debug=False,
        use_reloader=False
    )
