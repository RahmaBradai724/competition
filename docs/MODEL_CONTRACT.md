# Model contract: V2 flood-risk model ↔ PostGIS / application

This file lists what the application must send to the V2 model, what the model sends back,
and how to build each input in PostGIS. Code: `flood_risk/predict.py`. Model file:
`models/med_imerg_tuned/v2_hgb.joblib`, a gradient-boosting model trained on 13 Mediterranean
flash floods with GPM IMERG rain.

**What the model does, and what it does not do (yet).** The model ranks road segments by their risk of
flooding **during a given rain event**. It was trained on flood maps drawn after each event, which say
*whether* a road flooded but not *when*. So it has **not** been shown to predict a flood 20 minutes ahead;
the "lead time" tests only measure how the ranking degrades when the rain forecast is wrong. Training used
IMERG Final rain (gauge-corrected, published about 3.5 months later); in operation the inputs will come from
faster, less accurate sources (IMERG Early, radar, INM gauges).

## 1. How the model is called

Each forecast run needs **two tables** with the same columns (section 2):

| Table | Rows | Why |
|---|---|---|
| `area` | **every** road segment of the zone(s) the route crosses | levels are a budget per zone: the riskiest 2 % of each zone are High |
| `route` | the segments of the requested route, each one at its own ETA | what the user sees |

Scoring only the route segments is not enough. The route has too few segments to rank,
and the thresholds change with every forecast.

```python
import joblib
from flood_risk.predict import score_route

bundle = joblib.load("models/med_imerg_tuned/v2_hgb.joblib")
result = score_route(bundle, route_df, data_time="2026-10-23T14:00Z", area=area_df)
```

The same call from the command line:

```
python -m flood_risk.predict --model models/med_imerg_tuned/v2_hgb.joblib --route route.csv --area area.csv
```

If `area` is missing, the model falls back to fixed probability thresholds and prints a warning.
Do not use that mode in production: a region with frequent floods would be almost all High, and
a region with rare floods almost all Low.

## 2. Input columns (one row per segment)

All distances are in metres, in the zone's UTM projection. A missing value is not allowed
unless the table says so.

### 2.1 Identification

| Column | Type | Content |
|---|---|---|
| `segment_id` | text | unique id of the road segment (e.g. `<osm_way_id>_<index>`) |
| `aoi` | text | zone id; levels are ranked inside each `aoi` (optional if only one zone is served) |
| `eta_min` | float | minutes from departure to the segment (`route` only) |

### 2.2 Static columns: computed once per segment, stored in PostGIS

| Column | Unit | Definition |
|---|---|---|
| `elevation_rel_m` | m | ground elevation minus the lowest elevation within 1 km (bare-earth DEM, 30 m) |
| `slope_pct` | % | terrain slope at the segment midpoint |
| `twi` | – | topographic wetness index ln(upslope area / slope), from D8 flow accumulation |
| `depression_depth_m` | m | depth of the filled sink under the segment (max within ~75 m), 0 if none |
| `dist_wadi_m` | m | distance from the midpoint to the nearest waterway (OSM `waterway=*`), capped at 5000 |
| `impervious_frac` | 0–1 | share of built-up pixels (ESA WorldCover class 50) within ~100 m |
| `drain_inlet_density` | per km | OSM storm drains within 50 m, divided by segment length, capped at 60 |
| `underpass` | 0/1 | OSM tunnel, underpass or road below a bridge |
| `ford` | 0/1 | OSM `ford=yes` |
| `osm_completeness` | 0–1 | how well the area is mapped in OSM; use 0.5 when unknown |
| `black_spot_count` | count | documented past floods on the segment; 0 when none |

### 2.3 Percentile columns: recomputed when the set of segments of a zone changes

Rank of the segment **inside its zone**, between 0 and 1:

| Column | From |
|---|---|
| `elevation_rel_pct` | `elevation_rel_m` |
| `dist_wadi_pct` | `dist_wadi_m` |
| `twi_pct` | `twi` |
| `impervious_pct` | `impervious_frac` |

### 2.4 Rain columns: one value per segment and forecast run

Each value is taken in the rain cell that contains the segment, around the segment's **ETA**
(`t` = the hour of arrival). Rain is in mm, hourly totals.

| Column | Unit | Definition |
|---|---|---|
| `rain_eta_mmh` | mm/h | rain intensity during the hour of arrival (forecast) |
| `rain_1h_mm` | mm | rain in the hour before `t` |
| `rain_3h_mm` | mm | rain from `t − 3 h` to `t − 1 h` |
| `rain_24h_mm` | mm | rain from `t − 24 h` to `t − 1 h`; **the most important input of the model** |
| `dry_spell_days` | days | days since the last day with ≥ 5 mm before the current storm; 60 if none in the archive |
| `rain_interpolated` | 0/1 | 1 if the 15-min value was interpolated from an hourly forecast |
| `data_age_min` | min | age of the rain data when the route is scored |

