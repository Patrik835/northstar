from datetime import date
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError
from test_csv_exports import rows
from test_holdings_service import HoldingsRepository, _row, _transaction

from app.core.config import Settings
from app.integrations.market_data.current_prices import CurrentPriceError, CurrentPriceProvider
from app.models.enums import AssetType, Broker, TransactionType
from app.models.instrument import Instrument
from app.schemas.performance import PortfolioHistoryPoint
from app.services.analytics import _growth_series
from app.services.csv_exports import holdings_csv
from app.services.portfolio import PortfolioService


@pytest.mark.asyncio
async def test_partial_cost_excludes_unknown_source_value():
    instrument = Instrument(
        id=uuid4(), canonical_symbol="BTC", name="Bitcoin", asset_type=AssetType.CRYPTO
    )
    known = _row(
        Broker.TRADING212,
        instrument,
        provider_id="a",
        ticker="BTC",
        quantity="1",
        value="150",
        reported_pnl="50",
    )
    known.position.asset_type = AssetType.CRYPTO
    unknown = _row(
        Broker.BINANCE, instrument, provider_id="b", ticker="BTC", quantity="1", value="1000"
    )
    unknown.position.asset_type = AssetType.CRYPTO
    unknown.position.average_price = None
    portfolio = await PortfolioService(
        HoldingsRepository(
            [known, unknown],
            [
                _transaction(
                    known.connection_id,
                    instrument,
                    TransactionType.BUY,
                    quantity="1",
                    value="100",
                    day=1,
                )
            ],
        )
    ).holdings(uuid4())
    holding = portfolio.holdings[0]
    assert holding.calculated_gain_eur == Decimal(50)
    assert holding.performance.open_pnl_eur == Decimal(50)
    assert portfolio.performance.coverage == "partial"
    assert portfolio.performance.total_return_eur is None
    exported = holdings_csv(portfolio)
    row = rows(exported)[0]
    assert Decimal(row["open_pnl_percentage"]) == Decimal(50)
    assert row["open_pnl_coverage"] == "partial"


@pytest.mark.parametrize("currency", ["GBp", "GBX"])
@pytest.mark.asyncio
async def test_pence_quote_normalization(currency):
    provider = CurrentPriceProvider(
        httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "chart": {
                        "result": [
                            {
                                "meta": {
                                    "regularMarketPrice": 125,
                                    "currency": currency,
                                    "regularMarketTime": 1770000000,
                                }
                            }
                        ]
                    }
                },
            )
        )
    )
    price, unit, _ = await provider.price("VOD.L", AssetType.STOCK)
    assert (price, unit) == (Decimal("1.25"), "GBP")


def test_growth_neutralizes_deposits_withdrawals_and_gap_flows():
    points = [
        PortfolioHistoryPoint(
            date=date(2026, 1, day),
            total_value_eur=Decimal(value),
            net_invested_eur=Decimal(100),
            invested_value_eur=Decimal(value),
        )
        for day, value in [(1, 100), (2, 200), (4, 300), (5, 250)]
    ]
    series = _growth_series(
        points, {date(2026, 1, 3): Decimal(100), date(2026, 1, 5): Decimal(-50)}
    )
    assert [value for _, value in series] == [100, 200, 200, 200]


def test_production_settings_fail_closed():
    common = dict(
        app_secret_key="x" * 40,
        credential_encryption_key="MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
        app_env="production",
    )
    with pytest.raises(ValidationError) as invalid:
        Settings(**common)
    assert common["app_secret_key"] not in str(invalid.value)
    assert common["credential_encryption_key"] not in str(invalid.value)
    Settings(
        **common,
        cookie_secure=True,
        public_web_url="https://app.example.com",
        frontend_origin="https://app.example.com",
    )
    with pytest.raises(ValidationError):
        Settings(app_secret_key="x" * 40, credential_encryption_key="replace-this-key")


@pytest.mark.asyncio
async def test_quote_rejects_a_different_listing():
    provider = CurrentPriceProvider(
        httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "chart": {
                        "result": [
                            {
                                "meta": {
                                    "symbol": "VOD",
                                    "regularMarketPrice": 125,
                                    "currency": "GBP",
                                    "regularMarketTime": 1770000000,
                                }
                            }
                        ]
                    }
                },
            )
        )
    )
    with pytest.raises(CurrentPriceError):
        await provider.price("VOD.L", AssetType.STOCK)


def test_https_public_url_is_enough_for_production():
    settings = Settings(
        _env_file=None,
        app_secret_key="x" * 40,
        credential_encryption_key="MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
        app_env="production",
        public_web_url="https://app.example.com",
    )
    assert settings.secure_cookies is True
    assert settings.cors_origin == "https://app.example.com"
