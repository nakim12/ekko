# dbt

dbt-duckdb project: `staging` (rename and type, no logic) → `intermediate` (definitions from `analysis/PREREGISTRATION.md`) → `marts` (star schema).

```bash
cd dbt
dbt build --profiles-dir .                # local DuckDB (EKKO_DUCKDB_PATH, repo-relative; default data/ekko.duckdb)
dbt build --profiles-dir . --target prod  # MotherDuck (needs MOTHERDUCK_TOKEN)
dbt build --profiles-dir . --vars '{session_gap_minutes: 90}'   # registered sensitivity run
dbt build --profiles-dir . --vars '{phase: 1}'                  # Phase 1 sample, Q2 models enabled
```

`phase: 0` (default) builds on the Phase 0 tables; `phase: 1` switches the players and match-ID sources to the Phase 1 crawl and enables the Q2 models, whose sources only exist in Phase 1.

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

Q2 models (`models/*/q2/`, Phase 1 only):

| Layer | Model | Grain / purpose |
|---|---|---|
| staging | `stg_q2_matches`, `stg_q2_ranks`, `stg_q2_history_games`, `stg_rank_snapshots` | registry, rank lookups (with `ladder_position`), previous-game lists, daily snapshots |
| intermediate | `int_q2_participants` | the 10 participants of each qualified match, rank at match time (±20 LP for the matched game) |
| intermediate | `int_q2_streaks` | focal and placebo streak state from their previous 5 games |
| intermediate | `int_q2_autofill` | likely-autofilled non-focal participants (autofill sample) |
| marts | `fct_match_team_strength` | match × perspective (focal, placebo): strength gap, streak state, autofill gap |
| marts | `dim_rank_snapshot` | player × day |

`ladder_position` (macro): Iron IV 0 LP = 0, +100 per division, +400 per tier; Master and above = 2,800 + LP.

## Tests

Keys (`unique`, `not_null`, `relationships`), accepted values (role, queue, tier, streak state, break bucket), and singular tests in `tests/`: 10 participants and 5 per team, exactly one winning team, `gold_diff_14` missing only when expected, sessions respect the gap threshold, and the H1 sample is well formed. Q2: 10 participants and rank lookups per match, lookups within 24 hours, and strength gap missing exactly when too few players are ranked. `dbt source freshness --vars '{phase: 1}'` fails if the daily rank snapshots stop.
