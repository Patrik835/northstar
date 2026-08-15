import re
from dataclasses import dataclass

from app.models.enums import AssetType
from app.models.instrument import Instrument


@dataclass(frozen=True, slots=True)
class InstrumentClassification:
    sector: str | None
    geography: str | None


# Deliberately small and reviewable. Provider metadata always wins over this fallback.
_SYMBOL_PROFILES: dict[str, tuple[str, str]] = {
    "AAPL": ("Technology", "United States"),
    "AMD": ("Technology", "United States"),
    "AMZN": ("Consumer Discretionary", "United States"),
    "ASML": ("Technology", "Netherlands"),
    "AVGO": ("Technology", "United States"),
    "BABA": ("Consumer Discretionary", "China"),
    "CRWV": ("Technology", "United States"),
    "DMYI": ("Technology", "United States"),
    "DUOL": ("Consumer Discretionary", "United States"),
    "FB": ("Communication Services", "United States"),
    "FICO": ("Technology", "United States"),
    "GOOG": ("Communication Services", "United States"),
    "GOOGL": ("Communication Services", "United States"),
    "IONQ": ("Technology", "United States"),
    "META": ("Communication Services", "United States"),
    "MSFT": ("Technology", "United States"),
    "MU": ("Technology", "United States"),
    "NFLX": ("Communication Services", "United States"),
    "NVDA": ("Technology", "United States"),
    "PEP": ("Consumer Staples", "United States"),
    "PLTR": ("Technology", "United States"),
    "PYPL": ("Financials", "United States"),
    "SNAP": ("Communication Services", "United States"),
    "SPY5.L": ("Diversified", "United States"),
    "TSM": ("Technology", "Taiwan"),
    "UBER": ("Industrials", "United States"),
    "V": ("Financials", "United States"),
    "WEN": ("Consumer Discretionary", "United States"),
}

_ISIN_COUNTRIES = {
    "AT": "Austria",
    "BE": "Belgium",
    "CA": "Canada",
    "CH": "Switzerland",
    "CN": "China",
    "CZ": "Czechia",
    "DE": "Germany",
    "DK": "Denmark",
    "ES": "Spain",
    "FI": "Finland",
    "FR": "France",
    "GB": "United Kingdom",
    "HK": "Hong Kong",
    "IE": "Ireland",
    "IT": "Italy",
    "JP": "Japan",
    "LU": "Luxembourg",
    "NL": "Netherlands",
    "NO": "Norway",
    "PL": "Poland",
    "PT": "Portugal",
    "SE": "Sweden",
    "SK": "Slovakia",
    "TW": "Taiwan",
    "US": "United States",
}

_SECTOR_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "Technology",
        (
            "semiconductor",
            "software",
            "cybersecurity",
            "cloud computing",
            "information technology",
            "quantum computing",
        ),
    ),
    (
        "Financials",
        (
            "banking",
            "insurance",
            "financial services",
            "payments",
            "credit services",
            "asset management",
        ),
    ),
    (
        "Health Care",
        ("healthcare", "health care", "pharmaceutical", "biotechnology", "medical device"),
    ),
    (
        "Communication Services",
        ("telecommunication", "interactive media", "social media", "entertainment", "streaming"),
    ),
    (
        "Consumer Discretionary",
        ("automotive", "restaurants", "retail", "travel", "leisure", "apparel"),
    ),
    ("Consumer Staples", ("food products", "beverages", "household products", "personal products")),
    (
        "Industrials",
        (
            "aerospace",
            "defense",
            "transportation",
            "logistics",
            "industrial machinery",
            "construction",
        ),
    ),
    ("Energy", ("oil", "gas", "energy equipment", "energy exploration")),
    ("Utilities", ("electric utility", "water utility", "gas utility", "renewable utility")),
    ("Real Estate", ("real estate", "reit")),
    ("Materials", ("chemicals", "metals", "mining", "construction materials")),
)

_ETF_GEOGRAPHY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Global", ("all world", "all-world", "msci world", "global")),
    ("Emerging Markets", ("emerging markets", "emerging market")),
    ("United States", ("s&p 500", "s & p 500", "nasdaq", "russell 2000", "united states", "usa")),
    ("Europe", ("stoxx europe", "msci europe", "europe")),
    ("China", ("china", "csi 300")),
    ("Japan", ("japan", "nikkei", "topix")),
)

_SECTOR_ALIASES = {
    "communication services": "Communication Services",
    "consumer discretionary": "Consumer Discretionary",
    "consumer staples": "Consumer Staples",
    "energy": "Energy",
    "financial": "Financials",
    "financials": "Financials",
    "health care": "Health Care",
    "healthcare": "Health Care",
    "industrial": "Industrials",
    "industrials": "Industrials",
    "information technology": "Technology",
    "materials": "Materials",
    "real estate": "Real Estate",
    "technology": "Technology",
    "utilities": "Utilities",
}

_GEOGRAPHY_ALIASES = {
    "america": "United States",
    "england": "United Kingdom",
    "great britain": "United Kingdom",
    "the netherlands": "Netherlands",
    "u k": "United Kingdom",
    "u s": "United States",
    "u s a": "United States",
    "uk": "United Kingdom",
    "united states of america": "United States",
    "usa": "United States",
}


def _normalized(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").casefold()).strip()


def _rule_match(text: str, rules: tuple[tuple[str, tuple[str, ...]], ...]) -> str | None:
    padded = f" {text} "
    for label, phrases in rules:
        if any(f" {_normalized(phrase)} " in padded for phrase in phrases):
            return label
    return None


def _canonical_metadata(value: str | None, aliases: dict[str, str]) -> str | None:
    if not value or not value.strip():
        return None
    return aliases.get(_normalized(value), value.strip())


def classify_instrument(instrument: Instrument) -> InstrumentClassification:
    """Resolve stable allocation labels without inventing uncertain metadata."""

    symbol = instrument.canonical_symbol.upper().strip()
    profile = _SYMBOL_PROFILES.get(symbol)
    if profile is None and "." in symbol:
        profile = _SYMBOL_PROFILES.get(symbol.split(".", 1)[0])

    descriptive_text = _normalized(f"{instrument.name} {instrument.industry or ''}")
    sector = _canonical_metadata(instrument.sector, _SECTOR_ALIASES)
    geography = _canonical_metadata(instrument.country, _GEOGRAPHY_ALIASES)
    sector = sector or (profile[0] if profile else None)
    geography = geography or (profile[1] if profile else None)

    if sector is None:
        sector = _rule_match(descriptive_text, _SECTOR_RULES)
    if sector is None and instrument.asset_type is AssetType.ETF:
        sector = "Diversified"

    if geography is None and instrument.asset_type is AssetType.ETF:
        geography = _rule_match(descriptive_text, _ETF_GEOGRAPHY_RULES)
    if geography is None and instrument.isin and len(instrument.isin) >= 2:
        geography = _ISIN_COUNTRIES.get(instrument.isin[:2].upper())

    return InstrumentClassification(sector=sector, geography=geography)
