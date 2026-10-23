# Route-level flood risk: Version 2 prototype

Supervised flood-risk model per road segment and ETA (requirements FR-14, FR-25, section 7.2),
compared with the Version 1 multi-criteria index.

**The bundled data are synthetic.** They follow the schema of the real flood inventory so the
pipeline can be tested now; every metric they produce describes the pipeline, not the system.

## Run

```
pip install -r requirements.txt
python -m flood_risk.synth                 # data/inventory_synthetic.csv (800 segments x 16 storms x 4 slots)
python -m flood_risk.train                 # models/ + reports/v2_report.md (about 1-2 min)
python -m flood_risk.predict --demo        # score a 25-min route during an unseen storm
```

## Files

| File | Role |
|---|---|
| `flood_risk/schema.py` | Column names, levels, target recalls, reference rainfall |
| `flood_risk/features.py` | Drainage-vulnerability proxy (FR-08/09) and engineered hybrid features, monotonic constraints |
| `flood_risk/v1.py` | V1 weighted multi-criteria index (baseline) |
| `flood_risk/v2.py` | V2 models (logistic regression, monotonic gradient boosting), calibration, thresholds |
| `flood_risk/train.py` | Leave-events-out evaluation: recall, false-alarm rate, PR-AUC, Brier, ECE, lead time, drainage ablation |
| `flood_risk/predict.py` | Route scoring: score, level, calibrated probability, confidence (section 7.3), main factors, timestamp |
| `flood_risk/synth.py` | Synthetic inventory generator (hidden clogging, under-reporting, coarse rainfall) |

## Method

- **Split by storm event.** A storm is never in both train and test, otherwise the model learns
  that storm's rainfall field and the scores look far better than they are.
- **Calibration and thresholds** come from out-of-fold predictions inside the training events
  (isotonic when there are at least 150 positives, Platt scaling otherwise).
- **Levels.** High is placed to reach 70% recall on training events (section 8 target), Moderate
  at 90%, Very high at 35%. Compare models on false-alarm rate at that recall, not on recall.
- **Displayed score** is anchored on the levels (25 / 50 / 75); the calibrated probability is
  shown beside it, because a few percent can already be High when floods are rare.
- **Gradient boosting is monotonic**: more rain, lower slope, fewer drain inlets can never lower
  the risk. This keeps scores explainable and stable with few labels.
- **Forecast error.** The ETA rainfall is replaced by a forecast whose error grows with lead time
  and with hourly interpolation; training uses random leads from 0 to 30 min.

## Using a real inventory

Build a CSV with one row per segment x storm x time slot containing the columns in
`schema.py` (`RAW_FEATURES`, `flooded`, `segment_id`, `event_id`, `slot_min`,
`rain_interpolated`, `data_age_min`), then:

```
python -m flood_risk.train --data data/inventory_real.csv --out reports/real
```

Rows for non-flooded segments are as important as flooded ones: for each documented storm, add
every pilot segment with its rainfall, labelled 0 unless a flood was reported there. Use
historical rainfall (e.g. Open-Meteo archive or ERA5) for past storms.

## Real data: New York (training) and Nabeul 2018 (validation)

```
pip install geopandas rasterio pyproj pyogrio
python -m flood_risk.real.nyc                    # data/inventory_nyc.csv.gz (11 394 segments x 163 storms >= 15 mm)
python -m flood_risk.tune --data data/inventory_nyc.csv.gz --out models/nyc/hgb_params.json
python -m flood_risk.train --data data/inventory_nyc.csv.gz --out reports/nyc --models models/nyc     --neg-sample 0.15 --hgb-params models/nyc/hgb_params.json --levels budget
python -m flood_risk.real.drainage_test          # ablation: drainage, history, rain (reports/nyc/drainage_test.csv)
python -m flood_risk.real.nabeul                 # data/inventory_nabeul.csv + transfer test, reports/nabeul/
```

Then open `pipeline_reel.ipynb` for the full analysis.

| Source | Use |
|---|---|
| NYC Open Data 311 (street / highway flooding, catch basin clogged) | labels, flood history, drain-blocked reports |
| NYC DEP Citywide Catch Basins | catch-basin density per segment |
| JFK and LaGuardia hourly rain (Iowa Environmental Mesonet ASOS archive) | measured rain, interpolated per segment |
| Open-Meteo historical archive (ERA5 / ECMWF IFS) | fills station gaps; rain at Nabeul |
| OpenStreetMap (Overpass) | roads split into ~150 m segments, water, drains |
| USGS 3DEP 1/3 arc-second (10 m bare earth) | elevation, slope, depressions, TWI in New York |
| Copernicus DEM GLO-30 (buildings removed by a 150 m opening) | same factors at Nabeul |
| ESA WorldCover 2021 | built-up share (impervious_frac) |
| Copernicus EMS EMSR319 | flooded areas of the 22 September 2018 Cap Bon floods |

Downloads are cached in `data/raw/`. Road segments with their factors and labels are written as
GeoPackages (`data/real/nyc_segments.gpkg`, `data/real/nabeul_segments.gpkg`) that load directly
into PostGIS (`ogr2ogr -f PostgreSQL PG:"dbname=..." data/real/nyc_segments.gpkg`).

`--neg-sample 0.15` trains on every flooded row and 15 % of the others, then corrects the
probabilities (King and Zeng prior correction); evaluation always uses every row.
`--levels budget` places Moderate / High / Very high on the riskiest 10 % / 2 % / 0.5 % of
segment-storms (`schema.ALERT_SHARE`) instead of a target recall.

For flash floods on plains, `v1.relative_susceptibility` ranks segments by how low they sit and
how close they are to a watercourse within their area (Nabeul 2018: ROC-AUC 0.80). It was chosen
after looking at Nabeul and must be confirmed on another Tunisian event.
