import gzip
import json
import os
import statistics
from collections.abc import Mapping
from datetime import date
from pathlib import Path

SNAPSHOTS = Path("data/snapshots")
MAX_EXAMPLES = 10
# github.com/astrolabsoftware/fink-broker 2340a41e653acadf9bdf74e110e17d2f94c51808, fink_broker/rubin/science.py, mapping_cats_general
LABELS = {-1: "not classified", 11: "supernova-like", 12: "fast", 13: "long", 21: "periodic", 22: "non-periodic (AGN)"}
CLASSIFIED = tuple(c for c in LABELS if c != -1)
SN = 11
DETECTIONS = (("2-4", 2, 5), ("5-9", 5, 10), ("10-49", 10, 50), ("50+", 50, float("inf")))
DAYS = (("<30", float("-inf"), 30), ("30-99", 30, 100), ("100-199", 100, 200), ("200+", 200, float("inf")))
NOT_HOST = {"Star", "*", "QSO", "AGN", "Seyfert", "Seyfert1", "Seyfert2", "Sy1", "Sy2", "SyG", "WhiteDwarf", "WD*"}
"""SIMBAD otypes that cannot host a supernova: https://simbad.cds.unistra.fr/guide/otypes.htx"""
TNS_PREFIXES = (("SLSN", 13), ("SN", 11))
TNS_LABELS = {"TDE": 13, "Kilonova": 12, "Nova": 12, "AGN": 22}
MIN_TNS = 30
TNS_ENV = ("TNS_BOT_ID", "TNS_BOT_NAME", "TNS_API_KEY")
BASELINE_ROWS = 228317
TOLERANCE = 0.1
BASELINE = {
    "sn_share overall": 40907 / 48226,
    "sn_share <30": .964,
    "sn_share 30-99": .784,
    "sn_share 100-199": .497,
    "sn_share 200+": .214,
    "sn_long_lived 100+": 1565 / 40907,
    "sn_long_lived 200+": 217 / 40907,
    "crossmatch_fail": .75,
    "unknown_codes": 5 / 228317,
}


def share(part: int, whole: int) -> float | None:
    return part / whole if whole else None


def is_sn(row: dict) -> bool:
    return row["f:clf_cats_class"] == SN


def classified(rows: list[dict]) -> list[dict]:
    return [r for r in rows if r["f:clf_cats_class"] in CLASSIFIED]


def detections(row: dict) -> int:
    return row["r:nDiaSources"]


def days(row: dict) -> float | None:
    first, last = row["f:firstDiaSourceMjdTaiFink"], row["r:midpointMjdTai"]
    return None if first is None or last is None else last - first


def by_bucket(rows: list[dict], key, buckets: tuple) -> dict[str, list[dict]]:
    out = {name: [] for name, _, _ in buckets}
    for row in rows:
        x = key(row)
        for name, lo, hi in buckets:
            if x is not None and lo <= x < hi:
                out[name].append(row)
    return out


def sn_fraction(rows: list[dict]) -> float | None:
    return share(sum(map(is_sn, rows)), len(rows))


def sn_share(rows: list[dict]) -> tuple[dict, int, list[dict]]:
    cl = classified(rows)
    value = {
        "overall": sn_fraction(cl),
        "detections": {b: sn_fraction(rs) for b, rs in by_bucket(cl, detections, DETECTIONS).items()},
        "days": {b: sn_fraction(rs) for b, rs in by_bucket(cl, days, DAYS).items()},
    }
    return value, len(cl), [r for r in cl if is_sn(r)]


def score_median(rows: list[dict]) -> tuple[dict, int, list[dict]]:
    cl = classified(rows)
    groups = by_bucket(cl, detections, DETECTIONS)
    value = {
        code: {
            b: statistics.median(scores) if (scores := [r["f:clf_cats_score"] for r in rs if r["f:clf_cats_class"] == code]) else None
            for b, rs in groups.items()
        }
        for code in CLASSIFIED
    }
    return value, len(cl), []


def sn_long_lived(rows: list[dict]) -> tuple[dict, int, list[dict]]:
    sn = [r for r in rows if is_sn(r)]
    aged = [(r, d) for r in sn if (d := days(r)) is not None and d >= 100]
    return {"100+": len(aged), "200+": sum(d >= 200 for _, d in aged)}, len(sn), [r for r, _ in aged]


def sn_star_match(rows: list[dict]) -> tuple[int, int, list[dict]]:
    sn = [r for r in rows if is_sn(r)]
    hits = [r for r in sn if r["f:main_label_crossmatch"] in NOT_HOST]
    return len(hits), len(sn), hits


