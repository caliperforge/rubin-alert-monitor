# rubin-alert-monitor

The Rubin Observatory telescope sends out an alert each time something in the sky changes brightness or moves. Fink, an alert broker, receives these alerts, labels each object with a guess at what it is, and serves the results to the public. Once a day, this repository downloads what Fink serves for four patches of sky and checks whether its labels make sense. Each day's data is committed here under its date, with the results beside it. This builds a dated, public record of how good the alerts are, which can be taken to Fink as evidence.

To rerun it, use the commands under [Running](#running), or run the daily workflow by hand.

## Source

The download uses Fink's Rubin conesearch, which returns every object within a given radius of a point in the sky: `POST https://api.lsst.fink-portal.org/api/v1/conesearch` with a JSON body, `kind: across` and `output-format: json`.

## ALeRCE source

`alert_monitor/sources/alerce.py` uses the `alerce` client: `Alerce().query_objects(survey="lsst", format="json", ra, dec, radius, page_size, page, order_by="lastmjd", order_mode="ASC", lastmjd)`, with `radius` and `page_size` set from `radius` and `n` in `alert_monitor/fields.json`. It sends `GET https://api-lsst.alerce.online/object_api/list_objects`. For each field it asks for `page` 1, 2, … and stops after the first page with fewer than `n` rows, or after page 50 (5,000 rows per field at `n` = 100).

Each field's `lastmjd` is `[<that field's lastmjd in the newest earlier header>, <now, MJD TAI>]`, so a daily run fetches only objects last detected since the previous run, oldest first. The LSST endpoint accepts `lastmjd` (alerce_client@12f613a95340499dab89af5c5bf5416e3e1deb29 `alerce/ms_search.py:39`). When no earlier header has a `lastmjd` for the field, it is left out and the field's whole cone is fetched up to the cap. `--backfill` leaves it out too and pages each whole cone until a short page, with no cap.

ALeRCE's classes come from `Alerce().query_classes("stamp_classifier_rubin_beta", "2.0.1", survey="lsst")`, which sends `GET https://api-lsst.alerce.online/classifier_api/classes` (alerce_client@12f613a95340499dab89af5c5bf5416e3e1deb29 `alerce/default_config.json`). `alert_monitor/labels_map.json` maps them as `SN` → `sn`, `asteroid` → `moving`, `nuclear` → `nuclear`, `off-nuclear` → `unknown`, `bogus` → `unknown`, `VS` → `variable` and `AGN` → `agn`. Off-nuclear transients are mostly supernovae, but a label that only gives a location is not promoted to a class.

## Lasair source

`alert_monitor/sources/lasair.py` sends `POST https://api.lasair.lsst.ac.uk/api/query/` for each field, with a urlencoded body: `selected` = `diaObjectId,ra,decl,nDiaSources,firstDiaSourceMjdTai,lastDiaSourceMjdTai`, `tables` = `objects`, `limit` = `n`, and `conditions` = `decl BETWEEN dec±r AND ra BETWEEN ra±r/cos(dec) AND lastDiaSourceMjdTai > <now, MJD TAI> - 1`, where `r` is `radius` in degrees. It then sends `POST https://api.lasair.lsst.ac.uk/api/sherlock/object/` with `objectIds` (10 ids per call, in query order) and `lite=true`, and takes each object's Sherlock class as its label. The request and response shapes are the ones issue #7 documents. They have not yet been checked against the ZTF host, `https://lasair-ztf.lsst.ac.uk/api/`.

Every call needs a token. The token is read only from the `LASAIR_LSST_TOKEN` environment variable, which the daily workflow sets from the repository secret of the same name. A daily run makes `fields × (1 + n/10)` = 44 calls, under the token's limit of 100 calls per hour, and any config that would make 90 or more calls is refused. The header entry gains `"skipped": "no token"` when the variable is empty or unset, or `"skipped": "host unreachable"` when the host's TLS certificate fails verification. Verification is never turned off.

## Fields

A field is one patch of sky: a centre given as right ascension (`ra`) and declination (`dec`), in degrees. The fields are set in `alert_monitor/fields.json`, and each is searched within a radius of 3600 arcseconds, keeping at most 100 objects (`n`):

| ra | dec |
|---|---|
| 150.66 | 0.85 |
| 61.96 | -48.71 |
| 9.45 | -44.0 |
| 53.1 | -28.1 |

## Columns

