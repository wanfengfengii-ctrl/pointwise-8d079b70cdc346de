"""Raw replay inputs and byte authentication for the handoff examples."""
from dataclasses import replace
from hashlib import sha256
from hmac import compare_digest, digest
from pathlib import Path

from archive.readback import read
from bundle.intake import receive
from handoff import capture_recording, initialize_workspace
from portal.edits import AppliedEdit
from portal.recording import RecordingCatalog, load_recordings
from portal.replay import open_shift
from review.decision import reconcile_bundle


RECORDING_ID = "scroll-complete"
EXAMPLE_KEY = sha256(b"harbour source handoff example key").digest()
RECORDINGS = Path(__file__).resolve().parent / "data" / "recordings.json"


def replay_inputs(path: str | Path = RECORDINGS) -> dict[str, RecordingCatalog]:
    full = load_recordings(path).lookup(RECORDING_ID)
    short = replace(full, steps=full.steps[:2] + full.steps[:-3])
    return {"A": RecordingCatalog((short,)), "B": RecordingCatalog((full,))}


def auth_ports(key: bytes):
    def attest(message: bytes) -> str:
        return digest(key, message, "sha256").hex()

    def verify_source(message: bytes, tag: str) -> bool:
        return isinstance(tag, str) and tag.isascii() and compare_digest(attest(message), tag)

    return attest, verify_source


def seed_legacy(folder: str | Path) -> tuple[int, int]:
    workspace = initialize_workspace(folder)
    catalog = load_recordings(workspace.recordings)
    received_no = receive(workspace.catalog, capture_recording(catalog, "stable"))
    signed = reconcile_bundle(workspace.catalog, workspace.archive, received_no)
    reopened = read(workspace.archive, signed.result_no)
    assert tuple(line.mm for line in reopened.lines) == (0, 12, 5)
    return received_no, signed.result_no


def _check_inputs(verbose: bool = True) -> None:
    events = {}
    for attempt, catalog in replay_inputs().items():
        start, count, portal = open_shift(catalog, RECORDING_ID)
        assert (start, count) == ("s0", 4)
        events[attempt] = []
        while (event := portal.next_event()) is not None:
            events[attempt].append(event)
    assert events["A"][0] == events["A"][1] == events["B"][0]
    assert [event.kind for event in events["A"] if isinstance(event, AppliedEdit)] == ["move"]
    assert [event.kind for event in events["B"] if isinstance(event, AppliedEdit)] == ["move", "rewrite"]
    attest, verify_source = auth_ports(EXAMPLE_KEY)
    tag = attest(b"example")
    assert verify_source(b"example", tag)
    assert not verify_source(b"another example", tag)
    _check_certified(attest, verify_source)
    if verbose:
        print({attempt: [getattr(e, "kind", getattr(e, "window_id", None)) for e in log]
               for attempt, log in events.items()})


def check() -> None:
    """Quiet entry used by the verify command."""
    _check_inputs(verbose=False)


def _check_certified(attest, verify_source) -> None:
    """Exercise the certified path without printing anything but the summary."""
    from tempfile import TemporaryDirectory

    from archive.schema import SignedDraft
    from review.decision import MissingOrigins

    inputs = replay_inputs()

    def run(attempt, chosen):
        with TemporaryDirectory() as folder:
            workspace = initialize_workspace(folder)
            raw = capture_recording(inputs[attempt], RECORDING_ID, attempt_id=attempt,
                                    attest=attest, select_windows=lambda positions: chosen)
            number = receive(workspace.catalog, raw)
            return reconcile_bundle(workspace.catalog, workspace.archive, number,
                                    expected_recording_id=RECORDING_ID,
                                    expected_attempt_id=attempt, verify_source=verify_source)

    signed = run("B", (1, 3, 4))
    assert isinstance(signed, SignedDraft)
    assert tuple(line.mm for line in signed.lines) == (7, 11, 7, 13)
    assert tuple(line.capture_sequence for line in signed.lines) == (1, 1, 4, 3)
    gap = run("B", (1, 3))
    assert isinstance(gap, MissingOrigins) and gap.positions == (3,)
    full_a = run("A", (2, 4, 5))
    assert isinstance(full_a, SignedDraft)
    assert tuple(line.capture_sequence for line in full_a.lines) == (2, 2, 5, 4)


if __name__ == "__main__":
    _check_inputs()
