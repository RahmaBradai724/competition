# Model contract: V2 flood-risk model ↔ PostGIS / application

This file lists what the application must send to the V2 model, what the model sends back,
and how to build each input in PostGIS. Code: `flood_risk/predict.py`.

## 0. What the model is

The service has **two independent parts**:

| Part | File | Question it answers | Status |
|---|---|---|---|
| **Terrain model** | `models/final/v2_terrain.joblib` | *Where* in a zone do roads flood first? It ranks road segments by flood susceptibility from terrain only. | validated (section 6) |
| **Rain trigger** | `models/final/trigger.json` | *When* should that ranking become an alert? It fires when a zone's 24 h rain reaches 44 mm. | **provisional** |

| Terrain rank | Rain trigger | Result for the user |
|---|---|---|
| high | off | no active alert; the road is shown as exposed (`susceptibility`) |
| high | on | **alert**: `level` = Moderate / High / Very high |
| low | on | rain watch for the zone; this road stays Low |

**What it does not do.** Training used flood maps drawn days after each event, which say *whether* a
road flooded, not *when*. The model ranks roads for a rain event. It has **not** been shown to
predict a flood 20 minutes ahead.

**Why terrain only.** Rain variables (NASA IMERG, about 10 km) were rebuilt with only what is known at
each prediction time. Once that was done, they did not improve the ranking of roads inside a zone:
no significant difference on 13 floods, and worse transfer to a country left out of training.
See `pipeline_v2_temporel.ipynb`. Rain still matters, but it works at the zone scale. That is the
trigger's job.

## 1. How the model is called

Each forecast run needs **two tables** with the same columns (section 2):

| Table | Rows | Why |
|---|---|---|
| `area` | **every** road segment of the zone(s) the route crosses | levels are a budget per zone (the riskiest 2 % of each zone are High), and the trigger looks at the wettest part of the zone |
| `route` | the segments of the requested route, each one at its own ETA | what the user sees |

```python
import json, joblib
from flood_risk.predict import score_route

bundle = joblib.load("models/final/v2_terrain.joblib")
trigger = json.load(open("models/final/trigger.json"))
result = score_route(bundle, route_df, data_time="2026-10-23T14:00Z", area=area_df, trigger=trigger)
```

The same call from the command line:

```
python -m flood_risk.predict --model models/final/v2_terrain.joblib --route route.csv --area area.csv
```

`--trigger` defaults to `models/final/trigger.json`. If that file is absent, every `level` stays
`Low` and only `susceptibility` is filled.

## 2. Input columns (one row per segment)

All distances are in metres, in the zone's UTM projection. A missing value is not allowed
unless the table says so.

### 2.1 Identification

| Column | Type | Content |
|---|---|---|
| `segment_id` | text | unique id of the road segment (e.g. `<osm_way_id>_<index>`) |
| `aoi` | text | zone id; levels and the trigger work per `aoi` (optional if only one zone is served) |
| `eta_min` | float | minutes from departure to the segment (`route` only) |

### 2.2 Terrain columns: computed once per segment, stored in PostGIS (used by the model)

| Column | Unit | Definition |
|---|---|---|
| `elevation_rel_m` | m | ground elevation minus the lowest elevation within 1 km (bare-earth DEM, 30 m) |
| `slope_pct` | % | terrain slope at the segment midpoint |
| `twi` | – | topographic wetness index ln(upslope area / slope), from D8 flow accumulation |
| `depression_depth_m` | m | depth of the filled sink under the segment (max within ~75 m), 0 if none |
| `dist_wadi_m` | m | distance from the midpoint to the nearest waterway (OSM `waterway=*`), capped at 5000 |
| `underpass` | 0/1 | OSM tunnel, underpass or road below a bridge |
| `ford` | 0/1 | OSM `ford=yes` |

### 2.3 Percentile columns: recomputed when the set of segments of a zone changes (used by the model)

Rank of the segment **inside its zone**, between 0 and 1:

| Column | From |
|---|---|
| `elevation_rel_pct` | `elevation_rel_m` |
| `dist_wadi_pct` | `dist_wadi_m` |
| `twi_pct` | `twi` |

### 2.4 Rain trigger column: one value per zone and forecast run

| Column | Unit | Definition |
|---|---|---|
| `trigger_rain_24h_mm` | mm | rain from `t − 12 h` to `t + 12 h` (12 h already fallen + 12 h forecast), `t` = prediction time, in the 0.1° rain cell that contains the segment. The same value for every segment of a cell. The trigger takes the wettest segment of the zone. |

The rain already fallen comes from INM rain gauges, radar, or IMERG Early (about 4 h delay). The
forecast part comes from ECMWF or AROME. Use a 0.1° grid (≈ 10 km) or finer.

The threshold was calibrated on **calendar days** (00–24 UTC) of IMERG Final. The centred window used in
operation is always at least as large: ×1.03 in median and up to ×1.7 when a storm straddles midnight
(`reports/med_trigger/window_check.csv`). At the fixed 44 mm, the trigger therefore fires earlier and catches
27 of the 28 flood zones instead of 24. These are the 28 zones the threshold was studied on, not an independent
validation. It will also fire more often without a flood, and the daily data cannot measure how much more.
Check this during the Tunisian validation (`python -m flood_risk.real.validate_trigger`).

