import json
import sqlite3
from pathlib import Path

from archive.schema import CertifiedDraft, DraftLine, FirstReceipt, SignedDraft
from archive.shift_index import find_by_result_no
from storage import open_store


class UnavailableResult(ValueError):
    pass


def read(path: str | Path, result_no: int) -> SignedDraft:
    try:
        with open_store(path, mode='ro') as connection, connection:
            connection.execute('BEGIN')
            result = find_by_result_no(connection, result_no)
            if result is None:
                raise UnavailableResult(f'result {result_no!r} is unavailable')
            receipt_row = connection.execute(
                'SELECT first_receipt_no FROM first_receipts WHERE result_no = ?', (result_no,)
            ).fetchone()
            if receipt_row is None:
                raise UnavailableResult(f'result {result_no!r} has no first receipt')
            rows = connection.execute(
                '''SELECT origin_position, mm_decimal, state_id, window_id, screen_position, capture_sequence
                   FROM draft_lines WHERE result_no = ? ORDER BY origin_position''', (result_no,)
            )
            lines = tuple(DraftLine(position, int(mm), state, window, screen, sequence)
                          for position, mm, state, window, screen, sequence in rows)
            receipt = FirstReceipt(receipt_row[0], result_no, result.received_no)
            proof = json.loads(result.source_proof) if result.source_proof is not None else None
    except UnavailableResult:
        raise
    except (sqlite3.Error, OSError, ValueError, TypeError) as exc:
        raise UnavailableResult(f'could not read result {result_no!r}: {exc}') from exc
    if proof is None:
        return SignedDraft(result.result_no, result.received_no, result.recording_id, lines, receipt)
    return CertifiedDraft(result.result_no, result.received_no, result.recording_id, lines,
                          receipt, proof)
