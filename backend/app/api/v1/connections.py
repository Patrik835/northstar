import uuid
from typing import Annotated, Protocol

from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status
from sqlalchemy.exc import IntegrityError

from app.api.dependencies import CurrentUser, DbSession
from app.core.encryption import CredentialCipher
from app.integrations.connectors.registry import ConnectorRegistry
from app.integrations.import_sources import IMPORT_SOURCES
from app.models.broker import BrokerConnection
from app.models.enums import Broker, ConnectionStatus, SyncTrigger
from app.repositories.connections import ConnectionRepository
from app.schemas.auth import MessageResponse
from app.schemas.connection import (
    ConnectionCreate,
    ConnectionCredentialsUpdate,
    ConnectionGuide,
    ConnectionRead,
    FileImportGuide,
    StatementImportResult,
    SyncRunRead,
)
from app.services.broker_csv_import import (
    MAX_BROKER_CSV_BYTES,
    BrokerCsvImportError,
    BrokerCsvImportService,
)
from app.services.bybit_import import (
    MAX_BYBIT_FILE_BYTES,
    BybitImportError,
    BybitStatementImportService,
    BybitUpload,
)
from app.services.connection_sync import ConnectionSyncService
from app.services.connections import ConnectionService, InvalidConnectionCredentials
from app.services.trading212_crypto_import import (
    MAX_CSV_BYTES,
    CryptoCsvImportError,
    Trading212CryptoImportService,
)
from app.services.xtb_import import (
    MAX_XTB_FILE_BYTES,
    XtbImportError,
    XtbImportService,
    XtbUpload,
)

router = APIRouter()
live_connectors = ConnectorRegistry()


class ImportSummary(Protocol):
    connection: BrokerConnection
    rows_read: int
    transactions_added: int
    duplicates_skipped: int
    positions_imported: int
    warnings: list[str]


def _connection_read(connection: BrokerConnection) -> ConnectionRead:
    return ConnectionRead.from_connection(connection)


def _import_read(result: ImportSummary) -> StatementImportResult:
    return StatementImportResult(
        connection=_connection_read(result.connection),
        rows_read=result.rows_read,
        transactions_added=result.transactions_added,
        duplicates_skipped=result.duplicates_skipped,
        positions_imported=result.positions_imported,
        warnings=result.warnings,
    )


@router.get("/guides", response_model=list[ConnectionGuide])
async def guides(user: CurrentUser) -> list[ConnectionGuide]:
    return [
        ConnectionGuide(
            broker=definition.broker,
            display_name=definition.display_name,
            short_mark=definition.short_mark,
            connection_type="api",
            category=definition.category,
            description=definition.description,
            credential_fields=list(definition.credential_fields),
            credential_labels=definition.credential_labels,
            security_notice=definition.security_notice,
            setup_steps=list(definition.setup_steps),
            tutorial_url=definition.tutorial_url,
            sync_frequency_label=definition.sync_frequency_label,
        )
        for definition in live_connectors.definitions()
    ] + [
        ConnectionGuide(
            broker=definition.broker,
            display_name=definition.display_name,
            short_mark=definition.short_mark,
            connection_type="csv",
            category=definition.category,
            description=definition.description,
            credential_fields=[],
            credential_labels={},
            security_notice=definition.security_notice,
            setup_steps=list(definition.setup_steps),
            tutorial_url=definition.tutorial_url,
            sync_frequency_label=None,
            file_import=FileImportGuide(
                endpoint=definition.endpoint,
                accept=definition.accept,
                multiple=definition.multiple,
                prompt=definition.prompt,
                help_text=definition.help_text,
                empty_file_message=definition.empty_file_message,
                holding_label=definition.holding_label,
            ),
        )
        for definition in IMPORT_SOURCES
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


@router.post("/imports/trading212-crypto", response_model=StatementImportResult)
async def import_trading212_crypto(
    user: CurrentUser,
    db: DbSession,
    file: Annotated[UploadFile, File()],
) -> StatementImportResult:
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Select a CSV file")
    content = await file.read(MAX_CSV_BYTES + 1)
    try:
        result = await Trading212CryptoImportService(db, CredentialCipher()).import_csv(
            user.id, content
        )
    except CryptoCsvImportError as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return _import_read(result)


@router.post("/imports/xtb", response_model=StatementImportResult)
async def import_xtb(
    user: CurrentUser,
    db: DbSession,
    files: Annotated[list[UploadFile], File(alias="file")],
) -> StatementImportResult:
    if not files:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Select an XTB report")
    uploads: list[XtbUpload] = []
    for file in files:
        filename = file.filename or ""
        if not filename.lower().endswith((".csv", ".xlsx")):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "XTB imports support CSV and XLSX files",
            )
        uploads.append(
            XtbUpload(filename=filename, content=await file.read(MAX_XTB_FILE_BYTES + 1))
        )
    try:
        result = await XtbImportService(db, CredentialCipher()).import_files(user.id, uploads)
    except XtbImportError as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return _import_read(result)


