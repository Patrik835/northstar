from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query, status

from app.api.dependencies import CurrentUser, DbSession
from app.repositories.analytics import AnalyticsRepository
from app.repositories.portfolio import PortfolioRepository
from app.schemas.analytics import (
    AnalyticsResponse,
    BenchmarkUpdate,
    TargetsUpdate,
)
from app.schemas.performance import PerformanceRange
from app.services.analytics import AnalyticsService
from app.services.portfolio import PortfolioService

router = APIRouter()


def service(db: DbSession) -> AnalyticsService:
    return AnalyticsService(PortfolioRepository(db), AnalyticsRepository(db))


@router.get("", response_model=AnalyticsResponse)
async def analytics(
    user: CurrentUser,
    db: DbSession,
    selected_range: PerformanceRange = Query(default="1y", alias="range"),  # noqa: B008
) -> AnalyticsResponse:
    return await service(db).get(user.id, selected_range)


@router.put("/benchmark", response_model=AnalyticsResponse)
async def update_benchmark(
    payload: BenchmarkUpdate,
    user: CurrentUser,
    db: DbSession,
) -> AnalyticsResponse:
    repository = AnalyticsRepository(db)
    if payload.instrument_id is not None:
        allowed = {item.id for item in await repository.benchmark_options()}
        if payload.instrument_id not in allowed:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Choose an ETF with cached benchmark history.",
            )
    await repository.set_benchmark(user.id, payload.instrument_id)
    return await service(db).get(user.id, "1y")


@router.put("/targets", response_model=AnalyticsResponse)
async def update_targets(
    payload: TargetsUpdate,
    user: CurrentUser,
    db: DbSession,
) -> AnalyticsResponse:
    portfolio_repository = PortfolioRepository(db)
    holdings = await PortfolioService(portfolio_repository).holdings(user.id)
    current = {
        item.key: item.target_allocation_percentage
        for item in holdings.holdings
        if item.asset_type.value != "cash"
    }
    updates = {item.holding_key: item.target_percentage for item in payload.items}
    unknown = set(updates) - set(current)
    if unknown:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Holding not found")
    current.update(updates)
    total = sum((value or Decimal(0) for value in current.values()), Decimal(0))
    if total > 100:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Target allocations cannot total more than 100%.",
        )
    analytics_repository = AnalyticsRepository(db)
    await analytics_repository.save_targets(user.id, updates)
    return await service(db).get(user.id, "1y")
