from collections.abc import Iterable
from dataclasses import dataclass

from review.eligibility import EligibleObservation


class EvidenceConflict(ValueError):
    def __init__(self, first: EligibleObservation, other: EligibleObservation) -> None:
        self.origin_position = first.origin_position
        super().__init__(f'conflicting original readings for row {first.origin_position}: '
                         f'{first.mm} mm in {first.window_id!r} and {other.mm} mm in {other.window_id!r}')


@dataclass(frozen=True, slots=True)
class CoverageResult:
    covered: tuple[EligibleObservation, ...]
    missing: tuple[int, ...]


def compute_coverage(row_count: int, evidence: Iterable[EligibleObservation]) -> CoverageResult:
    by_origin: dict[int, EligibleObservation] = {}
    for observation in evidence:
        position = observation.origin_position
        if not 1 <= position <= row_count:
            raise ValueError('eligible observation outside the shift start')
        previous = by_origin.get(position)
        if previous is not None and previous.mm != observation.mm:
            raise EvidenceConflict(previous, observation)
        if previous is None or observation.capture_sequence < previous.capture_sequence:
            by_origin[position] = observation
    covered = []
    missing = []
    for position in range(1, row_count + 1):
        if position in by_origin:
            covered.append(by_origin[position])
        else:
            missing.append(position)
    return CoverageResult(tuple(covered), tuple(missing))
