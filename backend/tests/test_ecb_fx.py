from decimal import Decimal

import httpx
import pytest

from app.integrations.market_data import EcbFxRateProvider, FxRateError


def _transport() -> httpx.MockTransport:
    xml = b"""<?xml version="1.0" encoding="UTF-8"?>
    <Envelope><Cube><Cube time="2026-08-06">
      <Cube currency="USD" rate="1.2000"/>
      <Cube currency="GBP" rate="0.8000"/>
    </Cube></Cube></Envelope>"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=xml, request=request)

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_ecb_converts_reference_currency_to_eur() -> None:
    provider = EcbFxRateProvider(transport=_transport())

    assert await provider.convert_to_eur(Decimal("120"), "USD") == Decimal("100")
    assert await provider.convert_to_eur(Decimal("10"), "EUR") == Decimal("10")


@pytest.mark.asyncio
async def test_ecb_rejects_unsupported_currency() -> None:
    provider = EcbFxRateProvider(transport=_transport())

    with pytest.raises(FxRateError, match="does not publish"):
        await provider.convert_to_eur(Decimal("1"), "XYZ")
