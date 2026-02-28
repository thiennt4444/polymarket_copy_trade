import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # Target wallet to copy trade
    TARGET_WALLET: str = os.getenv("TARGET_WALLET", "").lower()

    # Our trading wallet private key
    PRIVATE_KEY: str = os.getenv("PRIVATE_KEY", "")

    # Fixed USDC amount to bet on every copied trade
    FIXED_USDC: float = float(os.getenv("FIXED_USDC", "10"))

    # Safety limits (applied on top of FIXED_USDC)
    MIN_TRADE_USDC: float = float(os.getenv("MIN_TRADE_USDC", "1"))
    MAX_TRADE_USDC: float = float(os.getenv("MAX_TRADE_USDC", "100"))

    # Risk controls
    BUY_ONLY: bool = os.getenv("BUY_ONLY", "true").lower() == "true"
    MAX_SLIPPAGE_PCT: float = float(os.getenv("MAX_SLIPPAGE_PCT", "2.0"))

    # Automation
    AUTO_REDEEM: bool = os.getenv("AUTO_REDEEM", "true").lower() == "true"
    POLL_INTERVAL: int = int(os.getenv("POLL_INTERVAL", "30"))

    # Polymarket endpoints (public, no API key needed)
    CLOB_HOST: str = "https://clob.polymarket.com"
    DATA_API: str = "https://data-api.polymarket.com"
    GAMMA_API: str = "https://gamma-api.polymarket.com"

    # Polygon network
    CHAIN_ID: int = 137
    POLYGON_RPC: str = "https://polygon-rpc.com"

    # CTF Exchange on Polygon (for redemption)
    CTF_EXCHANGE: str = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"
    USDC_ADDRESS: str = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"

    @staticmethod
    def validate() -> None:
        errors = []

        if not Config.TARGET_WALLET or Config.TARGET_WALLET == "0x" + "0" * 40:
            errors.append("TARGET_WALLET must be set to a valid wallet address")

        if not Config.PRIVATE_KEY or len(Config.PRIVATE_KEY) < 64:
            errors.append("PRIVATE_KEY must be a valid 32-byte hex private key")

        if Config.FIXED_USDC <= 0:
            errors.append("FIXED_USDC must be greater than 0")

        if Config.MIN_TRADE_USDC <= 0:
            errors.append("MIN_TRADE_USDC must be greater than 0")

        if Config.MAX_TRADE_USDC < Config.MIN_TRADE_USDC:
            errors.append("MAX_TRADE_USDC must be >= MIN_TRADE_USDC")

        if Config.POLL_INTERVAL < 10:
            errors.append("POLL_INTERVAL must be at least 10 seconds")

        if errors:
            raise ValueError("\n  - ".join(["Config errors:"] + errors))
