"""Settings and Riot API routing.

Confirm endpoints, routing values and rate limits in the Riot Developer Portal before relying on
them; they change.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

RANKED_SOLO_QUEUE_ID = 420
RANKED_SOLO_QUEUE_NAME = "RANKED_SOLO_5x5"

TIERS = (
    "IRON",
    "BRONZE",
    "SILVER",
    "GOLD",
    "PLATINUM",
    "EMERALD",
    "DIAMOND",
    "MASTER",
    "GRANDMASTER",
    "CHALLENGER",
)
DIVISIONS = ("I", "II", "III", "IV")
APEX_TIERS = ("MASTER", "GRANDMASTER", "CHALLENGER")


@dataclass(frozen=True)
class Settings:
    riot_api_key: str
    platform: str = "na1"
    region: str = "americas"
    # (requests, window seconds) pairs, enforced per routing host. Matches the
    # X-App-Rate-Limit header format: "20:1,100:120".
    rate_limits: tuple[tuple[int, float], ...] = ((20, 1.0), (100, 120.0))
    data_dir: Path = Path("data")
    duckdb_path: Path = Path("data/ekko.duckdb")

    @property
    def platform_base_url(self) -> str:
        """Base URL for platform-routed APIs (league-v4, champion-mastery-v4)."""
        return f"https://{self.platform}.api.riotgames.com"

    @property
    def regional_base_url(self) -> str:
        """Base URL for regionally routed APIs (account-v1, match-v5)."""
        return f"https://{self.region}.api.riotgames.com"

    @property
    def raw_dir(self) -> Path:
        """Immutable Parquet landing zone."""
        return self.data_dir / "raw"


def parse_rate_limits(spec: str) -> tuple[tuple[int, float], ...]:
    """Parse "20:1,100:120" into ((20, 1.0), (100, 120.0))."""
    limits = []
    for part in spec.split(","):
        requests, window = part.strip().split(":")
        limits.append((int(requests), float(window)))
    return tuple(limits)


def load_settings(env_file: str | os.PathLike[str] | None = ".env") -> Settings:
    if env_file is not None:
        load_dotenv(env_file)

    api_key = os.environ.get("RIOT_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("RIOT_API_KEY is not set; copy .env.example to .env and fill it in")

    data_dir = Path(os.environ.get("EKKO_DATA_DIR", "data"))
    return Settings(
        riot_api_key=api_key,
        platform=os.environ.get("RIOT_PLATFORM", "na1"),
        region=os.environ.get("RIOT_REGION", "americas"),
        rate_limits=parse_rate_limits(os.environ.get("RIOT_RATE_LIMITS", "20:1,100:120")),
        data_dir=data_dir,
        duckdb_path=Path(os.environ.get("EKKO_DUCKDB_PATH", str(data_dir / "ekko.duckdb"))),
    )
