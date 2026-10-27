# Rain trigger on Tunisian floods with INM synoptic gauges (exploratory)

This is a test of the provisional trigger (44 mm in 24 h, `models/final/trigger.json`) on **gauge** rain, for Tunisian floods
that the threshold was not fitted on. The threshold was **not refitted**. The results are exploratory and do
not validate 44 mm as an operational alert threshold.

## Reproduce

```
python -m flood_risk.real.synop_tn                       # raw SYNOP -> hourly rain + quality flags
python -m flood_risk.real.validate_trigger --rain data/tn_trigger/synop_hourly.csv.gz \
    --floods data/tn_trigger/floods.csv --max-missing-h 6 --out reports/tn_trigger_synop/main
python -m flood_risk.real.trigger_tables \
    --run before reports/tn_trigger_synop/before_qc reports/tn_trigger_synop/before_qc/hourly.csv.gz \
    --run after reports/tn_trigger_synop/main data/tn_trigger/synop_hourly.csv.gz
```

`before_qc/` was produced by the earlier version of `synop_tn.py`, before the quality checks, and is kept as it was.
That version is in commit `75b6b503`. These commands rebuild `before_qc/hourly.csv.gz`; the result was checked
identical. The old script writes its outputs next to `--out`, so pointing `--out` to a temporary folder leaves the
working files untouched:

```
mkdir -p <temporary folder>
git show 75b6b503:flood_risk/real/synop_tn.py > flood_risk/real/_synop_tn_old.py
python -m flood_risk.real._synop_tn_old --out <temporary folder>/hourly.csv.gz
rm flood_risk/real/_synop_tn_old.py
```

Running the commands of the first block into a fresh folder gives byte-identical files.

The raw station files come from `https://noaa-global-hourly-pds.s3.amazonaws.com/<year>/<station>.csv`. Save
them as `data/raw/synop_tn/<year>_<station>.csv`. They are not in git, which ignores them because of their size.

## Data

| Item | Content | File |
|---|---|---|
| Gauges | 8 INM synoptic stations, as sent to the WMO network and archived by NOAA. Each of 13 zones takes the nearest station (1 to 20 km). Tunis, Ariana and Ben Arous share Tunis-Carthage; Monastir, Moknine and Sousse share Monastir-Skanes | `data/tn_trigger/synop_stations.csv` |
| Floods | press reports, compiled before any result | `data/tn_trigger/floods.csv` |
| Period | 1 Sep 2014 to 31 Aug 2025 | |

## Preprocessing (`flood_risk/real/synop_tn.py`)

- **Raw values are never changed.** Times are UTC, at the end of each report's period. Amounts are in tenths of mm, and 9999 means missing.
- **Reconstruction.** Each station is rebuilt on a 3-hour grid from its 3, 6, 12, 18 and 24 h totals. Each
  slot records how it was obtained (`method`):
  - `measured`: a 3-hour report;
  - `difference_<h>h`: derived from a longer total;
  - `spread_<h>h`: a longer total spread evenly, which is an assumption, not a measurement.

  An hourly value is never a measurement.
- **Quality checks.** Every check is written to `data/tn_trigger/synop_quality_flags.csv`, with the original
  value, the reason, the decision and the value used.

  | Flag | Count | Decision |
  |---|---|---|
  | `duplicate_rounding`: the same 24 h total in whole mm (truncated) and in tenths | 2,567 | retained (tenths value) |
  | `duplicate_conflict`: two different values for the same total (e.g. 7 against 0.7, 999.4 against 8) | 22 | treated as missing; review required |
  | `negative_residual`: known slots exceed a longer total | 1,332 | retained; review required (most within 0.5 mm) |
  | `total_inconsistent`: a total differs from its rebuilt slots | 346 | retained; review required |
  | `large_spread`: 50 mm or more spread over unknown slots | 21 | retained; review required |

- **Before and after.** At 44 mm, the run before these checks (`before_qc/`) and the run after them (`main/`)
  give the same counts: 7/14 and 6/11 floods caught, 135 zone-episodes and 74 station-episodes without a
  listed flood. They are not the same data, though:
  - the wet spells go from 2,156 to 2,135;
  - the flagged false station-episodes go from 24 to 25;
  - some flood values move slightly (Sousse 23 Sep 2024: 40.0 to 39.6 mm; Grand Tunis 28 Oct 2019: 107.0 to 106.8 mm; Sfax 29 Sep 2016: 15.0 to 14.6 mm);
  - at 40 mm, the flood spells caught go from 10 to 9.

Data coverage (`data/tn_trigger/synop_coverage.csv`):
- 77 % to 98 % of the 3-hour slots are known.
- Nabeul, Zaghouan and Mahdia report mostly every 3 h.
- Tunis-Carthage, Bizerte, Kairouan and Sfax report mostly 6 to 24 h totals.

## Results at 44 mm (rolling 24 h; `comparison/summary.csv`)

**Units.**
- A **zone-date** is one flood reported in a zone on a day.
- An **event-station** merges the zone-dates that share a gauge on the same day.
- A **zone-episode** is a wet spell of a zone; a **station-episode** is a wet spell of a gauge.

