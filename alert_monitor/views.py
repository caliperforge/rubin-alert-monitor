import gzip
import json
from collections import Counter
from pathlib import Path

OBJECTS = Path("data/objects")
SANITY = Path("results/label_sanity.jsonl")
OUT = Path("data/views.json")
TOP = 50


def tile(entry: dict) -> dict:
    return {
        "rows": entry["rows"],
        "new_ids": entry["new_ids"],
        "stale": entry["stale"],
        "truncated": entry.get("truncated", False),
        "errors": entry["errors"],
    }


def best(record: dict) -> float:
    return max((label["score"] for label in record["labels"] if label["score"] is not None), default=float("-inf"))


def pick(record: dict) -> dict:
    return {
        "id": record["id"],
        "ra": record["ra"],
        "dec": record["dec"],
        "days_watched": record["days_watched"],
        "labels": {label["broker"]: {"label": label["label"], "score": label["score"]} for label in record["labels"]},
    }


def build(objects: Path = OBJECTS, sanity: Path = SANITY) -> dict:
    headers = sorted(objects.glob("*.header.json"))
    if not headers:
        raise FileNotFoundError(f"no *.header.json in {objects}")
    header = json.loads(headers[-1].read_text())
    day = gzip.decompress((objects / f"{header['date']}.jsonl.gz").read_bytes()).decode()
    records = [json.loads(line) for line in day.splitlines()]
    rows = [row for line in sanity.read_text().splitlines() if (row := json.loads(line))["check"] == "sn_share"]
    shares = {row["date"]: row["value"] for row in rows}
    labels: dict[str, Counter] = {}
    for label in (label for r in records for label in r["labels"]):
        labels.setdefault(label["broker"], Counter())[label["label"]] += 1
    two = [r for r in records if len({label["broker"] for label in r["labels"]}) >= 2]
    contested = [r for r in two if r["contested"]]
    return {
        "date": header["date"],
        "tiles": {broker: tile(entry) for broker, entry in header["brokers"].items()},
        "sn_share": {key: {d: shares[d][key] for d in sorted(shares)} for key in ("days", "detections", "overall")},
        "labels": labels,
        "two_brokers": len(two),
        "contested": len(contested),
        "worth_a_look": [pick(r) for r in sorted(contested, key=best, reverse=True)[:TOP]],
    }


def write(view: dict, out: Path = OUT) -> None:
    out.write_text(json.dumps(view, separators=(",", ":")))


if __name__ == "__main__":
    write(build())
