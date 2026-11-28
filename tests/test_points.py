import gzip
import json
import math
import random
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from alert_monitor import ingest, points

ROOT = Path(__file__).parents[1]
FIX = [json.loads(line) for line in (ROOT / "tests" / "fixtures" / "objects_day.jsonl").read_text().splitlines()]
LABELS = ["sn", "agn", "variable", "nuclear", "moving", "unknown"]


def lay(objects: Path, date: str, records: list[dict]) -> None:
    lines = "".join(json.dumps(r) + "\n" for r in records)
    (objects / f"{date}.jsonl.gz").write_bytes(gzip.compress(lines.encode()))


def build(tmp_path, records=FIX) -> dict:
    lay(tmp_path, "2026-11-26", [])
    lay(tmp_path, "2026-11-27", records)
    out = tmp_path / "points.json"
    points.write(points.build(tmp_path), out)
    return json.loads(out.read_text())


def rows(p: dict) -> dict:
    columns = [k for k in p if k not in ("date", "labels")]
    return {i: dict(zip(columns, row)) for i, row in zip(p["id"], zip(*(p[k] for k in columns)))}


def test_one_row_per_in_field_record(tmp_path):
    p = build(tmp_path)
    assert p["date"] == "2026-11-27"
    columns = [k for k in p if k not in ("date", "labels")]
    assert columns == ["field", "dx", "dy", "first", "days", "n", "fink", "alerce", "score", "id"]
    assert {len(p[k]) for k in columns} == {5}
    assert p["id"] == [r["id"] for r in FIX if r["id"] != "169298433216610307"]
    assert p["field"] == [0, 0, 1, 2, 3]
    assert p["first"][:2] == [61345.0, 61314.5]
    assert p["days"] == [26, 56, 17, 2, 0]
    assert p["n"] == [12, 40, 5, 2, 1]


def test_offsets_from_field_centre(tmp_path):
    by = rows(build(tmp_path))
    assert [by["169298433216610305"][k] for k in ("field", "dx", "dy")] == [0, 0.3, 0.0]
    assert [by["169298433216610306"][k] for k in ("dx", "dy")] == [0.0, 0.5]
    assert [by["169298433216610309"][k] for k in ("dx", "dy")] == [0.0, -0.5]
    assert [by["169298433216610310"][k] for k in ("dx", "dy")] == [0.0, 0.0]


def test_out_of_field_record_has_no_row(tmp_path):
    assert "169298433216610307" not in build(tmp_path)["id"]


def test_labels_lookup(tmp_path):
    p = build(tmp_path)
    assert p["labels"] == ["agn", "moving", "sn", "unknown", "variable"]
    by = rows(p)
    for r in FIX[:2] + FIX[3:]:
        given = {label["broker"]: label for label in r["labels"]}
        for broker in ("fink", "alerce"):
            i = by[r["id"]][broker]
            assert (p["labels"][i] if i is not None else None) == given.get(broker, {}).get("label")
    assert [by[i]["alerce"] for i in ("169298433216610306", "169298433216610309")] == [None, None]
    assert [by[i]["score"] for i in sorted(by)] == [0.87, None, None, 0.42, 0.33]


def generated(n: int) -> list[dict]:
    rng = random.Random(27)
    fields = ingest.load_config()["fields"]
    start = datetime(2025, 11, 27)
    records = []
    for _ in range(n):
        centre = rng.choice(fields)
        r, a = 0.99 * math.sqrt(rng.random()), rng.uniform(0, 2 * math.pi)
        ra = centre["ra"] + r * math.cos(a) / math.cos(math.radians(centre["dec"]))
        labels = [
            {"broker": broker, "label": rng.choice(LABELS), "score": rng.choice([None, rng.random()])}
            for broker in ("fink", "alerce", "lasair")
            if rng.random() < 0.6
        ]
        records.append({
            "id": f"1692984{rng.randrange(10**11):011d}",
            "ra": ra % 360,
            "dec": centre["dec"] + r * math.sin(a),
            "t_first": (start + timedelta(seconds=rng.uniform(0, 365 * 86400))).isoformat(timespec="milliseconds") + "Z",
            "n_obs": rng.randint(1, 300),
            "labels": labels,
            "days_watched": rng.uniform(0, 365),
        })
    return records


def test_gzipped_bytes_per_row(tmp_path):
    p = build(tmp_path, generated(6000))
    assert len(p["id"]) >= 5000
    assert len(gzip.compress((tmp_path / "points.json").read_bytes())) / len(p["id"]) <= 24


def test_no_day_raises(tmp_path):
    out = tmp_path / "points.json"
    with pytest.raises(FileNotFoundError, match="jsonl.gz"):
        points.write(points.build(tmp_path), out)
    assert not out.exists()
