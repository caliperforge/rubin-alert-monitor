from astropy.time import Time

from alert_monitor.labels import TABLE, normalise


def iso(mjd: float) -> str:
    return Time(mjd, format="mjd", scale="tai").utc.isot + "Z"  # pyright: ignore[reportAttributeAccessIssue]


def _far(source: str, id, ra: float, dec: float, first: float, last: float, n_obs: int, label: dict) -> dict:
    return {
        "schema_version": 0,
        "id": str(id),
        "lane": "far",
        "source": source,
        "ra": ra,
        "dec": dec,
        "t_first": iso(first),
        "t_last": iso(last),
        "n_obs": n_obs,
        "days_watched": last - first,
        "labels": [{"broker": source, **label}],
    }


def from_fink(row: dict, at: str) -> dict:
    raw = str(row["f:main_label_classifier"])
    label = TABLE["fink"]["is_sso"] if row["f:is_sso"] else normalise("fink", raw)
    last = row["r:midpointMjdTai"]
    first = last if row["f:firstDiaSourceMjdTaiFink"] is None else row["f:firstDiaSourceMjdTaiFink"]
    return _far(
        "fink", row["r:diaObjectId"], row["r:ra"], row["r:dec"], first, last, row["r:nDiaSources"],
        {"label": label, "raw": raw, "score": row["f:clf_cats_score"], "at": at},
    )


def from_alerce(row: dict, at: str) -> dict:
    return _far(
        "alerce", row["oid"], row["meanra"], row["meandec"], row["firstmjd"], row["lastmjd"], row["n_det"],
        {"label": normalise("alerce", row["class_name"]), "raw": row["class_name"], "score": row["probability"], "at": at},
    )


def from_lasair(row: dict, at: str) -> dict:
    return _far(
        "lasair", row["diaObjectId"], row["ra"], row["decl"], row["firstDiaSourceMjdTai"], row["lastDiaSourceMjdTai"],
        row["nDiaSources"],
        {"label": normalise("lasair", row["classification"]), "raw": row["classification"], "score": None, "at": at},
    )
