"""
trader.py — Execute mirrored trades on Polymarket via the CLOB API.

Authentication: L1 (EOA private key) + derived L2 API credentials.
No external API keys required — everything is derived from your wallet.
"""

from __future__ import annotations

from typing import Optional, Tuple

from eth_account import Account
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import AssetType, BalanceAllowanceParams, MarketOrderArgs, OrderType

import logger
from config import Config


class ClobTrader:
    """
    Wrapper around py_clob_client that handles authentication,
    order sizing, slippage checks, and order placement.
    """

    def __init__(self) -> None:
        # Derive wallet address from private key
        account = Account.from_key(Config.PRIVATE_KEY)
        self.address: str = account.address

        # Build client (signature_type=0 → standard EOA wallet)
        self._client = ClobClient(
            host=Config.CLOB_HOST,
            key=Config.PRIVATE_KEY,
            chain_id=Config.CHAIN_ID,
            signature_type=0,
            funder=self.address,
        )

        # Derive L2 API credentials from the private key (no registration needed)
        try:
            creds = self._client.create_or_derive_api_creds()
            self._client.set_api_creds(creds)
        except Exception as exc:
            raise RuntimeError(
                f"Failed to initialise Polymarket API credentials: {exc}\n"
                "Make sure your PRIVATE_KEY is a valid 32-byte hex key."
            ) from exc

        logger.success(f"Trader ready  |  wallet: {self.address}")

    # ── market data ──────────────────────────────────────────────────────────

    def get_best_price(self, token_id: str, side: str) -> Optional[float]:
        """
        Return the current best execution price for a token.
        BUY → lowest ask.  SELL → highest bid.
        """
        try:
            book = self._client.get_order_book(token_id)
            if side == "BUY" and book.asks:
                return min(float(a.price) for a in book.asks)
            if side == "SELL" and book.bids:
                return max(float(b.price) for b in book.bids)
        except Exception as exc:
            logger.warn(f"Order book unavailable for {token_id[:12]}…: {exc}")
        return None

    def get_usdc_balance(self) -> float:
        """Return the USDC (collateral) balance of our trading wallet."""
        try:
            resp = self._client.get_balance_allowance(
                params=BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
            )
            return float(resp.get("balance", 0))
        except Exception:
            return 0.0

    # ── order logic ──────────────────────────────────────────────────────────

    def calculate_order(
        self,
        their_price: float,
        side: str,
        token_id: str,
    ) -> Tuple[float, float]:
        """
        Determine (our_usdc_amount, execution_price) for a mirrored trade.

        Always bets FIXED_USDC (clamped to MIN/MAX_TRADE_USDC).

        Raises ValueError if slippage exceeds MAX_SLIPPAGE_PCT.
        """
        our_usdc = max(Config.MIN_TRADE_USDC, min(Config.MAX_TRADE_USDC, Config.FIXED_USDC))

        # Get current market price; fall back to whale's price if book is empty
        current_price = self.get_best_price(token_id, side)
        if current_price is None:
            logger.warn("Order book empty — falling back to whale's execution price")
            current_price = their_price

        # Slippage guard: skip if market moved too much since their trade
        if their_price > 0:
            slippage = abs(current_price - their_price) / their_price * 100
            if slippage > Config.MAX_SLIPPAGE_PCT:
                raise ValueError(
                    f"Slippage {slippage:.1f}% exceeds limit {Config.MAX_SLIPPAGE_PCT}%  "
                    f"(whale: ${their_price:.4f}  now: ${current_price:.4f})"
                )

        return our_usdc, current_price

    # ── order placement ──────────────────────────────────────────────────────

    def place_market_order(
        self,
        *,
        token_id: str,
        side: str,
        usdc_amount: float,
        execution_price: float,
        market_title: str = "",
        condition_id: str = "",
    ) -> dict:
        """
        Place a FOK market order.

        For BUY:  amount = USDC to spend  (py_clob_client handles share calc)
        For SELL: amount = shares to sell (outcome tokens)
        """
        shares_estimate = usdc_amount / execution_price if execution_price > 0 else 0

        try:
            # price acts as a limit — allows up to 2% slippage above/below quote
            limit_price = round(
                execution_price * (1.02 if side == "BUY" else 0.98), 6
            )
            signed_order = self._client.create_market_order(
                MarketOrderArgs(
                    token_id=token_id,
                    amount=usdc_amount,
                    side=side,
                    price=limit_price,
                )
            )

            resp = self._client.post_order(signed_order, OrderType.FOK)

            filled = resp.get("status") in ("matched", "filled")
            status = "FILLED" if filled else "UNMATCHED"
            tx_hash = resp.get("transactionHash", "")

            logger.log_trade(
                action="COPY_BUY" if side == "BUY" else "COPY_SELL",
                market_title=market_title,
                condition_id=condition_id,
                token_id=token_id,
                side=side,
                usdc_amount=usdc_amount,
                shares=shares_estimate,
                price=execution_price,
                target_wallet=Config.TARGET_WALLET,
                tx_hash=tx_hash,
                status=status,
            )

            return resp

        except Exception as exc:
            logger.log_trade(
                action="COPY_BUY" if side == "BUY" else "COPY_SELL",
                market_title=market_title,
                condition_id=condition_id,
                token_id=token_id,
                side=side,
                usdc_amount=usdc_amount,
                shares=shares_estimate,
                price=execution_price,
                target_wallet=Config.TARGET_WALLET,
                status="ERROR",
                notes=str(exc),
            )
            raise
