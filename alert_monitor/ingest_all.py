import gzip
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from jsonschema import Draft202012Validator

from alert_monitor import ingest, labels, merge
from alert_monitor.sources import alerce, fink, lasair

SCHEMA = json.loads((Path(__file__).parents[1] / "tests" / "fixtures" / "sky-schema" / "object.json").read_text())
SOURCES = {
    "fink": (fink.records, ingest.fetch_field),
    "alerce": (alerce.records, alerce.fetch_field),
    "lasair": (lasair.records, lasair.fetch),
}


def _broker(broker: str, records, fetch, config: dict, at: str) -> tuple[list[dict], dict]:
    errors: list[Exception] = []
    calls = 0
    results: list[list[dict]] = []
    skipped = {}

    def tracked(*args):
        nonlocal calls
        calls += 1
        try:
            result = fetch(*args)
        except lasair.Skipped:
            raise
        except Exception as exc:
            errors.append(exc)
            raise
        if broker == "alerce":
            results.append(result)
        return result

    try:
        got = list(records(config, at, fetch=tracked))
    except lasair.Skipped as exc:
        got, skipped = [], {"skipped": str(exc)}
    except Exception as exc:  # noqa: BLE001
        got = []
        if exc not in errors:
            errors.append(exc)
    entry = {
        "rows": len(got),
        "errors": [f"{type(e).__name__}: {e}" for e in errors],
        "calls": calls,
        "unmapped": labels.unmapped(got).get(broker, {}),
        **(alerce.paging(results, config, bool(errors)) if broker == "alerce" else {}),
        **skipped,
    }
    return got, entry


def _fresh(rows: list[dict], before: dict, seen: set[str]) -> dict:
    newest = max((r["t_last"] for r in rows), default=None)
    stale = newest is not None and before.get("newest") is not None and newest <= before["newest"]
    return {"newest": newest, "new_ids": len({r["id"] for r in rows} - seen), "stale": stale}


def _summary(day: str, brokers: dict, headers: list[dict]) -> str:
    moved = any(e["newest"] and not e["stale"] for e in brokers.values())
    stale = [
        b for b, e in brokers.items()
        if moved and e["stale"] and [h.get(b, {}).get("stale") for h in headers[-2:]] == [True, True]
    ]
    counts = ", ".join(f"{b} {e['new_ids']} new" for b, e in brokers.items())
    return f"{day}: {counts}" + (f"; stale 3 days: {', '.join(stale)}" if stale else "")


def run(config: dict, at: str, out_dir: Path = Path("data/objects"), sources=SOURCES, backfill=False) -> Path:
    previous = sorted(p for p in out_dir.glob("*.header.json") if p.name[:10] < at[:10])
    headers = [json.loads(p.read_text())["brokers"] for p in previous]
    last = headers[-1].get("alerce", {}) if headers else {}
    since = None if backfill else last.get("lastmjd")
    seen: set[str] = set()
    if previous:
        day = gzip.decompress((out_dir / f"{previous[-1].name[:10]}.jsonl.gz").read_bytes()).decode()
        seen = {json.loads(line)["id"] for line in day.splitlines()}
    config = {**config, "since": since, "backfill": backfill, "gap": last.get("gap")}
    got, brokers = [], {}
    for broker, (records, fetch) in sources.items():
        rows, brokers[broker] = _broker(broker, records, fetch, config, at)
        brokers[broker] |= _fresh(rows, headers[-1].get(broker, {}) if headers else {}, seen)
        got += rows
    if not got:
        raise RuntimeError(f"no broker returned rows: { {b: e['errors'] for b, e in brokers.items()} }")
    merged = merge.merge(got)
    validate = Draft202012Validator(SCHEMA).validate
    for r in merged:
        validate(r)
    lines = "".join(json.dumps(r, separators=(",", ":")) + "\n" for r in merged)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{at[:10]}.jsonl.gz"
    path.write_bytes(gzip.compress(lines.encode(), mtime=0))
    (out_dir / f"{at[:10]}.header.json").write_text(json.dumps({"date": at[:10], "brokers": brokers}))
    print(_summary(at[:10], brokers, headers))
    return path


if __name__ == "__main__":
    run(ingest.load_config(), datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), backfill="--backfill" in sys.argv)
