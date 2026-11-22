from dataclasses import dataclass

from portal.table import is_identifier
from portal.windows import WindowRead


@dataclass(frozen=True, slots=True)
class ObservedRow:
    position: int
    mm: int


@dataclass(frozen=True, slots=True)
class CapturedWindow:
    window_id: str
    state_id: str
    rows: tuple[ObservedRow, ...]


def validate_window(window: CapturedWindow, row_count: int) -> None:
    if not is_identifier(window.window_id) or not is_identifier(window.state_id):
        raise ValueError('invalid observed window identifiers')
    if not window.rows:
        raise ValueError('observed window contains no rows')
    positions = set()
    for row in window.rows:
        if type(row.position) is not int or not 1 <= row.position <= row_count:
            raise ValueError('observation outside its actual table state')
        if type(row.mm) is not int:
            raise ValueError('observed value must be integer millimetres')
        if row.position in positions:
            raise ValueError('repeated position inside one window')
        positions.add(row.position)


def capture_observation(window: WindowRead, row_count: int) -> CapturedWindow:
    try:
        rows = tuple(ObservedRow(position, mm) for position, mm in window.rows)
    except (TypeError, ValueError) as exc:
        raise ValueError('invalid observed row fields') from exc
    captured = CapturedWindow(window.window_id, window.state_id, rows)
    validate_window(captured, row_count)
    return captured
