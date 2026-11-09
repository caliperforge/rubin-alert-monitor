from alerce.core import Alerce

from alert_monitor import record

PAGES = 50


def fetch_field(field: dict, config: dict) -> list[dict]:
    client, rows = Alerce(), []
    for page in range(1, PAGES + 1):
        got = client.query_objects(
            survey="lsst",
            format="json",
            ra=field["ra"],
            dec=field["dec"],
            radius=config["radius"],
            page_size=config["n"],
            page=page,
        )
        if not isinstance(got, list):
            raise ValueError(f"expected a JSON list, got {type(got).__name__}")  # noqa: TRY004
        rows += got
        if len(got) < config["n"]:
            break
    return rows


def paging(sizes: list[int], config: dict) -> dict:
    n = config["n"]
    return {
        "pages": {
            f"{f['ra']},{f['dec']}": min(s // n + 1, PAGES) for f, s in zip(config["fields"], sizes, strict=False)
        },
        "truncated": PAGES * n in sizes,
    }


def records(config: dict, at: str, fetch=fetch_field):
    for field in config["fields"]:
        for row in fetch(field, config):
            yield record.from_alerce(row, at)
