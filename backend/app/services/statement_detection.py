"""Work out which broker produced an uploaded statement, without importing anything."""

import re
from dataclasses import dataclass
from fnmatch import fnmatch

from app.integrations.import_sources import IMPORT_SOURCES, ImportSourceDefinition
from app.models.enums import Broker

HEADER_LINES = 12


@dataclass(frozen=True, slots=True)
class StatementMatch:
    broker: Broker
    display_name: str
    score: float
    marker_hits: int


@dataclass(frozen=True, slots=True)
class StatementDetectionResult:
    matches: list[StatementMatch]
    # Set only when exactly one source's own header markers appear in the file.
    suggested: Broker | None


def _accepts(source: ImportSourceDefinition, filename: str) -> bool:
    extensions = [item.strip() for item in source.accept.split(",") if item.startswith(".")]
    return any(fnmatch(filename.lower(), f"*{extension}") for extension in extensions)


def _header_cells(content: bytes) -> set[str]:
    text = content[:16384].decode("utf-8-sig", errors="ignore")
    cells: set[str] = set()
    for line in text.splitlines()[:HEADER_LINES]:
        for cell in re.split(r"[,;\t]", line):
            normalized = re.sub(r"[^a-z0-9]", "", cell.lower())
            if normalized:
                cells.add(normalized)
    return cells


def detect_statement(uploads: list[tuple[str, bytes]]) -> StatementDetectionResult:
    """Return every import source that can read these files, best fit first.

    Several brokers produce similar files, so callers must let the user confirm the
    choice (and pick another match) before importing.
    """
    cells: set[str] = set()
    for _, content in uploads:
        cells |= _header_cells(content)
    matches: list[StatementMatch] = []
    for source in IMPORT_SOURCES:
        if not uploads or (len(uploads) > 1 and not source.multiple):
            continue
        if not all(_accepts(source, filename) for filename, _ in uploads):
            continue
        try:
            score = source.recognize(uploads)
        except Exception:  # noqa: BLE001 - any parser failure simply means "not this broker"
            continue
        if score > 0:
            matches.append(
                StatementMatch(
                    source.broker,
                    source.display_name,
                    round(score, 2),
                    len(cells & source.header_markers),
                )
            )
    matches.sort(key=lambda match: (match.marker_hits, match.score), reverse=True)
    marked = [match for match in matches if match.marker_hits]
    suggested = marked[0].broker if len(marked) == 1 else None
    return StatementDetectionResult(matches, suggested)
