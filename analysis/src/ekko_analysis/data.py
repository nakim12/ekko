"""Load dbt marts from the local DuckDB warehouse (read-only)."""

from __future__ import annotations

import os
from pathlib import Path

import duckdb
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[3]

PLAYER_GAMES_SQL = """
select f.*, m.game_start_at, m.duration_seconds, d.iso_day_of_week
from main.fct_player_games as f
join main.dim_match as m using (match_key)
join main.dim_date as d on d.date_key = f.date_key
"""


def warehouse_path() -> Path:
    """EKKO_DUCKDB_PATH (relative to the repo root), default data/ekko.duckdb."""
    p = Path(os.environ.get("EKKO_DUCKDB_PATH") or "data/ekko.duckdb")
    return p if p.is_absolute() else REPO_ROOT / p


def load_player_games(path: Path | None = None) -> pd.DataFrame:
    """fct_player_games joined with match start time and day of week."""
    with duckdb.connect(str(path or warehouse_path()), read_only=True) as con:
        return con.sql(PLAYER_GAMES_SQL).df()


TEAM_STRENGTH_SQL = """
select *
from main.fct_match_team_strength
where perspective = ?
"""


def load_team_strength(perspective: str = "focal", path: Path | None = None) -> pd.DataFrame:
    """fct_match_team_strength for one perspective: "focal" (H2, H2a) or "placebo".

    The H2 functions in q2.py take this frame as is (player_key is the perspective player).
    """
    if perspective not in ("focal", "placebo"):
        raise ValueError("perspective must be 'focal' or 'placebo'")
    with duckdb.connect(str(path or warehouse_path()), read_only=True) as con:
        return con.execute(TEAM_STRENGTH_SQL, [perspective]).df()
