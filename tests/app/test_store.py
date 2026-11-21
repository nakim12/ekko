from ekko_api.store import REPORT_TTL_SECONDS, Store


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def _store():
    clock = Clock()
    return Store(":memory:", clock=clock), clock


def test_duplicate_lookups_collapse_into_one_job():
    store, _ = _store()
    a = store.request_lookup("Tester#NA1")
    b = store.request_lookup("tester#na1 ")
    assert a["id"] == b["id"] and a["status"] == "queued"
    assert store.request_lookup("Someone#NA1")["id"] != a["id"]


def test_fresh_reports_are_reused_and_stale_ones_refreshed():
    store, clock = _store()
    job = store.request_lookup("Tester#NA1")
    claimed, token = store.claim()
    report_id = store.save_report("Tester#NA1", {"x": 1})
    assert store.finish(job["id"], token, "done", report_id=report_id)
    assert store.request_lookup("Tester#NA1")["id"] == job["id"]
    clock.t += REPORT_TTL_SECONDS + 1
    assert store.request_lookup("Tester#NA1")["id"] != job["id"]


def test_expired_lease_is_reclaimed_and_the_old_worker_is_locked_out():
    store, clock = _store()
    job = store.request_lookup("Tester#NA1")
    _, old = store.claim(lease=10)
    assert store.claim(lease=10) is None  # leased
    clock.t += 11
    reclaimed, new = store.claim(lease=10)
    assert reclaimed["id"] == job["id"] and new != old
    assert not store.update(job["id"], old, stage="games")  # stale worker can't write
    assert not store.finish(job["id"], old, "done")
    assert store.update(job["id"], new, stage="games", done=3, total=10)
    assert store.get_job(job["id"])["done"] == 3


def test_documents_are_cached():
    store, _ = _store()
    store.put_document("matches", "NA1_1", {"a": 1})
    store.put_document("matches", "NA1_1", {"a": 2})  # first write wins (documents are immutable)
    assert store.get_document("matches", "NA1_1") == {"a": 1}
    assert store.get_document("timelines", "NA1_1") is None
