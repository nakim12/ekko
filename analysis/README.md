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
- `results/`: tables and figures regenerated from one command (once the Phase 1 crawl is complete).

## Validation before real outcomes

Every model has to recover a planted effect and hold its false-positive rate before it touches real outcomes:

```bash
pytest tests/analysis                    # simulated data with known effects (~15 s)
python -m ekko_analysis.validate         # real Phase 0 structure, shuffled outcomes, planted effects
```

Validation found two problems in the registered models, both logged as deviations in `PREREGISTRATION.md`. The registered versions stay available (`lag="fill"`, `null="drift"`) so they can be reported alongside:

1. **H1, missing lagged outcome:** filling it with 0 biases the tilt estimate negative under realistic persistence. Those rows are dropped instead.
2. **H3 null:** the drifting-skill null is streakier than independent play, so it would reject a true H3. A within-block permutation null replaces it.
