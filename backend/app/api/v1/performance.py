from fastapi import APIRouter, Query

from app.api.dependencies import CurrentUser, DbSession
from app.repositories.portfolio import PortfolioRepository
from app.schemas.performance import PerformanceRange, PortfolioPerformanceResponse
from app.services.performance import PerformanceService

router = APIRouter()


@router.get("", response_model=PortfolioPerformanceResponse)
async def performance(
    user: CurrentUser,
    db: DbSession,
    selected_range: PerformanceRange = Query(default="1y", alias="range"),  # noqa: B008
) -> PortfolioPerformanceResponse:
    return await PerformanceService(PortfolioRepository(db)).portfolio(
        user.id, selected_range
    )
