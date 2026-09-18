import uuid
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

import app.models  # noqa: F401
from app.core.database import Base
from app.core.encryption import CredentialCipher
from app.models.enums import AssetType, Broker, TransactionType
from app.models.portfolio import Position, Transaction
from app.models.user import User
from app.services.broker_csv_import import BrokerCsvImportService, BrokerCsvParser


class IdentityRates:
    async def convert_to_eur(
        self, value: Decimal, currency: str, as_of: date | None = None
    ) -> Decimal:
        assert currency == "EUR"
        return value


class AsyncSessionAdapter:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, item: Any) -> None:
        self.session.add(item)

    def add_all(self, items: list[Any]) -> None:
        self.session.add_all(items)

    async def flush(self) -> None:
        self.session.flush()

    async def commit(self) -> None:
        self.session.commit()

    async def rollback(self) -> None:
        self.session.rollback()

    async def refresh(self, item: Any) -> None:
        self.session.refresh(item)

    async def execute(self, statement: Any):
        return self.session.execute(statement)

    async def scalar(self, statement: Any):
        return self.session.scalar(statement)

    async def scalars(self, statement: Any):
        return self.session.scalars(statement)

    async def get(self, model: type, item_id: Any):
        return self.session.get(model, item_id)


TRADE_REPUBLIC_CSV = (
    b"datetime,date,account_type,category,type,asset_class,name,symbol,shares,price,"
    b"amount,fee,tax,currency,description,transaction_id\n"
    b"2026-01-10T10:30:00+00:00,2026-01-10,SECURITIES,ORDER,BUY,STOCK,Apple Inc.,"
    b"US0378331005,2,100,200,1,0,EUR,Purchase,tr-buy-1\n"
    b"2026-02-10T10:30:00+00:00,2026-02-10,SECURITIES,ORDER,SAVINGS_PLAN_EXECUTED,"
    b"STOCK,Apple Inc.,US0378331005,1,120,120,0,0,EUR,Savings plan,tr-buy-2\n"
    b"2026-03-10T10:30:00+00:00,2026-03-10,SECURITIES,ORDER,SELL,STOCK,Apple Inc.,"
    b"US0378331005,1,130,130,1,0,EUR,Sale,tr-sell-1\n"
    b"2026-04-10T10:30:00+00:00,2026-04-10,SECURITIES,INCOME,DIVIDEND,STOCK,"
    b"Apple Inc.,US0378331005,0,0,4,0,1,EUR,Dividend,tr-div-1\n"
    b"2026-04-11T10:30:00+00:00,2026-04-11,CASH,CARD,CARD_TRANSACTION,,,0,0,20,"
    b"0,0,EUR,Groceries,tr-card-1\n"
)

SCALABLE_CSV = (
    b"date;time;status;reference;description;assetType;type;isin;shares;price;amount;"
    b"fee;tax;currency\n"
    b"2026-02-01;09:15:00;Executed;sc-buy-1;Vanguard FTSE All-World;Security;Buy;"
    b"IE00BK5BQT80;3;100,00;-300,00;0,99;0;EUR\n"
    b"2026-03-15;12:00:00;Executed;sc-div-1;Vanguard FTSE All-World;Security;"
    b"Distribution;IE00BK5BQT80;;;5,50;0;0,50;EUR\n"
)


def test_trade_republic_parser_reads_native_activity_and_ignores_card_payments() -> None:
    parsed = BrokerCsvParser().parse(Broker.TRADE_REPUBLIC, TRADE_REPUBLIC_CSV)

    assert parsed.rows_read == 5
    assert [item.transaction_type for item in parsed.transactions].count(TransactionType.BUY) == 2
    assert [item.transaction_type for item in parsed.transactions].count(TransactionType.SELL) == 1
    assert [item.transaction_type for item in parsed.transactions].count(
        TransactionType.DIVIDEND
    ) == 1
    assert [item.transaction_type for item in parsed.transactions].count(TransactionType.FEE) == 3
    assert all("tr-card-1" not in item.external_id for item in parsed.transactions)
    apple = parsed.transactions[0]
    assert apple.isin == "US0378331005"
    assert apple.asset_type is AssetType.STOCK


def test_scalable_parser_handles_semicolon_and_european_numbers() -> None:
    parsed = BrokerCsvParser().parse(Broker.SCALABLE_CAPITAL, SCALABLE_CSV)

    buy = next(item for item in parsed.transactions if item.transaction_type is TransactionType.BUY)
    assert buy.quantity == Decimal("3")
    assert buy.price == Decimal("100.00")
    assert buy.value == Decimal("300.00")
    assert buy.isin == "IE00BK5BQT80"
    # Scalable's generic "Security" label does not verify stock versus ETF. An existing
    # canonical instrument can supply that distinction without guessing from its name.
    assert buy.asset_type is AssetType.OTHER
    assert {item.transaction_type for item in parsed.transactions} == {
        TransactionType.BUY,
        TransactionType.DIVIDEND,
        TransactionType.FEE,
    }


def test_trade_republic_parser_recognizes_crypto_invoice_direction() -> None:
    content = (
        b"datetime,type,asset_class,name,symbol,shares,price,amount,currency,"
        b"transaction_id\n"
        b"2026-05-01T10:00:00+00:00,CRYPTO_INVOICE,CRYPTO,Bitcoin,BTC,0.01,"
        b"60000,-600,EUR,crypto-1\n"
    )

    parsed = BrokerCsvParser().parse(Broker.TRADE_REPUBLIC, content)

    assert parsed.transactions[0].transaction_type is TransactionType.BUY
    assert parsed.transactions[0].asset_type is AssetType.CRYPTO


@pytest.mark.asyncio
async def test_trade_republic_import_reconstructs_positions_and_deduplicates() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(engine, expire_on_commit=False)
    user_id = uuid.uuid4()
    try:
        with session_factory() as sync_db:
            db = AsyncSessionAdapter(sync_db)
            db.add(
                User(
                    id=user_id,
                    username="trade-republic-owner",
                    password_hash="unused",
                    is_admin=False,
                    is_active=True,
                )
            )
            await db.commit()
            service = BrokerCsvImportService(
                db,  # type: ignore[arg-type]
                CredentialCipher("MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA="),
                fx_rates=IdentityRates(),
            )

            first = await service.import_csv(user_id, Broker.TRADE_REPUBLIC, TRADE_REPUBLIC_CSV)
            second = await service.import_csv(user_id, Broker.TRADE_REPUBLIC, TRADE_REPUBLIC_CSV)

            assert first.connection.broker is Broker.TRADE_REPUBLIC
            assert first.positions_imported == 1
            assert second.transactions_added == 0
            assert second.duplicates_skipped == 7
            assert await db.scalar(select(func.count(Transaction.id))) == 7
            position = await db.scalar(select(Position))
            assert position is not None
            assert position.quantity == Decimal("2")
            assert position.current_value == Decimal("260")
            assert position.average_price == pytest.approx(Decimal("106.66666667"))
            assert position.reported_pnl == pytest.approx(Decimal("46.6667"))
            assert position.is_estimated is True
            assert position.canonical_instrument is not None
            assert position.canonical_instrument.isin == "US0378331005"
    finally:
        engine.dispose()
