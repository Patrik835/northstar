from fastapi import APIRouter

from app.api.dependencies import AppSettings, CurrentUser, DbSession
from app.core.encryption import CredentialCipher
from app.repositories.portfolio import PortfolioRepository
from app.schemas.portfolio import DashboardSummary, FeatureStatus
from app.services.manual_positions import QUOTE_MAX_AGE, ManualPositionService
from app.services.portfolio import PortfolioService

router = APIRouter()


@router.get("/summary", response_model=DashboardSummary)
async def summary(user: CurrentUser, db: DbSession) -> DashboardSummary:
    await ManualPositionService(db, CredentialCipher()).refresh(
        user.id, max_age=QUOTE_MAX_AGE
    )
    return await PortfolioService(PortfolioRepository(db)).dashboard(user.id)


@router.get("/features", response_model=FeatureStatus)
async def features(user: CurrentUser, settings: AppSettings) -> FeatureStatus:
    return FeatureStatus(
        ai=settings.ai_available,
        news=settings.news_available,
        benchmarks=settings.benchmarks_available,
    )
