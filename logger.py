import csv
import os
import logging
from datetime import datetime, timezone
from colorama import Fore, Style, init

init(autoreset=True)

LOG_FILE = "trades.csv"
_CSV_HEADERS = [
    "timestamp_utc",
    "action",
    "market_title",
    "condition_id",
    "token_id",
    "side",
    "usdc_amount",
    "shares",
    "price",
    "target_wallet",
    "tx_hash",
    "status",
    "notes",
]

# ── Console logger ────────────────────────────────────────────────────────────
_log = logging.getLogger("whale-copier")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
)


def _ensure_csv() -> None:
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, "w", newline="") as f:
            csv.writer(f).writerow(_CSV_HEADERS)


# ── Public helpers ────────────────────────────────────────────────────────────

def info(msg: str) -> None:
    print(f"{Fore.CYAN}[INFO]{Style.RESET_ALL}  {msg}")


def warn(msg: str) -> None:
    print(f"{Fore.YELLOW}[WARN]{Style.RESET_ALL}  {msg}")


def error(msg: str) -> None:
    print(f"{Fore.RED}[ERROR]{Style.RESET_ALL} {msg}")


def success(msg: str) -> None:
    print(f"{Fore.GREEN}[OK]{Style.RESET_ALL}    {msg}")


def log_trade(
    *,
    action: str,
    market_title: str,
    condition_id: str,
    token_id: str,
    side: str,
    usdc_amount: float,
    shares: float,
    price: float,
    target_wallet: str,
    tx_hash: str = "",
    status: str = "",
    notes: str = "",
) -> None:
    """Write a trade record to CSV and print a coloured summary line."""
    _ensure_csv()

    timestamp = datetime.now(timezone.utc).isoformat()
    with open(LOG_FILE, "a", newline="") as f:
        csv.writer(f).writerow([
            timestamp, action, market_title, condition_id, token_id,
            side, f"{usdc_amount:.4f}", f"{shares:.4f}", f"{price:.6f}",
            target_wallet, tx_hash, status, notes,
        ])

    if status == "FILLED":
        color = Fore.GREEN
    elif status in ("PENDING", "REDEEMED"):
        color = Fore.CYAN
    elif status == "SKIPPED":
        color = Fore.YELLOW
    else:
        color = Fore.RED

    tag = f"[{action}]"
    title = (market_title[:55] + "…") if len(market_title) > 56 else market_title
    print(
        f"{color}{tag:<14}{Style.RESET_ALL} {title}\n"
        f"             {side} {shares:.2f} shares @ ${price:.4f}"
        f"  =  ${usdc_amount:.2f} USDC  |  {status}"
        + (f"  |  {tx_hash[:14]}…" if tx_hash else "")
    )
