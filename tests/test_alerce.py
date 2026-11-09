import json
from pathlib import Path

import pytest

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
        {"survey": "lsst", "format": "json", "ra": 150.66, "dec": 0.85, "radius": 3600, "page_size": 100, "page": 1}
    ]


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


@pytest.mark.live
def test_live_field_validates(valid):
    calls = []

    def fetch(field, config):
        calls.append(field)
        return alerce.fetch_field(field, config)

    got = list(alerce.records(FIELD0, AT, fetch=fetch))
    assert calls == [CONFIG["fields"][0]]
    assert got
    for r in got:
        valid(r)
