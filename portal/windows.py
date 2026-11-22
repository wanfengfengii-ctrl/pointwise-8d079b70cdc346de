from dataclasses import dataclass

from portal.table import TableSnapshot, is_identifier


@dataclass(frozen=True, slots=True)
class WindowRead:
    window_id: str
    state_id: str
    rows: tuple[tuple[int, int], ...]


def read_window(snapshot: TableSnapshot, window_id: str, first: int, count: int) -> WindowRead:
    if not is_identifier(window_id):
        raise ValueError('invalid window identifier')
    if type(first) is not int or type(count) is not int or first < 1 or count < 1:
        raise ValueError('window requires a positive first position and length')
    stop = first + count - 1
    if stop > snapshot.row_count:
        raise ValueError('window goes past the actual table')
    rows = tuple(enumerate(snapshot.rows[first - 1:stop], start=first))
    return WindowRead(window_id, snapshot.state_id, rows)
