import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from astropy.time import Time

from alert_monitor import ingest, labels
from alert_monitor.sources import alerce

ROOT = Path(__file__).parents[1]
FIXTURE = json.loads((ROOT / "tests" / "fixtures" / "alerce_field.json").read_text())
CONFIG = ingest.load_config()
FIELD0 = {**CONFIG, "fields": CONFIG["fields"][:1]}
AT = "2026-11-07T06:00:00Z"


def test_fixture_replays_into_valid_records(valid):
    got = list(alerce.records(FIELD0, AT, fetch=lambda field, config: FIXTURE))
    assert [r["id"] for r in got] == [str(row["oid"]) for row in FIXTURE]
    for r in got:
        valid(r)


def test_every_fixture_class_is_mapped():
    assert {row["class_name"] for row in FIXTURE} <= set(labels.TABLE["alerce"])


def test_unmapped_class_is_unknown():
    row = {**FIXTURE[0], "class_name": "Periodic-Other"}
    (got,) = alerce.records(FIELD0, AT, fetch=lambda field, config: [row])
    assert got["labels"][0]["label"] == "unknown"


def test_fetch_refuses_non_list(monkeypatch):
    calls = []

    class Client:
        def query_objects(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr(alerce, "Alerce", Client)
    with pytest.raises(ValueError, match="expected a JSON list, got NoneType"):
        alerce.fetch_field(CONFIG["fields"][0], CONFIG)
    assert calls == [
        {
            "survey": "lsst",
            "format": "json",
            "ra": 150.66,
            "dec": 0.85,
            "radius": 3600,
            "page_size": 100,
            "page": 1,
            "order_by": "lastmjd",
            "order_mode": "DESC",
        }
    ]


def test_fetch_newest_first_stops_at_watermark(monkeypatch):
    calls = []

    class Client:
        def query_objects(self, **kwargs):
            calls.append(kwargs)
            n = kwargs["page_size"]
            return [{"lastmjd": 61350.0 + (3 - kwargs["page"]) * 10 + (n - 1 - i) / 1000} for i in range(n)]

    monkeypatch.setattr(alerce, "Alerce", Client)
    got = alerce.fetch_field(CONFIG["fields"][0], {**CONFIG, "lastmjd": [61350.0, 61400.0]})
    assert [c["page"] for c in calls] == [1, 2, 3]
    assert {c["order_mode"] for c in calls} == {"DESC"}
    assert len(got) == 3 * CONFIG["n"]
    assert alerce.paging([got], {**FIELD0, "since": {"150.66,0.85": 61350.0}}, False)["pages"] == {"150.66,0.85": 3}


def test_records_pass_lastmjd_range_from_since(monkeypatch):
    calls = []

    class Client:
        def query_objects(self, **kwargs):
            calls.append(kwargs)
            return []

    monkeypatch.setattr(alerce, "Alerce", Client)
    assert list(alerce.records({**CONFIG, "since": {"150.66,0.85": 61350.5}}, AT)) == []
    assert [c.get("lastmjd") for c in calls] == [[61350.5, pytest.approx(61351.25 + 37 / 86400)], None, None, None]


@pytest.mark.parametrize("short", [0, 1])
def test_fetch_stops_on_short_page(monkeypatch, short):
    pages = []

    class Client:
        def query_objects(self, **kwargs):
            pages.append(kwargs["page"])
            return [{"page": kwargs["page"]}] * (kwargs["page_size"] if kwargs["page"] < 3 else short)

    monkeypatch.setattr(alerce, "Alerce", Client)
    got = alerce.fetch_field(CONFIG["fields"][0], CONFIG)
    assert pages == [1, 2, 3]
    assert got == [{"page": 1}] * CONFIG["n"] + [{"page": 2}] * CONFIG["n"] + [{"page": 3}] * short


def test_fetch_stops_at_page_cap(monkeypatch):
    pages = []

    class Client:
        def query_objects(self, **kwargs):
            pages.append(kwargs["page"])
            return [{}] * kwargs["page_size"]

    monkeypatch.setattr(alerce, "Alerce", Client)
    got = alerce.fetch_field(CONFIG["fields"][0], CONFIG)
    assert pages == list(range(1, 51))
    assert len(got) == 50 * CONFIG["n"]


def test_backfill_pages_past_cap_until_short_page(monkeypatch):
    pages = []

    class Client:
        def query_objects(self, **kwargs):
            pages.append(kwargs["page"])
            return [{"lastmjd": 61000.0}] * (kwargs["page_size"] if kwargs["page"] < 60 else 0)

    monkeypatch.setattr(alerce, "Alerce", Client)
    config = {**FIELD0, "since": None, "backfill": True}
    got = alerce.fetch_field(CONFIG["fields"][0], config)
    assert pages == list(range(1, 61))
    assert len(got) == 59 * CONFIG["n"]
    assert alerce.paging([got], config, False) == {
        "pages": {"150.66,0.85": 60},
        "truncated": False,
        "lastmjd": {"150.66,0.85": 61000.0},
    }


def test_backfill_reads_gap_oldest_first(monkeypatch):
    calls = []

    class Client:
        def query_objects(self, **kwargs):
            calls.append(kwargs)
            return [{**FIXTURE[0], "lastmjd": 61000.5}] * (kwargs["page_size"] if kwargs["page"] < 60 else 0)

    monkeypatch.setattr(alerce, "Alerce", Client)
    config = {**FIELD0, "since": None, "backfill": True, "gap": {"150.66,0.85": [61000.0, 61001.0]}}
    assert len(list(alerce.records(config, AT))) == 59 * CONFIG["n"]
    assert [c["page"] for c in calls] == list(range(1, 61))
    assert all(c["lastmjd"] == [61000.0, 61001.0] and c["order_mode"] == "ASC" for c in calls)


def test_paging_newest_lastmjd_per_field():
    config = {**CONFIG, "fields": CONFIG["fields"][:3], "n": 1, "since": {"150.66,0.85": 61000.0, "61.96,-48.71": 61003.0}}
    capped = [{"lastmjd": 61000.0 + i / 100} for i in range(50)]
    got = alerce.paging([capped, [{"lastmjd": 61002.0}], []], config, False)
    assert got["pages"] == {"150.66,0.85": 50, "61.96,-48.71": 1, "9.45,-44.0": 1}
    assert got["truncated"] is True
    assert got["lastmjd"] == {"150.66,0.85": 61000.49, "61.96,-48.71": 61003.0, "9.45,-44.0": None}
    assert "gap" not in got


def test_paging_cap_records_gap_and_keeps_watermark():
    config = {**CONFIG, "fields": CONFIG["fields"][:2], "n": 1, "since": {"150.66,0.85": 60999.5}}
    capped = [{"lastmjd": 61000.0 + i / 100} for i in range(50)]
    got = alerce.paging([capped, capped], config, False)
    assert got["truncated"] is True
    assert got["gap"] == {"150.66,0.85": [60999.5, 61000.0]}
    assert got["lastmjd"] == {"150.66,0.85": 60999.5, "61.96,-48.71": 61000.49}


def test_paging_failed_keeps_since():
    config = {**CONFIG, "since": {"150.66,0.85": 61000.0}}
    assert alerce.paging([[{"lastmjd": 61002.0}]], config, True)["lastmjd"] == {
        "150.66,0.85": 61000.0,
        "61.96,-48.71": None,
        "9.45,-44.0": None,
        "53.1,-28.1": None,
    }


@pytest.mark.live
def test_live_field_validates(valid):
    at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    since = Time(at[:19], format="isot", scale="utc").tai.mjd - 3  # pyright: ignore[reportAttributeAccessIssue]
    config = {**CONFIG, "fields": CONFIG["fields"][1:2], "since": {"61.96,-48.71": since}}
    calls, results = [], []

    def fetch(field, config):
        calls.append(field)
        results.append(alerce.fetch_field(field, config))
        return results[-1]

    got = list(alerce.records(config, at, fetch=fetch))
    assert got
    assert calls == [CONFIG["fields"][1]]
    for r in got:
        valid(r)
    paged = alerce.paging(results, config, False)
    print(paged["pages"])
    assert paged["truncated"] is False
    assert "61.96,-48.71" in paged["pages"]
