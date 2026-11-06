import json
from pathlib import Path

from alert_monitor import record

ROOT = Path(__file__).parents[1]
SNAP = json.loads((ROOT / "tests" / "fixtures" / "labels_snapshot.json").read_text())
ROWS = {r["r:diaObjectId"]: {**r, "r:ra": 150.6612, "r:dec": 0.8503} for r in SNAP["rows"]}
AT = "2026-10-18T06:00:00Z"
FIRST, LAST = "2026-10-06T23:59:23.000Z", "2026-10-16T23:59:23.000Z"
ALERCE = {
    "oid": "ZTF26abcdxyz", "meanra": 150.6612, "meandec": 0.8503, "firstmjd": 61320.0, "lastmjd": 61330.0,
    "ndet": 3, "class": "SNIa", "probability": 0.9,
}
LASAIR = {
    "diaObjectId": 170028, "ra": 150.6612, "decl": 0.8503, "firstDiaSourceMjdTai": 61320.0,
    "lastDiaSourceMjdTai": 61330.0, "nDiaSources": 3, "classification": "NT",
}


def far(source, id, label, raw, score, n_obs=3, t_first=FIRST, days_watched=10.0):
    return {
        "schema_version": 0, "id": id, "lane": "far", "source": source, "ra": 150.6612, "dec": 0.8503,
        "t_first": t_first, "t_last": LAST, "n_obs": n_obs, "days_watched": days_watched,
        "labels": [{"broker": source, "label": label, "raw": raw, "score": score, "at": AT}],
    }


def test_from_fink():
    assert record.from_fink(ROWS[1], AT) == far("fink", "1", "sn", "11", 0.875)


def test_from_fink_sso_is_moving_keeps_code():
    assert record.from_fink({**ROWS[1], "f:is_sso": True}, AT) == far("fink", "1", "moving", "11", 0.875)


def test_from_fink_null_first_detection():
    assert record.from_fink(ROWS[12], AT) == far("fink", "12", "sn", "11", 0.75, 15, LAST, 0.0)


def test_from_alerce():
    assert record.from_alerce(ALERCE, AT) == far("alerce", "ZTF26abcdxyz", "sn", "SNIa", 0.9)


def test_from_lasair():
    assert record.from_lasair(LASAIR, AT) == far("lasair", "170028", "nuclear", "NT", None)


def test_records_and_far_fixture_validate(valid):
    for row in ROWS.values():
        valid(record.from_fink(row, AT))
    valid(record.from_alerce(ALERCE, AT))
    valid(record.from_lasair(LASAIR, AT))
    valid(json.loads((ROOT / "tests" / "fixtures" / "sky-schema" / "far.json").read_text()))
