# Rain trigger on Tunisian floods with IMERG (stand-in for INM gauges)

INM hourly gauge records were not available. This test runs the provisional trigger (44 mm in 24 h,
`models/final/trigger.json`) on **Tunisian floods that the threshold was not fitted on**, with the same rain
source as the fit: NASA IMERG Final. `validate_trigger.py` was used unchanged.

**This is not the INM validation.** It tests transfer to Tunisia with satellite rain. It does not test the
trigger with gauges or with the real-time rain feed. The 44 mm threshold stays provisional and unchanged.

## Data

| Item | Content | File |
|---|---|---|
| Zones | 14 towns of the north and the Sahel; each zone uses the IMERG cells (0.1°) within 10 km of its centre (2 to 4 cells) | `data/tn_trigger/zones.csv`, `zone_cells.csv` |
| Floods | 17 zone-dates from 2016 to 2024, each with a press source; 3 of them (Cap Bon, 22 Sep 2018) belong to the event the threshold was fitted on | `data/tn_trigger/floods.csv` |
| Rain | IMERG Final, 1 Sep 2014 to 31 Aug 2025 (IMERG Final stops in Sep 2025, so the January 2026 floods are out) | `data/tn_trigger/imerg_hourly.csv.gz` |
| Builder | `python -m flood_risk.real.imerg_tn` | |

The rain is half-hourly on every pair of days whose total reaches 30 mm at a zone cell (366 days), and daily
spread evenly over 24 h elsewhere. A 24 h window always lies within two days, so every threshold from 30 mm up
is measured exactly.

The flood list was compiled from press reports **before** looking at the IMERG results. It is short and
incomplete: floods that the press search missed count as spells without a flood.

## Results (rolling 24 h window, as in operation)

Outputs: `main/` (`summary.json`, `zones.csv`, `thresholds.csv`, `spells.csv`).

Units:

- A **zone-date** is one flood of `floods.csv`. There are 17 in the period, all matched to a spell. 3 of them
  (Cap Bon, 22 Sep 2018) belong to the event the threshold was fitted on; the other 14 are **independent**.
  The same 14 are excluded in every column and interval below.
- A **zone-episode** is a wet spell of a zone. A trigger without a listed flood is a zone-episode with no
  listed flood whose highest rolling 24 h rain reaches the threshold.
- A **group** merges zone-episodes of different zones that overlap in time (`validate_trigger.storms`). It is
  an algorithmic grouping, not a confirmed storm.

Intervals are Wilson score intervals at 95 % for recall, and exact Poisson intervals at 95 % for the yearly rate.

| Threshold | Zone-dates caught, all (17) | Independent zone-dates caught (14) | Zone-episodes without a listed flood | Groups | Per zone per year |
|---|---|---|---|---|---|
| 30 mm | 10 / 17 | 7 / 14 = 50 % (27–73 %) | 390 | 91 | 2.53 (2.29–2.80) |
| 40 mm | 8 / 17 | 5 / 14 = 36 % (16–61 %) | 195 | 63 | 1.27 (1.09–1.46) |
| **44 mm** | **8 / 17 = 47 % (26–69 %)** | **5 / 14 = 36 % (16–61 %)** | **143** | **46** | **0.93 (0.78–1.09)** |
| 50 mm | 7 / 17 | 5 / 14 = 36 % (16–61 %) | 87 | 31 | 0.57 (0.45–0.70) |
| 60 mm | 5 / 17 | 5 / 14 = 36 % (16–61 %) | 53 | 20 | 0.34 (0.26–0.45) |

The "all" column comes from `main/thresholds.csv`. The independent column leaves out the rows of `floods.csv`
with `in_calibration = 1`:

```python
import pandas as pd
s = pd.read_csv("reports/tn_trigger_imerg/main/spells.csv")
f = pd.read_csv("data/tn_trigger/floods.csv").query("'2014-09-01' <= date < '2025-09-01' and in_calibration == 0")
c = s[s.flood == 1].assign(date=s.flood_dates.str.split(";")).explode("date")
z = f.merge(c[["zone", "date", "rolling_24h_mm"]], on=["zone", "date"], how="left")
unmatched = z[z.rolling_24h_mm.isna()]          # a zone-date with no spell counts as not caught
print(len(unmatched), "unmatched:", unmatched[["zone", "date"]].values.tolist())
print((z.rolling_24h_mm >= 44).sum(), "/", len(z))
```

It prints `0 unmatched: []` and `5 / 14`: every independent zone-date has a spell.

