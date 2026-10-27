# Rain trigger on Tunisian floods with INM synoptic gauges

First test of the provisional trigger (44 mm in 24 h, `models/final/trigger.json`) on **gauge** rain. The
gauges are INM synoptic stations: they send their observations to the WMO network, and NOAA archives them
(Integrated Surface Database). No request is needed: `https://noaa-global-hourly-pds.s3.amazonaws.com/<year>/<station>.csv`.
`validate_trigger.py` was used unchanged, with `--max-missing-h 6` fixed before the run. The threshold is not changed.

## Data

| Item | Content | File |
|---|---|---|
| Stations | 8 synoptic stations; each of 13 zones takes the nearest one (1 to 20 km); Tunis, Ariana and Ben Arous share Tunis-Carthage | `data/tn_trigger/synop_stations.csv` |
| Rain | 1 Sep 2014 to 31 Aug 2025, rebuilt on a 3-hour grid from the 3, 6, 12 and 24 h totals of each station | `data/tn_trigger/synop_hourly.csv.gz`, builder `python -m flood_risk.real.synop_tn` |
| Floods | same list as the IMERG test, compiled from the press before any result | `data/tn_trigger/floods.csv` |

Data quality (`synop_coverage.csv`):

- 77 % to 98 % of the 3-hour slots are known.
- Nabeul, Zaghouan and Mahdia report mostly every 3 h.
- Tunis-Carthage, Bizerte, Kairouan and Sfax report mostly 6, 12 or 24 h totals. A total longer than 3 h is
  spread evenly over its slots, so their 24 h windows are less precise.

Check of the rebuild: Nabeul, 22 Sep 2018 gives 206 mm in 24 h, with 174 mm between 12 and 15 UTC. The
station reported 204 mm in 12 h; IMERG saw 57 mm.

## Results (rolling 24 h window)

Outputs: `main/` (`summary.json`, `zones.csv`, `thresholds.csv`, `spells.csv`).

| Threshold | Flood spells caught (16) | Complete flood spells (12) | Independent floods caught (14) | Triggers without a listed flood | Storms | Per zone per year (95 %) |
|---|---|---|---|---|---|---|
| 30 mm | 13 | 11 (92 %, 65–99 %) | 11 | 290 | 104 | 2.3 (2.0–2.5) |
| 35 mm | 11 | 9 (75 %) | 9 | 214 | 80 | 1.7 (1.5–1.9) |
| 40 mm | 10 | 8 (67 %) | 8 | 154 | 58 | 1.2 (1.0–1.4) |
| **44 mm** | **9** | **7 (58 %, 32–81 %)** | **7** | **135** | **50** | **1.05 (0.88–1.25)** |
| 50 mm | 9 | 7 (58 %) | 7 | 108 | 43 | 0.84 (0.69–1.02) |

Independent floods exclude Cap Bon, 22 Sep 2018 (the event the threshold was fitted on). Tunis and Ariana
share one gauge, so their floods are the same rain counted twice: the 14 independent zone-floods come from 11
distinct station-events, 6 of them caught at 44 mm.

### Each flood: gauge against IMERG (highest rolling 24 h, mm)

| Flood | Gauge | IMERG | 44 mm on gauge |
|---|---|---|---|
| Cap Bon 22 Sep 2018 (fitted event) | **206** | 57 | caught |
| Grand Tunis 28 Oct 2019 | **107** | 37 | caught (missed with IMERG) |
| Sousse 29 Sep 2016 | 73 | 63 | caught |
| Moknine 5 Sep 2020 | 62 | 60 | caught |
| Sfax 22 Oct 2024 | 60 | 75 | caught |
| Nabeul 17 Oct 2018 | 56 | 94 | caught |
| Zaghouan 17 Oct 2018 | 52 | 93 | caught |
| Sousse 23 Sep 2024 | 40 | 16 | missed |
| Sousse 23 Sep 2016 | 39 | 26 | missed |
| Grand Tunis 10 Sep 2019 | 33 | 23 | missed |
| Grand Tunis 10 Sep 2020 | 24 (23 h missing) | 17–28 | missed (incomplete) |
| Sfax 29 Sep 2016 | 15 | 19 | missed |

Older floods (`old_2003/`): Grand Tunis on 16 Sep 2003 reached 95 mm (caught), but the record has gaps there.
Nabeul (43 mm) and Zaghouan (25 mm) were missed, with 29 to 38 missing hours.

## What this says

1. **Gauge and satellite disagree in both directions.** On the most intense urban storms the gauge reads 3 to
   4 times IMERG (Cap Bon 2018, Grand Tunis 2019). On wider storms it reads less (Nabeul and Zaghouan 2018).
   A point gauge and a 10 km cell do not measure the same thing. A threshold fitted on IMERG cannot simply be
   rescaled for gauges.
2. **With gauges, 44 mm catches more independent floods than with IMERG**: 7 against 5 out of 14, for a
   similar trigger rate (1.05 against 0.93 per zone per year).
3. **Several missed floods sit just below the threshold** (33 to 40 mm: Sousse 2016 and 2024, Grand Tunis
   2019). At 30–35 mm, 9 to 11 of 14 are caught, but triggers rise to 1.7–2.3 per zone per year. The flood
   list is incomplete, so part of those triggers are unlisted floods (see `../tn_trigger_imerg/storm_checks.csv`).
4. **This is still not a decision on the threshold.** 11 distinct station-events give wide intervals. The
   threshold was not refitted here, and doing so on these same floods would leave no independent test
   (`docs/TRIGGER_VALIDATION.md`, section 5).

## Limits

- One station per zone, at 1 to 20 km. Sousse uses Monastir-Skanes (20 km away). A flash flood can miss the
  gauge entirely.
- Half of the stations report mostly 6–24 h totals. Their rolling 24 h is approximate.
- Only 8 synoptic stations. The denser INM climatological and DGRE networks are not in the WMO archive.
- The flood list is short and incomplete, so the false trigger rate is an overestimate.
- These are archived observations. Real-time availability is not tested.
