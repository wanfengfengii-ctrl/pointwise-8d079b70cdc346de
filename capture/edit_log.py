from dataclasses import dataclass

from portal.edits import AppliedEdit, position_result
from portal.table import is_identifier


@dataclass(frozen=True, slots=True)
class EditFact:
    kind: str
    before: str
    after: str
    position: int
    target: int | None = None


def capture_edit_fact(edit: AppliedEdit) -> EditFact:
    return EditFact(edit.kind, edit.before, edit.after, edit.position, edit.target)


def edit_row_count(fact: EditFact, row_count: int) -> int:
    if not is_identifier(fact.before) or not is_identifier(fact.after) or fact.before == fact.after:
        raise ValueError('invalid edit state identifiers')
    return position_result(fact.kind, fact.position, fact.target, row_count)
