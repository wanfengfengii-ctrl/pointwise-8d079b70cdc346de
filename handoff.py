import argparse
import json
import sqlite3
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from archive.readback import read
from archive.schema import SignedDraft, initialize_archive
from bundle.catalog import initialize_catalog
from bundle.intake import receive
from bundle.issue import seal
from capture.certified import certified_capture
from capture.session import capture_window, finish_capture, start_capture
from portal.recording import RecordingCatalog, load_recordings
from portal.replay import open_shift
from review.decision import MissingOrigins, ReconcileRejected, reconcile_bundle


_DEFAULT_RECORDINGS = Path(__file__).resolve().parent / 'data' / 'recordings.json'


@dataclass(frozen=True, slots=True)
class Workspace:
    root: Path

    @property
    def recordings(self) -> Path:
        return self.root / 'recordings.json'

    @property
    def catalog(self) -> Path:
        return self.root / 'intake.sqlite3'

    @property
    def archive(self) -> Path:
        return self.root / 'signed.sqlite3'


def initialize_workspace(root: str | Path) -> Workspace:
    workspace = Workspace(Path(root))
    workspace.root.mkdir(parents=True, exist_ok=True)
    initialize_catalog(workspace.catalog)
    initialize_archive(workspace.archive)
    if not workspace.recordings.exists():
        content = _DEFAULT_RECORDINGS.read_bytes()
        try:
            with workspace.recordings.open('xb') as destination:
                destination.write(content)
        except FileExistsError:
            pass
    return workspace


def capture_recording(catalog: RecordingCatalog, recording_id: str, *, attempt_id: str | None = None,
                      attest=None, select_windows=None) -> bytes:
    """Capture a recording.

    With only two positional arguments this produces the legacy V1 bundle.  Once
    a trusted portal supplies ``attempt_id``, ``attest`` and ``select_windows``
    it produces a certified bundle: the replay ends, source material is
    authenticated, and only the clerk's chosen windows travel.
    """
    certified = (attempt_id is not None, attest is not None, select_windows is not None)
    if not any(certified):
        state, row_count, replay = open_shift(catalog, recording_id)
        session = start_capture(recording_id, state, row_count)
        while (event := replay.next_event()) is not None:
            capture_window(session, event)
        finish_capture(session)
        return seal(session)
    if not all(certified):
        raise ValueError('certified capture needs an attempt, an attest callback and a selector')
    return certified_capture(catalog, recording_id, attempt_id, attest, select_windows)


def capture_certified(catalog: RecordingCatalog, recording_id: str, *, attempt_id: str,
                      attest, select_windows) -> bytes:
    """Replay once under a trusted portal, then let the clerk pick windows."""
    return certified_capture(catalog, recording_id, attempt_id, attest, select_windows)


def _output(data: object) -> None:
    print(json.dumps(data, ensure_ascii=False, sort_keys=True, default=_default))


def _default(value: object) -> object:
    if isinstance(value, tuple):
        return list(value)
    raise TypeError(f'not JSON serialisable: {type(value).__name__}')


def _demo() -> None:
    from dataclasses import replace

    from source_fixture import EXAMPLE_KEY, auth_ports, replay_inputs, seed_legacy

    attest, verify_source = auth_ports(EXAMPLE_KEY)
    inputs = replay_inputs()
    with TemporaryDirectory(prefix='harbour-handoff-') as folder:
        workspace = initialize_workspace(folder)

        # Legacy V1 flow stays intact.
        legacy_received, legacy_result = seed_legacy(Path(folder) / 'legacy')
        legacy = read(Path(folder) / 'legacy' / 'signed.sqlite3', legacy_result)

        # Certified flow: attempt B, choose windows 1, 3 and 4.
        chosen = (1, 3, 4)

        def select(positions):
            assert positions == (1, 3, 4, 6), positions
            return chosen

        raw_b = capture_certified(inputs['B'], 'scroll-complete', attempt_id='B',
                                  attest=attest, select_windows=select)
        received_b = receive(workspace.catalog, raw_b)
        signed_b = reconcile_bundle(workspace.catalog, workspace.archive, received_b,
                                    expected_recording_id='scroll-complete',
                                    expected_attempt_id='B', verify_source=verify_source)
        if not isinstance(signed_b, SignedDraft):
            raise ValueError(f'B unexpectedly lacked evidence: {signed_b.positions}')
        readings = tuple(line.mm for line in signed_b.lines)
        if readings != (7, 11, 7, 13):
            raise ValueError(f'B signed the wrong originals: {readings}')

        # Stop the portal: only the archive remains, and the source proof travels.
        workspace.recordings.unlink()
        deliverable = read(workspace.archive, signed_b.result_no)
        if deliverable != signed_b or deliverable.source_proof is None:
            raise ValueError('archived certified draft is unavailable after the portal stops')

        # Rejection: drop edit event 5 from an otherwise valid certified bundle.
        from bundle.envelope import verify_envelope, wrap_payload
        from bundle.source import decode_cert_payload, encode_cert_payload
        inner = decode_cert_payload(verify_envelope(raw_b).payload)
        stripped = replace(inner, records=tuple(r for r in inner.records if r.source_sequence != 5))
        forged = wrap_payload(inner.recording_id, encode_cert_payload(stripped))
        received_forged = receive(workspace.catalog, forged)
        rejection = None
        try:
            reconcile_bundle(workspace.catalog, workspace.archive, received_forged,
                             expected_recording_id='scroll-complete',
                             expected_attempt_id='B', verify_source=verify_source)
        except ReconcileRejected as exc:
            rejection = exc.code
        if rejection is None:
            raise ValueError('SHIFT_DRAFT_FALSE_SIGN: a bundle with a missing edit was signed')

        _output({
            'selected_sequences': list(chosen),
            'certified_lines': [asdict(line) for line in signed_b.lines],
            'first_receipt': asdict(deliverable.receipt),
            'source_attempt': deliverable.source_proof['attempt_id'],
            'source_events': len(deliverable.source_proof['material']['events']),
            'missing_edit_rejected': rejection,
            'legacy_result': asdict(legacy),
            'legacy_received_no': legacy_received,
        })


