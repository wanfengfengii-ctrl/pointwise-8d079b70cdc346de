from dataclasses import dataclass
from pathlib import Path

from storage import initialize_store


_TABLES = {
    'drafts': '''CREATE TABLE drafts (
        result_no INTEGER PRIMARY KEY,
        received_no INTEGER NOT NULL CHECK (received_no > 0),
        recording_id TEXT NOT NULL
    )''',
    'draft_lines': '''CREATE TABLE draft_lines (
        result_no INTEGER NOT NULL REFERENCES drafts(result_no),
        origin_position INTEGER NOT NULL CHECK (origin_position > 0),
        mm_decimal TEXT NOT NULL,
        state_id TEXT NOT NULL,
        window_id TEXT NOT NULL,
        screen_position INTEGER NOT NULL CHECK (screen_position > 0),
        capture_sequence INTEGER NOT NULL CHECK (capture_sequence > 0),
        PRIMARY KEY (result_no, origin_position)
    )''',
    'first_receipts': '''CREATE TABLE first_receipts (
        first_receipt_no INTEGER PRIMARY KEY,
        result_no INTEGER NOT NULL UNIQUE REFERENCES drafts(result_no)
    )''',
}


@dataclass(frozen=True, slots=True)
class DraftLine:
    origin_position: int
    mm: int
    state_id: str
    window_id: str
    screen_position: int
    capture_sequence: int


@dataclass(frozen=True, slots=True)
class FirstReceipt:
    first_receipt_no: int
    result_no: int
    received_no: int


@dataclass(frozen=True, slots=True)
class SignedDraft:
    result_no: int
    received_no: int
    recording_id: str
    lines: tuple[DraftLine, ...]
    receipt: FirstReceipt


def initialize_archive(path: str | Path) -> None:
    initialize_store(path, _TABLES)
