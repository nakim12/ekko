# analysis

- `PREREGISTRATION.md`: hypotheses, definitions, models and exclusions, committed before any outcome analysis. Changes after registration are logged in its Deviations section.
- `notebooks/`: exploration only. Nothing in a notebook is a result.
- `src/ekko_analysis/`: the registered models.
  - `q1.py`: H1 and H1a–c (within-player fixed effects, player-clustered SEs).
  - `selection.py`: continuation model, inverse probability weights, pattern-mixture bound (5.1).
  - `q2.py`: H2 equivalence test (TOST, ±25 LP), H2a. The placebo reruns `fit_h2` with a random non-focal player as "focal".
  - `q3.py`: per-player runs test, bootstrap over players.
  - `inference.py`: contrasts, joint Wald tests, Holm and BH corrections.
  - `simulate.py`: simulated data with planted effects.
  - `validate.py`: real data structure with shuffled outcomes.
  - `data.py`: loads the dbt marts.
- `results/`: written by `python -m ekko_analysis.run` (`results.md`, `results.json`, `h3_per_player.csv`, `h1_by_group.png`).

## Results, in one command (Phase 1 only)

```bash
python -m crawler.load
(cd dbt && dbt build --profiles-dir . --vars '{phase: 1}')
# session-threshold sensitivity builds, each into its own warehouse:
for gap in 30 90 120; do (cd dbt && EKKO_DUCKDB_PATH=$PWD/../data/ekko_gap$gap.duckdb \
  dbt build --profiles-dir . --vars "{phase: 1, session_gap_minutes: $gap}"); done
python -m ekko_analysis.run --session-warehouse 30=data/ekko_gap30.duckdb \
  --session-warehouse 90=data/ekko_gap90.duckdb --session-warehouse 120=data/ekko_gap120.duckdb
```

The runner refuses anything but a full Phase 1 build: it needs the Q2 mart and at least 1,000 players, so it can't touch Phase 0. It applies Holm to H1–H3 and BH to the secondary family. It reports the registered versions of the two deviated analyses alongside them, plus every section 8 sensitivity run. `tests/analysis/test_run.py` runs it end to end on simulated data.

The session-threshold warehouses need the raw views too. Run `python -m crawler.load` against each path first, or copy the main warehouse file before building.

## Validation before real outcomes

Every model has to recover a planted effect and hold its false-positive rate before it touches real outcomes:

```bash
pytest tests/analysis                    # simulated data with known effects (~15 s)
python -m ekko_analysis.validate         # real Phase 0 structure, shuffled outcomes, planted effects
```

Validation found two problems in the registered models, both logged as deviations in `PREREGISTRATION.md`. The registered versions stay available (`lag="fill"`, `null="drift"`) so they can be reported alongside:

1. **H1, missing lagged outcome:** filling it with 0 biases the tilt estimate negative under realistic persistence. Those rows are dropped instead.
2. **H3 null:** the drifting-skill null is streakier than independent play, so it would reject a true H3. A within-block permutation null replaces it.
