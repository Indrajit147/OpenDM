"""Typed access to the tables. All SQL lives here.

Cookies and auth headers are encrypted with DPAPI before they reach the database
(``core.secrets``); where that is unavailable they are not stored at all.
"""

# Postponed annotations: the repositories have a ``list`` method that would shadow
# the builtin inside class bodies.
from __future__ import annotations

import contextlib
import dataclasses
import json
import sqlite3
from collections.abc import Collection
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from opendm.core import secrets
from opendm.core.branding import PARTIAL_SUFFIX, STATE_SUFFIX
from opendm.core.models import (
    MAIN_QUEUE_ID,
    AfterAction,
    Category,
    DownloadRequest,
    Job,
    JobState,
    Queue,
    utc_now,
)
from opendm.storage.db import Database

SECRET_HEADERS = frozenset({"cookie", "authorization", "proxy-authorization"})
ACTIVE_STATES = frozenset({JobState.PROBING, JobState.DOWNLOADING, JobState.VERIFYING})

_JOB_COLUMNS = (
    "id, url, dest_dir, filename, final_path, category_id, queue_id, position, state, message, "
    "size, downloaded, connections, speed_limit, checksum, verify_tls, referrer, user_agent, "
    "headers, secrets, relinked, error_kind, error_message, sha256, created_at, started_at, "
    "completed_at"
)


