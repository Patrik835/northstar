from typing import Literal

from fastapi import APIRouter, Query

from app.api.dependencies import CurrentUser, DbSession
from app.repositories.portfolio import PortfolioRepository
from app.schemas.performance import PortfolioPerformanceResponse
from app.services.performance import PerformanceService

router = APIRouter()


@router.get("", response_model=PortfolioPerformanceResponse)
async def performance(
    user: CurrentUser,
    db: DbSession,
    selected_range: Literal["1m", "3m", "6m", "1y", "all"] = Query(
        default="1y", alias="range"
    ),
) -> PortfolioPerformanceResponse:
    return await PerformanceService(PortfolioRepository(db)).portfolio(
        user.id, selected_range
    )
