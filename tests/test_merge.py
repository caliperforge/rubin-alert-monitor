import pytest
from jsonschema import ValidationError

from alert_monitor import record
from alert_monitor.merge import merge

AT = "2026-10-18T06:00:00Z"
RA, DEC = 150.6612, 0.8503
FINK = {
    "r:diaObjectId": 1, "r:ra": RA, "r:dec": DEC, "r:nDiaSources": 3, "r:midpointMjdTai": 61330.0,
    "f:firstDiaSourceMjdTaiFink": 61320.0, "f:main_label_classifier": 11, "f:clf_cats_score": 0.875, "f:is_sso": False,
}


def alerce(cls, arcsec=1.0, first=61320.0, last=61330.0, ndet=3):
    row = {
        "oid": "ZTF26abcdxyz", "meanra": RA, "meandec": DEC + arcsec / 3600, "firstmjd": first, "lastmjd": last,
        "n_det": ndet, "class_name": cls, "probability": 0.9,
    }
    return record.from_alerce(row, AT)


def lasair(arcsec):
    row = {
        "diaObjectId": 170028, "ra": RA, "decl": DEC + arcsec / 3600, "firstDiaSourceMjdTai": 61320.0,
        "lastDiaSourceMjdTai": 61330.0, "nDiaSources": 3, "classification": "NT",
    }
    return record.from_lasair(row, AT)


def test_one_arcsec_merges_five_does_not():
    fink = record.from_fink(FINK, AT)
    one, other = merge([fink, alerce("SN"), lasair(5.0)])
    assert (one["id"], one["source"], one["ra"], one["dec"]) == ("1", "fink", RA, DEC)
    assert [label["broker"] for label in one["labels"]] == ["fink", "alerce"]
    assert (other["source"], other["labels"]) == ("lasair", lasair(5.0)["labels"])


def test_same_broker_rows_never_fold_together():
    one, other = merge([record.from_fink(FINK, AT), alerce("SN", 1.0), alerce("asteroid", 0.5)])
    assert [label["broker"] for label in one["labels"]] == ["fink", "alerce"]
    assert [label["broker"] for label in other["labels"]] == ["alerce"]


def test_contested():
    fink = record.from_fink(FINK, AT)
    assert merge([fink, alerce("asteroid")])[0]["contested"] is True
    assert merge([fink, alerce("SN")])[0]["contested"] is False
    assert merge([fink])[0]["contested"] is False


def test_days_watched_spans_both_records():
    (one,) = merge([record.from_fink(FINK, AT), alerce("SN", first=61310.0, last=61325.0, ndet=9)])
    assert (one["t_first"], one["t_last"]) == ("2026-09-26T23:59:23.000Z", "2026-10-16T23:59:23.000Z")
    assert (one["n_obs"], one["days_watched"]) == (9, 20.0)


def test_merged_records_validate_and_aliases_do_not(valid):
    merged = merge([record.from_fink(FINK, AT), alerce("asteroid"), lasair(5.0)])
    for r in merged:
        valid(r)
    with pytest.raises(ValidationError):
        valid({**merged[0], "aliases": [{"broker": "alerce", "id": "ZTF26abcdxyz"}]})
