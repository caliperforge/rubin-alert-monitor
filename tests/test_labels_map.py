import pytest
from alerce.core import Alerce

from alert_monitor import labels

PARENT = {
    "fink": {"11": "sn", "12": "unknown", "13": "unknown", "21": "variable", "22": "agn", "-1": "unknown", "is_sso": "moving"},
    "alerce": {"SN": "sn", "asteroid": "moving", "nuclear": "nuclear", "off-nuclear": "unknown", "bogus": "unknown", "VS": "variable", "AGN": "agn"},
    "lasair": {
        "SN": "sn", "Possible Supernova": "sn", "NT": "nuclear", "Nuclear Transient": "nuclear", "AGN": "agn",
        "Active Galaxy": "agn", "VS": "variable", "CV": "variable", "BS": "variable", "ORPHAN": "unknown", "UNCLEAR": "unknown",
    },
}


def test_table_is_parent_table():
    assert labels.TABLE == PARENT


def test_normalise_every_parent_entry():
    for broker, table in PARENT.items():
        for raw, label in table.items():
            assert labels.normalise(broker, raw) == label


def test_normalise_unmapped_is_unknown():
    assert labels.normalise("fink", "31") == "unknown"
    assert labels.normalise("alerce", "Periodic-Other") == "unknown"


def test_unmapped_counts_only_missing_raw():
    records = [{"labels": [{"broker": "fink", "raw": "31"}]}, {"labels": [{"broker": "fink", "raw": "-1"}]}]
    assert labels.unmapped(records) == {"fink": {"31": 1}}


@pytest.mark.live
def test_every_alerce_lsst_class_is_mapped():
    result = Alerce().query_classes("stamp_classifier_rubin_beta", "2.0.1", survey="lsst")
    assert {c["name"] for c in result} <= set(labels.TABLE["alerce"])
