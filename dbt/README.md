# dbt

dbt-duckdb project: `staging` (rename and type, no logic) → `intermediate` (sessions, lane opponents, streaks, performance scores) → `marts` (`fct_player_games`, `fct_match_team_strength`, dimensions).

```bash
cd dbt
dbt build --profiles-dir .              # local DuckDB at ../data/ekko.duckdb
dbt build --profiles-dir . --target prod  # MotherDuck (needs MOTHERDUCK_TOKEN)
```

Minimum tests are listed in `docs/PROJECT_PLAN.md` §6.3.
