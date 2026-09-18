import json
import uuid

from fastapi import APIRouter, HTTPException, status

from app.api.dependencies import CurrentUser, DbSession
from app.core.encryption import CredentialCipher
from app.models.portfolio import HoldingMetadata
from app.repositories.portfolio import PortfolioRepository
from app.schemas.auth import MessageResponse
from app.schemas.portfolio import (
    HoldingMetadataRead,
    HoldingMetadataUpdate,
    HoldingsResponse,
    ManualPositionRead,
    ManualPositionWrite,
)
from app.services.manual_positions import ManualPositionError, ManualPositionService
from app.services.portfolio import PortfolioService

router = APIRouter()


@router.get("", response_model=HoldingsResponse)
async def holdings(user: CurrentUser, db: DbSession) -> HoldingsResponse:
    return await PortfolioService(PortfolioRepository(db)).holdings(user.id)


@router.get("/manual", response_model=list[ManualPositionRead])
async def manual_positions(user: CurrentUser, db: DbSession) -> list[ManualPositionRead]:
    return await ManualPositionService(db, CredentialCipher()).list(user.id)


@router.post(
    "/manual", response_model=ManualPositionRead, status_code=status.HTTP_201_CREATED
)
async def create_manual_position(
    payload: ManualPositionWrite, user: CurrentUser, db: DbSession
) -> ManualPositionRead:
    try:
        return await ManualPositionService(db, CredentialCipher()).create(user.id, payload)
    except ManualPositionError as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


@router.put("/manual/{position_id}", response_model=ManualPositionRead)
async def update_manual_position(
    position_id: uuid.UUID,
    payload: ManualPositionWrite,
    user: CurrentUser,
    db: DbSession,
) -> ManualPositionRead:
    try:
        result = await ManualPositionService(db, CredentialCipher()).update(
            user.id, position_id, payload
        )
    except ManualPositionError as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Manual position not found")
    return result


@router.delete("/manual/{position_id}", response_model=MessageResponse)
async def delete_manual_position(
    position_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> MessageResponse:
    if not await ManualPositionService(db, CredentialCipher()).delete(user.id, position_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Manual position not found")
    return MessageResponse(message="Manual position deleted")


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