Training used **IMERG Final**: a 0.1° grid (about 10 km), every 30 min. In operation, rain
already fallen can come from IMERG Early or Late (available about 4 h or 14 h after the rain),
or from INM rain gauges. Future hours come from a weather forecast (ECMWF or AROME).
Use the same 0.1° grid, or finer.

### 2.5 Optional history columns

`flood_reports_250m`, `flood_reports_365d` and `basin_reports_prior` are counts of user
reports (FR-21) near the segment. If the columns are absent, the model reads them as 0.

## 3. Output (one row per route segment)

| Column | Content | Show to the user? |
|---|---|---|
| `segment_id`, `eta_min` | copied from the input | – |
| `level` | `Low`, `Moderate` (top 10 % of the zone), `High` (top 2 %), `Very high` (top 0.5 %) | **yes, main output** |
| `risk_score` | 0–100, anchored on the levels: 25 = Moderate, 50 = High, 75 = Very high | yes |
| `flood_prob_pct` | calibrated probability (%) | **no**, see section 5 |
| `confidence`, `confidence_level` | 0.1–1 and `High` / `Medium` / `Low`, from data quality rules (section 7.3) | yes |
| `confidence_notes` | reasons for lower confidence | on demand |
| `main_factors` | up to 3 factor groups that raise the risk the most, e.g. `depression / low point (+31)` | yes |
| `data_timestamp` | time of the rain data used | yes |

## 4. Building the inputs in PostGIS

The Python builders already compute every static column. The easiest path is to run them once
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

-- storm drains within 50 m, per km of road
UPDATE segments s SET drain_inlet_density = LEAST(60, (
  SELECT COUNT(*) FROM drains d WHERE ST_DWithin(d.geom, s.geom, 50)) / (ST_Length(s.geom) / 1000));

-- terrain layers stored as rasters (elevation_rel, slope, twi, depression, built-up share)
UPDATE segments s SET elevation_rel_m = ST_Value(r.rast, ST_LineInterpolatePoint(s.geom, 0.5))
FROM elevation_rel r WHERE ST_Intersects(r.rast, ST_LineInterpolatePoint(s.geom, 0.5));

-- percentiles inside each zone
UPDATE segments s SET elevation_rel_pct = p.pct
FROM (SELECT segment_id, CUME_DIST() OVER (PARTITION BY aoi ORDER BY elevation_rel_m) AS pct
      FROM segments) p
WHERE p.segment_id = s.segment_id;

-- rain: the 0.1° cell that contains each segment (segment_rain is filled by the rain job)
SELECT s.segment_id, r.rain_eta_mmh, r.rain_1h_mm, r.rain_3h_mm, r.rain_24h_mm
FROM segments s
JOIN rain_cells r
  ON r.cell_x = FLOOR((ST_X(ST_Transform(ST_LineInterpolatePoint(s.geom, 0.5), 4326)) + 180) / 0.1)
 AND r.cell_y = FLOOR((ST_Y(ST_Transform(ST_LineInterpolatePoint(s.geom, 0.5), 4326)) + 90) / 0.1)
WHERE r.valid_hour = :eta_hour;
```

Notes:

- `elevation_rel_m`, `twi` and `depression_depth_m` need flow routing on the DEM. PostGIS does
  not do this, so compute the rasters with `flood_risk/real/terrain.py` (`terrain_layers`) and
  import them with `raster2pgsql`.
- `CUME_DIST` and the pandas rank used in training differ only on tied values.
- Suggested tables:
  - `segments`: static and percentile columns, plus geometry;
  - `rain_cells`: one row per cell × hour;
  - `reports`: FR-21 user reports, for the history columns.

## 5. Rules for the application

1. **Show `level` and `risk_score`, not `flood_prob_pct`.** The probability is calibrated on
   average over all training floods, so it varies little inside one zone (e.g. about 10 % on
   every Nabeul segment). The level is computed from the ranking, and it is reliable.
2. **Score the whole zone for every forecast run**, then read the route segments from it. One
   run over a zone of 30 000 segments takes a few seconds.
3. **Rain must be taken at each segment's ETA**, not at departure time.
4. **Always show the disclaimer.** The risk is a possibility, not a certainty, and it does not
   replace official warnings.
5. Validated performance on 13 floods the model never saw:
   - ROC-AUC 0.74 (V1: 0.58);
   - High alerts are right 26 % of the time, against about 11 % for random alerts;
   - Nabeul 2018: ROC-AUC 0.81, with 35 % of flooded segments caught at High while 2 % of the
     roads are alerted.

   Details are in `pipeline_v2.ipynb`.
6. **Changing the alert budget** (`schema.ALERT_SHARE`: 10 / 2 / 0.5 %) does not require
   retraining.
