import uuid
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status
from sqlalchemy.exc import IntegrityError

from app.api.dependencies import CurrentUser, DbSession
from app.core.config import get_settings
from app.core.encryption import CredentialCipher
from app.models.broker import BrokerConnection
from app.models.enums import Broker, SyncTrigger
from app.repositories.connections import ConnectionRepository
from app.schemas.auth import MessageResponse
from app.schemas.connection import (
    ConnectionCreate,
    ConnectionGuide,
    ConnectionRead,
    CryptoCsvImportResult,
    SyncRunRead,
)
from app.services.connection_sync import ConnectionSyncService
from app.services.connections import (
    CREDENTIAL_FIELDS,
    ConnectionService,
    InvalidConnectionCredentials,
)
from app.services.trading212_crypto_import import (
    MAX_CSV_BYTES,
    CryptoCsvImportError,
    Trading212CryptoImportService,
)

router = APIRouter()
settings = get_settings()


def _connection_read(connection: BrokerConnection) -> ConnectionRead:
    return ConnectionRead.from_connection(connection, settings.portfolio_sync_minutes)


SECURITY_NOTICES = {
    Broker.TRADING212: (
        "Use a dedicated read-only API key. Never enable permissions that create, "
        "change, or cancel orders. Credentials are encrypted and never displayed again."
    ),
    Broker.ETORO: (
        "Provide the Public Key and Private Key shown by eToro. Northstar sends them "
        "as the documented x-api-key and x-user-key headers and never requests trading access."
    ),
    Broker.BINANCE: (
        "Create a read-only key: enable Reading only. Disable Spot & Margin Trading, "
        "Withdrawals, and Futures."
    ),
}

CREDENTIAL_LABELS = {
    Broker.TRADING212: {
        "api_key": "API key",
        "api_secret": "API secret",
    },
    Broker.ETORO: {
        "user_key": "Private key",
        "api_key": "Public key",
    },
    Broker.BINANCE: {
        "api_key": "API key",
        "secret_key": "Secret key",
    },
}

CREDENTIAL_FIELD_ORDER = {
    Broker.ETORO: ["api_key", "user_key"],
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

SOURCE_DESCRIPTIONS = {
    Broker.TRADING212: "Automatically synchronize stocks, ETFs, cash, and recent activity.",
    Broker.ETORO: "Automatically synchronize investments, cash, and Copy Portfolios.",
    Broker.BINANCE: "Automatically synchronize Spot crypto balances and trade activity.",
}

SOURCE_CATEGORIES = {
    Broker.TRADING212: "Broker",
    Broker.ETORO: "Broker",
    Broker.BINANCE: "Crypto exchange",
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
        "Copy eToro's Public Key and Private Key into the matching fields below. "
        "The Private Key is used as the documented x-user-key value.",
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
            connection_type="api",
            category=SOURCE_CATEGORIES[broker],
            description=SOURCE_DESCRIPTIONS[broker],
            credential_fields=CREDENTIAL_FIELD_ORDER.get(broker, list(fields)),
            credential_labels=CREDENTIAL_LABELS[broker],
            security_notice=SECURITY_NOTICES[broker],
            setup_steps=SETUP_STEPS[broker],
            tutorial_url=TUTORIAL_URLS[broker],
        )
        for broker, fields in CREDENTIAL_FIELDS.items()
    ] + [
        ConnectionGuide(
            broker=Broker.TRADING212_CRYPTO,
            connection_type="csv",
            category="Crypto broker",
            description=(
                "Import Trading 212 Crypto history safely from its official CSV export. "
                "Re-import later files without duplicating transactions."
            ),
            credential_fields=[],
            credential_labels={},
            security_notice=(
                "Trading 212 does not expose Crypto accounts through its Public API. "
                "Northstar reads only the CSV you choose and never asks for login credentials."
            ),
            setup_steps=[
                "Open the Crypto account in Trading 212.",
                "Go to Menu, then History, and select Export.",
                "Include completed Buy, Sell, Deposit, and Withdrawal activity.",
                "Choose the full available date range for the first import.",
                "Download the CSV and upload it below. Later overlapping exports are safe.",
            ],
            tutorial_url=(
                "https://helpcentre.trading212.com/hc/en-us/articles/"
                "30721201341213-What-are-the-Crypto-account-views"
            ),
        )
    ]


@router.get("", response_model=list[ConnectionRead])
async def list_connections(user: CurrentUser, db: DbSession) -> list[ConnectionRead]:
    connections = await ConnectionRepository(db).for_user(user.id)
    return [_connection_read(item) for item in connections]


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
    return _connection_read(connection)


@router.post("/imports/trading212-crypto", response_model=CryptoCsvImportResult)
async def import_trading212_crypto(
    user: CurrentUser,
    db: DbSession,
    file: Annotated[UploadFile, File()],
) -> CryptoCsvImportResult:
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Select a CSV file")
    content = await file.read(MAX_CSV_BYTES + 1)
    try:
        result = await Trading212CryptoImportService(
            db, CredentialCipher()
        ).import_csv(user.id, content)
    except CryptoCsvImportError as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return CryptoCsvImportResult(
        connection=_connection_read(result.connection),
        rows_read=result.rows_read,
        transactions_added=result.transactions_added,
        duplicates_skipped=result.duplicates_skipped,
        positions_imported=result.positions_imported,
        warnings=result.warnings,
    )


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
    synced = await ConnectionSyncService(db, CredentialCipher()).sync(
        connection, trigger=SyncTrigger.MANUAL
    )
    return _connection_read(synced)


@router.get("/{connection_id}/sync-runs", response_model=list[SyncRunRead])
async def connection_sync_runs(
    connection_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    limit: int = Query(default=20, ge=1, le=100),
) -> list[SyncRunRead]:
    repository = ConnectionRepository(db)
    if not await repository.owned(connection_id, user.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Connection not found")
    runs = await repository.sync_runs(connection_id, limit=limit)
    return [SyncRunRead.model_validate(run) for run in runs]