Zone-dates and event-stations count different things, and so do zone-episodes and station-episodes: keep them
apart. The intervals are Wilson score intervals at 95 %.

| Measure | Value | Unit |
|---|---|---|
| Floods caught | **7/14 = 50 % (27–73 %)** | zone-dates, excluding the event the threshold was fitted on (Cap Bon, 22 Sep 2018) |
| Floods caught | **6/11 = 54.5 % (28–79 %)** | event-stations |
| Triggers without a listed flood | **135** | zone-episodes |
| Triggers without a listed flood | **74** | station-episodes |
| Groups of time-overlapping station-episodes | 50 | an algorithmic grouping, not 50 confirmed storms |

### Time resolution of each flood (`comparison/zone_dates_after.csv`, `event_stations_after.csv`)

Resolution is judged on the 24 h window with the highest rain:

- **high**: no missing hour, and at least 80 % of the rain measured or derived;
- **insufficient**: more than 6 missing hours, or at least half the rain spread from totals of 12 h or more;
- **approximate**: otherwise.

| Resolution | Event-stations caught | Events |
|---|---|---|
| high | 3/4 | Nabeul 17 Oct 2018, Grand Tunis 28 Oct 2019, Moknine 5 Sep 2020 caught; Sousse 23 Sep 2024 missed at 39.6 mm |
| approximate | 2/3 | Zaghouan 17 Oct 2018 and Sfax 22 Oct 2024 caught; Sfax 29 Sep 2016 missed |
| insufficient | 1/4 | Sousse 29 Sep 2016 caught; Sousse 23 Sep 2016 and Grand Tunis 10 Sep 2019 and 10 Sep 2020 missed |

The threshold cannot be judged on the insufficient events.

### Triggers without a listed flood: manual review (`review/false_episodes_review.csv`)

25 of the 74 station-episodes have a quality flag within their reach. A flag marks a total to review; it does not
show that the total used is wrong. Each one was searched in the press and given a
decision, with sources and a justification:

| Review category | Station-episodes | Zone-episodes |
|---|---|---|
| not flagged (not reviewed) | 49 | 86 |
| unresolved | 6 | 12 |
| possible unlisted flood | 12 | 20 |
| unreliable rain data | 7 | 11 |
| confirmed false alarm | 0 | 0 |

These are **review categories, not confirmed ground truth**:
- A press report of flooding in a governorate does not show that the station value is right.
- Contradictory totals do not show which one is wrong.
- The absence of a report does not show that there was no flood.

The decisions sort the triggers; they do not change or remove any rain value. The review was made on the
`main/` spells. `trigger_tables` refuses to apply it to a run whose flagged episodes it does not cover. In
`comparison/summary.csv`, `before_qc/` therefore shows "not computed" for the review counts: 2 of its flagged
episodes have no decision. Its resolution counts also read "not computed", since its rain file has no `method`
column. "Not computed" never means zero.

### All thresholds (`main/thresholds.csv`, every flood spell including the fitted event)

| Threshold | Flood spells caught (16) | Complete flood spells (12) | Zone-episodes without a listed flood | Per zone per year (95 %) |
|---|---|---|---|---|
| 30 mm | 13 | 11 | 292 | 2.28 (2.02–2.55) |
| 35 mm | 11 | 9 | 210 | 1.64 (1.42–1.87) |
| 40 mm | 9 | 7 | 152 | 1.19 (1.00–1.39) |
| **44 mm** | **9** | **7** | **135** | **1.05 (0.88–1.25)** |
| 50 mm | 9 | 7 | 107 | 0.83 (0.68–1.01) |
| 60 mm | 7 | 6 | 84 | 0.66 (0.52–0.81) |

These counts must not be used to choose a new threshold on the same floods, since nothing independent would be
left to test it (`docs/TRIGGER_VALIDATION.md`, section 5).

## Gauge against satellite

| Flood | Gauge (mm/24 h) | IMERG (mm/24 h) |
|---|---|---|
| Cap Bon 22 Sep 2018 (fitted event) | 206 | 57 |
| Grand Tunis 28 Oct 2019 | 107 | 37 |
| Nabeul 17 Oct 2018 | 56 | 94 |
| Sfax 22 Oct 2024 | 60 | 75 |

The difference goes in both directions: a point gauge and a 10 km cell do not measure the same thing. A threshold
fitted on IMERG cannot simply be rescaled for gauges. With IMERG, the same 14 zone-dates gave 5/14
(`../tn_trigger_imerg/README.md`).

## Limits

- The flood list comes from the press and is incomplete. Some triggers without a listed flood may be real floods.
- There are few gauges, 1 to 20 km from each zone. Sousse uses Monastir-Skanes, 20 km away, and a flash flood can miss a gauge.
- The rain is partly rebuilt from 6–24 h totals; `method` and `resolution_h` say where.
- The review decisions were made by hand, and the review has only one reviewer.
- 11 independent events give wide intervals.
- The data are archived observations. Real-time availability and the 12 h forecast are not tested.
