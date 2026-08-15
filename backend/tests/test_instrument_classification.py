from app.models.enums import AssetType
from app.models.instrument import Instrument
from app.services.instrument_classification import classify_instrument


def instrument(
    symbol: str,
    name: str,
    *,
    asset_type: AssetType = AssetType.STOCK,
    isin: str | None = None,
    sector: str | None = None,
    country: str | None = None,
    industry: str | None = None,
) -> Instrument:
    return Instrument(
        identity_key=f"test:{symbol}:{isin or name}",
        canonical_symbol=symbol,
        name=name,
        asset_type=asset_type,
        isin=isin,
        sector=sector,
        country=country,
        industry=industry,
    )


def test_verified_metadata_wins_over_curated_profile() -> None:
    result = classify_instrument(
        instrument("AAPL", "Apple", sector="Verified sector", country="Verified country")
    )

    assert result.sector == "Verified sector"
    assert result.geography == "Verified country"


def test_provider_labels_are_normalized_to_avoid_duplicate_buckets() -> None:
    result = classify_instrument(
        instrument("AAPL", "Apple", sector="TECHNOLOGY", country="USA")
    )

    assert result.sector == "Technology"
    assert result.geography == "United States"


def test_curated_profile_handles_foreign_adrs_and_symbol_aliases() -> None:
    tsm = classify_instrument(instrument("TSM", "Taiwan Semiconductor", isin="US8740391003"))
    meta = classify_instrument(instrument("FB", "Meta Platforms"))

    assert tsm.sector == "Technology"
    assert tsm.geography == "Taiwan"
    assert meta.sector == "Communication Services"
    assert meta.geography == "United States"


def test_isin_and_industry_rules_fill_only_known_fields() -> None:
    result = classify_instrument(
        instrument(
            "NEW",
            "Example NV",
            isin="NL0000000001",
            industry="Semiconductor equipment",
        )
    )

    assert result.sector == "Technology"
    assert result.geography == "Netherlands"


def test_broad_market_etf_uses_fund_mandate_without_look_through() -> None:
    result = classify_instrument(
        instrument(
            "INDEX.L",
            "Example S&P 500 UCITS ETF",
            asset_type=AssetType.ETF,
            isin="IE0000000001",
        )
    )

    assert result.sector == "Diversified"
    assert result.geography == "United States"


def test_unknown_stock_remains_unclassified() -> None:
    result = classify_instrument(instrument("UNKNOWN", "Opaque Holdings"))

    assert result.sector is None
    assert result.geography is None
