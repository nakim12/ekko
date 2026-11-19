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
- **Personal API key:** the user is applying. Phase 1 (unattended crawler on Fly.io, daily rank snapshot cron) is blocked until it's approved.
- **Site:** `app/web/index.html` is the landing page: the approved moonlit-water hero plus questions, method, "spot the real streak" game (8 real 30-game W/L histories from Phase 0, hard-coded) and follow-along links. See `docs/DESIGN.md`. The shooting star repeating every 25-40 s is confirmed. `app/web/moodboard.html` is a discarded exploration. For screenshots, headless Chrome works (`--force-prefers-reduced-motion` renders a still frame with all content visible).

## Next steps

1. Landing page polish from user feedback (a LinkedIn link is planned but the URL isn't known yet).
2. Deploy (ekko.nakim.me on Vercel; needs the user's Vercel login and a DNS record). Deferred: the user wants to deploy once the app is done and work locally until then, so don't push for it.
3. Phase 1 crawler once the personal key arrives: stratified sampler with random pages and a minimum-games filter, checkpointed crawl to the Parquet landing zone, Fly.io deployment, daily rank snapshots via GitHub Actions.
4. Phase 2: dbt staging/intermediate/marts per plan section 6, built on the Phase 0 sample while the crawl runs.
