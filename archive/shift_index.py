import sqlite3
from dataclasses import dataclass

from storage import valid_number


@dataclass(frozen=True, slots=True)
class DraftLocator:
    result_no: int
    received_no: int
    recording_id: str
    source_proof: str | None = None


def insert_result_header(connection: sqlite3.Connection, received_no: int, recording_id: str,
                         source_proof: str | None = None) -> DraftLocator:
    if not connection.in_transaction:
        raise ValueError('result header requires a signing transaction')
    cursor = connection.execute(
        'INSERT INTO drafts (received_no, recording_id, source_proof) VALUES (?, ?, ?)',
        (received_no, recording_id, source_proof),
    )
    return DraftLocator(cursor.lastrowid, received_no, recording_id, source_proof)


def find_by_result_no(connection: sqlite3.Connection, result_no: int) -> DraftLocator | None:
    if not valid_number(result_no):
        return None
    row = connection.execute(
        'SELECT result_no, received_no, recording_id, source_proof FROM drafts WHERE result_no = ?',
        (result_no,),
    ).fetchone()
    return None if row is None else DraftLocator(*row)
