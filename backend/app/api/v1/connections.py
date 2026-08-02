import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy.exc import IntegrityError

from app.api.dependencies import CurrentUser, DbSession
from app.core.encryption import CredentialCipher
from app.models.enums import Broker
from app.repositories.connections import ConnectionRepository
from app.schemas.auth import MessageResponse
from app.schemas.connection import ConnectionCreate, ConnectionGuide, ConnectionRead
from app.services.connection_sync import ConnectionSyncService
from app.services.connections import (
    CREDENTIAL_FIELDS,
    ConnectionService,
    InvalidConnectionCredentials,
)

router = APIRouter()

SECURITY_NOTICES = {
    Broker.TRADING212: (
        "Use a dedicated read-only API key. Never enable permissions that create, "
        "change, or cancel orders. Credentials are encrypted and never displayed again."
    ),
    Broker.ETORO: "Provide the API key and user key from your verified eToro account.",
    Broker.BINANCE: (
        "Create a read-only key: enable Reading only. Disable Spot & Margin Trading, "
        "Withdrawals, and Futures."
    ),
}

TUTORIAL_URLS = {
    Broker.TRADING212: (
        "https://helpcentre.trading212.com/hc/en-us/articles/14584770928157-Trading-212-API-key"
    ),
    Broker.ETORO: "https://api-portal.etoro.com/getting-started/authentication",
    Broker.BINANCE: (
        "https://www.binance.com/en/academy/articles/what-are-api-keys-and-security-types"
    ),
}

SETUP_STEPS = {
    Broker.TRADING212: [
        "Sign in to Trading 212 and open Settings, then API (Beta).",
        "Accept the API risk notice and choose Generate API key.",
        "Give the key a recognizable name, such as Northstar.",
        "Enable Account data and Portfolio access.",
        "Under History, enable Orders, Dividends, and Transactions. All three are "
        "needed for the activity feed.",
        "Leave every permission that creates, changes, or cancels orders disabled. "
        "Northstar only reads your investment data.",
        "If you restrict the key by IP address, add the public IP of the server where "
        "Northstar runs. For local Docker use, that is your internet connection's public IP.",
        "Create the key, then copy both the API Key and API Secret. The secret is shown only once.",
    ],
    Broker.ETORO: [
        "Sign in to eToro and open Settings, then Trading.",
        "Find API Key Management and choose Create New Key.",
        "Select the Real environment and Read permission only.",
        "Complete the identity check sent to your phone.",
        "Copy the Public API Key and User Key into the matching fields below.",
    ],
    Broker.BINANCE: [
        "Sign in to Binance and open Profile, then API Management.",
        "Create a system-generated HMAC API key and name it Northstar.",
        "Complete Binance's security verification.",
        "Under API restrictions, enable Reading only.",
        "Keep Spot & Margin Trading, Futures, and Withdrawals disabled.",
        "Copy the API Key and Secret Key. Binance may show the secret only once.",
    ],
}


@router.get("/guides", response_model=list[ConnectionGuide])
async def guides(user: CurrentUser) -> list[ConnectionGuide]:
    return [
        ConnectionGuide(
            broker=broker,
            credential_fields=list(fields),
            security_notice=SECURITY_NOTICES[broker],
            setup_steps=SETUP_STEPS[broker],
            tutorial_url=TUTORIAL_URLS[broker],
        )
        for broker, fields in CREDENTIAL_FIELDS.items()
    ]


@router.get("", response_model=list[ConnectionRead])
async def list_connections(user: CurrentUser, db: DbSession) -> list[ConnectionRead]:
    connections = await ConnectionRepository(db).for_user(user.id)
    return [ConnectionRead.model_validate(item) for item in connections]


@router.post("", response_model=ConnectionRead, status_code=status.HTTP_201_CREATED)
async def create_connection(
    payload: ConnectionCreate, user: CurrentUser, db: DbSession
) -> ConnectionRead:
    try:
        connection = await ConnectionService(db, CredentialCipher()).create(
            user.id, payload.broker, payload.credentials
        )
    except InvalidConnectionCredentials as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "This source is already connected") from exc
    return ConnectionRead.model_validate(connection)


@router.delete("/{connection_id}", response_model=MessageResponse)
async def delete_connection(
    connection_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> MessageResponse:
    if not await ConnectionService(db, CredentialCipher()).delete(connection_id, user.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Connection not found")
    return MessageResponse(message="Connection and its imported data deleted")


@router.post("/{connection_id}/sync", response_model=ConnectionRead)
async def sync_connection(
    connection_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> ConnectionRead:
    connection = await ConnectionRepository(db).owned(connection_id, user.id)
    if not connection:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Connection not found")
    if connection.broker is not Broker.TRADING212:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Synchronization for this source is not available yet",
        )
    synced = await ConnectionSyncService(db, CredentialCipher()).sync(connection)
    return ConnectionRead.model_validate(synced)
