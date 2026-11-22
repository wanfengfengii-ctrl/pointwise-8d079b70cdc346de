import sqlite3
from pathlib import Path

from bundle.catalog import store_received
from bundle.envelope import verify_envelope
from bundle.format import BundlePayload, decode_payload


class IntakeRejected(ValueError):
    pass


def verify_bundle(raw: bytes) -> BundlePayload:
    checked = verify_envelope(raw)
    payload = decode_payload(checked.payload)
    if payload.recording_id != checked.recording_id:
        raise ValueError('fixed content recording identity mismatch')
    return payload


def receive(path: str | Path, raw: bytes) -> int:
    try:
        payload = verify_bundle(raw)
        received = store_received(path, payload.recording_id, raw)
    except (ValueError, sqlite3.Error, OSError) as exc:
        raise IntakeRejected(str(exc)) from exc
    return received.received_no
