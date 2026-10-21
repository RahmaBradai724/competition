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