The Poisson interval assumes independent triggers. The 143 zone-episodes come from 46 groups, so it is probably too narrow.

### Floods caught and missed at 44 mm

| Caught | Missed (IMERG rain in brackets) |
|---|---|
| Nabeul and Zaghouan 17 Oct 2018 (94 and 93 mm) | **Grand Tunis, every event**: Ariana and Tunis 10 Sep 2019 (23 mm), 28 Oct 2019 (37 mm), 10 Sep 2020 (17 and 28 mm) |
| Sousse 29 Sep 2016 (63 mm) | Sousse 23 Sep 2016 (26 mm), 23 Sep 2024 (16 mm) |
| Moknine 5 Sep 2020 (60 mm) | Sfax 29 Sep 2016 (19 mm) |
| Sfax 22 Oct 2024 (75 mm) | |
| Cap Bon 22 Sep 2018, 3 zones (49 to 57 mm; fitted event) | |

Older floods, run separately (`old_2003/`, `old_2009/`): Grand Tunis, Nabeul and Zaghouan, 16 Sep 2003 were all
caught (46 to 86 mm). Redeyef, 23 Sep 2009 (150 mm reported in one night) was missed: IMERG saw 35 mm.

### "False" triggers checked in the press

The 9 largest groups that triggered without a listed flood were searched in the press. Each one is a row of
`storm_checks.csv`, with its source:

| Group (start) | Press check |
|---|---|
| 17 Oct 2024 (Mahdia, Moknine) | flood confirmed (Sayada, 18 Oct) |
| 5 Dec 2016 (12 zones) | flood confirmed (Nabeul and Tunis, 8 Dec) |
| 15 Oct 2018 (Grand Tunis, Bizerte, ...) | flood confirmed (Tunis, 17 Oct) |
| 5 Sep 2020 (Kairouan, Mahdia, Monastir) | flood confirmed (Monastir) |
| 12 Jan 2025 (Grand Tunis, Bizerte, Mahdia) | flood confirmed (Bizerte and Grand Tunis, 16–17 Jan) |
| 21 Oct 2024 (8 Sahel and Cap Bon zones) | partly confirmed |
| 22 Oct 2021 (Grand Tunis, Bizerte, Zaghouan) | likely |
| 15 Nov 2016 (Cap Bon, Mahdia) | not found |
| 16 Dec 2023 (9 Sahel and Cap Bon zones) | rain confirmed, flood not found |

"Not found" does not mean a confirmed false alarm: the press search is incomplete.

These floods are **not** added to the recall: they were found because the trigger fired, which would bias it
upwards. These checks show that some zone-episodes without a listed flood were associated with reported
floods. Because the checks were selected after the trigger fired, they cannot estimate the true false-alarm
rate.

## What this says

1. **With IMERG, the 44 mm threshold missed most short urban floods.** All four Grand Tunis zone-dates and two of
   the three Sousse zone-dates were missed, with IMERG at 16–37 mm. One possible explanation: these are short,
   intense storms over a few km², which a 10 km satellite cell may smooth out. This test does not prove it.
   Gauges or a lower threshold could do better; that has to be tested, not assumed. The gauge test that followed
   (`../tn_trigger_synop/README.md`) caught 7 of the same 14 zone-dates. It is exploratory as well.
2. **A lower threshold is not better by itself.** At 30 mm, 2 more independent zone-dates are caught (7 / 14
   against 5 / 14), but the zone-episodes without a listed flood rise from 143 to 390, about 2.7 times (2.53
   against 0.93 per zone per year).
3. **Triggers without a listed flood are seasonal.** 57 of the 143 zone-episodes come from December–February,
   while every listed flood is from September–October. Long winter frontal rain reaches 44 mm without flash flooding. Bizerte (21) and Mahdia
   (21) have the most. A threshold per season, or one on rain intensity (e.g. a 3 h total), would be worth
   testing on gauge data.
4. **The rolling window adds triggers.** At 44 mm, it gives 143 zone-episodes without a listed flood, against 96
   with calendar days, for the same 8 of 17 zone-dates caught.

## Limits

- Satellite rain at 10 km, the same source as the fit. It is not a gauge validation.
- The flood list is short (14 independent zone-dates), compiled from the press, and incomplete. A trigger
  without a listed flood is not necessarily a false alarm. Recall intervals are wide (16–61 % for 5/14).
- Each flood date is matched to the zone named in the press. Governorate-level reports are less precise.
- IMERG Final is published months later. This test says nothing about real-time operation.
