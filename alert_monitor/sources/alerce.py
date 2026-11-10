from itertools import count

from alerce.core import Alerce
from astropy.time import Time

from alert_monitor import record

PAGES = 50


def fetch_field(field: dict, config: dict) -> list[dict]:
    client, rows = Alerce(), []
    window = {"lastmjd": config["lastmjd"]} if "lastmjd" in config else {}
    for page in count(1) if config.get("backfill") else range(1, PAGES + 1):
        got = client.query_objects(
            survey="lsst",
            format="json",
            ra=field["ra"],
            dec=field["dec"],
            radius=config["radius"],
            page_size=config["n"],
            page=page,
            order_by="lastmjd",
            order_mode="ASC",
            **window,
        )
        if not isinstance(got, list):
            raise ValueError(f"expected a JSON list, got {type(got).__name__}")  # noqa: TRY004
        rows += got
        if len(got) < config["n"]:
            break
    return rows


def paging(results: list[list[dict]], config: dict, failed: bool) -> dict:
    n, backfill, since = config["n"], config.get("backfill"), config["since"] or {}
    keys = [f"{f['ra']},{f['dec']}" for f in config["fields"]]
    sizes = [len(rows) for rows in results]
    lastmjd = {k: since.get(k) for k in keys}
    if not failed:
        for k, rows in zip(keys, results, strict=True):
            seen = [lastmjd[k], *(row["lastmjd"] for row in rows)]
            lastmjd[k] = max((m for m in seen if m is not None), default=None)
    return {
        "pages": {k: s // n + 1 if backfill else min(s // n + 1, PAGES) for k, s in zip(keys, sizes, strict=False)},
        "truncated": not backfill and PAGES * n in sizes,
        "lastmjd": lastmjd,
    }


def records(config: dict, at: str, fetch=fetch_field):
    now = Time(at[:19], format="isot", scale="utc").tai.mjd  # pyright: ignore[reportAttributeAccessIssue]
    since = config.get("since") or {}
    for field in config["fields"]:
        start = since.get(f"{field['ra']},{field['dec']}")
        window = {} if start is None else {"lastmjd": [start, now]}
        for row in fetch(field, {**config, **window}):
            yield record.from_alerce(row, at)
