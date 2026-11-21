# app

Public Riot ID lookup with a personal tilt report (PROJECT_PLAN.md sections 8 and 9).

## api (FastAPI)

```bash
uvicorn ekko_api.main:default_app --factory --reload --port 8000   # uses RIOT_API_KEY from .env
```

| Endpoint | |
|---|---|
| `POST /api/lookups {"riot_id": "name#tag"}` | starts (or joins) a lookup |
| `GET /api/lookups/{id}/events` | server-sent progress events until done or failed |
| `GET /api/reports/{report_id}` | the report |

- **Jobs** live in SQLite (`data/app.sqlite`) with leases:
  - a second lookup for the same Riot ID joins the active job;
  - a report under 6 hours old is reused;
  - a crashed worker's job is reclaimed when its lease expires, and the old worker can no longer write.
- **Caching:** match and timeline payloads are cached, so refreshes only fetch new games.
- **Features** (`features.py`) reimplement the dbt definitions for one player. `tests/app/test_dbt_parity.py` checks they match `fct_player_games` game by game: in CI on the synthetic warehouse, and once on all 1,787 Phase 0 games.
- **Stats** (`stats.py`):
  - tilt: the player's own H1 model, shrunk toward their tier's average;
  - cooldown;
  - stop rule (Wilson interval);
  - matchmaking check over the last 10 games, which never makes a claim.

  Each block has a `supported` flag for the AI coach.
- **Priors** (`priors.json`) are **placeholders**: neutral tier averages, and gold norms from the Phase 0 field check. Replace them with values exported from the Phase 1 results; computing them from Phase 0 would be outcome analysis on excluded data. Reports say so (`priors_are_placeholders`).
- **Privacy:** reports are addressed by a random ID and only describe the Riot ID entered. PUUIDs never appear in responses.

Public use needs a Riot production key. Local development works with a dev key.

## web

Next.js + TypeScript (next).
