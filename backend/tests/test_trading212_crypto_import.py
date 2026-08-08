from decimal import Decimal

import httpx
import pytest

from app.integrations.market_data import BinanceCryptoPriceProvider
from app.models.enums import TransactionType
from app.models.portfolio import Transaction
from app.services.trading212_crypto_import import (
    CryptoCsvImportError,
    Trading212CryptoCsvParser,
    _reconstruct_holdings,
)


def test_parser_reads_crypto_activity_and_skips_cancelled_rows() -> None:
    content = b"""Type,Status,Coin,Date,Quantity,Price,Total,Currency,Transaction ID
Buy,Completed,BTC,2026-01-02 10:00:00,0.10,40000,4000,EUR,buy-1
Sell,Completed,BTC,2026-02-03 11:00:00,0.02,50000,1000,EUR,sell-1
Deposit,Completed,,2026-01-01 09:00:00,,,5000,EUR,deposit-1
Buy,Cancelled,ETH,2026-02-04 12:00:00,1,2000,2000,EUR,cancelled-1
"""

    result = Trading212CryptoCsvParser().parse(content)

    assert result.rows_read == 4
    assert len(result.transactions) == 3
    assert result.transactions[0].external_id == "trading212-crypto:buy-1"
    assert result.transactions[0].ticker == "BTC"
    assert result.transactions[0].quantity == Decimal("0.10")
    assert result.transactions[1].transaction_type is TransactionType.SELL
    assert result.transactions[2].transaction_type is TransactionType.DEPOSIT
    assert len(result.warnings) == 1


def test_parser_rejects_partial_export_that_lacks_required_columns() -> None:
    with pytest.raises(CryptoCsvImportError, match="Missing columns"):
        Trading212CryptoCsvParser().parse(b"Coin,Quantity\nBTC,1\n")


def test_reconstruction_uses_moving_average_cost() -> None:
    transactions = [
        Transaction(
            ticker="BTC",
            transaction_type=TransactionType.BUY,
            quantity=Decimal("2"),
            value=Decimal("200"),
            value_eur=Decimal("200"),
        ),
        Transaction(
            ticker="BTC",
            transaction_type=TransactionType.SELL,
            quantity=Decimal("0.5"),
            value=Decimal("75"),
            value_eur=Decimal("75"),
        ),
    ]

    state = _reconstruct_holdings(transactions)["BTC"]

    assert state.quantity == Decimal("1.5")
    assert state.cost_eur == Decimal("150.0")
    assert state.last_price_eur == Decimal("1.5E+2")


@pytest.mark.asyncio
async def test_public_binance_prices_convert_crypto_to_eur() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/exchangeInfo":
            return httpx.Response(
                200,
                json={
                    "symbols": [
                        {
                            "symbol": "BTCUSDT",
                            "status": "TRADING",
                            "baseAsset": "BTC",
                            "quoteAsset": "USDT",
                        },
                        {
                            "symbol": "EURUSDT",
                            "status": "TRADING",
                            "baseAsset": "EUR",
                            "quoteAsset": "USDT",
                        },
                    ]
                },
                request=request,
            )
        if request.url.path == "/api/v3/ticker/price":
            return httpx.Response(
                200,
                json=[
                    {"symbol": "BTCUSDT", "price": "60000"},
                    {"symbol": "EURUSDT", "price": "1.2"},
                ],
                request=request,
            )
        raise AssertionError(request.url.path)

    provider = BinanceCryptoPriceProvider(transport=httpx.MockTransport(handler))

    assert (await provider.rates_to_eur({"BTC"}))["BTC"] == Decimal("50000.00000000000000000000000")
