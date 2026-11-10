import json
import os
import ssl
from math import ceil, cos, radians
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from astropy.time import Time

from alert_monitor import ingest, record

HOST = "https://api.lasair.lsst.ac.uk/api/"
SELECTED = "diaObjectId,ra,decl,nDiaSources,firstDiaSourceMjdTai,lastDiaSourceMjdTai"


class Skipped(Exception):
    pass


def fetch(endpoint: str, params: dict, token: str):
    req = Request(HOST + endpoint, data=urlencode(params).encode(), headers={"Authorization": f"Token {token}"}, method="POST")
    try:
        with urlopen(req, timeout=ingest.TIMEOUT) as resp:
            return json.load(resp)
    except URLError as exc:
        if isinstance(exc.reason, ssl.SSLCertVerificationError):
            raise Skipped("host unreachable") from exc
        raise


def budget(config: dict) -> int:
    return len(config["fields"]) * (1 + ceil(config["n"] / 10))


def records(config: dict, at: str, fetch=fetch):
    if (calls := budget(config)) >= 90:
        raise ValueError(f"budget is {calls} calls, refused at 90 or more")
    token = os.environ.get("LASAIR_LSST_TOKEN")
    if not token:
        raise Skipped("no token")
    r = config["radius"] / 3600
    since = Time(at[:19], format="isot", scale="utc").tai.mjd - 1  # pyright: ignore[reportAttributeAccessIssue]
    for field in config["fields"]:
        ra, dec, dra = field["ra"], field["dec"], r / cos(radians(field["dec"]))
        conditions = (
            f"decl BETWEEN {dec - r} AND {dec + r} AND ra BETWEEN {ra - dra} AND {ra + dra}"
            f" AND lastDiaSourceMjdTai > {since}"
        )
        query = {"selected": SELECTED, "tables": "objects", "conditions": conditions, "limit": config["n"]}
        rows = fetch("query/", query, token)
        if not isinstance(rows, list):
            raise ValueError(f"expected a JSON list, got {type(rows).__name__}")  # noqa: TRY004
        for i in range(0, len(rows), 10):
            batch = rows[i : i + 10]
            ids = [str(row["diaObjectId"]) for row in batch]
            classes = fetch("sherlock/object/", {"objectIds": ",".join(ids), "lite": "true"}, token)
            for oid, row in zip(ids, batch, strict=True):
                yield record.from_lasair({**row, "classification": classes[oid]["classifications"][oid][0]}, at)
