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

- **Coach** (`coach.py`, PROJECT_PLAN.md section 9): Claude Opus 5.5 writes a short note from a fact sheet. The fact sheet holds the report's numbers, rounded as shown, plus `supported` flags; the model never sees match data. The call uses structured output (`beta.messages.parse` with a Pydantic schema) and server-side refusal fallbacks (`fallbacks="default"`).
  - **Verification** runs on every note:
    - numbers must match facts;
    - cited facts must exist;
    - no effect may be claimed for an unsupported block;
    - recommendations come only from approved actions with supported evidence;
    - no claims about the matchmaker.
  - **Failure path:** one regeneration with the violations listed, then a deterministic template, which provably passes verification. Reports say which the reader got (`coach.source`).
  - The coach runs only when `ANTHROPIC_API_KEY` is set.
- **Coach evaluation** (`coach_eval.py`): 50 synthetic edge-case profiles, scored with and without the verification layer (numeric accuracy, unsupported-claim rate, coverage, template rate). `python -m ekko_api.coach_eval --yes`, about 100–150 model calls. Real profiles and the LLM-judge pass come with Phase 1 data.

Public use needs a Riot production key. Local development works with a dev key.

## web (Next.js 16 + TypeScript)

```bash
cd app/web && npm install && npm run dev      # http://localhost:3000, API proxied from :8000
```

- **`/`:** the approved landing page, served byte for byte from `public/index.html` by a `beforeFiles` rewrite.
- **`/report`:** the lookup and report. `?r=<report id>` opens a report directly, so reports can be shared by link.
- **`/api/*`:** proxied to the FastAPI backend (`EKKO_API_URL`, default `http://localhost:8000`), so the browser only talks to its own origin, server-sent events included.
- **Styling:** plain CSS with the site's tokens (`app/globals.css`) and Instrument Serif and Inter via `next/font`. Gold marks only findings with `supported: true`.
- **Next 16 note:** read `AGENTS.md` and `node_modules/next/dist/docs/` before changing framework-level code. Some APIs differ from older Next versions.

CI runs eslint, `next build` and `tsc`.
