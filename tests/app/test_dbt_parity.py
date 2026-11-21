"""The app's features match the dbt models game by game.

Runs against a built warehouse (CI's dbt job sets EKKO_DBT_PARITY_DB after building the synthetic
warehouse); skipped otherwise.
"""

import hashlib
import json
import os

import duckdb
import pytest
from ekko_api import features

DB = os.environ.get("EKKO_DBT_PARITY_DB")
pytestmark = pytest.mark.skipif(not DB, reason="set EKKO_DBT_PARITY_DB to a built dbt warehouse")


def test_app_features_match_fct_player_games():
    with duckdb.connect(DB, read_only=True) as con:
        players = [r[0] for r in con.execute("select puuid from raw.players").fetchall()]
        crawled = con.execute("select puuid, match_id from raw.player_match_ids").fetchall()
        docs = {
            kind: dict(con.execute(f"select match_id, payload::varchar from raw.{kind}").fetchall())
            for kind in ("matches", "timelines")
        }
        cols = (
            "player_key, match_key, game_number_in_session, lost_prev, session_losses_before, "
            "gold_diff_14, afk"
        )
        dbt = {
            (r[0], r[1]): r[2:]
            for r in con.execute(
                f"select {cols} from main.fct_player_games where not remake"
            ).fetchall()
        }

    app = {}
    for puuid in players:
        games = []
        for p, match_id in crawled:
            if p != puuid:
                continue
            tl = docs["timelines"].get(match_id)
            g = features.game_from_payloads(
                puuid, json.loads(docs["matches"][match_id]), tl and json.loads(tl)
            )
            if g:
                games.append(g)
        key = hashlib.md5(puuid.encode()).hexdigest()
        for g in features.sequence(games):
            app[(key, g.match_id)] = (
                g.game_number_in_session,
                g.lost_prev,
                g.session_losses_before,
                g.gold_diff_14,
                g.afk,
            )

    assert app.keys() == dbt.keys()
    mismatches = {k: (app[k], dbt[k]) for k in app if app[k] != dbt[k]}
    assert not mismatches, list(mismatches.items())[:5]
