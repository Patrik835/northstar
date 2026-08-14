import json

from fastapi import APIRouter, HTTPException, status

from app.api.dependencies import CurrentUser, DbSession
from app.models.portfolio import HoldingMetadata
from app.repositories.portfolio import PortfolioRepository
from app.schemas.portfolio import (
    HoldingMetadataRead,
    HoldingMetadataUpdate,
    HoldingsResponse,
)
from app.services.portfolio import PortfolioService

router = APIRouter()


@router.get("", response_model=HoldingsResponse)
async def holdings(user: CurrentUser, db: DbSession) -> HoldingsResponse:
    return await PortfolioService(PortfolioRepository(db)).holdings(user.id)


@router.put("/{holding_key}/metadata", response_model=HoldingMetadataRead)
async def update_holding_metadata(
    holding_key: str,
    payload: HoldingMetadataUpdate,
    user: CurrentUser,
    db: DbSession,
) -> HoldingMetadataRead:
    repository = PortfolioRepository(db)
    portfolio = await PortfolioService(repository).holdings(user.id)
    if holding_key not in {item.key for item in portfolio.holdings}:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Holding not found")
    metadata = await repository.get_holding_metadata(user.id, holding_key)
    if metadata is None:
        metadata = HoldingMetadata(user_id=user.id, holding_key=holding_key)
    metadata.category = payload.category
    metadata.tags_json = json.dumps(payload.tags)
    metadata.notes = payload.notes
    metadata.target_allocation_percentage = payload.target_allocation_percentage
    saved = await repository.save_holding_metadata(metadata)
    return HoldingMetadataRead(
        holding_key=saved.holding_key,
        category=saved.category,
        tags=payload.tags,
        notes=saved.notes,
        target_allocation_percentage=saved.target_allocation_percentage,
        updated_at=saved.updated_at,
    )
