import json
from datetime import date
from pathlib import Path
from urllib.request import Request, urlopen

URL = "https://api.lsst.fink-portal.org/api/v1/conesearch"
TIMEOUT = 90
FIELDS_PATH = Path(__file__).with_name("fields.json")


def load_config(path: Path = FIELDS_PATH) -> dict:
    return json.loads(path.read_text())


def fetch_field(field: dict, config: dict) -> list[dict]:
    body = {
        "ra": field["ra"],
        "dec": field["dec"],
        "radius": config["radius"],
        "n": config["n"],
        "kind": "across",
        "columns": ",".join(config["columns"]),
        "output-format": "json",
    }
    req = Request(
        URL,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(req, timeout=TIMEOUT) as resp:
        rows = json.load(resp)
    if not isinstance(rows, list):
        raise ValueError(f"expected a JSON list, got {type(rows).__name__}")  # noqa: TRY004
    return rows


def _fetch_twice(field: dict, config: dict, fetch) -> list[dict]:
    try:
        return fetch(field, config)
    except Exception:  # noqa: BLE001
        return fetch(field, config)


def snapshot(day: date, config: dict, fetch=fetch_field) -> dict:
    entries, rows, seen = [], [], set()
    for field in config["fields"]:
        entry = {"ra": field["ra"], "dec": field["dec"]}
        entries.append(entry)
        try:
            got = _fetch_twice(field, config, fetch)
        except Exception as exc:  # noqa: BLE001
            entry["error"] = f"{type(exc).__name__}: {exc}"
            continue
        entry["rows"] = len(got)
        for row in got:
            if row["r:diaObjectId"] not in seen:
                seen.add(row["r:diaObjectId"])
                rows.append(row)
    return {"header": {"date": day.isoformat(), "fields": entries}, "rows": rows}


def write_snapshot(snap: dict, out_dir: Path = Path("data/snapshots")) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{snap['header']['date']}.json"
    path.write_text(json.dumps(snap, indent=2))
    return path


if __name__ == "__main__":
    write_snapshot(snapshot(date.today(), load_config()))
