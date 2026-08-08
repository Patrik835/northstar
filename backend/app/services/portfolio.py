import uuid
from decimal import ROUND_HALF_UP, Decimal

from app.repositories.portfolio import PortfolioRepository
from app.schemas.portfolio import (
    AllocationItem,
    DashboardSummary,
    Holding,
    HoldingSource,
    HoldingsResponse,
)


def percentage(value: Decimal, total: Decimal) -> Decimal:
    if not total:
        return Decimal("0")
    return (value * 100 / total).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class PortfolioService:
    def __init__(self, repository: PortfolioRepository) -> None:
        self.repository = repository

    async def dashboard(self, user_id: uuid.UUID) -> DashboardSummary:
        total = await self.repository.total(user_id)
        source_rows = await self.repository.by_source(user_id)
        asset_rows = await self.repository.by_asset_type(user_id)
        return DashboardSummary(
            total_value_eur=total,
            positions_count=await self.repository.position_count(user_id),
            by_source=[
                AllocationItem(
                    label=label.value,
                    value_eur=value,
                    percentage=percentage(value, total),
                )
                for label, value in source_rows
            ],
            by_asset_type=[
                AllocationItem(
                    label=label.value,
                    value_eur=value,
                    percentage=percentage(value, total),
                )
                for label, value in asset_rows
            ],
            data_notice="History begins when each live connection is first synchronized.",
        )

    async def holdings(self, user_id: uuid.UUID) -> HoldingsResponse:
        rows = await self.repository.holding_positions(user_id)
        total = sum((row.position.current_value_eur for row in rows), Decimal(0))
        grouped: dict[str, list] = {}
        for row in rows:
            key = (
                str(row.instrument.id)
                if row.instrument
                else f"unmatched:{row.position.id}"
            )
            grouped.setdefault(key, []).append(row)

        holdings: list[Holding] = []
        for key, instrument_rows in grouped.items():
            first = instrument_rows[0]
            instrument = first.instrument
            value = sum(
                (row.position.current_value_eur for row in instrument_rows), Decimal(0)
            )
            sources = [
                HoldingSource(
                    broker=row.broker,
                    connection_id=row.connection_id,
                    provider_instrument_id=row.position.instrument_id,
                    provider_symbol=row.position.ticker,
                    provider_name=row.position.name,
                    quantity=row.position.quantity,
                    average_price=row.position.average_price,
                    current_value=row.position.current_value,
                    currency=row.position.currency,
                    current_value_eur=row.position.current_value_eur,
                    instrument_percentage=percentage(row.position.current_value_eur, value),
                    last_synced_at=row.last_synced_at,
                )
                for row in sorted(instrument_rows, key=lambda item: item.broker.value)
            ]
            holdings.append(
                Holding(
                    key=key,
                    canonical_instrument_id=instrument.id if instrument else None,
                    symbol=(
                        instrument.canonical_symbol if instrument else first.position.ticker
                    ),
                    name=(
                        instrument.name
                        if instrument
                        else first.position.name or first.position.ticker
                    ),
                    isin=instrument.isin if instrument else None,
                    asset_type=(
                        instrument.asset_type if instrument else first.position.asset_type
                    ),
                    total_quantity=sum(
                        (row.position.quantity for row in instrument_rows), Decimal(0)
                    ),
                    total_value_eur=value,
                    portfolio_percentage=percentage(value, total),
                    source_count=len(sources),
                    sources=sources,
                )
            )

        source_values: dict = {}
        for row in rows:
            source_values[row.broker] = (
                source_values.get(row.broker, Decimal(0))
                + row.position.current_value_eur
            )
        return HoldingsResponse(
            total_value_eur=total,
            instrument_count=len(holdings),
            position_count=len(rows),
            unmatched_positions=sum(row.instrument is None for row in rows),
            sources=[
                AllocationItem(
                    label=broker.value,
                    value_eur=value,
                    percentage=percentage(value, total),
                )
                for broker, value in sorted(
                    source_values.items(), key=lambda item: item[1], reverse=True
                )
            ],
            holdings=sorted(holdings, key=lambda item: item.total_value_eur, reverse=True),
        )
