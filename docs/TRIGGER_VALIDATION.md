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

**Ask INM before preparing the files**, and write the answers in the report:

1. Does a timestamp mark the start or the end of its interval? (`--time-label`)
2. Which time zone are the timestamps in: UTC, or local time, and with or without daylight saving in the
   years concerned?
3. What does each value hold: rain over the interval (needed), an intensity in mm/h, or a total since a
   fixed hour (e.g. since 06 UTC)? The last two must be converted first.
4. What is the length of each record, and did it change over the years (hourly, then 10-minute)?
5. How is a missing value written (empty, -999, a flag column), and is 0 ever written for "not measured"?

The synthetic tests show that a wrong start/end convention becomes visible (every hour comes out
incomplete). They cannot tell which convention INM uses.

### `inm_hourly.csv`: hourly rain

| Column | Content |
|---|---|
| `zone` | trigger zone, the same id as the model's `aoi` (e.g. `nabeul`) |
| `station` | INM station id |
| `time` | start of the interval, e.g. `2018-09-22 13:00` (use `--time-label end` if the source stamps the end, as many gauges do) |
| `minutes` | length of the interval, only for records shorter than an hour (e.g. `10`); without it, every row is one hour and must start on the hour |
| `rain_mm` | rain in that hour; **leave it empty (or leave the row out) when the gauge did not record, never write 0**. 0 means "measured, no rain". |

- **Station service periods (optional, `--stations`).** A CSV `station, start, end`, one row per period.
  Both ends are included; a date without a time (`2020-03-01`) covers the whole day; an empty `end` means
  still running. It separates a gauge fault (no value while the station was in service) from a period with
  no station at all. A station not listed is taken to be in service from its first to its last row.
  **Measurements take priority over this file**: a value recorded outside a declared period still counts,
  and the script reports how many there are (`values_outside_service`). Many of them mean the file is wrong.
- **Duplicates.** Rows repeating the same station, hour and value are dropped and counted
  (`duplicate_rows_dropped`). The same station and hour with two different values stops the run with the
  rows listed: fix the input rather than letting the script sum or choose.
- **Records shorter than an hour** (10-minute data). Each row is the rain *over its interval*, not an
  intensity or a running total; convert those first. The records of an hour are summed only if they cover
  all 60 minutes with values; otherwise the hour is missing. A record that overlaps the previous one of its
  station (for example an hourly total next to the 10-minute records of the same hour), or that crosses
  the hour, stops the run, because the sum would count rain twice. Check with INM whether a timestamp marks
  the start or the end of the interval: read with the wrong convention, every hour shifts by one record and
  comes out incomplete.
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
| Complete spell | at most 0 missing hours within its 24 h reach | `--max-missing-h` |
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
| `thresholds.csv` | for each threshold (30-70 mm and the current one) and each window: flood spells caught (all and complete, with a 95 % interval), misses with missing hours, spells triggered without a flood, false triggers per zone per year (with a 95 % interval) and the distinct storms behind them |
| `floods_matched.csv` | each flood date and whether a spell matched it |
| `summary.json` | flood dates matched, flood spells complete / incomplete / ambiguous, spells without flood complete / incomplete |
| `zones.csv` | per zone: stations, period, share of hours recorded, hours with rain / 0 mm / not recorded / no station in service, spells, flood spells caught and false triggers at the current threshold, false triggers per year |
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

**Protocol**, in this order:

1. Count the floods on each side of the cut from `inm_floods.csv`, before running anything.
2. Fix the cut and every setting; write them down.
3. Check data coverage in each period.
4. Evaluate complete flood spells with their intervals.
5. Examine false triggers: frequency, interval and number of distinct storms.
6. Report the sample size and the geographic limits.
7. Study real-time feasibility separately (section 6).

**Read the results in this order**:

1. **Data coverage** (`zones.csv`, `summary.json`): hours measured, `not_recorded`, `no_station`,
   duplicates, values outside service, unmatched flood dates, ambiguous flood spells. Review the ambiguous
   ones by hand before quoting any figure.
2. **Recall on complete flood spells** (`recall_complete`): floods caught out of the floods that can be
   judged. `recall` on all floods is given next to it; `missed_with_missing_hours` tells which misses come
   from gaps.
