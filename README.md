# rubin-alert-monitor

The Rubin Observatory telescope sends out an alert each time something in the sky changes brightness or moves. Fink, an alert broker, receives these alerts, labels each object with a guess at what it is, and serves the results to the public. Once a day, this repository downloads what Fink serves for four patches of sky and checks whether its labels make sense. Each day's data is committed here under its date, with the results beside it. This builds a dated, public record of how good the alerts are, which can be taken to Fink as evidence.

To rerun it, use the commands under [Running](#running), or run the daily workflow by hand.

## Source

The download uses Fink's Rubin conesearch, which returns every object within a given radius of a point in the sky: `POST https://api.lsst.fink-portal.org/api/v1/conesearch` with a JSON body, `kind: across` and `output-format: json`.

## Fields

A field is one patch of sky: a centre given as right ascension (`ra`) and declination (`dec`), in degrees. The fields are set in `alert_monitor/fields.json`, and each is searched within a radius of 3600 arcseconds, keeping at most 100 objects (`n`):

| ra | dec |
|---|---|
| 150.66 | 0.85 |
| 61.96 | -48.71 |
| 9.45 | -44.0 |
| 53.1 | -28.1 |

## Columns

Columns starting `r:` come from Rubin's alert. Columns starting `f:` are added by Fink. The columns are set in `alert_monitor/fields.json`: `r:diaObjectId`, `r:nDiaSources`, `r:midpointMjdTai`, `f:firstDiaSourceMjdTaiFink`, `f:clf_cats_class`, `f:clf_cats_score`, `f:main_label_classifier`, `f:main_label_crossmatch`, `f:xm_tns_type`, `f:is_sso`. Times are given as MJD (Modified Julian Date, a running count of days used in astronomy) on the TAI clock (International Atomic Time): `r:midpointMjdTai` is when Rubin last detected the object, and `f:firstDiaSourceMjdTaiFink` is when Fink first saw it detected. `f:main_label_classifier` is Fink's summary label for the object, and `f:is_sso` says whether it is a known Solar System object, such as an asteroid. The checks do not use these two.

`r:diaObjectId` is Rubin's ID for an object, and `r:nDiaSources` is how many times Rubin has detected it. `f:clf_cats_class` is the label from Fink's classifier, and `f:clf_cats_score` is the classifier's confidence in that label. `f:main_label_crossmatch` is the object's type in SIMBAD, a catalogue of known astronomical objects. `f:xm_tns_type` is the object's type in TNS, the Transient Name Server. TNS is the official register of reported transients, which are objects that appear or change for a short time, such as supernovae.

## Snapshot

Written to `data/snapshots/<YYYY-MM-DD>.json` and committed:

```
{"header": {"date": "<YYYY-MM-DD>", "fields": [{"ra", "dec", "rows" | "error"}]}, "rows": [...]}
```

Each field entry carries `rows`, the count Fink returned, or `error`, as `"<ExceptionName>: <message>"`. The top-level `rows` holds one row per `r:diaObjectId` across all fields.

## Label checks

`alert_monitor/checks/labels.py` reads today's snapshot and writes one row per check to `results/label_sanity.jsonl` and a summary to `results/label_sanity.md`. The label is Fink's `f:clf_cats_class`. A row is classified when its code is one of these: 11 supernova-like (an exploding star), 12 fast transient (rises and fades within days), 13 long transient (stays bright for months or longer), 21 periodic (brightness repeats on a regular cycle, as in a pulsating star), 22 non-periodic (brightness varies with no regular cycle, as in an active galactic nucleus, or AGN: the bright centre of a galaxy, lit by gas falling into its central black hole).

- `sn_share`: the share of classified rows labelled supernova-like (11), overall, by number of detections, and by days watched. Days watched counts from Fink's first detection to the latest one.
- `score_median`: the median `f:clf_cats_score` for each code within each detection bucket. A detection bucket groups rows by how many times Rubin has detected them.
- `sn_long_lived`: supernova-like rows watched 100+ and 200+ days. A supernova fades within months, so rows watched this long are suspect.
- `sn_star_match`: supernova-like rows that SIMBAD matches to a star, a white dwarf (the dense core a dead star leaves behind), a quasar (QSO, the brightest kind of AGN) or another AGN, none of which can host a supernova. Galaxies do not count.
- `unknown_codes`: rows whose code is outside Fink's mapping.
- `crossmatch_fail`: the share of rows whose SIMBAD lookup returned `"Fail"`.
- `tns_agreement`: agreement between the label and the TNS type, on rows whose TNS type maps to a code. No percentage is given below 30 mapped rows.
- `tns_direct`: whether TNS bot credentials are set. TNS is not queried.

The table at the end of `results/label_sanity.md` compares each of today's shares with the 2026-10-18 measurement. Each row gets a verdict: `near` (close to that measurement), `data moved` (today's row count is far from that day's), or `check suspect` (anything else). The labels are Fink's and are not corrected here. A gap is evidence, not a verdict.

## Daily run

`.github/workflows/daily.yml` runs the snapshot and the label checks at 11:00 UTC daily, and on manual dispatch, then commits `data/snapshots/<YYYY-MM-DD>.json`, `results/label_sanity.jsonl` and `results/label_sanity.md` to main. When no field returns rows, the job fails and commits nothing.

## Running

- `uv run pytest` runs the offline tests.
- `uv run pytest -m live` calls Fink and writes today's snapshot.
- `uv run python -m alert_monitor.ingest` writes today's snapshot.
- `uv run python -m alert_monitor.checks.labels` runs the label checks on today's snapshot.
- `gh workflow run daily.yml`, or **Run workflow** on the Actions tab, runs the daily job by hand.