def _capture_key(value: str) -> bytes:
    if not value:
        raise ValueError('authentication key must not be empty')
    return value.encode('utf-8')


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Recorded port inspection shift handoff')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('init').add_argument('workspace', type=Path)
    capture = commands.add_parser('capture')
    capture.add_argument('workspace', type=Path)
    capture.add_argument('recording_id')
    capture.add_argument('output', type=Path)
    certified = commands.add_parser('certified-capture')
    certified.add_argument('workspace', type=Path)
    certified.add_argument('recording_id')
    certified.add_argument('output', type=Path)
    certified.add_argument('--attempt-id', required=True)
    certified.add_argument('--select', default='', help='comma separated window source sequences')
    certified.add_argument('--key', required=True, help='portal authentication key')
    intake = commands.add_parser('receive')
    intake.add_argument('workspace', type=Path)
    intake.add_argument('bundle', type=Path)
    review = commands.add_parser('reconcile')
    review.add_argument('workspace', type=Path)
    review.add_argument('received_no', type=int)
    review.add_argument('--recording-id')
    review.add_argument('--attempt-id')
    review.add_argument('--key', help='archive source verification key')
    pickup = commands.add_parser('read')
    pickup.add_argument('workspace', type=Path)
    pickup.add_argument('result_no', type=int)
    commands.add_parser('demo')
    return parser


def _selected(value: str) -> tuple[int, ...]:
    if not value:
        return ()
    return tuple(int(item) for item in value.split(','))


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == 'demo':
            _demo()
            return 0
        workspace = Workspace(args.workspace)
        if args.command == 'init':
            initialize_workspace(workspace.root)
            _output({'workspace': str(workspace.root)})
        elif args.command == 'capture':
            raw = capture_recording(load_recordings(workspace.recordings), args.recording_id)
            with args.output.open('xb') as destination:
                destination.write(raw)
            _output({'recording_id': args.recording_id, 'bundle': str(args.output)})
        elif args.command == 'certified-capture':
            from hmac import digest as mac
            key = _capture_key(args.key)

            def attest(message: bytes) -> str:
                return mac(key, message, 'sha256').hex()

            chosen = _selected(args.select)
            raw = capture_certified(load_recordings(workspace.recordings), args.recording_id,
                                    attempt_id=args.attempt_id, attest=attest,
                                    select_windows=lambda positions: chosen)
            with args.output.open('xb') as destination:
                destination.write(raw)
            _output({'recording_id': args.recording_id, 'attempt_id': args.attempt_id,
                     'selected': list(chosen), 'bundle': str(args.output)})
        elif args.command == 'receive':
            _output({'received_no': receive(workspace.catalog, args.bundle.read_bytes())})
        elif args.command == 'reconcile':
            verifier = None
            if args.key is not None:
                from hmac import compare_digest, digest as mac
                key = _capture_key(args.key)

                def verifier(message: bytes, tag: str) -> bool:
                    return isinstance(tag, str) and compare_digest(mac(key, message, 'sha256').hex(), tag)
            result = reconcile_bundle(workspace.catalog, workspace.archive, args.received_no,
                                      expected_recording_id=args.recording_id,
                                      expected_attempt_id=args.attempt_id,
                                      verify_source=verifier)
            _output(asdict(result))
            if isinstance(result, MissingOrigins):
                return 2
        elif args.command == 'read':
            _output(asdict(read(workspace.archive, args.result_no)))
    except (OSError, sqlite3.Error, ValueError, KeyError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
