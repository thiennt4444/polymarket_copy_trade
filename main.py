"""
main.py — Polymarket Whale Copier entry point.

Run:  python main.py
Stop: Ctrl-C  (graceful shutdown)
"""

from __future__ import annotations

import signal
import sys
import time

from colorama import Fore, Style, init

import logger
from config import Config
from redeemer import AutoRedeemer
from tracker import WalletTracker
from trader import ClobTrader

init(autoreset=True)

_BANNER = f"""
{Fore.CYAN}╔══════════════════════════════════════════════════╗
║    🐋   Polymarket Whale Copier  —  OpenClaw    ║
║   Track any wallet · Mirror bets · Claim wins   ║
╚══════════════════════════════════════════════════╝{Style.RESET_ALL}
"""

# How often (seconds) to run the auto-redeem check
_REDEEM_CHECK_INTERVAL = 300


def _print_config() -> None:
    buy_sell = "BUY only" if Config.BUY_ONLY else "BUY + SELL"
    redeem = "ON" if Config.AUTO_REDEEM else "OFF"
    print(
        f"  Target wallet : {Config.TARGET_WALLET}\n"
        f"  Bet per trade : ${Config.FIXED_USDC} USDC (max ${Config.MAX_TRADE_USDC})\n"
        f"  Max slippage  : {Config.MAX_SLIPPAGE_PCT}%\n"
        f"  Mode          : {buy_sell}\n"
        f"  Auto-redeem   : {redeem}\n"
        f"  Poll interval : {Config.POLL_INTERVAL}s\n"
    )


def main() -> None:
    print(_BANNER)

    # ── validate config ───────────────────────────────────────────────────────
    try:
        Config.validate()
    except ValueError as exc:
        logger.error(str(exc))
        logger.error("Copy .env.example → .env and fill in your values.")
        sys.exit(1)

    _print_config()

    # ── initialise components ─────────────────────────────────────────────────
    try:
        trader = ClobTrader()
        balance = trader.get_usdc_balance()
        logger.info(f"USDC balance: ${balance:.2f}")
    except RuntimeError as exc:
        logger.error(str(exc))
        sys.exit(1)

    tracker = WalletTracker(Config.TARGET_WALLET)
    tracker.initialize()  # seed seen IDs — avoids re-executing old trades

    redeemer: AutoRedeemer | None = None
    if Config.AUTO_REDEEM:
        redeemer = AutoRedeemer(trader.address, Config.PRIVATE_KEY)

    # ── graceful shutdown ─────────────────────────────────────────────────────
    running = True

    def _handle_stop(sig, frame):  # noqa: ANN001
        nonlocal running
        print(f"\n{Fore.YELLOW}Shutting down …{Style.RESET_ALL}")
        running = False

    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)

    # ── main loop ─────────────────────────────────────────────────────────────
    last_redeem_ts = 0.0
    logger.success("Bot is live — watching for new trades …\n")

    while running:
        try:
            # ── copy new trades ───────────────────────────────────────────────
            new_trades = tracker.get_new_trades()

            for trade in new_trades:
                logger.info(
                    f"New trade detected on target wallet\n"
                    f"  Market : {trade.market_title[:60]}\n"
                    f"  Side   : {trade.side}  {trade.shares:.2f} shares "
                    f"@ ${trade.price:.4f}  ≈  ${trade.usdc_amount:.2f} USDC"
                )

                try:
                    our_usdc, exec_price = trader.calculate_order(
                        their_price=trade.price,
                        side=trade.side,
                        token_id=trade.token_id,
                    )

                    resp = trader.place_market_order(
                        token_id=trade.token_id,
                        side=trade.side,
                        usdc_amount=our_usdc,
                        execution_price=exec_price,
                        market_title=trade.market_title,
                        condition_id=trade.condition_id,
                    )

                    if resp.get("status") in ("matched", "filled"):
                        logger.success(f"Order filled → ${our_usdc:.2f} USDC {trade.side}")
                    else:
                        logger.warn(f"Order unmatched: {resp.get('status', 'unknown')}")

                except ValueError as exc:
                    # Slippage guard, etc.
                    logger.warn(f"Trade skipped — {exc}")
                    logger.log_trade(
                        action="SKIPPED",
                        market_title=trade.market_title,
                        condition_id=trade.condition_id,
                        token_id=trade.token_id,
                        side=trade.side,
                        usdc_amount=0.0,
                        shares=0.0,
                        price=trade.price,
                        target_wallet=Config.TARGET_WALLET,
                        status="SKIPPED",
                        notes=str(exc),
                    )
                except Exception as exc:
                    logger.error(f"Order failed: {exc}")

            # ── auto-redeem check (every 5 minutes) ───────────────────────────
            if redeemer and (time.time() - last_redeem_ts >= _REDEEM_CHECK_INTERVAL):
                last_redeem_ts = time.time()
                count = redeemer.redeem_all_winning()
                if count:
                    logger.success(f"Auto-redeemed {count} winning position(s)")

        except Exception as exc:
            logger.error(f"Unexpected error in main loop: {exc}")

        # Sleep until next poll (interruptible)
        deadline = time.time() + Config.POLL_INTERVAL
        while running and time.time() < deadline:
            time.sleep(1)

    logger.info("Bot stopped.")


if __name__ == "__main__":
    main()
