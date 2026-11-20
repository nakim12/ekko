"""The results runner end to end on simulated data (never on real outcomes in tests)."""

import json

import duckdb
import pytest
from ekko_analysis import run
from ekko_analysis.simulate import simulate_player_games, simulate_team_strength


@pytest.fixture(scope="module")
def results():
    pg = simulate_player_games(n_players=120, games_per_player=60, beta=-0.15, seed=21)
    pg["gold_diff_14"] = pg["gold_diff_14_z"] * 1400
    pg["cs_diff_14"] = pg["cs_diff_14_z"] * 15
    inputs = run.Inputs(
        player_games=pg,
        team_focal=simulate_team_strength(n_matches=10_000, n_players=120, delta=0.0, seed=22),
        team_placebo=simulate_team_strength(n_matches=3000, n_players=120, seed=23),
        session_variants={90: pg},
    )
    return run.run_all(inputs, n_sims=300, n_boot=500)


def test_primary_family_is_holm_adjusted(results):
    p = results["primary"]
    assert set(p) == {"H1", "H2", "H3"}
    assert p["H1"]["holm_p"] >= p["H1"]["p_value"]
    assert p["H1"]["reject"]  # planted beta = -0.15
    assert p["H2"]["equivalence_supported"]  # planted delta = 0
    d = results["descriptive"]
    assert d["H1 in gold at 14"] == pytest.approx(p["H1"]["estimate"] * d["gold_diff_14_sd"])
    assert 1000 < d["gold_diff_14_sd"] < 2000


def test_every_registered_piece_is_reported(results):
    assert len(results["secondary"]["bh"]) == 4 + 5 + 1
    assert {"H1 (lag filled, Deviation 1)", "H3 (drift null, Deviation 2)"} == set(
        results["registered_versions"]
    )
    sens = results["sensitivity"]
    for key in [
        "H1 without lagged outcome",
        "H1 games 15+ minutes",
        "H1 z within tier x role",
        "H1 excluding likely duos",
        "H2 without the 20 LP adjustment",
        "H2 with match result as covariate",
        "H2 placebo (random non-focal player)",
        "H3 constant win rate (whole-sequence shuffle)",
        "H3 50-game blocks",
        "H1 session gap 90 min",
    ]:
        assert key in sens
    assert results["selection"]["bound"]["stop_rate_after_loss"] > 0


def test_report_files(results, tmp_path):
    run.write_report(dict(results), tmp_path)
    assert {p.name for p in tmp_path.iterdir()} == {
        "results.json",
        "results.md",
        "h3_per_player.csv",
        "h1_by_group.png",
    }
    assert json.loads((tmp_path / "results.json").read_text())["primary"]["H1"]["n_obs"] > 0
    assert "## Primary hypotheses" in (tmp_path / "results.md").read_text()


def test_refuses_anything_but_a_phase1_build(tmp_path, monkeypatch):
    db = tmp_path / "w.duckdb"
    with duckdb.connect(str(db)) as con:
        con.execute("create table fct_player_games as select 'p1' as player_key")
    monkeypatch.setenv("EKKO_DUCKDB_PATH", str(db))
    with pytest.raises(SystemExit, match="No Q2 mart"):
        run.main([])
    with duckdb.connect(str(db)) as con:
        con.execute("create table fct_match_team_strength as select 1 as x")
    with pytest.raises(SystemExit, match="Refusing"):
        run.main([])
    with pytest.raises(SystemExit, match="outside analysis/results"):
        run.main(["--allow-small"])
