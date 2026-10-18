# rubin-alert-monitor
A daily public check of Rubin alert data as served by the brokers: impossible values, schema drift, label sanity, and agreement with confirmed transients

## Source

Fink's Rubin conesearch: `POST https://api.lsst.fink-portal.org/api/v1/conesearch` with a JSON body, `kind: across` and `output-format: json`.

## Fields

Set in `alert_monitor/fields.json`, each searched with radius 3600 arcsec and `n` 100:

| ra | dec |
|---|---|
| 150.66 | 0.85 |
| 61.96 | -48.71 |
| 9.45 | -44.0 |
| 53.1 | -28.1 |

## Columns

Set in `alert_monitor/fields.json`: `r:diaObjectId`, `r:nDiaSources`, `r:midpointMjdTai`, `f:firstDiaSourceMjdTaiFink`, `f:clf_cats_class`, `f:clf_cats_score`, `f:main_label_classifier`, `f:main_label_crossmatch`, `f:xm_tns_type`, `f:is_sso`.

## Snapshot

Written to `data/snapshots/<YYYY-MM-DD>.json` (gitignored):

```
{"header": {"date": "<YYYY-MM-DD>", "fields": [{"ra", "dec", "rows" | "error"}]}, "rows": [...]}
```

Each field entry carries `rows`, the count Fink returned, or `error`, as `"<ExceptionName>: <message>"`. The top-level `rows` holds one row per `r:diaObjectId` across all fields.

## Label checks

`alert_monitor/checks/labels.py` reads today's snapshot and writes one row per check to `results/label_sanity.jsonl` and a summary to `results/label_sanity.md`. The label is Fink's `f:clf_cats_class`; a row is classified when its code is 11, 12, 13, 21 or 22.

- `sn_share`: share of classified rows labelled supernova-like (11), overall, by detections and by days watched.
- `score_median`: median `f:clf_cats_score` per code and detection bucket.
- `sn_long_lived`: supernova-like rows watched 100+ and 200+ days.
- `sn_star_match`: supernova-like rows SIMBAD matches to a star, QSO, AGN or white dwarf. Galaxies do not count.
- `unknown_codes`: rows whose code is outside Fink's mapping.
- `crossmatch_fail`: share of rows whose SIMBAD lookup returned `"Fail"`.
- `tns_agreement`: agreement between the label and the TNS type on TNS-matched rows, with no percentage below 30 mapped rows.
- `tns_direct`: whether TNS bot credentials are set. TNS is not queried.

The summary compares each share with the 2026-10-18 measurement. The labels are Fink's and are not corrected here: a gap is evidence, not a verdict.

## Running

- `uv run pytest` runs the offline tests.
- `uv run pytest -m live` calls Fink and writes today's snapshot.
- `uv run python -m alert_monitor.checks.labels` runs the label checks on today's snapshot.