@router.post("/imports/bybit", response_model=StatementImportResult)
async def import_bybit(
    user: CurrentUser,
    db: DbSession,
    files: Annotated[list[UploadFile], File(alias="file")],
) -> StatementImportResult:
    if not files:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Select a Bybit export")
    uploads: list[BybitUpload] = []
    for file in files:
        filename = file.filename or ""
        if not filename.lower().endswith((".csv", ".xlsx")):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Bybit imports support CSV and XLSX files",
            )
        uploads.append(
            BybitUpload(
                filename=filename,
                content=await file.read(MAX_BYBIT_FILE_BYTES + 1),
            )
        )
    try:
        result = await BybitStatementImportService(
            db, CredentialCipher()
        ).import_files(user.id, uploads)
    except BybitImportError as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return _import_read(result)


async def _import_broker_csv(
    broker: Broker,
    user: CurrentUser,
    db: DbSession,
    file: UploadFile,
) -> StatementImportResult:
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Select a CSV file")
    content = await file.read(MAX_BROKER_CSV_BYTES + 1)
    try:
        result = await BrokerCsvImportService(db, CredentialCipher()).import_csv(
            user.id, broker, content
        )
    except BrokerCsvImportError as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return _import_read(result)


@router.post("/imports/trade-republic", response_model=StatementImportResult)
async def import_trade_republic(
    user: CurrentUser,
    db: DbSession,
    file: Annotated[UploadFile, File()],
) -> StatementImportResult:
    return await _import_broker_csv(Broker.TRADE_REPUBLIC, user, db, file)


@router.post("/imports/scalable-capital", response_model=StatementImportResult)
async def import_scalable_capital(
    user: CurrentUser,
    db: DbSession,
    file: Annotated[UploadFile, File()],
) -> StatementImportResult:
    return await _import_broker_csv(Broker.SCALABLE_CAPITAL, user, db, file)


@router.post("/sync-all", response_model=list[ConnectionRead])
async def sync_all_connections(user: CurrentUser, db: DbSession) -> list[ConnectionRead]:
    connections = await ConnectionRepository(db).for_user(user.id)
    live_connections = [
        connection
        for connection in connections
        if live_connectors.supports(connection.broker)
        and connection.status != ConnectionStatus.DISABLED
    ]
    sync_service = ConnectionSyncService(db, CredentialCipher())
    synced_connections = []
    for connection in live_connections:
        synced_connections.append(await sync_service.sync(connection, trigger=SyncTrigger.MANUAL))
    return [_connection_read(connection) for connection in synced_connections]


@router.delete("/{connection_id}", response_model=MessageResponse)
async def delete_connection(
    connection_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> MessageResponse:
    if not await ConnectionService(db, CredentialCipher()).delete(connection_id, user.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Connection not found")
    return MessageResponse(message="Connection and its imported data deleted")


@router.put("/{connection_id}/credentials", response_model=ConnectionRead)
async def replace_connection_credentials(
    connection_id: uuid.UUID,
    payload: ConnectionCredentialsUpdate,
    user: CurrentUser,
    db: DbSession,
) -> ConnectionRead:
    try:
        connection = await ConnectionService(db, CredentialCipher()).replace_credentials(
            connection_id, user.id, payload.credentials
        )
    except InvalidConnectionCredentials as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    if not connection:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Connection not found")
    return _connection_read(connection)


@router.post("/{connection_id}/sync", response_model=ConnectionRead)
async def sync_connection(
    connection_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> ConnectionRead:
    connection = await ConnectionRepository(db).owned(connection_id, user.id)
    if not connection:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Connection not found")
    if not live_connectors.supports(connection.broker):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This source is updated by importing a new statement file",
        )
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
