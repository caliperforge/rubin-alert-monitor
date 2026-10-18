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

## Running

- `uv run pytest` runs the offline tests.
- `uv run pytest -m live` calls Fink and writes today's snapshot.