### 2.5 Columns used only for the confidence rules (section 7.3 of the specification)

`impervious_frac` (built-up share within 100 m, ESA WorldCover), `osm_completeness` (0.5 when unknown),
`black_spot_count` (0 when none), `rain_interpolated` (0/1), `data_age_min` (minutes).

Rain columns of earlier versions (`rain_eta_mmh`, `rain_1h_mm`, …) are no longer needed. If they are
absent, the terrain model fills them with 0.

## 3. Output (one row per route segment)

| Column | Content | Show to the user? |
|---|---|---|
| `segment_id`, `eta_min` | copied from the input | – |
| `level` | the **alert**: `Low` while the trigger is off; otherwise `Moderate` (top 10 % of the zone), `High` (top 2 %), `Very high` (top 0.5 %) | **yes, main output** |
| `susceptibility` | the same ranking whatever the weather: how exposed the road is | yes, as "exposed road", never as an alert |
| `rain_trigger` | `on`, `off`, or `not validated` (no trigger file) | yes |
| `risk_score` | 0–100, anchored on the levels: 25 = Moderate, 50 = High, 75 = Very high | yes |
| `flood_prob_pct` | model probability (%) | **no**, see section 5 |
| `confidence`, `confidence_level` | 0.1–1 and `High` / `Medium` / `Low`, from data-quality rules | yes |
| `confidence_notes` | reasons for lower confidence | on demand |
| `main_factors` | up to 3 factor groups that raise the risk the most, e.g. `depression / low point (+34)` | yes |
| `data_timestamp` | time of the rain data used | yes |

## 4. Building the inputs in PostGIS

The Python builders already compute every terrain column. The easiest path is to run them once
per zone and load the result into PostGIS:

```python
from flood_risk.real import osm, terrain
seg = osm.build_segments(area, cache_dir, clip=zone_polygon)   # 150 m segments, OSM columns
seg = terrain.add_terrain(seg, area, cache_dir)                # DEM and WorldCover columns
seg.to_postgis("segments", engine, if_exists="append")         # needs geoalchemy2
```

To compute them in SQL instead, these are the equivalents:

```sql
-- 150 m segments (geometry in the UTM zone, e.g. EPSG:32632 for Nabeul)
SELECT way_id, n AS idx,
       ST_LineSubstring(geom, (n - 1)::float / k, n::float / k) AS geom
FROM (SELECT way_id, geom, GREATEST(1, ROUND(ST_Length(geom) / 150))::int AS k FROM roads) r,
     generate_series(1, k) AS n;

-- distance to the nearest waterway, capped at 5 km
UPDATE segments s SET dist_wadi_m = LEAST(5000, (
  SELECT ST_Distance(ST_LineInterpolatePoint(s.geom, 0.5), w.geom)
  FROM waterways w ORDER BY w.geom <-> ST_LineInterpolatePoint(s.geom, 0.5) LIMIT 1));

-- terrain layers stored as rasters (elevation_rel, slope, twi, depression)
UPDATE segments s SET elevation_rel_m = ST_Value(r.rast, ST_LineInterpolatePoint(s.geom, 0.5))
FROM elevation_rel r WHERE ST_Intersects(r.rast, ST_LineInterpolatePoint(s.geom, 0.5));

-- percentiles inside each zone
UPDATE segments s SET elevation_rel_pct = p.pct
FROM (SELECT segment_id, CUME_DIST() OVER (PARTITION BY aoi ORDER BY elevation_rel_m) AS pct
      FROM segments) p
WHERE p.segment_id = s.segment_id;

-- trigger rain: the 0.1° cell that contains each segment (rain_cells is filled by the rain job)
SELECT s.segment_id, s.aoi, r.rain_24h_mm AS trigger_rain_24h_mm
FROM segments s
JOIN rain_cells r
  ON r.cell_x = FLOOR((ST_X(ST_Transform(ST_LineInterpolatePoint(s.geom, 0.5), 4326)) + 180) / 0.1)
 AND r.cell_y = FLOOR((ST_Y(ST_Transform(ST_LineInterpolatePoint(s.geom, 0.5), 4326)) + 90) / 0.1)
WHERE r.valid_time = :prediction_time;
```

Notes:

- `elevation_rel_m`, `twi` and `depression_depth_m` need flow routing on the DEM, which PostGIS
  does not do. Compute the rasters with `flood_risk/real/terrain.py` (`terrain_layers`) and import
  them with `raster2pgsql`.
- `CUME_DIST` and the pandas rank used in training differ only on tied values.
- The terrain columns never change with the weather. **The ranking of a zone can be computed once
  and stored.** Only the trigger needs to be recomputed at each forecast run.

## 5. Rules for the application

1. **Show `level`, `susceptibility` and `risk_score`, not `flood_prob_pct`.** The probabilities do
   not beat a constant forecast (Brier skill score ≈ 0). The ranking is what is reliable.
