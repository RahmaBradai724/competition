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

| Threshold | Flood spells caught (all 17) | Independent floods caught (14) | Spells triggered without a listed flood | Distinct storms | Per zone per year (95 %) |
|---|---|---|---|---|---|
| 30 mm | 10 / 17 | 7 / 14 | 390 | 91 | 2.5 (2.3–2.8) |
| 40 mm | 8 / 17 | 5 / 14 | 195 | 63 | 1.3 (1.1–1.5) |
| **44 mm** | **8 / 17 (47 %, 26–69 %)** | **5 / 14 (36 %)** | **143** | **46** | **0.93 (0.78–1.09)** |
| 50 mm | 7 / 17 | 5 / 14 | 87 | 31 | 0.57 (0.45–0.70) |
| 60 mm | 5 / 17 | – | 53 | 20 | 0.34 (0.26–0.45) |

The Poisson interval is probably too narrow: 143 triggers come from only 46 storms.

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

The 9 largest storms that triggered without a listed flood were searched in the press (`storm_checks.csv`):

- 5 were floods: 8 Dec 2016 Nabeul and Tunis, 17 Oct 2018 Tunis, Sep 2020 Monastir, 18 Oct 2024 Sayada, 17 Jan 2025 Bizerte and Grand Tunis;
- 1 was partly confirmed, and 1 was likely;
- 2 were not confirmed.

These floods are **not** added to the recall: they were found because the trigger fired, which would bias it
upwards. They show that the false trigger rate above is an overestimate.

## What this says

1. **The 44 mm threshold misses most short urban floods with IMERG.** All four Grand Tunis floods and two of the
   three Sousse floods were missed, with IMERG at 16–37 mm. These are short, intense storms over a few
   km², which a 10 km satellite cell smooths out. Gauges, or a lower threshold, could do better. **The INM test
   is needed to tell which.**
2. **Lowering the threshold to 30 mm** catches 2 more independent floods (7 / 14), but triples the triggers
   (2.5 per zone per year).
3. **False triggers are seasonal.** 57 of the 143 come from December–February, while every listed flood is from
   September–October. Long winter frontal rain reaches 44 mm without flash flooding. Bizerte (21) and Mahdia
   (21) have the most. A threshold per season, or one on rain intensity (e.g. a 3 h total), would be worth
   testing on gauge data.
4. **The rolling window adds triggers.** At 44 mm it gives 143 triggers against 96 with calendar days, for the
   same 8 floods caught.

## Limits

- Satellite rain at 10 km, the same source as the fit. It is not a gauge validation.
- The flood list is short (14 independent floods), compiled from the press, and incomplete. Recall intervals
  are wide (26–69 % for 8/17).
- Each flood date is matched to the zone named in the press. Governorate-level reports are less precise.
- IMERG Final is published months later. This test says nothing about real-time operation.
