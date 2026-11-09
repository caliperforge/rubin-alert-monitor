import gzip
import json
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
    sizes: list[int] = []
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
        sizes.append(len(result))
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
        **(alerce.paging(sizes, config) if broker == "alerce" else {}),
        **skipped,
    }
    return got, entry


def run(config: dict, at: str, out_dir: Path = Path("data/objects"), sources=SOURCES) -> Path:
    got, brokers = [], {}
    for broker, (records, fetch) in sources.items():
        rows, brokers[broker] = _broker(broker, records, fetch, config, at)
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
    return path


if __name__ == "__main__":
    run(ingest.load_config(), datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))
