# Ekko

Is it tilt, or is it the queue? A Riot API data platform, a pre-registered causal study of ranked League of Legends losing streaks, and a public site/app. The full plan is `docs/PROJECT_PLAN.md`; read it before planning work. Site identity decisions are in `docs/DESIGN.md`.

## Working conventions

- Commit messages: one line only (e.g. `feat(crawler): ...`). No body, no Co-Authored-By trailer.
- Work on `main`, commit small verified milestones, push to `origin main`. Never force-push.
- Never commit `.env`, anything under `data/`, `*.duckdb` or `*.parquet`. Riot keys stay in `.env`; don't print them.
- Python: `source .venv/bin/activate`, then `ruff check .`, `ruff format .`, `pytest`. dbt: `cd dbt && dbt parse --profiles-dir .`.
- Local site preview with auto-reload: `npx live-server app/web --port=5173 --no-browser` (run in the background), then http://localhost:5173.
- The Riot key in `.env` may be a 24-hour development key. A 401 "Unknown apikey" means it expired or was just generated (new keys can take a few minutes to activate).
- `analysis/PREREGISTRATION.md` must be committed before any outcome analysis. Don't run outcome models before it exists.

## Status (2026-11-18)

- **Phase 0 done.** 20 players (2 per tier, Iron to Challenger), 1,836 ranked games with timelines, loaded into `data/ekko.duckdb` (`raw.matches`, `raw.timelines`, `raw.phase0_players`). Every field in the data model is present; see `docs/phase0-field-check.md`. Code: `crawler/riot.py` (per-host sliding-window rate limiter, 429/5xx retries), `crawler/phase0.py` (`fetch` / `load` / `check`).
- Finding to carry forward: some players have far fewer than 100 ranked games (min 11), so the real sampler needs a minimum-games filter.
- **Pre-registration committed** (`analysis/PREREGISTRATION.md`, 2026-11-18, `235ac5f`). It governs over the plan where they differ. Changes go in its Deviations section, in a separate commit; never edit it silently. Implications for Phase 1 and Phase 2:
  - Sampler: 250 per tier (Iron to Diamond, random divisions/pages) + 250 random Master+; keep players with 30+ ranked solo games (else redraw); last 150 games each; Phase 0 players ineligible.
  - Q2 is a daily job, not a one-off: for focal players' newest matches, look up all 10 ranks within 24 h of match end, until 10,000 matches qualify. Also fetch 5 prior games of one random non-focal participant (placebo).
  - H2a (autofill) runs on a random 1,000-match subsample only (needs each participant's previous 20 games).
  - Every model must be validated on simulated data with a planted effect before it runs on real outcomes.
- **Phase 2 started:** dbt staging → intermediate → marts on the Phase 0 sample (`dbt build` passes, 64 checks; sessions/streaks cross-checked against an independent Python recomputation). See `dbt/README.md`. Still to build once Phase 1 data exists: rank snapshots and `fct_match_team_strength` (Q2). Phase 0 output is for building and testing only, never results.
- **Analysis code built and validated** (`analysis/src/ekko_analysis`, see `analysis/README.md`): Q1, selection, Q2, Q3 models; `pytest tests/analysis` (simulated planted effects) and `python -m ekko_analysis.validate` (Phase 0 structure, shuffled outcomes) both pass. Validation found two flaws in the registered models, logged as Deviations 1-2 in the pre-registration (H1 drops missing-lag rows; H3 uses a block permutation null); registered versions stay available via `lag="fill"` / `null="drift"` and must be reported alongside. Results runner built: `python -m ekko_analysis.run` (see `analysis/README.md`). It refuses anything but a full Phase 1 build, and is tested end to end on simulated data only. Never run it on Phase 0.
- **Q2 dbt models built** (`dbt/models/*/q2/`, `fct_match_team_strength` with focal and placebo perspectives, `dim_rank_snapshot`), tested on live scratch data. The crawler now also fetches the focal player's previous 5 games per Q2 match (streak state). Observation for Phase 1: the registered 60% main-role rule flags role-flexible players as autofilled (6 of 9 in one Iron match); check the flag rate by tier on Phase 1 data (descriptive, no outcomes) before H2a.
- **Timeline size matters for Phase 1:** raw timelines are ~0.8 MB of JSON each (1.5 GB for 1,836), so 300k would be ~240 GB uncompressed. DuckDB can't parse them whole-table (the timeline staging models are Python models that parse in hash buckets). Decide in Phase 1 whether the landing zone keeps full timelines (Parquet with zstd) or only participant frames + kill events.
- **Phase 1 crawler built, not yet run for real** (see `crawler/README.md`):
  - What it does: stratified sampler, resumable match/timeline crawl to Parquet segments, daily rank snapshots, Q2 collection, a supervisor process for Fly.io (`Dockerfile`, `fly.toml`), and a loader exposing Parquet as `raw.*` views.
  - Testing: 51 tests pass with a mocked API.
  - Live-tested 2026-11-19 with a dev key in a scratch data dir (8-player sample, 40 documents, snapshots, 2 Q2 matches, load, dbt build on Phase 1 vars): all worked. Sampling's page-count search costs ~570 requests (~10 min) once. dbt on Phase 1 data: `dbt build --vars '{phase: 1}'` (switches sources to Phase 1 tables and enables the Q2 models); focal games are restricted to each player's crawled match IDs.
  - Not done yet:
    - Fly deploy (needs the user's Fly login and the personal key);
    - getting data back from the Fly volume.
  - Infra choice: the crawl and the scheduled jobs share one supervisor process, not GitHub Actions cron, because a Fly volume attaches to one machine and rate limits are per key. Q2 runs every 6 h with an 8 h window, so rank lookups land within 24 h of match end.
- **CI** (`.github/workflows/ci.yml`): ruff, pytest, and dbt build for both phases on a synthetic warehouse (`tests/fixtures/synthetic_warehouse.py`; real data never goes in git). Check that CI is green after pushing: `gh` isn't logged in here, so use `curl -s https://api.github.com/repos/nakim12/ekko/actions/runs?per_page=1`. It was red from `d66cc92` to `98e1d01` (missing analysis deps, then a YAML error) without anyone noticing.
- **Phase 0 descriptive notes (no outcomes):** the duo flag (a teammate in 4+ of a player's games) hits 25% of Phase 0 games. It varies by player (Bronze 88%, Gold 4%), which looks like real duo habits. Check again on Phase 1.
- **App backend built** (`app/api/ekko_api`, see `app/README.md`): FastAPI, SQLite job queue with leases, SSE progress, cached documents, personal stats with empirical Bayes shrinkage. The priors are placeholders until Phase 1 results exist. Feature parity with dbt is checked in CI, and was 0 mismatches on 1,787 Phase 0 games. Frontend chosen: Next.js + TypeScript, landing page served byte-identical as a static file at `/`, report at `/report`. Matchmaking check: last 10 games only.
- **Personal API key:** the user is applying. Phase 1 (unattended crawler on Fly.io, daily rank snapshot cron) is blocked until it's approved.
- **Site:** `app/web/index.html` is the landing page: the approved moonlit-water hero plus questions, method, "spot the real streak" game (8 real 30-game W/L histories from Phase 0, hard-coded) and follow-along links. See `docs/DESIGN.md`. The shooting star repeating every 25-40 s is confirmed. `app/web/moodboard.html` is a discarded exploration. For screenshots, headless Chrome works (`--force-prefers-reduced-motion` renders a still frame with all content visible).

## Next steps

1. Landing page polish from user feedback (a LinkedIn link is planned but the URL isn't known yet).
2. Deploy (ekko.nakim.me on Vercel; needs the user's Vercel login and a DNS record). Deferred: the user wants to deploy once the app is done and work locally until then, so don't push for it.
3. Phase 1 crawler once the personal key arrives: stratified sampler with random pages and a minimum-games filter, checkpointed crawl to the Parquet landing zone, Fly.io deployment, daily rank snapshots via GitHub Actions.
4. Phase 2: dbt staging/intermediate/marts per plan section 6, built on the Phase 0 sample while the crawl runs.
