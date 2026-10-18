import json
from datetime import date
from pathlib import Path

import pytest

from alert_monitor.checks import labels

ROOT = Path(__file__).parents[1]
SNAP = json.loads((ROOT / "tests" / "fixtures" / "labels_snapshot.json").read_text())
DAY = "2026-10-18"
CHECKS = ["sn_share", "score_median", "sn_long_lived", "sn_star_match", "unknown_codes", "crossmatch_fail", "tns_agreement"]
TNS = {"TNS_BOT_ID": "1", "TNS_BOT_NAME": "bot", "TNS_API_KEY": "key"}


def by_check(snap, env=None):
    return {r["check"]: r for r in labels.run(snap, env={} if env is None else env)}


def many(k):
    return {"header": SNAP["header"], "rows": [{**SNAP["rows"][0], "r:diaObjectId": i} for i in range(k)]}


def summary(snap, tmp_path):
    labels.write(labels.run(snap, env={}), tmp_path)
    return (tmp_path / "label_sanity.md").read_text()


def test_checks_in_order_with_known_values():
    none4 = dict.fromkeys(["2-4", "5-9", "10-49", "50+"])
    expected = [
        ("sn_share", {
            "overall": 6 / 13,
            "detections": {"2-4": 1 / 3, "5-9": 2 / 3, "10-49": 0.5, "50+": 0.5},
            "days": {"<30": 0.5, "30-99": 1 / 3, "100-199": 0.5, "200+": 1 / 3},
        }, 13, [1, 2, 3, 4, 12, 14]),
        ("score_median", {
            11: {"2-4": 0.875, "5-9": 0.8125, "10-49": 0.6875, "50+": 0.5},
            12: {**none4, "2-4": 0.375},
            13: {**none4, "2-4": 0.25, "50+": 0.125},
            21: {**none4, "5-9": 0.25, "10-49": 0.625},
            22: {**none4, "10-49": 0.5},
        }, 13, []),
        ("sn_long_lived", {"100+": 2, "200+": 1}, 6, [3, 4]),
        ("sn_star_match", 1, 6, [2]),
        ("unknown_codes", {"count": 1, "codes": [31]}, 15, [10]),
        ("crossmatch_fail", 0.2, 15, [6, 13, 14]),
        ("tns_agreement", {"matched": 4, "mapped": 3, "agree": 2, "percent": None}, 4, [13]),
        ("tns_direct", "not configured", 0, []),
    ]
    assert labels.run(SNAP, env={}) == [
        {"date": DAY, "check": c, "value": v, "n": n, "examples": ex} for c, v, n, ex in expected
    ]
    rows = labels.run(many(30), env={})
    assert [r["check"] for r in rows] == [*CHECKS, "tns_direct"]
    assert all(r["date"] == DAY and len(r["examples"]) <= 10 for r in rows)
    assert rows[0]["examples"] == list(range(10))


def test_unknown_code_outside_classified():
    rows = by_check(SNAP)
    assert rows["unknown_codes"]["value"] == {"count": 1, "codes": [31]}
    sn = rows["sn_share"]["value"]
    assert sn["overall"] == 6 / 13
    assert sn["detections"]["5-9"] == 2 / 3
    assert sn["days"]["<30"] == 0.5


def test_star_counts_galaxy_does_not():
    row = by_check(SNAP)["sn_star_match"]
    assert row["value"] == 1
    assert row["examples"] == [2]


def test_crossmatch_fail_share():
    assert by_check(SNAP)["crossmatch_fail"]["value"] == 3 / 15


def test_tns_direct_configured_only_with_all_three():
    assert by_check(SNAP)["tns_direct"]["value"] == "not configured"
    assert by_check(SNAP, {k: TNS[k] for k in ("TNS_BOT_ID", "TNS_BOT_NAME")})["tns_direct"]["value"] == "not configured"
    assert by_check(SNAP, TNS)["tns_direct"]["value"] == "configured"


def test_tns_percent_needs_thirty_mapped(tmp_path):
    assert by_check(many(29))["tns_agreement"]["value"] == {"matched": 29, "mapped": 29, "agree": 29, "percent": None}
    (line,) = [x for x in summary(many(29), tmp_path).splitlines() if x.startswith("- tns_agreement")]
    assert line == "- tns_agreement: 29 mapped rows, fewer than 30"
    assert by_check(many(30))["tns_agreement"]["value"]["percent"] == 100.0
    (line,) = [x for x in summary(many(30), tmp_path).splitlines() if x.startswith("- tns_agreement")]
    assert line == "- tns_agreement: 100.0% of 30 mapped rows agree"


def test_write_replaces_its_date_keeps_others(tmp_path):
    rows = labels.run(SNAP, env={})
    other = [{**r, "date": "2026-10-17"} for r in rows]
    labels.write(other, tmp_path)
    labels.write(rows, tmp_path)
    labels.write(rows, tmp_path)
    lines = (tmp_path / "label_sanity.jsonl").read_text().splitlines()
    assert [json.loads(x) for x in lines] == json.loads(json.dumps(other + rows))


def test_small_fixture_verdicts(tmp_path):
    lines = summary(SNAP, tmp_path).splitlines()
    table = [x.strip("| ").split(" | ") for x in lines[lines.index("|---|---|---|---|") + 1 :]]
    assert {m: v for m, _, _, v in table} == {
        "sn_share overall": "data moved",
        "sn_share <30": "data moved",
        "sn_share 30-99": "data moved",
        "sn_share 100-199": "near",
        "sn_share 200+": "data moved",
        "sn_long_lived 100+": "data moved",
        "sn_long_lived 200+": "data moved",
        "crossmatch_fail": "data moved",
        "unknown_codes": "near",
    }


@pytest.mark.live
def test_live_label_rows():
    today = date.today().isoformat()
    labels.write(labels.run(json.loads((Path("data/snapshots") / f"{today}.json").read_text())))
    rows = [json.loads(x) for x in Path("results/label_sanity.jsonl").read_text().splitlines()]
    assert [r["check"] for r in rows if r["date"] == today and r["check"] != "tns_direct"] == CHECKS
