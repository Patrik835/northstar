from datetime import date
from typing import Literal

from fastapi import APIRouter, Query

from app.api.dependencies import CurrentUser, DbSession
from app.integrations.market_data import EcbFxRateProvider
from app.models.enums import Broker, TransactionType
from app.repositories.portfolio import PortfolioRepository
from app.schemas.activity import ActivityResponse
from app.services.activity import ActivityService

router = APIRouter()


@router.get("", response_model=ActivityResponse)
async def activity(
    user: CurrentUser,
    db: DbSession,
    broker: Broker | None = None,
    transaction_type: TransactionType | None = None,
    activity_group: Literal["trade", "dividend", "deposit"] | None = None,
    display_only: bool = False,
    date_from: date | None = None,
    date_to: date | None = None,
    search: str | None = Query(default=None, max_length=100),
    holding_key: str | None = Query(default=None, max_length=200),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> ActivityResponse:
    return await ActivityService(
        PortfolioRepository(db), fx_rates=EcbFxRateProvider(db)
    ).list(
        user.id,
        broker=broker,
        transaction_type=transaction_type,
        activity_group=activity_group,
        display_only=display_only,
        date_from=date_from,
        date_to=date_to,
        search=search,
        holding_key=holding_key,
        offset=offset,
        limit=limit,
    )