def _ts(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _path(value: str | None) -> Path | None:
    return Path(value) if value else None


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class JobRepository:
    def __init__(self, db: Database, *, store_secrets: bool | None = None) -> None:
        self.db = db
        self.store_secrets = secrets.available() if store_secrets is None else store_secrets

    # --- (de)serialization ------------------------------------------------------------------

    def _seal(self, request: DownloadRequest) -> tuple[str, bytes | None]:
        plain = {k: v for k, v in request.headers.items() if k.lower() not in SECRET_HEADERS}
        hidden = {k: v for k, v in request.headers.items() if k.lower() in SECRET_HEADERS}
        blob = None
        if self.store_secrets and (hidden or request.cookies):
            payload = json.dumps({"headers": hidden, "cookies": request.cookies})
            blob = secrets.protect(payload.encode("utf-8"))
        return json.dumps(plain), blob

    def _unseal(self, headers_json: str, blob: bytes | None) -> tuple[dict[str, str], str | None]:
        headers: dict[str, str] = json.loads(headers_json)
        cookies = None
        if blob and self.store_secrets:
            with contextlib.suppress(secrets.SecretsError, ValueError):
                hidden = json.loads(secrets.unprotect(blob).decode("utf-8"))
                headers.update(hidden.get("headers", {}))
                cookies = hidden.get("cookies")
        return headers, cookies

    def _row(self, job: Job) -> dict[str, Any]:
        r = job.request
        headers, blob = self._seal(r)
        return {
            "id": job.id, "url": r.url, "dest_dir": str(r.dest_dir), "filename": r.filename,
            "final_path": str(job.final_path) if job.final_path else None,
            "category_id": job.category_id, "queue_id": job.queue_id, "position": job.position,
            "state": str(job.state), "message": job.message, "size": job.size,
            "downloaded": job.downloaded, "connections": job.connections,
            "speed_limit": r.speed_limit, "checksum": r.checksum, "verify_tls": int(r.verify_tls),
            "referrer": r.referrer, "user_agent": r.user_agent, "headers": headers,
            "secrets": blob, "relinked": int(job.relinked), "error_kind": job.error_kind,
            "error_message": job.error_message, "sha256": job.sha256,
            "created_at": _ts(job.created_at), "started_at": _ts(job.started_at),
            "completed_at": _ts(job.completed_at),
        }  # fmt: skip

    def _job(self, row: sqlite3.Row | tuple[Any, ...]) -> Job:
        (job_id, url, dest_dir, filename, final_path, category_id, queue_id, position, state,
         message, size, downloaded, connections, speed_limit, checksum, verify_tls, referrer,
         user_agent, headers_json, blob, relinked, error_kind, error_message, sha256, created_at,
         started_at, completed_at) = row  # fmt: skip
        headers, cookies = self._unseal(headers_json, blob)
        request = DownloadRequest(
            url=url, dest_dir=Path(dest_dir), filename=filename, headers=headers,
            user_agent=user_agent, referrer=referrer, cookies=cookies,
            verify_tls=bool(verify_tls), checksum=checksum, speed_limit=speed_limit,
        )  # fmt: skip
        return Job(
            request=request, id=job_id, queue_id=queue_id, category_id=category_id,
            position=position, state=JobState(state), message=message,
            final_path=_path(final_path), size=size, downloaded=downloaded,
            connections=connections, relinked=bool(relinked), error_kind=error_kind,
            error_message=error_message, sha256=sha256,
            created_at=_dt(created_at) or utc_now(), started_at=_dt(started_at),
            completed_at=_dt(completed_at),
        )  # fmt: skip

    # --- commands ---------------------------------------------------------------------------------

    def next_position(self, queue_id: int) -> int:
        row = self.db.execute("SELECT max(position) FROM jobs WHERE queue_id = ?", (queue_id,))
        return (row.fetchone()[0] or 0) + 1

    def add(self, job: Job) -> Job:
        job.position = self.next_position(job.queue_id)
        row = self._row(job)
        names = ", ".join(row)
        marks = ", ".join(f":{k}" for k in row)
        self.db.execute(f"INSERT INTO jobs ({names}) VALUES ({marks})", row)
        return job

    def save(self, job: Job) -> None:
        row = self._row(job)
        sets = ", ".join(f"{k} = :{k}" for k in row if k != "id")
        self.db.execute(f"UPDATE jobs SET {sets} WHERE id = :id", row)

    def update_progress(self, job_id: str, downloaded: int, size: int | None) -> None:
        self.db.execute(
            "UPDATE jobs SET downloaded = ?, size = ? WHERE id = ?", (downloaded, size, job_id)
        )

    def get(self, job_id: str) -> Job | None:
        row = self.db.execute(f"SELECT {_JOB_COLUMNS} FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return self._job(row) if row else None

    def list(
        self,
        *,
        states: Collection[JobState] | None = None,
        queue_id: int | None = None,
        category_id: int | None = None,
        search: str | None = None,
        order: Literal["position", "created", "completed"] = "position",
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Job]:
        where, params = [], []
        if states is not None:
            where.append(f"state IN ({', '.join('?' * len(states))})")
            params += [str(s) for s in states]
        if queue_id is not None:
            where.append("queue_id = ?")
            params.append(queue_id)
        if category_id is not None:
            where.append("category_id = ?")
            params.append(category_id)
        if search:
            pattern = f"%{_escape_like(search)}%"
            where.append(
                "(coalesce(final_path, '') LIKE ? ESCAPE '\\' OR coalesce(filename, '') LIKE ? "
                "ESCAPE '\\' OR url LIKE ? ESCAPE '\\')"
            )
            params += [pattern] * 3
        order_by = {
            "position": "queue_id, position, created_at",
            "created": "created_at DESC",
            "completed": "completed_at DESC",
        }[order]
        sql = f"SELECT {_JOB_COLUMNS} FROM jobs"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += f" ORDER BY {order_by} LIMIT ? OFFSET ?"
        params += [-1 if limit is None else limit, offset]
        return [self._job(r) for r in self.db.execute(sql, params)]

    def history(
        self,
        *,
        search: str | None = None,
        category_id: int | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Job]:
        """Completed downloads, newest first."""
        return self.list(
            states={JobState.COMPLETED}, search=search, category_id=category_id,
            order="completed", limit=limit, offset=offset,
        )  # fmt: skip

    def clear_history(self) -> int:
        """Remove completed entries (never their files)."""
        cur = self.db.execute("DELETE FROM jobs WHERE state = ?", (str(JobState.COMPLETED),))
        return cur.rowcount

    def mark_interrupted(self) -> int:
        """After a crash: running jobs become PAUSED ("interrupted")."""
        marks = ", ".join("?" * len(ACTIVE_STATES))
        cur = self.db.execute(
            f"UPDATE jobs SET state = ?, message = 'interrupted' WHERE state IN ({marks})",
            [str(JobState.PAUSED), *(str(s) for s in ACTIVE_STATES)],
        )
        return cur.rowcount

    def delete(self, job_id: str, *, delete_file: bool = False) -> bool:
        """Remove the entry; with ``delete_file`` also the file or its partial files.

        The caller is responsible for asking the user before deleting files.
        """
        job = self.get(job_id)
        if job is None:
            return False
        self.db.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        if delete_file and job.final_path is not None:
            target = job.final_path
            doomed = [target.with_name(target.name + s) for s in (PARTIAL_SUFFIX, STATE_SUFFIX)]
            if job.state is JobState.COMPLETED:
                doomed.append(target)
            for path in doomed:
                with contextlib.suppress(OSError):
                    path.unlink(missing_ok=True)
        return True

    def redownload(self, job_id: str) -> Job:
        """A fresh queued copy of a job's request."""
        old = self.get(job_id)
        if old is None:
            raise KeyError(job_id)
        request = dataclasses.replace(old.request, restart=False, part_file=None)
        job = Job(request, queue_id=old.queue_id, category_id=old.category_id)
        return self.add(job)


def _check_time(value: str | None) -> None:
    if value is None:
        return
    try:
        datetime.strptime(value, "%H:%M")
    except ValueError as exc:
        raise ValueError(f"time must be HH:MM, got {value!r}") from exc


class QueueRepository:
    _COLUMNS = (
        "id, name, max_concurrent, enabled, start_time, stop_time, days, after_action, position"
    )

    def __init__(self, db: Database) -> None:
        self.db = db

    @staticmethod
    def _validate(queue: Queue) -> None:
        if not queue.name.strip():
            raise ValueError("queue name is empty")
        if not 1 <= queue.max_concurrent <= 32:
            raise ValueError("max_concurrent must be 1-32")
        if not 0 <= queue.days <= 0b1111111:
            raise ValueError("days must be a 7-bit mask")
        _check_time(queue.start_time)
        _check_time(queue.stop_time)

    def _queue(self, row: tuple[Any, ...]) -> Queue:
        qid, name, max_c, enabled, start, stop, days, action, position = row
        return Queue(
            name, qid, max_c, bool(enabled), start, stop, days, AfterAction(action), position
        )

    def list(self) -> list[Queue]:
        rows = self.db.execute(f"SELECT {self._COLUMNS} FROM queues ORDER BY position, id")
        return [self._queue(r) for r in rows]

    def get(self, queue_id: int) -> Queue | None:
        row = self.db.execute(f"SELECT {self._COLUMNS} FROM queues WHERE id = ?", (queue_id,))
        found = row.fetchone()
        return self._queue(found) if found else None

    def add(self, queue: Queue) -> Queue:
        self._validate(queue)
        queue.position = self.db.execute(
            "SELECT coalesce(max(position), -1) + 1 FROM queues"
        ).fetchone()[0]
        try:
            cur = self.db.execute(
                "INSERT INTO queues (name, max_concurrent, enabled, start_time, stop_time, days, "
                "after_action, position) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (queue.name, queue.max_concurrent, int(queue.enabled), queue.start_time,
                 queue.stop_time, queue.days, str(queue.after_action), queue.position),
            )  # fmt: skip
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"a queue named {queue.name!r} already exists") from exc
        queue.id = cur.lastrowid
        return queue

    def save(self, queue: Queue) -> None:
        self._validate(queue)
        self.db.execute(
            "UPDATE queues SET name = ?, max_concurrent = ?, enabled = ?, start_time = ?, "
            "stop_time = ?, days = ?, after_action = ?, position = ? WHERE id = ?",
            (queue.name, queue.max_concurrent, int(queue.enabled), queue.start_time,
             queue.stop_time, queue.days, str(queue.after_action), queue.position, queue.id),
        )  # fmt: skip

    def delete(self, queue_id: int) -> None:
        """Delete a queue; its jobs move to Main."""
        if queue_id == MAIN_QUEUE_ID:
            raise ValueError("the Main queue cannot be deleted")
        self.db.execute("DELETE FROM queues WHERE id = ?", (queue_id,))


