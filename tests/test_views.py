import gzip
import json
from pathlib import Path

import pytest

from alert_monitor import views

ROOT = Path(__file__).parents[1]
FIX = json.loads((ROOT / "tests" / "fixtures" / "views.json").read_text())


def lay(objects: Path, header: dict, records: list[dict]) -> None:
    (objects / f"{header['date']}.header.json").write_text(json.dumps(header))
    lines = "".join(json.dumps(r) + "\n" for r in records)
    (objects / f"{header['date']}.jsonl.gz").write_bytes(gzip.compress(lines.encode()))


def build(tmp_path, records=FIX["objects"]):
    lay(tmp_path, FIX["header"], records)
    sanity = tmp_path / "label_sanity.jsonl"
    sanity.write_text("".join(json.dumps(r) + "\n" for r in FIX["sanity"]))
    out = tmp_path / "views.json"
    views.write(views.build(tmp_path, sanity), out)
    return json.loads(out.read_text())


def contested(i, score):
    labels = [{"broker": "fink", "label": "SN", "score": score}, {"broker": "alerce", "label": "AGN", "score": None}]
    return {"id": str(i), "ra": 0.0, "dec": 0.0, "days_watched": 1.0, "labels": labels, "contested": True}


def test_tiles_show_failing_broker_with_error(tmp_path):
    tiles = build(tmp_path)["tiles"]
    assert list(tiles) == ["fink", "alerce", "lasair"]
    assert tiles["lasair"] == {
        "rows": 0, "new_ids": 0, "stale": False, "truncated": False, "errors": ["HTTPError: HTTP Error 401: Unauthorized"],
    }
    assert tiles["alerce"]["truncated"] is True
    assert tiles["fink"]["truncated"] is False


def test_sn_share_curves_cover_every_sanity_date(tmp_path):
    sn = build(tmp_path)["sn_share"]
    latest = {r["date"]: r["value"] for r in (FIX["sanity"][0], FIX["sanity"][3])}
    for key in ("days", "detections"):
        assert list(sn[key]) == ["2026-11-15", "2026-11-16"]
        assert "2026-11-14" not in sn[key]
        assert sn[key] == {d: v[key] for d, v in latest.items()}
    assert sn["overall"] == {"2026-11-15": 0.85, "2026-11-16": 0.8}
    assert list(sn["overall"]) == ["2026-11-15", "2026-11-16"]


def test_label_counts_and_contested(tmp_path):
    view = build(tmp_path)
    assert view["labels"] == {"fink": {"SN": 4}, "alerce": {"SN": 2, "AGN": 1}, "lasair": {"AGN": 2}}
    assert (view["two_brokers"], view["contested"]) == (4, 3)


def test_worth_a_look_ranks_contested_by_score_and_caps_at_50(tmp_path):
    top = build(tmp_path)["worth_a_look"]
    assert [r["id"] for r in top] == ["contested-high", "contested-low", "contested-null"]
    assert top[0] == {
        "id": "contested-high", "ra": 14.0, "dec": -5.0, "days_watched": 11.0,
        "labels": {"alerce": {"label": "SN", "score": 0.95}, "lasair": {"label": "AGN", "score": None}},
    }
    many = tmp_path / "many"
    many.mkdir()
    agreeing = {**contested("agree", 1.0), "contested": False}
    top = build(many, [contested(i, i / 100) for i in range(51)] + [agreeing])["worth_a_look"]
    assert [r["id"] for r in top] == [str(i) for i in range(50, 0, -1)]


def test_newest_header_is_used(tmp_path):
    lay(tmp_path, {"date": "2026-11-15", "brokers": {"fink": FIX["header"]["brokers"]["fink"]}}, [])
    view = build(tmp_path)
    assert view["date"] == "2026-11-16"
    assert list(view["tiles"]) == ["fink", "alerce", "lasair"]
    assert view["two_brokers"] == 4


def test_no_header_raises(tmp_path):
    sanity = tmp_path / "label_sanity.jsonl"
    sanity.write_text("".join(json.dumps(r) + "\n" for r in FIX["sanity"]))
    out = tmp_path / "views.json"
    with pytest.raises(FileNotFoundError, match="header"):
        views.write(views.build(tmp_path, sanity), out)
    assert not out.exists()
