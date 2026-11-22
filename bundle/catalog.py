from dataclasses import dataclass
from pathlib import Path

from storage import initialize_store, open_store, valid_number


_TABLES = {
    'received_bundles': '''CREATE TABLE received_bundles (
        received_no INTEGER PRIMARY KEY,
        recording_id TEXT NOT NULL,
        raw BLOB NOT NULL
    )''',
}


@dataclass(frozen=True, slots=True)
class ReceivedBundle:
    received_no: int
    recording_id: str
    raw: bytes


def initialize_catalog(path: str | Path) -> None:
    initialize_store(path, _TABLES)


def store_received(path: str | Path, recording_id: str, raw: bytes) -> ReceivedBundle:
    with open_store(path) as connection, connection:
        cursor = connection.execute(
            'INSERT INTO received_bundles (recording_id, raw) VALUES (?, ?)', (recording_id, raw)
        )
        received = ReceivedBundle(cursor.lastrowid, recording_id, raw)
    return received


def load_received(path: str | Path, received_no: int) -> ReceivedBundle | None:
    if not valid_number(received_no):
        return None
    with open_store(path, mode='ro') as connection:
        row = connection.execute(
            'SELECT received_no, recording_id, raw FROM received_bundles WHERE received_no = ?',
            (received_no,),
        ).fetchone()
    return None if row is None else ReceivedBundle(*row)
