import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest

from app.core.encryption import CredentialCipher
from app.integrations.connectors.base import (
    BrokerConnector,
    BrokerPermissionError,
    ConnectorSnapshot,
    ConnectorTransaction,
)
from app.models.broker import BrokerConnection
from app.models.enums import Broker, ConnectionStatus, SyncRunStatus, SyncTrigger
from app.models.sync import SyncRun
from app.services.connection_sync import ConnectionSyncService, reconciliation_result

TEST_KEY = "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA="


class EurRates:
    async def convert_to_eur(
        self, value: Decimal, currency: str, as_of: date | None = None
    ) -> Decimal:
        assert currency == "EUR"
        return value


class FakeConnector(BrokerConnector):
    def __init__(self, *, history_error: Exception | None = None) -> None:
        super().__init__({})
        self.history_error = history_error

    async def validate_credentials(self) -> None:
        return None

    async def fetch_positions(self) -> list:
        return []

    async def fetch_transactions(self, since: Any) -> list[ConnectorTransaction]:
        if self.history_error:
            raise self.history_error
        return []

    async def fetch_snapshot(self, snapshot_date: date) -> ConnectorSnapshot:
        return ConnectorSnapshot(snapshot_date, Decimal("250"), "EUR")


class UnsafeFailureConnector(FakeConnector):
    async def validate_credentials(self) -> None:
        raise RuntimeError("private-key=should-never-be-persisted")


class SyncSession:
    def __init__(self, connection: BrokerConnection) -> None:
        self.connection = connection
        self.run: SyncRun | None = None
        self.committed_run_states: list[SyncRunStatus] = []

    def add(self, item: Any) -> None:
        if isinstance(item, SyncRun):
            item.id = uuid.uuid4()
            self.run = item

    def add_all(self, items: list[Any]) -> None:
        return None

    async def commit(self) -> None:
        if self.run is not None:
            self.committed_run_states.append(self.run.status)

    async def rollback(self) -> None:
        return None

    async def refresh(self, item: Any) -> None:
        return None

    async def execute(self, statement: Any) -> None:
        return None

    async def scalar(self, statement: Any) -> None:
        return None

    async def scalars(self, statement: Any) -> list:
        return []

    async def get(self, model: type, item_id: uuid.UUID) -> Any:
        if model is BrokerConnection:
            return self.connection
        if model is SyncRun:
            return self.run
        return None


def _connection() -> BrokerConnection:
    return BrokerConnection(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        broker="trading212",
        encrypted_credentials=CredentialCipher(TEST_KEY).encrypt({"unused": "unused"}),
        credential_hint="••••test",
        status=ConnectionStatus.PENDING,
    )


def test_reconciliation_ignores_normal_timing_difference() -> None:
    difference, warning = reconciliation_result(
        Broker.TRADING212, Decimal("9894"), Decimal("10000")
    )

    assert difference == Decimal("1.0600")
    assert warning is None


def test_reconciliation_warns_only_for_material_difference() -> None:
    difference, warning = reconciliation_result(
        Broker.ETORO, Decimal("9500"), Decimal("10000")
    )

    assert difference == Decimal("5.00")
    assert warning is not None
    assert "5.0%" in warning
    assert "latest holdings were preserved" in warning.lower()


@pytest.mark.asyncio
async def test_sync_records_success_and_persists_running_first() -> None:
    connection = _connection()
    db = SyncSession(connection)
    synced = await ConnectionSyncService(  # type: ignore[arg-type]
        db, CredentialCipher(TEST_KEY), EurRates()
    ).sync(connection, FakeConnector(), trigger=SyncTrigger.SCHEDULED)

    assert synced.status is ConnectionStatus.ACTIVE
    assert db.run is not None
    assert db.run.status is SyncRunStatus.SUCCESS
    assert db.run.trigger is SyncTrigger.SCHEDULED
    assert db.run.positions_written == 0
    assert db.run.transactions_read == 0
    assert db.run.transactions_written == 0
    assert db.run.finished_at is not None
    assert db.committed_run_states == [SyncRunStatus.RUNNING, SyncRunStatus.SUCCESS]
    assert synced.last_sync_attempt_at is not None
    assert synced.last_successful_sync_at is not None
    assert synced.last_successful_sync_at >= synced.last_sync_attempt_at


@pytest.mark.asyncio
async def test_sync_records_partial_history_permission_failure() -> None:
    connection = _connection()
    db = SyncSession(connection)
    synced = await ConnectionSyncService(  # type: ignore[arg-type]
        db, CredentialCipher(TEST_KEY), EurRates()
    ).sync(
        connection,
        FakeConnector(history_error=BrokerPermissionError("History permission missing")),
    )

    assert synced.status is ConnectionStatus.LIMITED
    assert db.run is not None
    assert db.run.status is SyncRunStatus.PARTIAL
    assert db.run.warning_count == 1
    assert db.run.safe_error_detail == "History permission missing"


@pytest.mark.asyncio
async def test_sync_never_persists_unexpected_exception_details() -> None:
    connection = _connection()
    previous_success = datetime.now(timezone.utc) - timedelta(hours=1)
    connection.last_successful_sync_at = previous_success
    db = SyncSession(connection)
    synced = await ConnectionSyncService(  # type: ignore[arg-type]
        db, CredentialCipher(TEST_KEY), EurRates()
    ).sync(connection, UnsafeFailureConnector())

    assert synced.status is ConnectionStatus.ERROR
    assert db.run is not None
    assert db.run.status is SyncRunStatus.ERROR
    assert db.run.safe_error_detail is not None
    assert "private-key" not in db.run.safe_error_detail
    assert "should-never-be-persisted" not in db.run.safe_error_detail
    assert synced.last_sync_attempt_at is not None
    assert synced.last_successful_sync_at == previous_success
