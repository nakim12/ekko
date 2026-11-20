import pytest

from crawler.config import load_settings


def test_missing_api_key_raises(monkeypatch):
    monkeypatch.delenv("RIOT_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="RIOT_API_KEY"):
        load_settings(env_file=None)


def test_routing_urls(monkeypatch):
    monkeypatch.setenv("RIOT_API_KEY", "RGAPI-test")
    monkeypatch.setenv("RIOT_PLATFORM", "na1")
    monkeypatch.setenv("RIOT_REGION", "americas")
    settings = load_settings(env_file=None)
    assert settings.platform_base_url == "https://na1.api.riotgames.com"
    assert settings.regional_base_url == "https://americas.api.riotgames.com"
    assert settings.raw_dir.as_posix() == "data/raw"


def test_key_optional_for_jobs_that_do_not_call_the_api(monkeypatch):
    monkeypatch.delenv("RIOT_API_KEY", raising=False)
    assert load_settings(env_file=None, require_key=False).riot_api_key == ""
