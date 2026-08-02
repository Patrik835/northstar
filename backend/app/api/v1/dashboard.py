from fastapi import APIRouter

from app.api.dependencies import AppSettings, CurrentUser, DbSession
from app.repositories.portfolio import PortfolioRepository
from app.schemas.portfolio import DashboardSummary, FeatureStatus
from app.services.portfolio import PortfolioService

router = APIRouter()


@router.get("/summary", response_model=DashboardSummary)
async def summary(user: CurrentUser, db: DbSession) -> DashboardSummary:
    return await PortfolioService(PortfolioRepository(db)).dashboard(user.id)


@router.get("/features", response_model=FeatureStatus)
async def features(user: CurrentUser, settings: AppSettings) -> FeatureStatus:
    return FeatureStatus(
        ai=settings.ai_enabled,
        news=settings.news_enabled,
        benchmarks=settings.benchmarks_enabled,
    )

