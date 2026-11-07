from datetime import date

from alert_monitor import ingest, record


def records(config: dict, at: str, fetch=ingest.fetch_field):
    for row in ingest.snapshot(date.fromisoformat(at[:10]), config, fetch)["rows"]:
        yield record.from_fink(row, at)