3. **False triggers**, overall (`false_triggers_per_zone_per_year`) and per zone (`zones.csv`), over the
   time actually recorded.
4. **Sample size**: number of flood spells and of spells without a flood. A good result on two or three
   floods proves nothing. `thresholds.csv` gives 95 % intervals (`recall_complete_low` / `_high`, Wilson;
   `false_triggers_low` / `_high`, exact Poisson). Quote the interval with the value. For example, 9 floods
   caught out of 10 is compatible with a true recall anywhere between 60 % and 98 %.
   The Poisson interval assumes independent false triggers. One storm often triggers several zones at once:
   compare `spells_triggered_without_flood` with `false_trigger_storms`. If the storms are much fewer, the
   Poisson assumption does not hold. The interval is then *probably* too narrow, but how far off it is
   depends on the data. Report together:
   - the number of false triggers;
   - the number of distinct storms behind them;
   - the rate per recorded year;
   - the Poisson interval, marked as possibly too narrow when triggers are grouped.

   With enough storms, an interval computed per storm (e.g. bootstrap over storms or seasons) would be
   more appropriate. Several false triggers in the same wet season point the same way.
5. **Sensitivity**: compare all thresholds from 30 to 70 mm. Do not pick the one that maximises recall;
   recall alone always favours the lowest threshold.

Check these before reading `thresholds.csv`:

- **Every flood date is matched.** An unmatched date means missing rain, a wrong date or a wrong zone. Fix
  the inputs; do not drop the flood.
- **Coverage is at least 90 %** in every zone.
- **Few flood spells have missing hours.**

## 5. Deciding on the threshold

Compare the results at 44 mm with the IMERG study: 24 of 28 flood zones caught on calendar days, and about
0.65 triggers per zone per year without a mapped flood.

**Keep a held-out set.** If the Tunisian records are used to choose a new threshold, the same records can no
longer show how good it is. Before looking at any result, set aside the most recent rainy seasons (for
example the last third of the period, and at least a few floods):

1. Fix the cut date first, in the dry season (e.g. `2019-07-01`), so that no storm falls on both sides.
   All the zones flooded by one storm then stay in the same set.
2. Run the script on the earlier seasons only (`--period-end 2019-07-01`), and choose the threshold and any
   other setting there (`--max-missing-h`, `--match-days`, ...).
3. Write that threshold in a copy of `trigger.json` and run the script **once** on the held-out seasons
   (`--period-start 2019-07-01 --trigger <copy>`), with the same settings. Report those figures.
4. Change nothing after seeing them. If the threshold or the rules are changed afterwards, the held-out set
   has been used for tuning and is no longer independent; a new independent test then needs new seasons.

If the records are kept at 44 mm without any change, the whole set tests a threshold fitted on other data
(IMERG, 13 Mediterranean events, no Tunisian gauge). It is independent of the *fitting*, provided the
settings are fixed before looking at the results. It is **not** an independent test of any change decided
after seeing it: a threshold chosen on these records needs the held-out split above.

**Check that the held-out set is large enough**, before choosing the cut and without running the script:
count the flood dates on each side in `inm_floods.csv`, and the rainy seasons of hourly records. The held-out
set should have at least about 10 floods and several seasons. Otherwise its intervals will be too wide to
support any conclusion. In that case, move the cut now (on these counts only), or keep 44 mm and use the
whole set as a test of the existing threshold. **Never move the cut after seeing results**. If the test set
turns out too small, report that the evidence is insufficient.

**What a time split does not guarantee.** It keeps each storm on one side, but both sides share the same
zones, the same stations and the same climate. It shows that the threshold holds on later years in the same
places, not that it holds in other regions (south, Sahel) or under a changing climate. Write these limits in
the report. A zone left out entirely (leave-one-zone-out) would test geographic transfer, but needs floods in
many zones.

- **44 mm catches most Tunisian floods with an acceptable false trigger rate:** keep it, and record the
  Tunisian figures in `trigger.json` (`validation`).
- **It misses many floods**, or **gauges read systematically higher or lower than IMERG:** recalibrate on the
  Tunisian records. Choose the new threshold on the earlier seasons only (leave-one-flood-out there, as in
  the IMERG study), then judge it once on the held-out seasons, never on the set it was chosen on.
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
