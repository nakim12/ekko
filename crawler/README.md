# crawler

Async Riot API client and crawl jobs (Phases 0–1).

- `httpx` async client with one shared token-bucket rate limiter (app lookups get priority later)
- `Retry-After` handling on 429, retries on 5xx via `tenacity`
- Resumable: checkpoints match IDs already fetched, so a killed run restarts without duplicates
- Writes raw JSON to an immutable Parquet landing zone under `data/raw/`, partitioned by date
- Long crawls run as a Fly.io machine; daily rank snapshots run as a GitHub Actions cron

Tests to write alongside: rate limiter, 429/5xx retry, checkpoint resume.
