BINANCE_ASSET_EQUIVALENTS: dict[str, str] = {
    # Binance exposes this internal Earn/lending balance in Spot account responses,
    # but it has no independent Spot market. Its units represent underlying USDC.
    "LDUSDC": "USDC",
}


def binance_valuation_asset(asset: str) -> str:
    normalized = asset.strip().upper()
    return BINANCE_ASSET_EQUIVALENTS.get(normalized, normalized)