def unknown_codes(rows: list[dict]) -> tuple[dict, int, list[dict]]:
    odd = [r for r in rows if r["f:clf_cats_class"] not in LABELS]
    return {"count": len(odd), "codes": sorted({r["f:clf_cats_class"] for r in odd})}, len(rows), odd


def crossmatch_fail(rows: list[dict]) -> tuple[float | None, int, list[dict]]:
    fails = [r for r in rows if r["f:main_label_crossmatch"] == "Fail"]
    return share(len(fails), len(rows)), len(rows), fails


def tns_code(tns_type: str) -> int | None:
    for prefix, code in TNS_PREFIXES:
        if tns_type.startswith(prefix):
            return code
    return TNS_LABELS.get(tns_type)


def tns_agreement(rows: list[dict]) -> tuple[dict, int, list[dict]]:
    matched = [r for r in rows if r["f:xm_tns_type"] is not None]
    mapped = [(r, c) for r in matched if (c := tns_code(r["f:xm_tns_type"])) is not None]
    agree = sum(r["f:clf_cats_class"] == c for r, c in mapped)
    percent = 100 * agree / len(mapped) if len(mapped) >= MIN_TNS else None
    value = {"matched": len(matched), "mapped": len(mapped), "agree": agree, "percent": percent}
    return value, len(matched), [r for r, c in mapped if r["f:clf_cats_class"] != c]


def tns_direct(env: Mapping[str, str]) -> tuple[str, int, list[dict]]:
    return ("configured" if all(k in env for k in TNS_ENV) else "not configured"), 0, []


CHECKS = (sn_share, score_median, sn_long_lived, sn_star_match, unknown_codes, crossmatch_fail, tns_agreement)


def run(snap: dict, env: Mapping[str, str] = os.environ) -> list[dict]:
    rows = snap["rows"]
    results = [(check.__name__, check(rows)) for check in CHECKS] + [("tns_direct", tns_direct(env))]
    return [
        {
            "date": snap["header"]["date"],
            "check": name,
            "value": value,
            "n": n,
            "examples": [r["r:diaObjectId"] for r in examples[:MAX_EXAMPLES]],
        }
        for name, (value, n, examples) in results
    ]


def pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.1%}"


def check_line(row: dict) -> str:
    if row["check"] != "tns_agreement":
        return f"- {row['check']}: {json.dumps(row['value'])} (n={row['n']})"
    v = row["value"]
    if v["percent"] is None:
        return f"- tns_agreement: {v['mapped']} mapped rows, fewer than {MIN_TNS}"
    return f"- tns_agreement: {v['percent']:.1f}% of {v['mapped']} mapped rows agree"


def measures(by: dict[str, dict]) -> dict[str, float | None]:
    sn, aged, odd = by["sn_share"]["value"], by["sn_long_lived"], by["unknown_codes"]
    return {
        "sn_share overall": sn["overall"],
        **{f"sn_share {name}": sn["days"][name] for name, _, _ in DAYS},
        "sn_long_lived 100+": share(aged["value"]["100+"], aged["n"]),
        "sn_long_lived 200+": share(aged["value"]["200+"], aged["n"]),
        "crossmatch_fail": by["crossmatch_fail"]["value"],
        "unknown_codes": share(odd["value"]["count"], odd["n"]),
    }


def verdict(now: float | None, base: float, n: int) -> str:
    if now is not None and abs(now - base) <= TOLERANCE:
        return "near"
    if abs(n - BASELINE_ROWS) > TOLERANCE * BASELINE_ROWS:
        return "data moved"
    return "check suspect"


def summary(rows: list[dict]) -> str:
    by = {r["check"]: r for r in rows}
    now, n = measures(by), by["unknown_codes"]["n"]
    table = [f"| {m} | {pct(now[m])} | {pct(base)} | {verdict(now[m], base, n)} |" for m, base in BASELINE.items()]
    head = ["", "| measure | today | baseline | verdict |", "|---|---|---|---|"]
    return "\n".join([f"# Label sanity {rows[0]['date']}", "", *map(check_line, rows), *head, *table, ""])


def write(rows: list[dict], out_dir: Path = Path("results")) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "label_sanity.jsonl"
    old = path.read_text().splitlines() if path.exists() else []
    kept = [entry for entry in old if json.loads(entry)["date"] != rows[0]["date"]]
    path.write_text("".join(f"{entry}\n" for entry in [*kept, *map(json.dumps, rows)]))
    (out_dir / "label_sanity.md").write_text(summary(rows))


def load(day: str, snapshots: Path = SNAPSHOTS) -> dict:
    with gzip.open(snapshots / f"{day}.json.gz") as f:
        return json.load(f)


if __name__ == "__main__":
    write(run(load(date.today().isoformat())))
