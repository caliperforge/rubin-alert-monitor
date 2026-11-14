from itertools import count

from alerce.core import Alerce
from astropy.time import Time

from alert_monitor import record

PAGES = 50


def fetch_field(field: dict, config: dict) -> list[dict]:
    client, rows, backfill = Alerce(), [], config.get("backfill")
    window = {"lastmjd": config["lastmjd"]} if "lastmjd" in config else {}
    for page in count(1) if backfill else range(1, PAGES + 1):
        got = client.query_objects(
            survey="lsst",
            format="json",
            ra=field["ra"],
            dec=field["dec"],
            radius=config["radius"],
            page_size=config["n"],
            page=page,
            order_by="lastmjd",
            order_mode="ASC" if backfill else "DESC",
            **window,
        )
        if not isinstance(got, list):
            raise ValueError(f"expected a JSON list, got {type(got).__name__}")  # noqa: TRY004
        rows += got
        if len(got) < config["n"] or (window and not backfill and got[-1]["lastmjd"] <= window["lastmjd"][0]):
            break
    return rows


def _pages(rows: list[dict], n: int, start: float | None) -> int:
    reached = start is not None and bool(rows) and len(rows) % n == 0 and rows[-1]["lastmjd"] <= start
    return len(rows) // n + (not reached)


def paging(results: list[list[dict]], config: dict, failed: bool) -> dict:
    n, backfill, since = config["n"], config.get("backfill"), config["since"] or {}
    keys = [f"{f['ra']},{f['dec']}" for f in config["fields"]]
    sizes = [len(rows) for rows in results]
    lastmjd, gap = {k: since.get(k) for k in keys}, {}
    if not failed:
        for k, rows in zip(keys, results, strict=True):
            mjds = [row["lastmjd"] for row in rows]
            if not backfill and len(rows) == PAGES * n and since.get(k) is not None and min(mjds) > since[k]:
                gap[k] = [since[k], min(mjds)]
            else:
                lastmjd[k] = max((m for m in [lastmjd[k], *mjds] if m is not None), default=None)
    return {
        "pages": {
            k: _pages(rows, n, None) if backfill else min(_pages(rows, n, since.get(k)), PAGES)
            for k, rows in zip(keys, results, strict=False)
        },
        "truncated": not backfill and PAGES * n in sizes,
        "lastmjd": lastmjd,
        **({"gap": gap} if gap else {}),
    }


def records(config: dict, at: str, fetch=fetch_field):
    now = Time(at[:19], format="isot", scale="utc").tai.mjd  # pyright: ignore[reportAttributeAccessIssue]
    since, gap = config.get("since") or {}, config.get("gap") or {}
    for field in config["fields"]:
        key = f"{field['ra']},{field['dec']}"
        if config.get("backfill") and key in gap:
            window = {"lastmjd": gap[key]}
        else:
            window = {} if since.get(key) is None else {"lastmjd": [since[key], now]}
        for row in fetch(field, {**config, **window}):
            yield record.from_alerce(row, at)
