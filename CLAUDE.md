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
- **Site:** `app/web/hero.html` is the approved hero prototype (moonlit water, see `docs/DESIGN.md`). `app/web/index.html` is still the old placeholder page. `app/web/moodboard.html` is a discarded exploration.

## Next steps

1. Fold the hero into `index.html` and restyle the rest of the landing page in the same palette and motion language. Remove the `?at=` test hook from the hero before it ships (it renders one frame at a given time for screenshots).
2. Decide with the user whether the shooting star repeats every 25-40 s (current) or plays once per visit.
3. Deploy the landing page (plan: ekko.nakim.me on Vercel; needs the user's Vercel login and a DNS record).
4. Phase 1 crawler once the personal key arrives: stratified sampler with random pages and a minimum-games filter, checkpointed crawl to the Parquet landing zone, Fly.io deployment, daily rank snapshots via GitHub Actions.
5. Phase 2: dbt staging/intermediate/marts per plan section 6, built on the Phase 0 sample while the crawl runs.
