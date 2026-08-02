import uuid
from decimal import ROUND_HALF_UP, Decimal

from app.repositories.portfolio import PortfolioRepository
from app.schemas.portfolio import AllocationItem, DashboardSummary


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
