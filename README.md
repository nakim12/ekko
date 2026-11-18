# Ekko

**Is it tilt, or is it the queue?** When you go on a ranked losing streak in League of Legends, is it you (tilt) or the matchmaker (loser's queue)?

Ekko is a data platform, a pre-registered causal study, and a public app that answers that question with Riot API data.

> Status: **Phase 0 (setup and data check).** No findings yet. The full plan is in [`docs/PROJECT_PLAN.md`](docs/PROJECT_PLAN.md).

## Questions

| | Question | Primary test |
|---|---|---|
| Q1 | **Tilt:** after a loss, does a player perform worse next game than their own baseline? | Within-player fixed effects on standardized gold diff at 14, with selection correction |
| Q2 | **Loser's queue:** after a streak, are your teammates weaker relative to your opponents than your rank predicts? | Team strength gap by streak state, with a placebo test |
| Q3 | **Streaks:** are win/loss streaks longer than chance? | Per-player runs test against a simulated null with drifting skill |

Hypotheses, definitions and exclusions are fixed in `analysis/PREREGISTRATION.md`, committed before any outcome analysis.

## Architecture

```
Riot API → async crawler (Fly.io) → Parquet landing zone → MotherDuck/DuckDB
        → dbt (staging → intermediate → marts) → analysis · Power BI · Tableau · FastAPI + Next.js app
```

## Repository layout

| Path | Contents |
|---|---|
| `crawler/` | Async Riot API client, rate limiter, crawl jobs |
| `dbt/` | dbt-duckdb project: staging, intermediate, marts, tests |
| `analysis/` | Pre-registration, notebooks (exploration only), `src/` models, generated `results/` |
| `app/api`, `app/web` | FastAPI backend and Next.js frontend (Phase 6) |
| `ai/` | AI coach prompts, verifier, eval set and runner (Phase 7) |
| `bi/` | Power BI `.pbix`, Tableau workbook, screenshots (Phase 5) |
| `docs/` | Project plan and interview notes |

## Setup

Requires Python 3.11+.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[crawler,dbt,dev]"      # add ,analysis / ,app / ,ai as phases need them
cp .env.example .env                     # then fill in RIOT_API_KEY
pytest
cd dbt && dbt parse --profiles-dir .
```

Raw data lands in `data/` locally and is never committed.

## Legal

Ekko isn't endorsed by Riot Games and doesn't reflect the views or opinions of Riot Games or anyone officially involved in producing or managing Riot Games properties. Riot Games and all associated properties are trademarks or registered trademarks of Riot Games, Inc.
