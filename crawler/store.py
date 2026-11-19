"""Raw landing zone under data/raw/: immutable Parquet segments plus JSONL control files.

API documents (matches, timelines) are buffered and written as Parquet segments of a few hundred
rows: data/raw/<kind>/dt=<UTC date>/part-<time>-<id>.parquet, with columns match_id, payload and
fetched_at.
Each segment is written to a temp file and renamed, so a killed run never leaves a partial file and
loses at most the current buffer. What's already stored is the checkpoint: `stored_ids` reads the
match_id column of every segment.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

DOCUMENT_SCHEMA = pa.schema(
    [
        ("match_id", pa.string()),
        ("payload", pa.string()),
        ("fetched_at", pa.timestamp("us", tz="UTC")),
    ]
)


def utc_now() -> datetime:
    return datetime.now(UTC)


class SegmentWriter:
    """Buffers documents of one kind and writes them as Parquet segments."""

    def __init__(
        self,
        raw_dir: Path,
        kind: str,
        flush_every: int = 500,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.dir = raw_dir / kind
        self.flush_every = flush_every
        self._clock = clock
        self._rows: list[tuple[str, str, datetime]] = []
        self.written = 0

    def add(self, match_id: str, payload: object) -> None:
        self._rows.append((match_id, json.dumps(payload, separators=(",", ":")), self._clock()))
        if len(self._rows) >= self.flush_every:
            self.flush()

    def flush(self) -> Path | None:
        if not self._rows:
            return None
        now = self._clock()
        out = self.dir / f"dt={now.date().isoformat()}"
        out.mkdir(parents=True, exist_ok=True)
        path = out / f"part-{now.strftime('%H%M%S')}-{uuid.uuid4().hex[:8]}.parquet"
        ids, payloads, stamps = zip(*self._rows, strict=True)
        table = pa.table(
            {"match_id": list(ids), "payload": list(payloads), "fetched_at": list(stamps)},
            schema=DOCUMENT_SCHEMA,
        )
        tmp = path.with_suffix(".parquet.tmp")
        pq.write_table(table, tmp, compression="zstd")
        tmp.rename(path)
        self.written += len(self._rows)
        self._rows.clear()
        return path


def stored_ids(raw_dir: Path, kind: str) -> set[str]:
    """match_ids already in the landing zone for `kind` (the crawl checkpoint)."""
    ids: set[str] = set()
    for path in sorted((raw_dir / kind).glob("dt=*/*.parquet")):
        ids.update(pq.read_table(path, columns=["match_id"]).column("match_id").to_pylist())
    return ids


def append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, separators=(",", ":")) + "\n")


def read_jsonl(path: Path) -> Iterator[dict]:
    """Records from a JSONL file; a torn last line (killed mid-write) is ignored."""
    if not path.exists():
        return
    with path.open(encoding="utf-8") as f:
        for line in f:
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue
