from dataclasses import dataclass
from pathlib import Path

from storage import IncompatibleStore, initialize_store, open_store


_LEGACY_DRAFT_COLUMNS = ['result_no', 'received_no', 'recording_id']
_DRAFT_COLUMNS = ['result_no', 'received_no', 'recording_id', 'source_proof']

_TABLES = {
    'drafts': '''CREATE TABLE drafts (
        result_no INTEGER PRIMARY KEY,
        received_no INTEGER NOT NULL CHECK (received_no > 0),
        recording_id TEXT NOT NULL,
        source_proof TEXT
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

_AUX_TABLES = {name: definition for name, definition in _TABLES.items() if name != 'drafts'}


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

    @property
    def source_proof(self) -> dict | None:
        """Certified drafts override this; legacy drafts carry no source proof."""
        return None


@dataclass(frozen=True, slots=True)
class CertifiedDraft(SignedDraft):
    source_proof: dict | None = None


def initialize_archive(path: str | Path) -> None:
    initialize_store(path, _AUX_TABLES)
    _ensure_drafts(path)


def _ensure_drafts(path: str | Path) -> None:
    """Create the draft header, accepting and widening a pre-source one."""
    with open_store(path, mode='rwc') as connection, connection:
        connection.execute('BEGIN IMMEDIATE')
        row = connection.execute(
            'SELECT type FROM sqlite_master WHERE name = ? COLLATE NOCASE', ('drafts',)
        ).fetchone()
        if row is None:
            connection.execute(_TABLES['drafts'])
            return
        if row[0] != 'table':
            raise IncompatibleStore('incompatible storage table: drafts')
        columns = [item[1] for item in connection.execute('PRAGMA table_info(drafts)')]
        if columns == _LEGACY_DRAFT_COLUMNS:
            connection.execute('ALTER TABLE drafts ADD COLUMN source_proof TEXT')
        elif columns != _DRAFT_COLUMNS:
            raise IncompatibleStore('incompatible storage table: drafts')
