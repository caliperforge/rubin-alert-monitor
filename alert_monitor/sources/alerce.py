from alerce.core import Alerce

from alert_monitor import record


def fetch_field(field: dict, config: dict) -> list[dict]:
    rows = Alerce().query_objects(
        survey="lsst", format="json", ra=field["ra"], dec=field["dec"], radius=config["radius"], page_size=config["n"]
    )
    if not isinstance(rows, list):
        raise ValueError(f"expected a JSON list, got {type(rows).__name__}")  # noqa: TRY004
    return rows


def records(config: dict, at: str, fetch=fetch_field):
    for field in config["fields"]:
        for row in fetch(field, config):
            yield record.from_alerce(row, at)
