# dbt

dbt-duckdb project: `staging` (rename and type, no logic) → `intermediate` (definitions from `analysis/PREREGISTRATION.md`) → `marts` (star schema).

```bash
cd dbt
dbt build --profiles-dir .                # local DuckDB (EKKO_DUCKDB_PATH, repo-relative; default data/ekko.duckdb)
dbt build --profiles-dir . --target prod  # MotherDuck (needs MOTHERDUCK_TOKEN)
dbt build --profiles-dir . --vars '{session_gap_minutes: 90}'   # registered sensitivity run
```

## Models

| Layer | Model | Grain / purpose |
|---|---|---|
| staging | `stg_matches`, `stg_participants`, `stg_players` | match; player × match; focal player |
| staging | `stg_timeline_frames`, `stg_champion_kills` (Python) | participant × minute; kill event. Parsed in hash buckets: timelines are ~0.8 MB of JSON each and whole-table parsing runs out of memory |
| intermediate | `int_matches` | remake flag, minute-14 availability, US Central hour and date |
| intermediate | `int_participant_minute_mark`, `int_lane_opponents` | gold/XP/CS at 14, deaths before 14; unique same-position opponent |
| intermediate | `int_player_games` | focal player-games with lane diffs and the AFK flag |
| intermediate | `int_sessions` | sessions, breaks, previous result, loss/win runs (across and within sessions) |
| intermediate | `int_performance_scores` | z-scores within sampled tier × role × patch, `perf_index` |
| marts | `fct_player_games` | focal player × match; `q1_eligible` is the H1 sample |
| marts | `dim_player`, `dim_match`, `dim_champion`, `dim_role`, `dim_date` | dimensions; `player_key` is an MD5 of the PUUID |

Definitions live in `dbt_project.yml` vars and follow the pre-registration; change them only through a logged deviation.

Not built yet (need Phase 1 data): `stg_rank_snapshots`, `dim_rank_snapshot`, `fct_match_team_strength` (Q2).

## Tests

Keys (`unique`, `not_null`, `relationships`), accepted values (role, queue, tier, streak state, break bucket), and singular tests in `tests/`: 10 participants and 5 per team, exactly one winning team, `gold_diff_14` missing only when expected, sessions respect the gap threshold, and the H1 sample is well formed.
