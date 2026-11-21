import json

from ekko_api.lookup import load_priors
from ekko_api.main import create_app
from ekko_api.store import Store
from fastapi.testclient import TestClient

from .conftest import FakeRiot


def _client(riot, tmp_path):
    store = Store(tmp_path / "app.sqlite")
    return TestClient(create_app(store, riot, load_priors(), workers=1, poll_seconds=0.01)), store


def _events(client, job_id):
    with client.stream("GET", f"/api/lookups/{job_id}/events") as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        return [json.loads(line[6:]) for line in r.iter_lines() if line.startswith("data: ")]


def test_lookup_streams_progress_then_serves_the_report(tmp_path):
    riot = FakeRiot(n_games=40, delay=0.001)
    client, _ = _client(riot, tmp_path)
    with client:
        assert client.post("/api/lookups", json={"riot_id": "nope"}).status_code == 422
        job = client.post("/api/lookups", json={"riot_id": "Tester#NA1"}).json()
        events = _events(client, job["id"])
        stages = [e["stage"] for e in events]
        assert stages[-1] == "done" and "games" in stages and "matchmaking" in stages
        assert any(e["stage"] == "games" and 0 < e["done"] < e["total"] for e in events)

        report = client.get(f"/api/reports/{events[-1]['report_id']}").json()
        assert report["riot_id"] == "Tester#NA1"
        assert report["games_analyzed"] == 39  # one remake dropped
        assert report["priors_are_placeholders"] is True
        assert {"tilt", "cooldown", "stop_rule", "matchmaking", "history"} <= set(report)
        assert report["matchmaking"]["games"] == 10
        assert "puuid" not in json.dumps(report).lower()

        # A second lookup within the cache window reuses the report without calling Riot.
        calls = riot.calls
        again = client.post("/api/lookups", json={"riot_id": "tester#na1"}).json()
        assert again["report_id"] == events[-1]["report_id"] and riot.calls == calls


def test_unknown_riot_id_fails_cleanly(tmp_path):
    client, _ = _client(FakeRiot(n_games=5), tmp_path)
    with client:
        job = client.post("/api/lookups", json={"riot_id": "Nobody#NA1"}).json()
        events = _events(client, job["id"])
        assert events[-1]["status"] == "failed"
        assert "No Riot account" in events[-1]["message"]
        assert client.get("/api/reports/doesnotexist").status_code == 404


def test_report_includes_the_checked_coach_note(tmp_path):
    from .test_coach import GOOD, FakeClient

    store = Store(tmp_path / "app.sqlite")
    app = create_app(
        store,
        FakeRiot(n_games=30),
        load_priors(),
        workers=1,
        poll_seconds=0.01,
        coach_client=FakeClient([GOOD, GOOD]),
    )
    with TestClient(app) as client:
        job = client.post("/api/lookups", json={"riot_id": "Tester#NA1"}).json()
        events = _events(client, job["id"])
        report = client.get(f"/api/reports/{events[-1]['report_id']}").json()
        note = report["coach"]
        assert note["source"] in (
            "model",
            "template",
        )  # model if GOOD's numbers fit this report's facts
        assert note["summary"] and 2 <= len(note["findings"]) <= 3