Columns starting `r:` come from Rubin's alert. Columns starting `f:` are added by Fink. The columns are set in `alert_monitor/fields.json`: `r:diaObjectId`, `r:ra`, `r:dec`, `r:nDiaSources`, `r:midpointMjdTai`, `f:firstDiaSourceMjdTaiFink`, `f:clf_cats_class`, `f:clf_cats_score`, `f:main_label_classifier`, `f:main_label_crossmatch`, `f:xm_tns_type`, `f:is_sso`. Times are given as MJD (Modified Julian Date, a running count of days used in astronomy) on the TAI clock (International Atomic Time): `r:midpointMjdTai` is when Rubin last detected the object, and `f:firstDiaSourceMjdTaiFink` is when Fink first saw it detected. `f:main_label_classifier` is Fink's summary label for the object, and `f:is_sso` says whether it is a known Solar System object, such as an asteroid. The checks do not use these two.

`r:diaObjectId` is Rubin's ID for an object, and `r:nDiaSources` is how many times Rubin has detected it. `f:clf_cats_class` is the label from Fink's classifier, and `f:clf_cats_score` is the classifier's confidence in that label. `f:main_label_crossmatch` is the object's type in SIMBAD, a catalogue of known astronomical objects. `f:xm_tns_type` is the object's type in TNS, the Transient Name Server. TNS is the official register of reported transients, which are objects that appear or change for a short time, such as supernovae.

## Snapshot

Written as compact gzipped JSON to `data/snapshots/<YYYY-MM-DD>.json.gz` and committed, and refused when over 50 MB gzipped:

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

`.github/workflows/daily.yml` runs the snapshot, `ingest_all` and the label checks at 11:00 UTC daily, and on manual dispatch, then commits `data/snapshots/<YYYY-MM-DD>.json.gz`, `data/objects`, `results/label_sanity.jsonl` and `results/label_sanity.md` to main. When no field returns rows, or the gzipped snapshot is over 50 MB, the job fails and commits nothing.

## Combined run

`uv run python -m alert_monitor.ingest_all` fetches Fink, ALeRCE and Lasair, merges their records, validates each against the sky-schema object schema, and writes `data/objects/<YYYY-MM-DD>.jsonl.gz`, one record per line, and `data/objects/<YYYY-MM-DD>.header.json`:

```
{"date": "<YYYY-MM-DD>", "brokers": {"fink" | "alerce" | "lasair": {"rows", "errors", "calls", "unmapped", "newest", "new_ids", "stale", "pages"?, "truncated"?, "lastmjd"?, "skipped"?}}}
```

`rows` is the broker's record count, `errors` lists each failure as `"<ExceptionName>: <message>"`, `calls` counts fetches including retries, and `unmapped` counts raw labels missing from `alert_monitor/labels_map.json`. `newest` is the latest `t_last` among the broker's records, or `null` when it returned none. `new_ids` counts its ids missing from the newest earlier `<YYYY-MM-DD>.jsonl.gz`. `stale` is true when `newest` is no later than the previous header's `newest` for that broker. The ALeRCE entry adds `pages`, the pages fetched for each `"<ra>,<dec>"` field, `truncated`, true when a field stopped at the 50-page cap, and `lastmjd`, kept per field: the newest last-detection MJD it returned for each `"<ra>,<dec>"` field, never lower than the previous header's. When ALeRCE records an error, each field's `lastmjd` keeps the previous header's value. A failing broker contributes no rows. When no broker returns rows, or a record fails the schema, the run fails and writes nothing.

After writing, the run prints `<YYYY-MM-DD>: fink <new_ids> new, alerce <new_ids> new, lasair <new_ids> new`, followed by `; stale 3 days: <brokers>` naming each broker stale today and in the two previous headers while another broker's `newest` moved. A stale day alone may mean Rubin did not visit the four fields that night. A broker stale 3 days while another moves is the sign of a stopped feed.

## Running

- `uv run pytest` runs the offline tests.
- `uv run pytest -m live` calls Fink and writes today's snapshot, calls ALeRCE for the second field, and calls Lasair for the first field.
- `uv run python -m alert_monitor.ingest` writes today's snapshot.
- `uv run python -m alert_monitor.ingest_all` writes today's merged objects and header.
- `uv run python -m alert_monitor.ingest_all --backfill` does the same, fetching each whole ALeRCE cone without the page cap.
- `uv run python -m alert_monitor.checks.labels` runs the label checks on today's snapshot.
- `gh workflow run daily.yml`, or **Run workflow** on the Actions tab, runs the daily job by hand.
