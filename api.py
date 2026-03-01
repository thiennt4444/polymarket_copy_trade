"""
api.py — HTTP control API for AI agent integration.

Runs as a background thread alongside the main bot loop.
Default port: 8765  (set API_PORT in .env to override)

Endpoints
---------
GET  /status          Bot state, wallet balance, config summary
GET  /trades          Recent trades from trades.csv
PATCH /config         Update FIXED_USDC, POLL_INTERVAL, TARGET_WALLET live
POST /stop            Graceful shutdown
POST /redeem          Trigger manual redemption check

AI agent example (Claude tool call)
-------------------------------------
  GET  http://localhost:8765/status
  PATCH http://localhost:8765/config  body: {"fixed_usdc": 5, "poll_interval": 20}
"""

from __future__ import annotations

import csv
import os
import threading
from typing import Any, Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from config import Config
import logger

app = FastAPI(
    title="Polymarket Whale Copier — Control API",
    version="1.0.0",
    description="AI agent interface for the OpenClaw Polymarket skill",
)

# ── shared state (written by main.py, read by API) ────────────────────────────
class BotState:
    running: bool = False
    usdc_balance: float = 0.0
    trades_copied: int = 0
    trades_skipped: int = 0
    stop_event: Optional[threading.Event] = None

bot_state = BotState()
state = bot_state  # backward-compat alias


# ── request models ────────────────────────────────────────────────────────────
class ConfigPatch(BaseModel):
    fixed_usdc: Optional[float] = None
    min_trade_usdc: Optional[float] = None
    max_trade_usdc: Optional[float] = None
    poll_interval: Optional[int] = None
    max_slippage_pct: Optional[float] = None
    buy_only: Optional[bool] = None
    auto_redeem: Optional[bool] = None
    target_wallet: Optional[str] = None


# ── helpers ───────────────────────────────────────────────────────────────────
def _read_trades(limit: int = 50) -> list[dict]:
    log_file = "trades.csv"
    if not os.path.exists(log_file):
        return []
    with open(log_file, newline="") as f:
        rows = list(csv.DictReader(f))
    return rows[-limit:][::-1]  # newest first


# ── endpoints ─────────────────────────────────────────────────────────────────

@app.get("/")
def root() -> dict:
    return {
        "skill": "polymarket-whale-copier",
        "version": "1.0.0",
        "docs": "/docs",
    }


@app.get("/status")
def get_status() -> dict:
    """Return current bot state and active configuration."""
    return {
        "running": state.running,
        "usdc_balance": state.usdc_balance,
        "trades_copied": state.trades_copied,
        "trades_skipped": state.trades_skipped,
        "config": {
            "target_wallet": Config.TARGET_WALLET,
            "fixed_usdc": Config.FIXED_USDC,
            "min_trade_usdc": Config.MIN_TRADE_USDC,
            "max_trade_usdc": Config.MAX_TRADE_USDC,
            "poll_interval": Config.POLL_INTERVAL,
            "max_slippage_pct": Config.MAX_SLIPPAGE_PCT,
            "buy_only": Config.BUY_ONLY,
            "auto_redeem": Config.AUTO_REDEEM,
        },
    }


@app.get("/trades")
def get_trades(limit: int = 20) -> list[dict]:
    """Return recent trades from the CSV log (newest first)."""
    limit = max(1, min(limit, 500))
    return _read_trades(limit)


@app.patch("/config")
def patch_config(patch: ConfigPatch) -> dict:
    """
    Update one or more config values while the bot is running.
    Changes take effect on the next poll cycle.
    """
    changed: dict[str, Any] = {}

    if patch.fixed_usdc is not None:
        if patch.fixed_usdc <= 0:
            raise HTTPException(400, "fixed_usdc must be > 0")
        Config.FIXED_USDC = patch.fixed_usdc
        changed["fixed_usdc"] = patch.fixed_usdc

    if patch.min_trade_usdc is not None:
        if patch.min_trade_usdc <= 0:
            raise HTTPException(400, "min_trade_usdc must be > 0")
        Config.MIN_TRADE_USDC = patch.min_trade_usdc
        changed["min_trade_usdc"] = patch.min_trade_usdc

    if patch.max_trade_usdc is not None:
        Config.MAX_TRADE_USDC = patch.max_trade_usdc
        changed["max_trade_usdc"] = patch.max_trade_usdc

    if patch.poll_interval is not None:
        if patch.poll_interval < 10:
            raise HTTPException(400, "poll_interval must be >= 10")
        Config.POLL_INTERVAL = patch.poll_interval
        changed["poll_interval"] = patch.poll_interval

    if patch.max_slippage_pct is not None:
        Config.MAX_SLIPPAGE_PCT = patch.max_slippage_pct
        changed["max_slippage_pct"] = patch.max_slippage_pct

    if patch.buy_only is not None:
        Config.BUY_ONLY = patch.buy_only
        changed["buy_only"] = patch.buy_only

    if patch.auto_redeem is not None:
        Config.AUTO_REDEEM = patch.auto_redeem
        changed["auto_redeem"] = patch.auto_redeem

    if patch.target_wallet is not None:
        Config.TARGET_WALLET = patch.target_wallet.lower()
        changed["target_wallet"] = Config.TARGET_WALLET

    if changed:
        logger.info(f"[API] Config updated by agent: {changed}")

    return {"updated": changed, "current_config": {
        "fixed_usdc": Config.FIXED_USDC,
        "min_trade_usdc": Config.MIN_TRADE_USDC,
        "max_trade_usdc": Config.MAX_TRADE_USDC,
        "poll_interval": Config.POLL_INTERVAL,
        "max_slippage_pct": Config.MAX_SLIPPAGE_PCT,
        "buy_only": Config.BUY_ONLY,
        "auto_redeem": Config.AUTO_REDEEM,
        "target_wallet": Config.TARGET_WALLET,
    }}


@app.post("/stop")
def stop_bot() -> dict:
    """Signal the bot to stop gracefully."""
    if state.stop_event:
        state.stop_event.set()
        logger.info("[API] Stop requested by agent")
        return {"status": "stopping"}
    return {"status": "already_stopped"}


@app.post("/redeem")
def trigger_redeem() -> dict:
    """
    Mark next loop iteration to run a redemption check immediately.
    The bot picks this up within one poll cycle.
    """
    state._force_redeem = True
    logger.info("[API] Manual redemption triggered by agent")
    return {"status": "queued"}


# ── server launcher (called from main.py) ─────────────────────────────────────

def start_api_server(port: int = 8765) -> None:
    """Launch uvicorn in a daemon thread — dies when the main process exits."""
    def _run() -> None:
        uvicorn.run(
            app,
            host="127.0.0.1",
            port=port,
            log_level="warning",   # suppress uvicorn access logs
        )

    thread = threading.Thread(target=_run, daemon=True, name="api-server")
    thread.start()
    logger.success(f"Control API running at http://127.0.0.1:{port}")
