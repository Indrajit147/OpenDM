"""SQLite database and migrations."""

import sqlite3
from pathlib import Path

import pytest

from opendm.storage.db import Database, Migration, MigrationError, load_migrations


def test_bundled_migrations_are_numbered_from_one() -> None:
    migrations = load_migrations()
    assert [m.version for m in migrations] == list(range(1, len(migrations) + 1))
    assert migrations[0].name == "initial"


def test_fresh_database_is_fully_migrated() -> None:
    db = Database(":memory:")
    assert db.version == len(load_migrations())
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"jobs", "queues", "categories", "settings"} <= tables
    assert db.execute("SELECT name FROM queues WHERE id = 1").fetchone()[0] == "Main"
    names = [r[0] for r in db.execute("SELECT name FROM categories ORDER BY position")]
    assert names == ["Video", "Audio", "Documents", "Compressed", "Programs", "Other"]
    assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    db.close()


def test_file_database_uses_wal_and_survives_reopen(tmp_path: Path) -> None:
    path = tmp_path / "opendm.db"
    db = Database(path)
    assert db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    db.execute("INSERT INTO settings (key, value) VALUES ('k', '1')")
    db.close()
    again = Database(path)
    assert again.execute("SELECT value FROM settings WHERE key = 'k'").fetchone()[0] == "1"
    assert again.version == len(load_migrations())  # re-running migrations is a no-op
    again.close()


def test_upgrade_keeps_existing_data(tmp_path: Path) -> None:
    path = tmp_path / "db"
    v1 = [Migration(1, "one", "CREATE TABLE t (x INTEGER);")]
    db = Database(path, migrations=v1)
    db.execute("INSERT INTO t VALUES (42)")
    db.close()
    v2 = [*v1, Migration(2, "two", "ALTER TABLE t ADD COLUMN y TEXT DEFAULT 'new';")]
    db = Database(path, migrations=v2)
    assert db.version == 2
    assert db.execute("SELECT x, y FROM t").fetchone() == (42, "new")
    db.close()


def test_failed_migration_rolls_back_completely(tmp_path: Path) -> None:
    path = tmp_path / "db"
    good = Migration(1, "good", "CREATE TABLE a (x);")
    bad = Migration(2, "bad", "CREATE TABLE b (x); INSERT INTO nope VALUES (1);")
    with pytest.raises(MigrationError):
        Database(path, migrations=[good, bad])
    conn = sqlite3.connect(path)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
    assert "a" in tables and "b" not in tables  # migration 2 left nothing behind
    conn.close()


def test_newer_database_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "db"
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA user_version = 999")
    conn.close()
    with pytest.raises(MigrationError):
        Database(path)


def test_transaction_rolls_back_on_error() -> None:
    db = Database(":memory:")
    with pytest.raises(RuntimeError), db.transaction():
        db.execute("INSERT INTO settings (key, value) VALUES ('a', '1')")
        raise RuntimeError("boom")
    assert db.execute("SELECT count(*) FROM settings").fetchone()[0] == 0
    with db.transaction():
        db.execute("INSERT INTO settings (key, value) VALUES ('a', '1')")
    assert db.execute("SELECT count(*) FROM settings").fetchone()[0] == 1
