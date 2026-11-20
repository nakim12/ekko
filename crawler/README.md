# crawler

Async Riot API client and crawl jobs (Phases 0–1).

- `riot.py`: `httpx` async client with a sliding-window rate limiter per routing host, `Retry-After` on 429, backoff on 5xx and network errors, 404 → `None`, 401/403 → `RiotAPIError`.
- `store.py`: the raw landing zone. API documents are written as immutable Parquet segments (`data/raw/<kind>/dt=<date>/part-*.parquet`, temp file then rename). What's stored is the checkpoint, so every job resumes after a crash or an expired key.
- `sampler.py`, `phase1.py`: the stratified sample and the main crawl.
- `daily.py`: rank snapshots and the Q2 collection.
- `supervisor.py`: everything in one process for Fly.io.
- `load.py`: exposes the landing zone to DuckDB as `raw.*` views for dbt.

## Phase 0 sample

```bash
python -m crawler.phase0 fetch   # 20 players (2 per tier), last 100 ranked games + timelines
python -m crawler.phase0 load    # data/raw/phase0/*.json.gz -> Parquet -> raw.* tables in DuckDB
python -m crawler.phase0 check   # writes docs/phase0-field-check.md
```

`fetch` is resumable: rerun it after the dev key expires and it skips what's already on disk. The player sample is page 1 of one random division per tier, a convenience sample for the field check only.

## Phase 1 (PREREGISTRATION.md section 3)

```bash
python -m crawler.phase1 sample      # 250 per tier Iron-Diamond + 250 Master+; active, not Phase 0, 30+ ranked games
python -m crawler.phase1 match-ids   # last 150 ranked solo match IDs per player
python -m crawler.phase1 fetch       # matches + timelines; --max-docs N for a short test burst
python -m crawler.phase1 status
python -m crawler.daily snapshots    # once a day
python -m crawler.daily q2           # every 6 hours, until 10,000 matches qualify
python -m crawler.supervisor         # all of the above in one process (what Fly runs)
python -m crawler.load               # landing zone -> raw.* views, then (in dbt/):
                                     # dbt build --profiles-dir . --vars '{players_table: players, player_match_ids_table: player_match_ids}'
```

Control files live in `data/raw/phase1/`:
- `sample_config.json`, `players.jsonl`;
- `sample_log.jsonl`: every draw and why it was kept or rejected;
- `first_match_ids.jsonl`, `match_ids.jsonl`;
- `missing.jsonl` (404s, not retried) and `errors.jsonl`.

Draw n of a stratum is seeded by `(seed, stratum, n)`, so a resumed sample continues the same sequence of draws.

**Budget** (personal key, 100 requests per 2 minutes per routing host): sampling plus match IDs is roughly 10k requests. Matches plus timelines are about 2 × the unique matches, around 500k at full size, or about 8 days on the `americas` host. Q2 costs per match:
- 10 rank lookups on `na1`;
- about 6 requests for the placebo history;
- about 190 requests for the 10% autofill subsample.

Q2 shares the `americas` host with the crawl, so it slows the crawl somewhat while both run.

**Storage:** timelines are about 60 KB each in zstd Parquet, so the full crawl plus Q2 is about 25 GB.

## Deploy to Fly.io

One machine runs `crawler.supervisor` with a volume at `/data`. A Fly volume attaches to a single machine, and rate limits are per key, so the crawl and the scheduled jobs share one process instead of separate cron machines or GitHub Actions.

```bash
fly apps create ekko-crawler
fly volumes create ekko_data --region ord --size 40
fly secrets set RIOT_API_KEY=RGAPI-...      # the personal key; also restarts the machine
fly deploy
fly logs                                    # progress lines from every job
fly ssh console -C "python -m crawler.phase1 status"
```

An expired or revoked key stops the run cleanly, with no restart loop. Set the new key with `fly secrets set` and it resumes. A crash restarts the machine, and every job picks up from what's on disk. Copying the landing zone back for dbt (or syncing it to MotherDuck) is still to be set up.
