from capture.edit_log import EditFact
from capture.observations import CapturedWindow


TimelineEntry = EditFact | CapturedWindow


class CaptureTimeline:
    def __init__(self) -> None:
        self._entries: list[TimelineEntry] = []
        self._frozen: tuple[TimelineEntry, ...] | None = None

    def append(self, entry: TimelineEntry) -> None:
        if self._frozen is not None:
            raise ValueError('capture timeline is frozen')
        if not isinstance(entry, (EditFact, CapturedWindow)):
            raise ValueError('invalid timeline entry')
        self._entries.append(entry)

    def snapshot(self) -> tuple[TimelineEntry, ...]:
        if self._frozen is not None:
            return self._frozen
        return tuple(self._entries)

    def freeze(self) -> tuple[TimelineEntry, ...]:
        if self._frozen is None:
            self._frozen = tuple(self._entries)
            self._entries.clear()
        return self._frozen
