from datetime import datetime

import astropy.units as u
from astropy.coordinates import SkyCoord

MATCH = 2 * u.arcsec


def _coords(records: list[dict]) -> SkyCoord:
    return SkyCoord(ra=[r["ra"] for r in records], dec=[r["dec"] for r in records], unit="deg")


def _fold(into: dict, record: dict) -> None:
    into["labels"] = into["labels"] + record["labels"]
    into["t_first"] = min(into["t_first"], record["t_first"])
    into["t_last"] = max(into["t_last"], record["t_last"])
    into["n_obs"] = max(into["n_obs"], record["n_obs"])
    span = datetime.fromisoformat(into["t_last"]) - datetime.fromisoformat(into["t_first"])
    into["days_watched"] = span.total_seconds() / 86400


def merge(records: list[dict]) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for record in records:
        groups.setdefault(record["source"], []).append(dict(record))
    merged: list[dict] = []
    for group in groups.values():
        if not merged:
            merged = group
            continue
        idx, sep2d, _ = _coords(group).match_to_catalog_sky(_coords(merged))
        taken: set[int] = set()
        for record, i, sep in zip(group, idx, sep2d):
            if sep < MATCH and i not in taken:
                taken.add(i)
                _fold(merged[i], record)
            else:
                merged.append(record)
    return [{**r, "contested": len({label["label"] for label in r["labels"]}) > 1} for r in merged]
