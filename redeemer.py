"""
redeemer.py — Auto-redeem winning Polymarket positions.

Workflow:
1. Fetch our open positions from the public Data API.
2. Find positions in markets that have resolved in our favour
   (redeemable > 0).
3. Call the CTF Exchange contract on Polygon to claim USDC.

No external API keys required — uses a public Polygon RPC.
"""

from __future__ import annotations

from typing import List

import requests
from web3 import Web3

import logger
from config import Config

# ── Minimal ABI for CTF Exchange redeemPositions ─────────────────────────────
_CTF_ABI = [
    {
        "name": "redeemPositions",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "collateralToken", "type": "address"},
            {"name": "parentCollectionId", "type": "bytes32"},
            {"name": "conditionId", "type": "bytes32"},
            {"name": "indexSets", "type": "uint256[]"},
        ],
        "outputs": [],
    }
]

_ZERO_BYTES32 = b"\x00" * 32
_INDEX_SETS = [1, 2]  # Covers both YES (1) and NO (2) — exchange redeems only winners


class AutoRedeemer:
    """
    Polls our positions and redeems any resolved winning ones.
    """

    def __init__(self, wallet_address: str, private_key: str) -> None:
        self.address = wallet_address
        self._private_key = private_key
        self._session = requests.Session()
        self._session.headers["User-Agent"] = "OpenClaw-WhaleCopier/1.0"

        # Connect to Polygon via public RPC
        self._w3 = Web3(Web3.HTTPProvider(Config.POLYGON_RPC))
        self._ctf = self._w3.eth.contract(
            address=Web3.to_checksum_address(Config.CTF_EXCHANGE),
            abi=_CTF_ABI,
        )

    # ── data fetching ─────────────────────────────────────────────────────────

    def _get_positions(self) -> List[dict]:
        try:
            resp = self._session.get(
                f"{Config.DATA_API}/positions",
                params={"user": self.address},
                timeout=12,
            )
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else []
        except Exception as exc:
            logger.warn(f"Could not fetch positions: {exc}")
            return []

    def _winning_positions(self) -> List[dict]:
        """Return resolved positions with claimable USDC > 0."""
        positions = self._get_positions()
        return [
            p for p in positions
            if p.get("resolved") and float(p.get("redeemable") or 0) > 0
        ]

    # ── redemption ────────────────────────────────────────────────────────────

    def _redeem_one(self, position: dict) -> bool:
        """
        Submit a redeemPositions transaction for a single winning position.
        Returns True on success.
        """
        condition_id_hex: str = position.get("conditionId", "")
        redeemable: float = float(position.get("redeemable") or 0)
        title: str = position.get("title") or "Unknown market"

        if not condition_id_hex:
            logger.warn(f"Missing conditionId for position: {title}")
            return False

        try:
            # condition_id must be bytes32
            condition_bytes = bytes.fromhex(condition_id_hex.removeprefix("0x"))
            condition_bytes = condition_bytes.ljust(32, b"\x00")[:32]

            nonce = self._w3.eth.get_transaction_count(self.address)
            gas_price = self._w3.eth.gas_price

            tx = self._ctf.functions.redeemPositions(
                Web3.to_checksum_address(Config.USDC_ADDRESS),
                _ZERO_BYTES32,
                condition_bytes,
                _INDEX_SETS,
            ).build_transaction(
                {
                    "from": self.address,
                    "nonce": nonce,
                    "gasPrice": gas_price,
                    "gas": 200_000,
                    "chainId": Config.CHAIN_ID,
                }
            )

            signed = self._w3.eth.account.sign_transaction(tx, self._private_key)
            tx_hash = self._w3.eth.send_raw_transaction(signed.raw_transaction)
            receipt = self._w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

            if receipt.status == 1:
                tx_hex = tx_hash.hex()
                logger.log_trade(
                    action="REDEEM",
                    market_title=title,
                    condition_id=condition_id_hex,
                    token_id="",
                    side="",
                    usdc_amount=redeemable,
                    shares=0.0,
                    price=1.0,
                    target_wallet=self.address,
                    tx_hash=tx_hex,
                    status="REDEEMED",
                )
                logger.success(f"Redeemed ${redeemable:.2f} USDC  ←  {title[:50]}")
                return True
            else:
                logger.warn(f"Redeem tx reverted for: {title[:50]}")
                return False

        except Exception as exc:
            logger.error(f"Redemption failed for '{title[:40]}': {exc}")
            return False

    # ── public ────────────────────────────────────────────────────────────────

    def redeem_all_winning(self) -> int:
        """
        Find and redeem all winning positions.
        Returns the number of successful redemptions.
        """
        winning = self._winning_positions()
        if not winning:
            return 0

        logger.info(f"Found {len(winning)} winning position(s) — redeeming …")
        return sum(1 for p in winning if self._redeem_one(p))
