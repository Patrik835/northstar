from datetime import date
from typing import Literal

from fastapi import APIRouter, Query, Response

from app.api.dependencies import CurrentUser, DbSession
from app.models.enums import Broker, TransactionType
from app.repositories.portfolio import PortfolioRepository
from app.schemas.performance import PerformanceRange
from app.services.csv_exports import AssetGroup, CsvExportService

router = APIRouter()


def _response(content: bytes, name: str) -> Response:
    filename = f"northstar-{name}-{date.today().isoformat()}.csv"
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "private, no-store",
        },
    )


@router.get("/holdings.csv")
async def export_holdings(
    user: CurrentUser,
    db: DbSession,
    broker: Broker | None = None,
    asset_group: AssetGroup = "all",
    search: str | None = Query(default=None, max_length=100),
) -> Response:
    content = await CsvExportService(PortfolioRepository(db)).holdings(
        user.id,
        broker=broker,
        asset_group=asset_group,
        search=search,
    )
    return _response(content, "holdings")


@router.get("/transactions.csv")
async def export_transactions(
    user: CurrentUser,
    db: DbSession,
    broker: Broker | None = None,
    transaction_type: TransactionType | None = None,
    activity_group: Literal["trade", "dividend", "deposit"] | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    search: str | None = Query(default=None, max_length=100),
) -> Response:
    content = await CsvExportService(PortfolioRepository(db)).activity(
        user.id,
        broker=broker,
        transaction_type=transaction_type,
        activity_group=activity_group,
        date_from=date_from,
        date_to=date_to,
        search=search,
    )
    return _response(content, "transactions")


@router.get("/income.csv")
async def export_income(
    user: CurrentUser,
    db: DbSession,
    broker: Broker | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    search: str | None = Query(default=None, max_length=100),
) -> Response:
    content = await CsvExportService(PortfolioRepository(db)).income(
        user.id,
        broker=broker,
        date_from=date_from,
        date_to=date_to,
        search=search,
    )
    return _response(content, "income")


@router.get("/performance.csv")
async def export_performance(
    user: CurrentUser,
    db: DbSession,
    selected_range: PerformanceRange = Query(default="1y", alias="range"),  # noqa: B008
) -> Response:
    content = await CsvExportService(PortfolioRepository(db)).performance(user.id, selected_range)
    return _response(content, f"performance-{selected_range}")
