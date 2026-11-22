import base64
import hashlib
import hmac
from dataclasses import dataclass

from bundle.format import json_bytes, load_json
from portal.table import is_identifier


@dataclass(frozen=True, slots=True)
class CheckedEnvelope:
    recording_id: str
    payload: bytes


def _digest(recording_id: str, payload: bytes) -> str:
    identity = json_bytes(recording_id)
    return hashlib.sha256(b'harbour-handoff-v1\x00' + identity + b'\x00' + payload).hexdigest()


def wrap_payload(recording_id: str, payload: bytes) -> bytes:
    if not is_identifier(recording_id) or type(payload) is not bytes:
        raise ValueError('invalid envelope recording or payload')
    return json_bytes({'version': 1, 'recording_id': recording_id,
                       'payload': base64.b64encode(payload).decode('ascii'),
                       'sha256': _digest(recording_id, payload)})


def verify_envelope(raw: bytes) -> CheckedEnvelope:
    data = load_json(raw)
    fields = {'version', 'recording_id', 'payload', 'sha256'}
    if not isinstance(data, dict) or data.keys() != fields:
        raise ValueError('invalid fixed envelope fields')
    if type(data['version']) is not int or data['version'] != 1:
        raise ValueError('unsupported fixed envelope version')
    recording_id = data['recording_id']
    encoded = data['payload']
    digest = data['sha256']
    if not is_identifier(recording_id) or not isinstance(encoded, str):
        raise ValueError('invalid envelope recording or payload')
    if not isinstance(digest, str) or len(digest) != 64 or not digest.isascii():
        raise ValueError('invalid envelope digest')
    payload = base64.b64decode(encoded, validate=True)
    if not hmac.compare_digest(digest, _digest(recording_id, payload)):
        raise ValueError('fixed content digest mismatch')
    return CheckedEnvelope(recording_id, payload)
