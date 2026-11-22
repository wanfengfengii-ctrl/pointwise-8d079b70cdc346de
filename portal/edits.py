from dataclasses import dataclass

from portal.table import TableSnapshot, is_identifier


@dataclass(frozen=True, slots=True)
class RecordedEdit:
    kind: str
    before: str
    after: str
    position: int
    target: int | None = None
    mm: int | None = None


@dataclass(frozen=True, slots=True)
class AppliedEdit:
    kind: str
    before: str
    after: str
    position: int
    target: int | None = None


def position_result(kind: str, position: int, target: int | None, row_count: int) -> int:
    if kind not in ('insert', 'delete', 'move', 'rewrite'):
        raise ValueError('unknown edit operation')
    limit = row_count + (kind == 'insert')
    if type(position) is not int or not 1 <= position <= limit:
        raise ValueError('edit position outside its table')
    if kind == 'move':
        if type(target) is not int or not 1 <= target <= row_count:
            raise ValueError('invalid final move position')
    elif target is not None:
        raise ValueError('only a move has a target')
    return row_count + (kind == 'insert') - (kind == 'delete')


def apply_edit(snapshot: TableSnapshot, edit: RecordedEdit) -> tuple[TableSnapshot, AppliedEdit]:
    if edit.before != snapshot.state_id:
        raise ValueError('edit does not start at the current table state')
    if not is_identifier(edit.after) or edit.after == edit.before:
        raise ValueError('invalid resulting table state')
    position_result(edit.kind, edit.position, edit.target, snapshot.row_count)
    if edit.kind in ('insert', 'rewrite'):
        if type(edit.mm) is not int:
            raise ValueError('edit requires integer millimetres')
    elif edit.mm is not None:
        raise ValueError('unexpected edit reading')

    rows = list(snapshot.rows)
    index = edit.position - 1
    match edit.kind:
        case 'insert':
            rows.insert(index, edit.mm)
        case 'delete':
            rows.pop(index)
        case 'move':
            reading = rows.pop(index)
            rows.insert(edit.target - 1, reading)
        case 'rewrite':
            rows[index] = edit.mm
    fact = AppliedEdit(edit.kind, edit.before, edit.after, edit.position, edit.target)
    return TableSnapshot(edit.after, tuple(rows)), fact