def _normalize_extensions(extensions: Collection[str]) -> tuple[str, ...]:
    return tuple(e.strip().lower().lstrip(".") for e in extensions if e.strip(" ."))


class CategoryRepository:
    _COLUMNS = "id, name, extensions, folder, fallback, position"

    def __init__(self, db: Database) -> None:
        self.db = db

    def _category(self, row: tuple[Any, ...]) -> Category:
        cid, name, extensions, folder, fallback, position = row
        return Category(name, tuple(extensions.split()), folder, bool(fallback), cid, position)

    def list(self) -> list[Category]:
        rows = self.db.execute(f"SELECT {self._COLUMNS} FROM categories ORDER BY position, id")
        return [self._category(r) for r in rows]

    def get(self, category_id: int) -> Category | None:
        row = self.db.execute(
            f"SELECT {self._COLUMNS} FROM categories WHERE id = ?", (category_id,)
        ).fetchone()
        return self._category(row) if row else None

    def fallback(self) -> Category:
        row = self.db.execute(
            f"SELECT {self._COLUMNS} FROM categories WHERE fallback = 1 ORDER BY position LIMIT 1"
        ).fetchone()
        return self._category(row)

    def add(self, category: Category) -> Category:
        category.extensions = _normalize_extensions(category.extensions)
        category.position = self.db.execute(
            "SELECT coalesce(max(position), -1) + 1 FROM categories"
        ).fetchone()[0]
        cur = self.db.execute(
            "INSERT INTO categories (name, extensions, folder, fallback, position) "
            "VALUES (?, ?, ?, 0, ?)",
            (category.name, " ".join(category.extensions), category.folder, category.position),
        )
        category.id = cur.lastrowid
        return category

    def save(self, category: Category) -> None:
        category.extensions = _normalize_extensions(category.extensions)
        self.db.execute(
            "UPDATE categories SET name = ?, extensions = ?, folder = ?, position = ? WHERE id = ?",
            (category.name, " ".join(category.extensions), category.folder, category.position,
             category.id),
        )  # fmt: skip

    def delete(self, category_id: int) -> None:
        category = self.get(category_id)
        if category is not None and category.fallback:
            raise ValueError("the fallback category cannot be deleted")
        self.db.execute("DELETE FROM categories WHERE id = ?", (category_id,))


class SettingsRepository:
    """Key -> JSON value."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def get(self, key: str, default: Any = None) -> Any:
        row = self.db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def all(self) -> dict[str, Any]:
        return {k: json.loads(v) for k, v in self.db.execute("SELECT key, value FROM settings")}

    def set_many(self, values: dict[str, Any]) -> None:
        with self.db.transaction():
            for key, value in values.items():
                self.set(key, value)

    def set(self, key: str, value: Any) -> None:
        self.db.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value)),
        )
