# Validating the rain trigger on Tunisian records

The rain trigger (`models/final/trigger.json`, 44 mm in 24 h) is **provisional**. It was fitted on 28 flood
zones in 13 Mediterranean events, with NASA IMERG Final daily rain. This page describes the local validation
that must be done before production. Code: `flood_risk/real/validate_trigger.py`. Tests:
`python -m tests.test_validate_trigger`.

The script only measures. **It never changes the threshold.** Any change to `trigger.json` is a separate
decision, taken after reading the results (section 5).

## 1. What the earlier figures mean

All three figures use the same 28 flood zones that the threshold was studied on. **None of them is an
independent validation.**

| Figure | Threshold | Rain window | Meaning |
|---|---|---|---|
| 25 / 28 | refitted each time, leave-one-event-out (44-52 mm) | calendar day | how well the fitting method generalises to an unseen event |
| 24 / 28 | fixed 44 mm | calendar day (00-24 UTC), as fitted | coverage of the final threshold |
| 27 / 28 | fixed 44 mm | rolling 24 h (t − 12 h to t + 12 h), as in operation | coverage in operation; the extra false triggers are unknown |

## 2. Input files

All times are in **UTC**. Convert local Tunisian time (UTC+1) before running the script.

### `inm_hourly.csv`: hourly rain

| Column | Content |
|---|---|
| `zone` | trigger zone, the same id as the model's `aoi` (e.g. `nabeul`) |
| `station` | INM station id |
| `time` | start of the hour, e.g. `2018-09-22 13:00` |
| `rain_mm` | rain in that hour; leave the row out when the gauge did not record, never write 0 |

- **Station to zone.** A station belongs to a zone if it lies inside the zone or within 10 km of it,
  which is one IMERG cell. List the assignment in the report.
- **Period.** Use whole rainy seasons (September to May), several years if possible. False triggers can only
  be counted over the hours that are recorded.
- **Daily data only.** If INM gives only daily totals, the rolling window cannot be measured. The script then
  reproduces the calendar-day study at best. State this in the results.

### `inm_floods.csv`: known floods

| Column | Content |
|---|---|
| `zone` | trigger zone, as above |
| `date` | day the roads flooded (UTC) |
| `source` | where the date comes from (optional, but needed for the report) |
| `description` | roads or places affected (optional) |

Sources for flood dates, from most to least reliable:

1. Civil protection (Protection civile) intervention records.
2. Ministry of Equipment road closure records, municipal reports.
3. INM bulletins and press reports (TAP, national newspapers), with the place named.
4. Copernicus EMS and DesInventar records (major events only).

**One row per zone and per day.** A flood that hit two zones gets two rows. If press reports only name the
governorate, list the date for every zone of that governorate, and mark it in `source`.

## 3. Definitions used by the script

Each definition can be changed on the command line, and the values used are saved to `settings.json`.

| Choice | Default | Option |
|---|---|---|
| Wet hour | rain ≥ 0.2 mm in the hour (the usual gauge resolution) | `--wet-mmh` |
| End of a spell | more than 24 h without a wet hour | `--gap-h` |
| Spell kept | total ≥ 5 mm (same as the IMERG study) | `--min-spell-mm` |
| Flood spell | a flood date of the **same zone** falls between the first day of the spell and 1 day after its last day; a date goes to **one spell only** (the one containing it, the wettest that day if two do, else the last one before it); a date with several candidates is flagged `flood_ambiguous` | `--match-days` |
| Alert | the spell's highest rolling 24 h rain reaches the threshold; **at most one alert per spell** | – |
| False triggers per zone per year | alerts on spells without a flood in all zones ÷ years recorded in all zones (an hour counts if at least one station of the zone has it; 8766 h per year) | – |

A spell without a flood in its own zone, but with a flood in another zone on the same days, is flagged
(`flood_other_zone`). If many false triggers carry this flag, the zones or the station assignment are
probably too narrow.

A spell "without a flood" only means that no flood was recorded. Small street flooding is often not reported.
The false trigger rate is therefore an **upper bound**.

## 4. Outputs (`reports/tn_trigger/`)

| File | Content |
|---|---|
| `spells.csv` | one row per spell: dates, total, rolling 24 h and calendar-day maxima, missing hours, flood, `observed_24h_reached` (see below) |
| `thresholds.csv` | for each threshold (30-70 mm and the current one) and each window: flood spells caught, spells triggered without a flood, false triggers per zone per year |
| `floods_matched.csv` | each flood date and whether a spell matched it |
| `zones.csv` | per zone: stations, period, share of hours recorded, spells, flood spells caught and false triggers at the current threshold, false triggers per year |
| `settings.json` | definitions and input files used |

**Missing hours.** They lower both the false trigger count and the years in the denominator, so the rate
stays comparable. `missing_hours` counts the hours missing in a spell or within 23 h of it, since they all
enter its 24 h totals; a gauge that stops mid-storm is therefore caught even though the spell then seems to
end. A missing hour counts as 0 mm, so the spell's rain is underestimated and a
flood can be missed because of the gap, not the threshold. `thresholds.csv` counts these misses
(`missed_with_missing_hours`); check them before concluding that a threshold is too high. Missing hours can
also send a flood date to the wrong spell when two are close; such dates are flagged `flood_ambiguous`.
The overall rate pools all zones and weights them by record length. Read `zones.csv` too: one zone with many
false triggers can hide behind a good average.

**Time of the alert.** `observed_24h_reached` is the end of the first 24 h of observed rain above the
threshold. It is the time an *observations-only* trigger (t − 24 h to t) would fire. On the same hourly
series, the operational window (t − 12 h to t + 12 h) has the same maximum over a spell, so it catches the
same spells. That no longer holds if the operational feed misses other hours than the archive, or revises
them later. It also fires at a different time: 12 h earlier with a perfect forecast, at an unknown time with a real one. **Do not read
`observed_24h_reached` as the operational alert time.**

Check these before reading `thresholds.csv`:

- **Every flood date is matched.** An unmatched date means missing rain, a wrong date or a wrong zone. Fix
  the inputs; do not drop the flood.
- **Coverage is at least 90 %** in every zone.
- **Few flood spells have missing hours.**

## 5. Deciding on the threshold

Compare the results at 44 mm with the IMERG study: 24 of 28 flood zones caught on calendar days, and about
0.65 triggers per zone per year without a mapped flood.

- **44 mm catches most Tunisian floods with an acceptable false trigger rate:** keep it, and record the
  Tunisian figures in `trigger.json` (`validation`).
- **It misses many floods**, or **gauges read systematically higher or lower than IMERG:** recalibrate on the
  Tunisian records. Choose the new threshold with leave-one-flood-out, as in the IMERG study, not on the full
  set it is then judged on.
- **Fewer than about 10 flood spells:** the result is indicative. Keep the trigger provisional.

Whoever owns the alert service sets the acceptable false trigger rate. This is not a model question.

## 6. Operational data (a separate check)

A good result on the INM archive does not prove that the trigger works in real time. Before production, also
check the source that will feed `trigger_rain_24h_mm`:

- **Delay.** How long after the hour is the gauge, radar or IMERG Early value available? The trigger needs
  the last 12 h within minutes to an hour.
- **Coverage.** Does each zone have at least one station that reports in real time, and what happens when it
  is down?
- **Forecast part.** The 12 h forecast (ECMWF or AROME) is not in this validation. Test it separately, or
  measure the trigger with observed rain only (`observed_24h_reached`, section 4).
