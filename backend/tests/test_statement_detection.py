"""Uploading a statement suggests its broker, but only when the file clearly says so."""

from app.models.enums import Broker
from app.services.statement_detection import detect_statement
from tests.test_broker_csv_import import SCALABLE_CSV, TRADE_REPUBLIC_CSV
from tests.test_xtb_import import HISTORY, OPEN_POSITIONS

TRADING212_CRYPTO_CSV = (
    b"Type,Status,Coin,Date,Quantity,Price,Total,Currency,Transaction ID\n"
    b"Buy,Completed,BTC,2026-01-02 10:00:00,0.10,40000,4000,EUR,buy-1\n"
)


def test_each_supported_export_is_suggested_as_its_own_broker() -> None:
    cases = {
        Broker.TRADE_REPUBLIC: [("export.csv", TRADE_REPUBLIC_CSV)],
        Broker.SCALABLE_CAPITAL: [("export.csv", SCALABLE_CSV)],
        Broker.TRADING212_CRYPTO: [("export.csv", TRADING212_CRYPTO_CSV)],
        Broker.XTB: [("open.csv", OPEN_POSITIONS), ("history.csv", HISTORY)],
    }
    for broker, uploads in cases.items():
        result = detect_statement(uploads)
        assert result.suggested is broker, broker
        assert result.matches[0].broker is broker


def test_other_brokers_that_can_read_the_file_stay_available_as_alternatives() -> None:
    # The lenient parsers also accept a Trade Republic file, so the user can still pick another.
    result = detect_statement([("export.csv", TRADE_REPUBLIC_CSV)])
    brokers = [match.broker for match in result.matches]
    assert brokers[0] is Broker.TRADE_REPUBLIC
    assert Broker.SCALABLE_CAPITAL in brokers


def test_unrecognised_files_get_no_suggestion() -> None:
    assert detect_statement([("notes.csv", b"hello,world\n1,2\n")]).matches == []
    assert detect_statement([("statement.pdf", b"%PDF-1.7")]).matches == []
    assert detect_statement([]).suggested is None


def test_several_files_only_match_sources_that_accept_several_files() -> None:
    result = detect_statement(
        [("a.csv", TRADE_REPUBLIC_CSV), ("b.csv", TRADE_REPUBLIC_CSV)]
    )
    assert all(match.broker is Broker.XTB for match in result.matches)
    assert result.suggested is None
