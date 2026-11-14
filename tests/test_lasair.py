import json
import ssl
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.error import URLError

import pytest
from astropy.time import Time

from alert_monitor import ingest, ingest_all
from alert_monitor.sources import alerce, lasair

ROOT = Path(__file__).parents[1]
QUERY = json.loads((ROOT / "tests" / "fixtures" / "lasair_query.json").read_text())
SHERLOCK = json.loads((ROOT / "tests" / "fixtures" / "lasair_sherlock.json").read_text())
ALERCE = json.loads((ROOT / "tests" / "fixtures" / "alerce_field.json").read_text())
CONFIG = ingest.load_config()
FIELD0 = {**CONFIG, "fields": CONFIG["fields"][:1]}
AT = "2026-11-07T06:00:00Z"
IDS = [str(row["diaObjectId"]) for row in QUERY]
NO_ROWS = {"newest": None, "new_ids": 0, "stale": False, "behind_days": None, "behind": False}


@pytest.fixture
def token(monkeypatch):
    monkeypatch.setenv("LASAIR_LSST_TOKEN", "test-token")


def replay(calls):
    def fetch(endpoint, params, token):
        calls.append((endpoint, params))
        return QUERY if endpoint == "query/" else {i: SHERLOCK[i] for i in params["objectIds"].split(",")}

    return fetch


def run(tmp_path, fetch):
    out = tmp_path / "objects"
    sources = {"alerce": (alerce.records, lambda field, config: ALERCE), "lasair": (lasair.records, fetch)}
    ingest_all.run(FIELD0, AT, out, sources)
    return json.loads((out / "2026-11-07.header.json").read_text())["brokers"]


def test_replay_yields_sherlock_classes_in_query_order(token, valid):
    got = list(lasair.records(FIELD0, AT, fetch=replay([])))
    assert [(r["id"], r["labels"][0]["raw"]) for r in got] == [(i, SHERLOCK[i]["classifications"][i][0]) for i in IDS]
    assert len({r["labels"][0]["raw"] for r in got}) >= 2
    for r in got:
        valid(r)


def test_sherlock_batches_of_ten_in_query_order(token):
    calls = []
    list(lasair.records({**CONFIG, "fields": [{"ra": 10.0, "dec": 0.0}]}, AT, fetch=replay(calls)))
    since = Time("2026-11-07T06:00:00", format="isot", scale="utc").tai.mjd - 1  # pyright: ignore[reportAttributeAccessIssue]
    conditions = f"decl BETWEEN -1.0 AND 1.0 AND ra BETWEEN 9.0 AND 11.0 AND lastDiaSourceMjdTai > {since}"
    assert calls[0] == ("query/", {"selected": lasair.SELECTED, "tables": "objects", "conditions": conditions, "limit": 100})
    assert [p["objectIds"].split(",") for _, p in calls[1:]] == [IDS[:10], IDS[10:20], IDS[20:]]
    assert {p["lite"] for _, p in calls[1:]} == {"true"}


def test_budget_refused_before_any_call(token):
    calls = []
    assert lasair.budget(CONFIG) == 44
    with pytest.raises(ValueError, match="budget is 404 calls"):
        list(lasair.records({**CONFIG, "n": 1000}, AT, fetch=replay(calls)))
    assert calls == []


@pytest.mark.parametrize("value", [None, ""])
def test_no_token_skips_before_any_call(monkeypatch, tmp_path, value):
    monkeypatch.delenv("LASAIR_LSST_TOKEN", raising=False)
    if value is not None:
        monkeypatch.setenv("LASAIR_LSST_TOKEN", value)
    calls = []
    with pytest.raises(lasair.Skipped, match="no token"):
        list(lasair.records(FIELD0, AT, fetch=replay(calls)))
    assert run(tmp_path, replay(calls))["lasair"] == {"rows": 0, "errors": [], "calls": 0, "unmapped": {}, "skipped": "no token", **NO_ROWS}
    assert calls == []


@pytest.mark.parametrize(
    ("reason", "entry"),
    [
        (ssl.SSLCertVerificationError(), {"rows": 0, "errors": [], "calls": 1, "unmapped": {}, "skipped": "host unreachable", **NO_ROWS}),
        ("refused", {"rows": 0, "errors": ["URLError: <urlopen error refused>"], "calls": 1, "unmapped": {}, **NO_ROWS}),
    ],
)
def test_host_failure_recorded_other_brokers_write(monkeypatch, tmp_path, token, reason, entry):
    seen = []

    def urlopen(req, timeout):
        seen.append((req.full_url, req.get_header("Authorization"), timeout))
        raise URLError(reason)

    monkeypatch.setattr(lasair, "urlopen", urlopen)
    brokers = run(tmp_path, lasair.fetch)
    assert brokers["lasair"] == entry
    assert brokers["alerce"]["rows"] == len(ALERCE)
    assert seen == [("https://api.lasair.lsst.ac.uk/api/query/", "Token test-token", ingest.TIMEOUT)]


@pytest.mark.live
def test_live_query_and_sherlock(valid):
    calls = []

    def fetch(endpoint, params, token):
        calls.append(endpoint)
        return lasair.fetch(endpoint, params, token)

    yesterday = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        got = list(lasair.records({**FIELD0, "n": 10}, yesterday, fetch=fetch))
    except lasair.Skipped as exc:
        pytest.skip(str(exc))
    assert calls == ["query/", "sherlock/object/"]
    for r in got:
        valid(r)
