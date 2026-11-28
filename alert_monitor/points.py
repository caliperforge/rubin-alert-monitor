import gzip
import json
import math
from pathlib import Path

from astropy.time import Time

from alert_monitor import ingest

OBJECTS = Path("data/objects")
OUT = Path("data/points.json")


def place(ra: float, dec: float, fields: list[dict], radius: float) -> tuple[int, float, float] | None:
    d = math.radians(dec)
    for i, centre in enumerate(fields):
        d0, da = math.radians(centre["dec"]), math.radians(ra - centre["ra"])
        cosc = math.sin(d0) * math.sin(d) + math.cos(d0) * math.cos(d) * math.cos(da)
        if math.degrees(math.acos(min(cosc, 1.0))) <= radius:
            xi = math.cos(d) * math.sin(da) / cosc
            eta = (math.cos(d0) * math.sin(d) - math.sin(d0) * math.cos(d) * math.cos(da)) / cosc
            return i, math.degrees(xi), math.degrees(eta)
    return None


def build(objects: Path = OBJECTS, config: dict | None = None) -> dict:
    config = ingest.load_config() if config is None else config
    days = sorted(objects.glob("*.jsonl.gz"))
    if not days:
        raise FileNotFoundError(f"no *.jsonl.gz in {objects}")
    day = gzip.decompress(days[-1].read_bytes()).decode()
    records = [json.loads(line) for line in day.splitlines()]
    radius = config["radius"] / 3600
    rows = [(r, p) for r in records if (p := place(r["ra"], r["dec"], config["fields"], radius))]
    by = [{label["broker"]: label for label in r["labels"]} for r, _ in rows]
    labels = sorted({b[broker]["label"] for b in by for broker in ("fink", "alerce") if broker in b})
    index = {label: i for i, label in enumerate(labels)}
    first = Time([r["t_first"][:19] for r, _ in rows], format="isot", scale="utc").tai.mjd  # pyright: ignore[reportAttributeAccessIssue]
    return {
        "date": days[-1].name.removesuffix(".jsonl.gz"),
        "labels": labels,
        "field": [p[0] for _, p in rows],
        "dx": [round(p[1], 3) for _, p in rows],
        "dy": [round(p[2], 3) for _, p in rows],
        "first": [round(t, 2) for t in first.tolist()],
        "days": [int(r["days_watched"]) for r, _ in rows],
        "n": [r["n_obs"] for r, _ in rows],
        "fink": [index[b["fink"]["label"]] if "fink" in b else None for b in by],
        "alerce": [index[b["alerce"]["label"]] if "alerce" in b else None for b in by],
        "score": [None if b.get("fink", {}).get("score") is None else round(b["fink"]["score"], 2) for b in by],
        "id": [r["id"] for r, _ in rows],
    }


def write(points: dict, out: Path = OUT) -> None:
    out.write_text(json.dumps(points, separators=(",", ":")))


if __name__ == "__main__":
    write(build())
