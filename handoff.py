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
from capture.session import capture_window, finish_capture, start_capture
from portal.recording import RecordingCatalog, load_recordings
from portal.replay import open_shift
from review.decision import MissingOrigins, reconcile_bundle


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


def capture_recording(catalog: RecordingCatalog, recording_id: str) -> bytes:
    state, row_count, replay = open_shift(catalog, recording_id)
    session = start_capture(recording_id, state, row_count)
    while (event := replay.next_event()) is not None:
        capture_window(session, event)
    finish_capture(session)
    return seal(session)


def _output(data: object) -> None:
    print(json.dumps(data, ensure_ascii=False, sort_keys=True))


def _demo() -> None:
    with TemporaryDirectory(prefix='harbour-handoff-') as folder:
        workspace = initialize_workspace(folder)
        recordings = load_recordings(workspace.recordings)
        missing_raw = capture_recording(recordings, 'scroll-missing')
        complete_raw = capture_recording(recordings, 'scroll-complete')
        del recordings
        missing_no = receive(workspace.catalog, missing_raw)
        complete_no = receive(workspace.catalog, complete_raw)
        pending = reconcile_bundle(workspace.catalog, workspace.archive, missing_no)
        if isinstance(pending, SignedDraft):
            raise ValueError('SHIFT_DRAFT_FALSE_SIGN: a shift with no original row 3 reading was signed')
        if pending.positions != (3,):
            raise ValueError(f'unexpected missing origin positions: {pending.positions}')
        signed = reconcile_bundle(workspace.catalog, workspace.archive, complete_no)
        if not isinstance(signed, SignedDraft):
            raise ValueError(f'complete shift unexpectedly lacked evidence: {signed.positions}')
        reopened = read(workspace.archive, signed.result_no)
        readings = tuple(line.mm for line in reopened.lines)
        sources = tuple((line.state_id, line.window_id, line.screen_position) for line in reopened.lines)
        expected_sources = (('s0', 'start', 1), ('s0', 'start', 2),
                            ('s1', 'before-rewrite', 4), ('s1', 'shifted', 1))
        if reopened != signed or readings != (7, 11, 7, 13) or sources != expected_sources:
            raise ValueError('signed draft or its evidence differs from the recorded shift')
        _output({'pending': asdict(pending), 'signed_and_reopened': asdict(reopened)})


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Recorded port inspection shift handoff')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('init').add_argument('workspace', type=Path)
    capture = commands.add_parser('capture')
    capture.add_argument('workspace', type=Path)
    capture.add_argument('recording_id')
    capture.add_argument('output', type=Path)
    intake = commands.add_parser('receive')
    intake.add_argument('workspace', type=Path)
    intake.add_argument('bundle', type=Path)
    review = commands.add_parser('reconcile')
    review.add_argument('workspace', type=Path)
    review.add_argument('received_no', type=int)
    pickup = commands.add_parser('read')
    pickup.add_argument('workspace', type=Path)
    pickup.add_argument('result_no', type=int)
    commands.add_parser('demo')
    return parser


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
        elif args.command == 'receive':
            _output({'received_no': receive(workspace.catalog, args.bundle.read_bytes())})
        elif args.command == 'reconcile':
            result = reconcile_bundle(workspace.catalog, workspace.archive, args.received_no)
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
