import json
from collections import Counter
from decimal import Decimal
from pathlib import Path

import pytest

from app.refresh_asset_catalogue import crypto_assets, stock_assets
from app.schemas.portfolio import ManualPositionWrite


def test_bundled_catalogue_is_complete_and_every_asset_can_be_saved() -> None:
    path = Path(__file__).resolve().parents[2] / "frontend/public/asset-catalogue.json"
    catalogue = json.loads(path.read_text(encoding="utf-8"))
    assets = catalogue["assets"]
    assert Counter(asset["asset_type"] for asset in assets) == {"stock": 3000, "crypto": 150}
    assert len({asset["catalogue_id"] for asset in assets}) == 3150
    assert catalogue["ranking"] == "market_cap_desc"
    for asset in assets:
        payload = ManualPositionWrite(
            ticker=asset["ticker"], name=asset["name"], asset_type=asset["asset_type"],
            quantity=Decimal("1"), average_price=Decimal("100"),
        )
        assert payload.ticker == asset["ticker"]
        assert "&amp;" not in payload.name


def test_incomplete_stock_feed_is_rejected() -> None:
    with pytest.raises(ValueError, match="3,000"):
        stock_assets('Rank,Name,Symbol,marketcap,country\n1,Apple,AAPL,1,United States\n')


def test_crypto_feed_does_not_silently_accept_partial_rankings() -> None:
    with pytest.raises(ValueError, match="150"):
        crypto_assets([{"id": "bitcoin", "symbol": "btc", "name": "Bitcoin", "market_cap_rank": 1}])


def test_crypto_feed_rejects_duplicate_symbols_that_would_merge_distinct_tokens() -> None:
    rows = [
        {"id": f"token-{rank}", "symbol": f"T{rank}", "name": f"Token {rank}",
         "market_cap_rank": rank}
        for rank in range(1, 151)
    ]
    rows[-1]["symbol"] = rows[0]["symbol"]
    with pytest.raises(ValueError, match="150"):
        crypto_assets(rows)
