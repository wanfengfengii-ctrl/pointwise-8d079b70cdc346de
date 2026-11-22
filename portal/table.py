from dataclasses import dataclass
from typing import Iterable


def is_identifier(value: object) -> bool:
    return isinstance(value, str) and bool(value)


@dataclass(frozen=True, slots=True)
class TableSnapshot:
    state_id: str
    rows: tuple[int, ...]

    def __post_init__(self) -> None:
        if not is_identifier(self.state_id):
            raise ValueError('invalid table state')
        if not isinstance(self.rows, tuple) or any(type(mm) is not int for mm in self.rows):
            raise ValueError('table rows must be integer millimetres')

    @property
    def row_count(self) -> int:
        return len(self.rows)


def make_initial_snapshot(state_id: str, rows: Iterable[int]) -> TableSnapshot:
    return TableSnapshot(state_id, tuple(rows))
