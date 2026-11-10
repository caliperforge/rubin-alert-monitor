import gzip
import json
from collections import Counter
from datetime import date
from pathlib import Path

import pytest
from jsonschema import ValidationError

from alert_monitor import ingest, ingest_all, labels, merge
from alert_monitor.sources import alerce, fink

ROOT = Path(__file__).parents[1]
CONESEARCH = json.loads((ROOT / "tests" / "fixtures" / "conesearch.json").read_text())
ALERCE = json.loads((ROOT / "tests" / "fixtures" / "alerce_field.json").read_text())
CONFIG = ingest.load_config()
FIELDS = CONFIG["fields"]
AT = "2026-11-07T06:00:00Z"
FINK = {
    f"{f['ra']},{f['dec']}": [{**r, "r:ra": f["ra"], "r:dec": f["dec"]} for r in CONESEARCH[f"{f['ra']},{f['dec']}"]]
    for f in FIELDS
}


def fink_replay(field, config):
    return FINK[f"{field['ra']},{field['dec']}"]


def alerce_replay(field, config):
    return ALERCE if field == FIELDS[0] else []


def timeout(field, config):
    raise TimeoutError("timed out")


def sources(fink_fetch=fink_replay, alerce_fetch=alerce_replay):
    return {"fink": (fink.records, fink_fetch), "alerce": (alerce.records, alerce_fetch)}


def header(out):
    return json.loads((out / "2026-11-07.header.json").read_text())


def test_fink_records_validate(valid):
    got = list(fink.records(CONFIG, AT, fetch=fink_replay))
    ids = dict.fromkeys(str(r["r:diaObjectId"]) for f in FIELDS for r in fink_replay(f, CONFIG))
    assert [r["id"] for r in got] == list(ids)
    for r in got:
        valid(r)


def test_failing_broker_recorded_other_writes(tmp_path):
    out = tmp_path / "objects"
    path = ingest_all.run(CONFIG, AT, out, sources(alerce_fetch=timeout))
    lines = gzip.decompress(path.read_bytes()).decode().splitlines()
    assert [json.loads(line) for line in lines] == merge.merge(list(fink.records(CONFIG, AT, fetch=fink_replay)))
    assert header(out)["brokers"]["alerce"] == {
        "rows": 0,
        "errors": ["TimeoutError: timed out"],
        "calls": 1,
        "unmapped": {},
        "pages": {},
        "truncated": False,
        "lastmjd": {f"{f['ra']},{f['dec']}": None for f in FIELDS},
    }


def test_all_brokers_failing_raises_and_writes_nothing(tmp_path):
    with pytest.raises(RuntimeError, match=r"'fink': \['TimeoutError: timed out'.*'alerce': \['TimeoutError: timed out'\]"):
        ingest_all.run(CONFIG, AT, tmp_path / "objects", sources(timeout, timeout))
    assert not (tmp_path / "objects").exists()


def test_header_per_broker(tmp_path):
    calls = []

    def flaky(field, config):
        calls.append(field)
        if len(calls) == 1:
            raise TimeoutError("timed out")
        return fink_replay(field, config)

    out = tmp_path / "objects"
    ingest_all.run(CONFIG, AT, out, sources(fink_fetch=flaky))
    fink_rows = ingest.snapshot(date(2026, 11, 7), CONFIG, fink_replay)["rows"]
    fink_raw = Counter(str(r["f:main_label_classifier"]) for r in fink_rows)
    alerce_raw = Counter(r["class_name"] for r in ALERCE)
    assert header(out) == {
        "date": "2026-11-07",
        "brokers": {
            "fink": {
                "rows": len(fink_rows),
                "errors": ["TimeoutError: timed out"],
                "calls": len(FIELDS) + 1,
                "unmapped": {k: n for k, n in fink_raw.items() if k not in labels.TABLE["fink"]},
            },
            "alerce": {
                "rows": len(ALERCE),
                "errors": [],
                "calls": len(FIELDS),
                "unmapped": {k: n for k, n in alerce_raw.items() if k not in labels.TABLE["alerce"]},
                "pages": {f"{f['ra']},{f['dec']}": 1 for f in FIELDS},
                "truncated": False,
                "lastmjd": {
                    f"{f['ra']},{f['dec']}": max(r["lastmjd"] for r in ALERCE) if f == FIELDS[0] else None for f in FIELDS
                },
            },
        },
    }


def test_alerce_cap_marks_truncated(tmp_path):
    def full(field, config):
        return [{**ALERCE[0], "oid": f"cap{i}"} for i in range(50)] if field == FIELDS[0] else []

    out = tmp_path / "objects"
    ingest_all.run({**CONFIG, "n": 1}, AT, out, sources(alerce_fetch=full))
    entry = header(out)["brokers"]["alerce"]
    assert entry["pages"]["150.66,0.85"] == 50
    assert entry["truncated"] is True


def previous_headers(out):
    out.mkdir()
    for day, mjd in [("2026-11-05", 61349.0), ("2026-11-06", 61350.0), ("2026-11-07", 61351.0)]:
        brokers = {"alerce": {"lastmjd": {"150.66,0.85": mjd, "61.96,-48.71": mjd + 10}}}
        (out / f"{day}.header.json").write_text(json.dumps({"date": day, "brokers": brokers}))


def test_since_read_from_previous_day_header(tmp_path):
    configs = []

    def fetch(field, config):
        configs.append(config)
        return alerce_replay(field, config)

    out = tmp_path / "objects"
    previous_headers(out)
    ingest_all.run(CONFIG, AT, out, sources(alerce_fetch=fetch))
    assert [c.get("lastmjd", [None])[0] for c in configs] == [61350.0, 61360.0, None, None]
    assert header(out)["brokers"]["alerce"]["lastmjd"] == {
        "150.66,0.85": max(61350.0, *(r["lastmjd"] for r in ALERCE)),
        "61.96,-48.71": 61360.0,
        "9.45,-44.0": None,
        "53.1,-28.1": None,
    }


def test_backfill_ignores_previous_header(tmp_path):
    configs = []

    def fetch(field, config):
        configs.append(config)
        return alerce_replay(field, config)

    out = tmp_path / "objects"
    previous_headers(out)
    ingest_all.run(CONFIG, AT, out, sources(alerce_fetch=fetch), backfill=True)
    assert {(c["since"], c["backfill"]) for c in configs} == {(None, True)}
    assert all("lastmjd" not in c for c in configs)


def test_invalid_record_refused(tmp_path):
    def bad(field, config):
        rows = fink_replay(field, config)
        return [{**rows[0], "r:ra": 400}, *rows[1:]] if field == FIELDS[0] else rows

    with pytest.raises(ValidationError):
        ingest_all.run(CONFIG, AT, tmp_path / "objects", sources(fink_fetch=bad))
    assert not (tmp_path / "objects").exists()


def test_written_lines_validate(tmp_path, valid):
    path = ingest_all.run(CONFIG, AT, tmp_path / "objects", sources())
    assert path == tmp_path / "objects" / "2026-11-07.jsonl.gz"
    got = [json.loads(line) for line in gzip.decompress(path.read_bytes()).decode().splitlines()]
    for r in got:
        valid(r)
    fink_got = list(fink.records(CONFIG, AT, fetch=fink_replay))
    assert got == merge.merge(fink_got + list(alerce.records(CONFIG, AT, fetch=alerce_replay)))
