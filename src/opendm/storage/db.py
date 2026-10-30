"""SQLite connection and schema migrations (decision D7).

Migrations are ``storage/migrations/NNNN_name.sql`` files. Each runs in its own
transaction together with the ``PRAGMA user_version`` bump, so a failure leaves the
database at the previous version. The connection is owned by one thread (the
engine thread from M4 on).
"""

import re
import sqlite3
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

_MIGRATION_FILE = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")


class MigrationError(Exception):
    """The database could not be brought to the expected schema version."""


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str


def load_migrations() -> list[Migration]:
    """The migrations bundled with the app, in order."""
    found = []
    for entry in resources.files("opendm.storage.migrations").iterdir():
        match = _MIGRATION_FILE.match(entry.name)
        if match:
            found.append(Migration(int(match[1]), match[2], entry.read_text("utf-8")))
    return sorted(found, key=lambda m: m.version)


class Database:
    def __init__(self, path: Path | str, migrations: Sequence[Migration] | None = None) -> None:
        if isinstance(path, Path):
            path.parent.mkdir(parents=True, exist_ok=True)
        # Autocommit mode: transactions are explicit (see transaction()).
        self.conn = sqlite3.connect(path, isolation_level=None)
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA busy_timeout = 5000")
        if str(path) != ":memory:":
            self.conn.execute("PRAGMA journal_mode = WAL")
            self.conn.execute("PRAGMA synchronous = NORMAL")
        self.migrate(load_migrations() if migrations is None else migrations)

    @property
    def version(self) -> int:
        return int(self.conn.execute("PRAGMA user_version").fetchone()[0])

    def migrate(self, migrations: Iterable[Migration]) -> None:
        migrations = list(migrations)
        latest = max((m.version for m in migrations), default=0)
        if self.version > latest:
            raise MigrationError(
                f"database schema v{self.version} is newer than this app supports (v{latest})"
            )
        for migration in migrations:
            if migration.version <= self.version:
                continue
            script = f"BEGIN;\n{migration.sql}\nPRAGMA user_version = {migration.version};\nCOMMIT;"
            try:
                self.conn.executescript(script)
            except sqlite3.Error as exc:
                if self.conn.in_transaction:
                    self.conn.execute("ROLLBACK")
                raise MigrationError(
                    f"migration {migration.version} ({migration.name}) failed: {exc}"
                ) from exc

    @contextmanager
    def transaction(self) -> Iterator[None]:
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        self.conn.execute("COMMIT")

    def execute(self, sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> sqlite3.Cursor:
        return self.conn.execute(sql, params)

    def close(self) -> None:
        self.conn.close()
