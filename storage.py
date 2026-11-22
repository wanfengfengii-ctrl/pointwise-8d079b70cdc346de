import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path


class IncompatibleStore(ValueError):
    pass


def valid_number(number: object) -> bool:
    return type(number) is int and 1 <= number < (1 << 63)


@contextmanager
def open_store(path: str | Path, *, mode: str = 'rw') -> Iterator[sqlite3.Connection]:
    uri = Path(path).resolve().as_uri()
    connection = sqlite3.connect(f'{uri}?mode={mode}', uri=True)
    try:
        connection.execute('PRAGMA foreign_keys = ON')
        yield connection
    finally:
        connection.close()


def initialize_store(path: str | Path, tables: Mapping[str, str]) -> None:
    with open_store(path, mode='rwc') as connection, connection:
        connection.execute('BEGIN IMMEDIATE')
        missing = []
        for name, definition in tables.items():
            row = connection.execute(
                'SELECT type, sql FROM sqlite_master WHERE name = ? COLLATE NOCASE', (name,)
            ).fetchone()
            if row is None:
                missing.append(definition)
            elif row[0] != 'table' or ' '.join(row[1].split()) != ' '.join(definition.split()):
                raise IncompatibleStore(f'incompatible storage table: {name}')
        for definition in missing:
            connection.execute(definition)
