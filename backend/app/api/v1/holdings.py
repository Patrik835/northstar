from fastapi import APIRouter

from app.api.dependencies import CurrentUser, DbSession
from app.repositories.portfolio import PortfolioRepository
from app.schemas.portfolio import HoldingsResponse
from app.services.portfolio import PortfolioService

router = APIRouter()


@router.get("", response_model=HoldingsResponse)
async def holdings(user: CurrentUser, db: DbSession) -> HoldingsResponse:
    return await PortfolioService(PortfolioRepository(db)).holdings(user.id)
