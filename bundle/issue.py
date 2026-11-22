from bundle.envelope import wrap_payload
from bundle.format import BundlePayload, encode_payload
from capture.session import CaptureSession


def seal(session: CaptureSession) -> bytes:
    if not session.checkpoint.finished:
        raise ValueError('finish the capture before sealing')
    payload = BundlePayload(session.recording_id, session.checkpoint.start, session.records)
    return wrap_payload(payload.recording_id, encode_payload(payload))
