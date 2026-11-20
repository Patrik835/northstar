"""Generate the bundled asset catalogue from public market-cap rankings.

Run from the repo root: backend/.venv/bin/python -m app.refresh_asset_catalogue
with PYTHONPATH=backend, or from backend: .venv/bin/python -m app.refresh_asset_catalogue.
The generated JSON is committed and shipped with the frontend; no runtime API key is needed.
"""

import asyncio
import csv
import html
import io
import json
import os
import re
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import httpx

STOCK_URL = "https://companiesmarketcap.com/?download=csv"
CRYPTO_URL = "https://api.coingecko.com/api/v3/coins/markets"
STOCK_COUNT = 3000
CRYPTO_COUNT = 150
SYMBOL_PATTERN = re.compile(r"^[\w.&$/-]{1,32}$")


def stock_assets(csv_text: str) -> list[dict]:
    rows = sorted(csv.DictReader(io.StringIO(csv_text)), key=lambda row: int(row["Rank"]))
    assets = []
    for row in rows[:STOCK_COUNT]:
        ticker = row["Symbol"].strip().upper()
        name = html.unescape(row["Name"]).strip()
        if not SYMBOL_PATTERN.fullmatch(ticker) or not name or len(name) > 200:
            raise ValueError(f"Invalid stock at rank {row['Rank']}: {ticker!r}, {name!r}")
        assets.append({
            "ticker": ticker, "name": name, "asset_type": "stock", "isin": None,
            "catalogue_id": f"stock:{ticker}", "rank": int(row["Rank"]),
            "country": row["country"].strip(),
        })
    if len(assets) != STOCK_COUNT or len({item["ticker"] for item in assets}) != STOCK_COUNT:
        raise ValueError("Stock feed must contain 3,000 distinct ranked stock tickers")
    return assets


def crypto_assets(rows: list[dict]) -> list[dict]:
    ranked = sorted(rows, key=lambda row: row.get("market_cap_rank") or 10**9)
    assets = []
    for row in ranked[:CRYPTO_COUNT]:
        ticker = str(row["symbol"]).strip().upper()
        name = str(row["name"]).strip()
        rank = row.get("market_cap_rank")
        if not SYMBOL_PATTERN.fullmatch(ticker) or not name or len(name) > 200 or not rank:
            raise ValueError(f"Invalid crypto at rank {rank}: {ticker!r}, {name!r}")
        assets.append({
            "ticker": ticker, "name": name, "asset_type": "crypto", "isin": None,
            "catalogue_id": f"coingecko:{row['id']}", "rank": rank,
            "country": None,
        })
    if (
        len(assets) != CRYPTO_COUNT
        or len({item["catalogue_id"] for item in assets}) != CRYPTO_COUNT
        or len({item["ticker"] for item in assets}) != CRYPTO_COUNT
    ):
        raise ValueError("Crypto feed must contain 150 distinct ranked assets")
    return assets


async def fetch_catalogue() -> dict:
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        stocks, crypto = await asyncio.gather(
            client.get(STOCK_URL),
            client.get(CRYPTO_URL, params={
                "vs_currency": "usd", "order": "market_cap_desc",
                "per_page": CRYPTO_COUNT, "page": 1, "sparkline": "false",
            }),
        )
        stocks.raise_for_status()
        crypto.raise_for_status()
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ranking": "market_cap_desc",
        "stock_count": STOCK_COUNT,
        "crypto_count": CRYPTO_COUNT,
        "sources": {"stocks": STOCK_URL, "crypto": CRYPTO_URL},
        "assets": stock_assets(stocks.text) + crypto_assets(crypto.json()),
    }


def write_catalogue(payload: dict, destination: Path) -> None:
    """Publish only a fully validated snapshot; failures leave the last one intact."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=destination.parent, suffix=".json.tmp")
    try:
        os.fchmod(descriptor, 0o644)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, separators=(",", ":"))
            stream.write("\n")
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main() -> None:
    # Resolve the repository from this module rather than the caller's working directory.
    destination = Path(__file__).resolve().parents[2] / "frontend/public/asset-catalogue.json"
    payload = asyncio.run(fetch_catalogue())
    write_catalogue(payload, destination)
    collisions = [symbol for symbol, count in Counter(
        asset["ticker"] for asset in payload["assets"] if asset["asset_type"] == "crypto"
    ).items() if count > 1]
    print(f"Saved {STOCK_COUNT} stocks and {CRYPTO_COUNT} crypto assets to {destination}")
    print(f"Catalogue generated at {payload['generated_at']}; shared crypto symbols: {collisions}")


if __name__ == "__main__":
    main()
