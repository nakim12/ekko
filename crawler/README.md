# crawler

Async Riot API client and crawl jobs (Phases 0–1).

- `httpx` async client with one shared token-bucket rate limiter (app lookups get priority later)
- `Retry-After` handling on 429, backoff retries on 5xx and network errors
- Resumable: checkpoints match IDs already fetched, so a killed run restarts without duplicates
- Writes raw JSON to an immutable Parquet landing zone under `data/raw/`, partitioned by date
- Long crawls run as a Fly.io machine; daily rank snapshots run as a GitHub Actions cron

Tests to write alongside: rate limiter, 429/5xx retry, checkpoint resume.

## Phase 0 sample

```bash
python -m crawler.phase0 fetch   # 20 players (2 per tier), last 100 ranked games + timelines
python -m crawler.phase0 load    # data/raw/phase0/*.json.gz -> Parquet -> raw.* tables in DuckDB
python -m crawler.phase0 check   # writes docs/phase0-field-check.md
```

`fetch` is resumable: rerun it after the dev key expires and it skips what's already on disk. The player sample is page 1 of one random division per tier, a convenience sample for the field check only.
