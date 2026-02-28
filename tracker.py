"""
tracker.py — Poll a target wallet's Polymarket trade activity.

Uses the public Data API (no authentication required).
Endpoint: https://data-api.polymarket.com/activity?user={address}&type=TRADE
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import List, Optional, Set

import requests

import logger
from config import Config


@dataclass
class Trade:
    """A single trade event detected on the target wallet."""

    id: str
    timestamp: int           # Unix timestamp
    condition_id: str
    token_id: str            # CLOB asset / ERC-1155 token ID
    side: str                # "BUY" or "SELL"
    shares: float            # Number of outcome tokens
    price: float             # Price per share (0–1)
    usdc_amount: float       # Approximate USDC spent/received
    market_title: str
    outcome: str             # "Yes" / "No"
    slug: str


class WalletTracker:
    """
    Continuously watch a Polymarket wallet and yield new trades.

    Usage
    -----
    tracker = WalletTracker(target_wallet)
    tracker.initialize()          # seed seen IDs without triggering trades
    new = tracker.get_new_trades()  # call in your polling loop
    """

    _ACTIVITY_URL = f"{Config.DATA_API}/activity"

    def __init__(self, target_wallet: str) -> None:
        self.target_wallet = target_wallet.lower()
        self._seen_ids: Set[str] = set()
        self._session = requests.Session()
        self._session.headers["User-Agent"] = "OpenClaw-WhaleCopier/1.0"

    # ── private ──────────────────────────────────────────────────────────────

    def _fetch(self, limit: int = 50) -> List[dict]:
        try:
            resp = self._session.get(
                self._ACTIVITY_URL,
                params={"user": self.target_wallet, "limit": limit, "type": "TRADE"},
                timeout=12,
            )
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else []
        except requests.RequestException as exc:
            logger.warn(f"Activity API error: {exc}")
            return []

    def _parse(self, item: dict) -> Optional[Trade]:
        """Map a raw API dict to a Trade. Returns None on bad data."""
        try:
            trade_id = str(item.get("id") or item.get("tradeId") or "")
            if not trade_id:
                return None

            side = str(item.get("side", "BUY")).upper()
            shares = float(item.get("size") or item.get("shares") or 0)
            price = float(item.get("price") or 0)
            if shares <= 0 or price <= 0:
                return None

            # token_id is stored as "asset" in the Data API
            token_id = str(
                item.get("asset")
                or item.get("tokenId")
                or item.get("token_id")
                or ""
            )
            condition_id = str(item.get("conditionId") or "")

            return Trade(
                id=trade_id,
                timestamp=int(item.get("timestamp") or time.time()),
                condition_id=condition_id,
                token_id=token_id,
                side=side,
                shares=shares,
                price=price,
                usdc_amount=shares * price,
                market_title=str(item.get("title") or item.get("question") or "Unknown market"),
                outcome=str(item.get("outcome") or ""),
                slug=str(item.get("slug") or ""),
            )
        except Exception as exc:
            logger.warn(f"Could not parse activity item: {exc}")
            return None

    # ── public ───────────────────────────────────────────────────────────────

    def initialize(self) -> None:
        """
        Seed the set of known trade IDs with recent history so the bot
        doesn't re-execute old trades on startup.
        """
        logger.info(f"Seeding trade history for {self.target_wallet} …")
        items = self._fetch(limit=100)
        for item in items:
            trade_id = str(item.get("id") or item.get("tradeId") or "")
            if trade_id:
                self._seen_ids.add(trade_id)
        logger.success(
            f"Loaded {len(self._seen_ids)} existing trades — watching for new ones."
        )

    def get_new_trades(self) -> List[Trade]:
        """
        Return trades that appeared since the last call.
        Respects BUY_ONLY mode from Config.
        """
        items = self._fetch(limit=50)
        new: List[Trade] = []

        for item in items:
            trade = self._parse(item)
            if trade is None:
                continue
            if trade.id in self._seen_ids:
                continue
            if not trade.token_id:
                continue

            self._seen_ids.add(trade.id)

            # Skip SELLs when BUY_ONLY is active
            if Config.BUY_ONLY and trade.side != "BUY":
                logger.info(f"Skipping SELL (BUY_ONLY mode): {trade.market_title[:40]}")
                continue

            new.append(trade)

        return new
