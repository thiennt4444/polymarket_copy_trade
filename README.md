# 🐋 Polymarket Whale Copier

> Automatically copy trade winning Polymarket wallets.
> Track any wallet, mirror their bets, profit from their alpha.

---

## Features

| Feature | Detail |
|---|---|
| 🎯 Copy Any Wallet | Paste any Polymarket wallet address |
| 📊 Configurable Size | Copy 1–100% of their position |
| 🛡️ Risk Controls | Min/max USDC limits + slippage guard |
| 🚫 BUY-Only Mode | Mirror buys only, skip sells |
| 📝 Full Logging | Every trade written to `trades.csv` |
| 🔄 Auto-Redemption | Claims winning positions automatically |
| 💰 No API Keys | Uses only public Polymarket APIs |

---

## Requirements

- Python 3.9+
- A wallet with **USDC on Polygon** (Polymarket's collateral)
- The wallet's **private key** (stored locally in `.env`, never shared)

> **First-time users:** Before the bot can trade, you must approve the
> Polymarket exchange contracts to spend your USDC. Visit
> [polymarket.com](https://polymarket.com) once with your wallet connected
> and make a manual trade — this triggers the on-chain approvals automatically.

---

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure
cp .env.example .env
# Edit .env with your target wallet and private key

# 3. Run
python main.py
```

---

## Configuration (`.env`)

```env
# Wallet to copy-trade
TARGET_WALLET=0xAbCd...

# Your wallet private key  !! KEEP SECRET !!
PRIVATE_KEY=0x...

# Copy 10% of their trade size
COPY_PERCENT=10

# Risk limits per trade
MIN_TRADE_USDC=1
MAX_TRADE_USDC=100

# Only copy buys (recommended)
BUY_ONLY=true

# Skip if price moved >2% since their trade
MAX_SLIPPAGE_PCT=2.0

# Auto-claim winning positions
AUTO_REDEEM=true

# Poll every 30 seconds
POLL_INTERVAL=30
```

---

## How It Works

```
Every POLL_INTERVAL seconds:
  1. Fetch target wallet's recent trades (Polymarket Data API)
  2. For each NEW trade:
     a. Get current order book price (Polymarket CLOB API)
     b. Check slippage vs whale's execution price
     c. Calculate our position size (COPY_PERCENT of theirs)
     d. Apply MIN/MAX_TRADE_USDC limits
     e. Place FOK market order on our wallet
  3. Every 5 min: check our positions for resolved winners → redeem USDC
```

**Order type:** FOK (Fill-or-Kill)
Each copy order either fills immediately at the current market price
or is cancelled — no open limit orders accumulate.

---

## Output

### Console

```
[INFO]   Seeding trade history for 0xabc… — watching for new ones.
[OK]     Trader ready  |  wallet: 0x123…
[OK]     Bot is live — watching for new trades …

[INFO]   New trade detected on target wallet
           Market : Will BTC hit $100k before April 2025?
           Side   : BUY  153.84 shares @ $0.6500  ≈  $100.00 USDC
[COPY_BUY]     Will BTC hit $100k before April 2025?
               BUY 15.38 shares @ $0.6510  =  $10.01 USDC  |  FILLED
[OK]     Copied 10% → $10.01 USDC BUY
```

### trades.csv

Every trade (copies + redemptions + skips) is appended to `trades.csv`:

| Column | Description |
|---|---|
| `timestamp_utc` | ISO 8601 UTC timestamp |
| `action` | COPY_BUY / COPY_SELL / REDEEM / SKIPPED |
| `market_title` | Market question |
| `condition_id` | Polymarket condition ID |
| `token_id` | ERC-1155 outcome token ID |
| `side` | BUY or SELL |
| `usdc_amount` | USDC spent/received |
| `shares` | Outcome tokens transacted |
| `price` | Execution price |
| `target_wallet` | The wallet being copied |
| `tx_hash` | On-chain transaction hash |
| `status` | FILLED / UNMATCHED / REDEEMED / SKIPPED / ERROR |
| `notes` | Reason if skipped/errored |

---

## Architecture

```
polymarket_copy_trade/
├── main.py          Entry point and main polling loop
├── config.py        Loads settings from .env
├── tracker.py       Watches target wallet via Data API
├── trader.py        Places orders via CLOB API (py-clob-client)
├── redeemer.py      Redeems winning positions via Polygon/web3
├── logger.py        Console output + CSV trade log
├── skill.json       OpenClaw skill metadata
├── requirements.txt Python dependencies
└── .env.example     Configuration template
```

---

## APIs Used

| API | URL | Auth |
|---|---|---|
| Polymarket Data API | `data-api.polymarket.com` | None |
| Polymarket CLOB API | `clob.polymarket.com` | Wallet signature (derived) |
| Polygon RPC | `polygon-rpc.com` | None |

---

## Security Notes

- Your `PRIVATE_KEY` is read from `.env` and used only to sign transactions locally — it is **never sent** to any external service.
- The bot only has access to funds you hold in your wallet; it cannot access more than your on-chain balance.
- Add `.env` to `.gitignore` before committing to any repository.

---

## Disclaimer

This tool is for educational purposes. Prediction market trading involves financial risk. Past performance of a copied wallet does not guarantee future results. Use at your own risk.
