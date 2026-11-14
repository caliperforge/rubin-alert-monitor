import gzip
import json
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from urllib.error import HTTPError

import pytest
from astropy.time import Time
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


def unauthorized(field, config):
    raise HTTPError("https://example.invalid", 401, "Unauthorized", None, None)  # pyright: ignore[reportArgumentType]


def days_behind(newest):
    return (datetime.fromisoformat(AT) - datetime.fromisoformat(newest)).days


def sources(fink_fetch=fink_replay, alerce_fetch=alerce_replay):
    return {"fink": (fink.records, fink_fetch), "alerce": (alerce.records, alerce_fetch)}


def header(out):
    return json.loads((out / "2026-11-07.header.json").read_text())


def records():
    return list(fink.records(CONFIG, AT, fetch=fink_replay))


def write_day(out, day, brokers, rows=()):
    out.mkdir(exist_ok=True)
    (out / f"{day}.header.json").write_text(json.dumps({"date": day, "brokers": brokers}))
    (out / f"{day}.jsonl.gz").write_bytes(gzip.compress("".join(json.dumps(r) + "\n" for r in rows).encode()))


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
        "newest": None,
        "new_ids": 0,
        "stale": False,
        "behind_days": None,
        "behind": False,
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
    fink_got, alerce_got = records(), list(alerce.records(CONFIG, AT, fetch=alerce_replay))
    assert header(out) == {
        "date": "2026-11-07",
        "brokers": {
            "fink": {
                "rows": len(fink_rows),
                "errors": ["TimeoutError: timed out"],
                "calls": len(FIELDS) + 1,
                "unmapped": {k: n for k, n in fink_raw.items() if k not in labels.TABLE["fink"]},
                "newest": max(r["t_last"] for r in fink_got),
                "new_ids": len({r["id"] for r in fink_got}),
                "stale": False,
                "behind_days": days_behind(max(r["t_last"] for r in fink_got)),
                "behind": True,
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
                "newest": max(r["t_last"] for r in alerce_got),
                "new_ids": len({r["id"] for r in alerce_got}),
                "stale": False,
                "behind_days": days_behind(max(r["t_last"] for r in alerce_got)),
                "behind": True,
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
    for day, mjd in [("2026-11-05", 61349.0), ("2026-11-06", 61350.0), ("2026-11-07", 61351.0)]:
        write_day(out, day, {"alerce": {"lastmjd": {"150.66,0.85": mjd, "61.96,-48.71": mjd + 10}}})


def test_same_newest_is_stale_with_no_new_ids(tmp_path):
    out = tmp_path / "objects"
    write_day(out, "2026-11-06", {"fink": {"newest": max(r["t_last"] for r in records())}}, records())
    ingest_all.run(CONFIG, AT, out, sources())
    entry = header(out)["brokers"]["fink"]
    assert (entry["stale"], entry["new_ids"]) == (True, 0)


@pytest.mark.parametrize("before", [{"fink": {"newest": "2000-01-01T00:00:00.000Z"}}, {"fink": {}}, None])
def test_moved_newest_counts_new_ids(tmp_path, before):
    ids = list(dict.fromkeys(r["id"] for r in records()))
    out = tmp_path / "objects"
    if before is not None:
        write_day(out, "2026-11-06", before, [r for r in records() if r["id"] not in ids[:3]])
    ingest_all.run(CONFIG, AT, out, sources())
    entry = header(out)["brokers"]["fink"]
    assert (entry["stale"], entry["new_ids"]) == (False, len(ids) if before is None else 3)


def stale_days(out, stale):
    newest = max(r["t_last"] for r in records())
    for day, s in zip(["2026-11-05", "2026-11-06"], stale, strict=True):
        write_day(out, day, {"fink": {"newest": newest, "stale": s}})


def test_stale_three_days_named_in_summary(tmp_path, capsys):
    out = tmp_path / "objects"
    stale_days(out, [True, True])
    ingest_all.run(CONFIG, AT, out, sources())
    brokers = header(out)["brokers"]
    f, a = brokers["fink"], brokers["alerce"]
    assert capsys.readouterr().out == (
        f"2026-11-07: fink {f['new_ids']} new, alerce {a['new_ids']} new; stale 3 days: fink"
        f"; behind: fink {f['behind_days']} d, alerce {a['behind_days']} d\n"
    )


@pytest.mark.parametrize(("ago", "days", "part"), [(328.5, 328, "; behind: alerce 328 d"), (1.5, 1, "")])
def test_behind_over_three_days_named_in_summary(tmp_path, capsys, ago, days, part):
    last = Time(AT[:19], format="isot", scale="utc").tai.mjd - ago  # pyright: ignore[reportAttributeAccessIssue]
    rows = [{**r, "firstmjd": last, "lastmjd": last} for r in ALERCE]
    out = tmp_path / "objects"
    ingest_all.run(CONFIG, AT, out, {"alerce": (alerce.records, lambda field, config: rows if field == FIELDS[0] else [])})
    entry = header(out)["brokers"]["alerce"]
    assert (entry["behind_days"], entry["behind"]) == (days, days > 3)
    assert capsys.readouterr().out == f"2026-11-07: alerce {entry['new_ids']} new{part}\n"


@pytest.mark.parametrize(("alerce_fetch", "why"), [(unauthorized, "401"), (timeout, "TimeoutError")])
def test_errors_without_rows_named_failing(tmp_path, capsys, alerce_fetch, why):
    calls = []

    def flaky(field, config):
        calls.append(field)
        if len(calls) == 1:
            raise TimeoutError("timed out")
        return fink_replay(field, config)

    out = tmp_path / "objects"
    ingest_all.run(CONFIG, AT, out, sources(fink_fetch=flaky, alerce_fetch=alerce_fetch))
    f = header(out)["brokers"]["fink"]
    assert f["errors"] == ["TimeoutError: timed out"]
    assert capsys.readouterr().out == (
        f"2026-11-07: fink {f['new_ids']} new, alerce 0 new; behind: fink {f['behind_days']} d; failing: alerce ({why})\n"
    )


@pytest.mark.parametrize(("stale", "alerce_fetch"), [([False, True], alerce_replay), ([True, True], timeout)])
def test_stale_two_days_or_nothing_moved_not_named(tmp_path, capsys, stale, alerce_fetch):
    out = tmp_path / "objects"
    stale_days(out, stale)
    ingest_all.run(CONFIG, AT, out, sources(alerce_fetch=alerce_fetch))
    assert header(out)["brokers"]["fink"]["stale"] is True
    assert "stale 3 days" not in capsys.readouterr().out


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


def test_capped_run_records_gap_in_header(tmp_path):
    def full(field, config):
        return [{**ALERCE[0], "oid": f"cap{i}", "lastmjd": 61351.0 + i / 100} for i in range(50)] if field == FIELDS[0] else []

    out = tmp_path / "objects"
    previous_headers(out)
    ingest_all.run({**CONFIG, "n": 1}, AT, out, sources(alerce_fetch=full))
    entry = header(out)["brokers"]["alerce"]
    assert entry["gap"] == {"150.66,0.85": [61350.0, 61351.0]}
    assert entry["lastmjd"]["150.66,0.85"] == 61350.0


def test_backfill_reads_previous_header_gap(tmp_path):
    configs = []

    def fetch(field, config):
        configs.append(config)
        return alerce_replay(field, config)

    out = tmp_path / "objects"
    write_day(out, "2026-11-06", {"alerce": {"lastmjd": {"150.66,0.85": 61350.0}, "gap": {"150.66,0.85": [61340.0, 61345.0]}}})
    ingest_all.run(CONFIG, AT, out, sources(alerce_fetch=fetch), backfill=True)
    assert [c.get("lastmjd") for c in configs] == [[61340.0, 61345.0], None, None, None]


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