2. **Never present `susceptibility` as an alert.** It says "this road floods early when it rains
   hard", not "this road will flood now".
3. **Score the whole zone**, then read the route segments from it. One run over 30 000 segments
   takes a few seconds.
4. **Always show the disclaimer.** The risk is a possibility, not a certainty, and it does not
   replace official warnings (INM, civil protection).
5. **Changing the alert budget** (`schema.ALERT_SHARE`: 10 / 2 / 0.5 %) or the trigger threshold
   (`trigger.json`) does not require retraining.

## 6. Measured performance

The terrain model is validated as described below. The rain trigger is provisional: its results are tests, not an operational validation.

### Terrain model

The test labels count only roads that the satellite actually observed. Each test fold is never
seen during training. Alerts are set to High for 2 % of each zone.

| Validation | ROC-AUC | PR-AUC | Recall at High | Precision at High | False alarms |
|---|---|---|---|---|---|
| 13 floods, one left out at a time | 0.74 (V1: 0.56) | 0.26 (V1: 0.15) | 11.5 % (V1: 2.8 %) | 32 % (V1: 17 %) | 68 % |
| 6 countries, one left out at a time | 0.76 | 0.27 | 17 % | 33 % | 67 % |
| Nabeul 2018 (Tunisia left out) | 0.79 | – | 33 % | – | – |

Each fold trains, calibrates and sets its base rate on the other events only; no event or zone is on both
sides. The hyperparameters (`models/med_imerg/hgb_params.json`) and the choice of terrain-only features were
selected with cross-validation on the same 13 events, without a nested cross-validation, so these scores may be
slightly optimistic.

Recall is limited by the budget. When a flood covers more than 2 % of a zone, even a perfect
ranking cannot alert on all of it. Raising the budget to 10 % brings recall to about 35 %.
The model fails on urban torrent floods (Mandra 2017, Derna 2023).

### Rain trigger (provisional)

The trigger was tested on 28 zones. For each zone, the test compared the mapped flood with
126 other rain spells from the 120 days before it. Those other spells had no Copernicus
activation. The threshold was set leave-one-event-out.

| Threshold | Flood zones triggered | Rain spells triggered without a mapped flood | Triggers per zone per year without a mapped flood |
|---|---|---|---|
| **44 mm / 24 h** | **25 / 28** | **5 / 126** | **≈ 0.65** |

At least one of those 5 "false" triggers was a real flood that Copernicus did not map: Heraklion, 20 October 2020.
Details are in `reports/med_trigger/README.md`.

### Rain trigger on Tunisian gauges (exploratory)

The 44 mm threshold was then run, **unchanged**, on Tunisian floods that it was not fitted on. The rain came from 8 INM synoptic gauges, 2014–2025, as archived by NOAA (WMO SYNOP messages). It was rebuilt on a 3-hour grid, partly from 6–24 h totals. Details and how to reproduce: `reports/tn_trigger_synop/README.md`.

These results are **exploratory**. They do not validate 44 mm as an operational alert threshold.

| Measure (44 mm, rolling 24 h) | Value | Unit |
|---|---|---|
| Floods caught | **7/14** = 50 % (Wilson 95 %: 27–73 %) | zone-dates from the press, excluding the event the threshold was fitted on |
| Floods caught | **6/11** = 54.5 % (28–79 %) | event–station: zones that share a gauge on the same day count once |
| Triggers without a listed flood | **135** | zone-episodes |
| Triggers without a listed flood | **74** | station-episodes |
| Groups of time-overlapping station-episodes | 50 | an algorithmic grouping, not 50 confirmed storms |

How to read them:

- Of the 11 events, 4 have **insufficient** time resolution around the flood (mostly 12 h totals or gaps). The threshold cannot be judged on them. On the 4 events with high resolution, 3 were caught.
- 25 of the 74 station-episodes have a quality flag within their reach. A flag marks a total to review; it does not show that the total used is wrong. A manual review sorted them into categories:
  - 12 possible unlisted floods (press reports of flooding nearby);
  - 7 with unreliable rain data (totals contradicted by the same station);
  - 6 unresolved.

  These are **review categories, not confirmed ground truth**. Press reports do not prove that the station value is right, and contradictory totals do not show which one is wrong. No station-episode was confirmed as a false alarm, and none was removed.
- The flood list comes from the press and is incomplete, so part of the triggers without a listed flood may be real floods.

The earlier test with satellite rain on the same floods caught 5/14 (`reports/tn_trigger_imerg/README.md`). Satellite and gauge rain differ in both directions: the gauge reads 3–4 times more on the most intense urban storms, and less on wider ones. A threshold fitted on IMERG cannot simply be rescaled for gauges.

**Before production, these checks remain:**

- Validation on a denser gauge network (INM climatological, DGRE) with hourly data, and a flood list from the Civil Protection.
- Any change of threshold must be chosen on one period and tested once on a held-out period (`docs/TRIGGER_VALIDATION.md`, section 5).
- The real-time rain feed (delay, coverage, 12 h forecast) is not tested.
