import io
import json
from collections import Counter
from datetime import date
from http.client import IncompleteRead
from pathlib import Path

import pytest

from alert_monitor import ingest

ROOT = Path(__file__).parents[1]
FIXTURE = json.loads((ROOT / "tests" / "fixtures" / "conesearch.json").read_text())
CONFIG = ingest.load_config()
FIELDS = CONFIG["fields"]
DAY = date(2026, 10, 18)


def key(field):
    return f"{field['ra']},{field['dec']}"


def replay(field, config):
    return FIXTURE[key(field)]


def stub_urlopen(monkeypatch, payload):
    calls = []

    def urlopen(req, timeout):
        calls.append((req, timeout))
        return io.BytesIO(json.dumps(payload).encode())

    monkeypatch.setattr(ingest, "urlopen", urlopen)
    return calls


def test_header_counts():
    snap = ingest.snapshot(DAY, CONFIG, fetch=replay)
    assert snap["header"] == {
        "date": "2026-10-18",
        "fields": [{"ra": f["ra"], "dec": f["dec"], "rows": len(FIXTURE[key(f)])} for f in FIELDS],
    }


def test_failed_field_recorded():
    bad = FIELDS[1]
    calls = []

    def fetch(field, config):
        calls.append(key(field))
        if field is bad:
            raise IncompleteRead(b"")
        return replay(field, config)

    expected = ingest.snapshot(DAY, CONFIG, fetch=replay)
    expected["header"]["fields"][1] = {
        "ra": bad["ra"],
        "dec": bad["dec"],
        "error": "IncompleteRead: IncompleteRead(0 bytes read)",
    }
    others = [f for f in FIELDS if f is not bad]
    expected["rows"] = ingest.snapshot(DAY, {**CONFIG, "fields": others}, fetch=replay)["rows"]
    assert ingest.snapshot(DAY, CONFIG, fetch=fetch) == expected
    assert calls.count(key(bad)) == 2


def test_retry_once():
    calls = []

    def fetch(field, config):
        calls.append(key(field))
        if calls.count(key(field)) == 1:
            raise TimeoutError("timed out")
        return replay(field, config)

    snap = ingest.snapshot(DAY, CONFIG, fetch=fetch)
    assert calls == [key(f) for f in FIELDS for _ in range(2)]
    assert snap == ingest.snapshot(DAY, CONFIG, fetch=replay)


def test_dedup_by_dia_object_id():
    seen = [r for f in FIELDS for r in FIXTURE[key(f)]]
    counts = Counter(r["r:diaObjectId"] for r in seen)
    (shared,) = [i for i, n in counts.items() if n > 1]
    first, second = [r for r in seen if r["r:diaObjectId"] == shared]
    assert first != second
    snap = ingest.snapshot(DAY, CONFIG, fetch=replay)
    assert snap["rows"] == [r for r in seen if r is not second]


def test_fetch_refuses_non_list(monkeypatch):
    stub_urlopen(monkeypatch, {"status": "error"})
    with pytest.raises(ValueError):
        ingest.fetch_field(FIELDS[0], CONFIG)
    snap = ingest.snapshot(DAY, CONFIG)
    assert [e["error"] for e in snap["header"]["fields"]] == ["ValueError: expected a JSON list, got dict"] * len(FIELDS)


def test_fetch_body_and_timeout(monkeypatch):
    calls = stub_urlopen(monkeypatch, FIXTURE[key(FIELDS[0])])
    assert ingest.fetch_field(FIELDS[0], CONFIG) == FIXTURE[key(FIELDS[0])]
    ((req, timeout),) = calls
    assert timeout == 90
    assert req.full_url == "https://api.lsst.fink-portal.org/api/v1/conesearch"
    assert req.get_method() == "POST"
    assert req.get_header("Content-type") == "application/json"
    assert json.loads(req.data) == {
        "ra": 150.66,
        "dec": 0.85,
        "radius": 3600,
        "n": 100,
        "kind": "across",
        "columns": ",".join(CONFIG["columns"]),
        "output-format": "json",
    }


def test_write_snapshot(tmp_path):
    snap = ingest.snapshot(DAY, CONFIG, fetch=replay)
    path = ingest.write_snapshot(snap, tmp_path / "snapshots")
    assert path == tmp_path / "snapshots" / "2026-10-18.json"
    assert json.loads(path.read_text()) == snap
    assert "data/snapshots/" not in (ROOT / ".gitignore").read_text().split()


def test_write_snapshot_refuses_all_errors(tmp_path):
    def fetch(field, config):
        raise TimeoutError("timed out")

    snap = ingest.snapshot(DAY, CONFIG, fetch=fetch)
    with pytest.raises(RuntimeError, match="TimeoutError: timed out"):
        ingest.write_snapshot(snap, tmp_path / "snapshots")
    assert not (tmp_path / "snapshots").exists()


def test_write_snapshot_one_field_rows(tmp_path):
    def fetch(field, config):
        if field is not FIELDS[0]:
            raise TimeoutError("timed out")
        return replay(field, config)

    snap = ingest.snapshot(DAY, CONFIG, fetch=fetch)
    path = ingest.write_snapshot(snap, tmp_path / "snapshots")
    assert json.loads(path.read_text()) == snap
    assert [e.get("error") for e in snap["header"]["fields"]] == [None] + ["TimeoutError: timed out"] * (len(FIELDS) - 1)


@pytest.mark.live
def test_live_snapshot():
    today = date.today()
    path = ingest.write_snapshot(ingest.snapshot(today, CONFIG))
    assert path == Path("data/snapshots") / f"{today.isoformat()}.json"
    header = json.loads(path.read_text())["header"]
    assert header["date"] == today.isoformat()
    assert any("rows" in e for e in header["fields"])
