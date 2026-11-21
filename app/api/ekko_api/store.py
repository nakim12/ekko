"""App state in SQLite: lookup jobs with leases, cached API documents, and reports.

Jobs (PROJECT_PLAN.md 8.3):
- A lookup for a Riot ID that's already queued or running joins that job instead of starting
  another, and one with a report under REPORT_TTL old returns that job.
- A worker claims a job by taking a lease and renews it with every progress update. If the worker
  dies, the lease expires and another worker reclaims the job. A worker that lost its lease can't
  write: every update checks the lease token.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path

REPORT_TTL_SECONDS = 6 * 3600
LEASE_SECONDS = 180.0  # longer than any single rate-limited wait between progress updates

SCHEMA = """
create table if not exists jobs (
    id text primary key,
    riot_id text not null,          -- normalized (lowercase) name#tag
    display_riot_id text not null,
    status text not null,           -- queued | running | done | failed
    stage text,
    done integer default 0,
    total integer default 0,
    message text,
    report_id text,
    lease_token text,
    lease_until real,
    created_at real not null,
    updated_at real not null
);
create index if not exists jobs_riot_id on jobs (riot_id, created_at);
create table if not exists documents (
    kind text not null,
    match_id text not null,
    payload text not null,
    primary key (kind, match_id)
);
create table if not exists reports (
    id text primary key,
    riot_id text not null,
    created_at real not null,
    body text not null
);
"""


def normalize_riot_id(riot_id: str) -> str:
    return riot_id.strip().lower()


class Store:
    def __init__(self, path: Path | str, clock=time.time) -> None:
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("pragma journal_mode = wal")
        self._db.executescript(SCHEMA)
        self._lock = threading.Lock()
        self.clock = clock

    def _one(self, sql: str, args=()) -> dict | None:
        row = self._db.execute(sql, args).fetchone()
        return dict(row) if row else None

    # --- jobs ---

    def request_lookup(self, riot_id: str) -> dict:
        """The job for this Riot ID: an active one, a fresh finished one, or a new one."""
        key, now = normalize_riot_id(riot_id), self.clock()
        with self._lock:
            self._db.execute("begin immediate")
            try:
                active = self._one(
                    "select * from jobs where riot_id = ? and status in ('queued', 'running') "
                    "order by created_at desc limit 1",
                    (key,),
                )
                fresh = self._one(
                    "select j.* from jobs j join reports r on r.id = j.report_id "
                    "where j.riot_id = ? and j.status = 'done' and r.created_at > ? "
                    "order by r.created_at desc limit 1",
                    (key, now - REPORT_TTL_SECONDS),
                )
                job = active or fresh
                if job is None:
                    job_id = uuid.uuid4().hex
                    self._db.execute(
                        "insert into jobs (id, riot_id, display_riot_id, status, stage, "
                        "created_at, updated_at) values (?, ?, ?, 'queued', 'queued', ?, ?)",
                        (job_id, key, riot_id.strip(), now, now),
                    )
                    job = self._one("select * from jobs where id = ?", (job_id,))
                self._db.execute("commit")
            except Exception:
                self._db.execute("rollback")
                raise
        return job

    def claim(self, lease: float = LEASE_SECONDS) -> tuple[dict, str] | None:
        """Take the oldest queued job, or a running one whose lease expired: (job, lease token)."""
        now, token = self.clock(), uuid.uuid4().hex
        with self._lock:
            self._db.execute("begin immediate")
            try:
                job = self._one(
                    "select * from jobs where status = 'queued' "
                    "or (status = 'running' and lease_until < ?) order by created_at limit 1",
                    (now,),
                )
                if job:
                    self._db.execute(
                        "update jobs set status = 'running', lease_token = ?, lease_until = ?, "
                        "updated_at = ? where id = ?",
                        (token, now + lease, now, job["id"]),
                    )
                self._db.execute("commit")
            except Exception:
                self._db.execute("rollback")
                raise
        return (self.get_job(job["id"]), token) if job else None

    def update(self, job_id: str, token: str, lease: float = LEASE_SECONDS, **fields) -> bool:
        """Progress update that also renews the lease. False if this worker no longer owns it."""
        now = self.clock()
        sets = ", ".join(f"{k} = ?" for k in fields)
        with self._lock:
            cur = self._db.execute(
                f"update jobs set {sets + ', ' if sets else ''}lease_until = ?, updated_at = ? "
                "where id = ? and lease_token = ? and status = 'running'",
                (*fields.values(), now + lease, now, job_id, token),
            )
        return cur.rowcount == 1

    def finish(self, job_id: str, token: str, status: str, **fields) -> bool:
        now = self.clock()
        sets = "".join(f", {k} = ?" for k in fields)
        with self._lock:
            cur = self._db.execute(
                f"update jobs set status = ?, lease_until = null, updated_at = ?{sets} "
                "where id = ? and lease_token = ? and status = 'running'",
                (status, now, *fields.values(), job_id, token),
            )
        return cur.rowcount == 1

    def get_job(self, job_id: str) -> dict | None:
        return self._one("select * from jobs where id = ?", (job_id,))

    # --- documents (match-v5 payloads, shared across lookups) ---

    def get_document(self, kind: str, match_id: str) -> dict | None:
        row = self._one(
            "select payload from documents where kind = ? and match_id = ?", (kind, match_id)
        )
        return json.loads(row["payload"]) if row else None

    def put_document(self, kind: str, match_id: str, payload: dict) -> None:
        with self._lock:
            self._db.execute(
                "insert or ignore into documents (kind, match_id, payload) values (?, ?, ?)",
                (kind, match_id, json.dumps(payload, separators=(",", ":"))),
            )

    # --- reports ---

    def save_report(self, riot_id: str, body: dict) -> str:
        report_id = uuid.uuid4().hex
        with self._lock:
            self._db.execute(
                "insert into reports (id, riot_id, created_at, body) values (?, ?, ?, ?)",
                (
                    report_id,
                    normalize_riot_id(riot_id),
                    self.clock(),
                    json.dumps({**body, "report_id": report_id}),
                ),
            )
        return report_id

    def get_report(self, report_id: str) -> dict | None:
        row = self._one("select body from reports where id = ?", (report_id,))
        return json.loads(row["body"]) if row else None
