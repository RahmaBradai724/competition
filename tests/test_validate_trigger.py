"""Tests of the trigger validation on small hand-built rain series.

    python -m tests.test_validate_trigger      (or pytest, if installed)
"""

import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from flood_risk.real.validate_trigger import (DEFAULTS, check_rain, hour_status, intervals, poisson_rate,
                                              read_inputs, restrict, run, spells, storms, wilson, zone_series)

HOURS = pd.date_range("2020-01-01", "2020-01-31 23:00", freq="h")


def series(*storms):
    """Hourly rain: zero everywhere, `mm` per hour from `start` for `hours` hours."""
    s = pd.Series(0.0, index=HOURS)
    for start, hours, mm in storms:
        s[pd.Timestamp(start):pd.Timestamp(start) + pd.Timedelta(hours=hours - 1)] = mm
    return s


def test_storm_across_midnight():
    # 8 h x 6 mm = 48 mm split 24 / 24 over two days: only the rolling window reaches 44 mm.
    sp = spells(series(("2020-01-10 20:00", 8, 6.0)), [])
    assert len(sp) == 1
    assert sp.rolling_24h_mm[0] == 48 and sp.calendar_day_mm[0] == 24


def test_storm_within_one_day_gives_same_value():
    sp = spells(series(("2020-01-10 06:00", 8, 6.0)), [])
    assert sp.rolling_24h_mm[0] == sp.calendar_day_mm[0] == 48


def test_spell_split_needs_more_than_gap():
    # 24 dry hours between the two storms: two spells; 23 dry hours: one spell.
    two = spells(series(("2020-01-05 00:00", 2, 5.0), ("2020-01-06 02:00", 2, 5.0)), [])
    one = spells(series(("2020-01-05 00:00", 2, 5.0), ("2020-01-06 01:00", 2, 5.0)), [])
    assert len(two) == 2 and len(one) == 1


def test_small_spells_dropped():
    assert spells(series(("2020-01-05 00:00", 2, 2.0)), []).empty   # 4 mm < 5 mm


def test_flood_reported_day_after():
    s = series(("2020-01-10 10:00", 6, 10.0))
    flood = [pd.Timestamp("2020-01-11")]
    assert spells(s, flood).flood[0] == 1
    assert spells(s, flood, match_days=0).flood[0] == 0
    assert spells(s, [pd.Timestamp("2020-01-13")]).flood[0] == 0


def test_flood_date_counted_once():
    # One spell ends on the 10th, the next starts on the 11th, flood on the 11th: only the second is a flood spell.
    sp = spells(series(("2020-01-10 00:00", 3, 3.0), ("2020-01-11 04:00", 3, 3.0)), [pd.Timestamp("2020-01-11")])
    assert len(sp) == 2 and sp.flood.tolist() == [0, 1]


def test_two_spells_same_day():
    # Possible only with a gap shorter than 24 h: the flood goes to the wettest spell of that day only.
    s = series(("2020-01-10 01:00", 2, 3.0), ("2020-01-10 12:00", 2, 10.0))
    sp = spells(s, [pd.Timestamp("2020-01-10")], gap_h=6)
    assert len(sp) == 2 and sp.flood.tolist() == [0, 1]
    assert len(spells(s, [pd.Timestamp("2020-01-10")])) == 1   # default 24 h gap: one spell


def test_wettest_spell_by_total_not_peak():
    # 3 h x 10 mm (30 mm, intense) against 10 h x 2 mm (20 mm, light): the intense one is wetter that day.
    s = series(("2020-01-10 00:00", 10, 2.0), ("2020-01-10 17:00", 3, 10.0))
    sp = spells(s, [pd.Timestamp("2020-01-10")], gap_h=6)
    assert sp.flood.tolist() == [0, 1] and sp.flood_ambiguous.tolist() == [0, 1]
    # 12 h x 2 mm (24 mm) against 1 h x 20 mm: the long light spell is wetter that day.
    s = series(("2020-01-10 00:00", 12, 2.0), ("2020-01-10 20:00", 1, 20.0))
    assert spells(s, [pd.Timestamp("2020-01-10")], gap_h=6).flood.tolist() == [1, 0]


def test_missing_hours_can_move_the_flood_and_are_flagged():
    # The second spell is the wetter one (30 mm), but the gauge stops after its first hour: it looks like
    # 10 mm and the flood goes to the first spell (20 mm). The date is flagged ambiguous so it can be checked
    # by hand, and both spells report the 2 missing hours, which fall within their 24 h windows.
    s = series(("2020-01-10 00:00", 10, 2.0), ("2020-01-10 17:00", 3, 10.0))
    s[pd.Timestamp("2020-01-10 18:00"):pd.Timestamp("2020-01-10 19:00")] = np.nan
    sp = spells(s, [pd.Timestamp("2020-01-10")], gap_h=6)
    assert sp.flood.tolist() == [1, 0] and sp.flood_ambiguous.tolist() == [1, 0]
    assert sp.missing_hours.tolist() == [2, 2]


def test_gauge_stopping_mid_storm_is_flagged():
    # The last recorded hour ends the spell, but the hours lost after it still count as missing.
    s = series(("2020-01-10 00:00", 6, 8.0))
    s[pd.Timestamp("2020-01-10 03:00"):pd.Timestamp("2020-01-10 08:00")] = np.nan
    sp = spells(s, [])
    assert sp.end[0] == pd.Timestamp("2020-01-10 02:00") and sp.missing_hours[0] == 6


def test_single_candidate_not_ambiguous():
    sp = spells(series(("2020-01-10 10:00", 6, 10.0)), [pd.Timestamp("2020-01-10")])
    assert sp.flood_ambiguous[0] == 0


def test_trailing_max_equals_centred_max_on_same_series():
    # Random storms with random missing hours: on the same hourly series, the highest centred window
    # (t - 12 h to t + 12 h) over a spell equals the highest trailing 24 h the script reports.
    rng = np.random.default_rng(1)
    for _ in range(20):
        s = pd.Series(np.where(rng.random(len(HOURS)) < 0.05, rng.gamma(0.8, 6, len(HOURS)), 0.0), index=HOURS)
        s[rng.random(len(HOURS)) < 0.05] = np.nan
        sp = spells(s, [])
        filled = s.fillna(0).to_numpy()
        cum = np.concatenate([[0], np.cumsum(filled)])
        for start, end, value in zip(sp.start, sp.end, sp.rolling_24h_mm):
            i0, i1 = HOURS.get_loc(start), HOURS.get_loc(end)
            centred = [cum[min(k + 12, len(filled))] - cum[max(k - 12, 0)] for k in range(i0 - 12, i1 + 12)]
            assert abs(max(centred) - value) < 1e-9


def test_missed_flood_with_missing_hours_counted():
    rows = []
    s = series(("2020-01-10 02:00", 10, 5.0))
    s[pd.Timestamp("2020-01-10 05:00"):pd.Timestamp("2020-01-10 06:00")] = np.nan   # 40 mm recorded of 50
    rain = pd.DataFrame({"zone": "z", "station": "x", "time": s.index, "rain_mm": s.to_numpy()}).dropna()
    res = run(rain, pd.DataFrame({"zone": ["z"], "date": ["2020-01-10"]}), 44.0, DEFAULTS)[2]
    r = res.set_index(["window", "threshold"]).loc[("rolling_24h_mm", 44)]
    assert r.flood_spells_caught == "0/1" and r.missed_with_missing_hours == 1


def test_flood_in_other_zone_flagged():
    sp = spells(series(("2020-01-10 10:00", 6, 10.0)), [], [pd.Timestamp("2020-01-10")])
    assert sp.flood[0] == 0 and sp.flood_other_zone[0] == 1


def test_observed_24h_reached_time():
    sp = spells(series(("2020-01-10 00:00", 10, 5.0)), [], threshold=44)
    assert sp.observed_24h_reached[0] == pd.Timestamp("2020-01-10 08:00")   # 9 h x 5 mm = 45 mm


def test_wettest_station_total_and_missing_hours():
    t = pd.date_range("2020-01-01", periods=4, freq="h")
    rain = pd.DataFrame({"station": ["a"] * 4 + ["b"] * 3, "time": list(t) + list(t[[0, 1, 3]]),
                         "rain_mm": [1, 2, 3, 4, 5, 0, 0]})
    st = zone_series(rain)
    assert st.a.tolist() == [1, 2, 3, 4] and np.isnan(st.b[t[2]])
    # Station a totals 10 mm, b 5 mm. Taking the wettest station each hour would give 5 + 2 + 3 + 4 = 14 mm.
    sp = spells(st, [], min_spell_mm=1)
    assert sp.rolling_24h_mm[0] == sp.calendar_day_mm[0] == 10
    assert sp.missing_hours[0] == 0   # b is missing at t[2], but a recorded it
    rain = rain[~((rain.station == "a") & (rain.time == t[2]))]
    assert zone_series(rain).loc[t[2]].isna().all()


def test_recorded_hours_counted_once_per_zone():
    # Two stations recording the same 744 hours: 744 hours recorded, not 1488. A third station recording
    # only hours missing elsewhere adds them.
    s = series(("2020-01-20 10:00", 2, 3.0))
    one = pd.DataFrame({"zone": "z", "station": "a", "time": s.index, "rain_mm": s.to_numpy()})
    two = pd.concat([one, one.assign(station="b")])
    no_floods = pd.DataFrame({"zone": [], "date": []})
    assert run(one, no_floods, 44.0, DEFAULTS)[1].hours_with_data[0] == 744
    assert run(two, no_floods, 44.0, DEFAULTS)[1].hours_with_data[0] == 744
    holes = pd.concat([one[one.time >= "2020-01-16"], one[one.time < "2020-01-11"].assign(station="c")])
    assert run(holes, no_floods, 44.0, DEFAULTS)[1].hours_with_data[0] == 744 - 5 * 24


def test_missing_hours_inside_spell():
    # 10 h x 5 mm with 2 hours missing: both windows sum only what was recorded (40 mm), and the spell is flagged.
    s = series(("2020-01-10 02:00", 10, 5.0))
    s[pd.Timestamp("2020-01-10 05:00"):pd.Timestamp("2020-01-10 06:00")] = np.nan
    sp = spells(s, [], threshold=44)
    assert len(sp) == 1 and sp.missing_hours[0] == 2
    assert sp.rolling_24h_mm[0] == sp.calendar_day_mm[0] == 40
    assert pd.isna(sp.observed_24h_reached[0])


def test_empty_value_is_missing_not_zero():
    t = pd.date_range("2020-01-01", periods=3, freq="h")
    rain = pd.DataFrame({"station": "a", "time": t, "rain_mm": [1.0, np.nan, 0.0]})
    st = zone_series(rain)
    assert st.a[t[0]] == 1 and np.isnan(st.a[t[1]]) and st.a[t[2]] == 0


def test_hour_status():
    # a: in service 00-05 h, value missing at 02 h; nothing in service at 06-07 h; b back at 08 h.
    t = pd.date_range("2020-01-01", periods=9, freq="h")
    rain = pd.DataFrame({"station": ["a"] * 6 + ["b"],
                         "time": list(t[:6]) + [t[8]],
                         "rain_mm": [0.0, 2.0, np.nan, 0.0, 1.0, 0.0, 3.0]})
    st = zone_series(rain)
    service = rain.groupby("station").time.agg(start="min", end="max").reset_index()
    status = hour_status(st, service)
    assert status.tolist() == ["zero", "rain", "not_recorded", "zero", "rain", "zero",
                               "no_station", "no_station", "rain"]
    # A station declared in service at 06-07 h turns those hours into faults rather than gaps in coverage.
    service = pd.concat([service, pd.DataFrame({"station": ["b"], "start": [t[6]], "end": [t[7]]})])
    assert hour_status(st, service)[t[6]] == "not_recorded"


def test_recall_on_complete_spells():
    # Two flood spells: one complete and caught, one with 2 missing hours and missed (40 of 50 mm).
    s = series(("2020-01-05 02:00", 10, 5.0), ("2020-01-20 02:00", 10, 5.0))
    s[pd.Timestamp("2020-01-20 05:00"):pd.Timestamp("2020-01-20 06:00")] = np.nan
    rain = pd.DataFrame({"zone": "z", "station": "x", "time": s.index, "rain_mm": s.to_numpy()})
    floods = pd.DataFrame({"zone": ["z", "z"], "date": ["2020-01-05", "2020-01-20"]})
    out = run(rain, floods, 44.0, DEFAULTS)
    r = out[2].set_index(["window", "threshold"]).loc[("rolling_24h_mm", 44)]
    assert r.flood_spells_caught == "1/2" and r.recall == 0.5
    assert r.complete_flood_spells_caught == "1/1" and r.recall_complete == 1
    assert r.missed_with_missing_hours == 1
    assert out[5]["flood_spells_incomplete"] == 1
    z = out[1].iloc[0]
    assert z.hours_not_recorded == 2 and z.hours_rain == 18 and z.hours_with_data == 742
    # Allowing up to 2 missing hours makes that spell count as complete.
    r = run(rain, floods, 44.0, {**DEFAULTS, "max_missing_h": 2})[2].set_index(["window", "threshold"])
    assert r.loc[("rolling_24h_mm", 44), "recall_complete"] == 0.5
    # One missing hour allowed: the spell with 2 is still incomplete and stays out of the denominator.
    r = run(rain, floods, 44.0, {**DEFAULTS, "max_missing_h": 1})[2].set_index(["window", "threshold"])
    assert r.loc[("rolling_24h_mm", 44), "complete_flood_spells_caught"] == "1/1"


def test_incomplete_spells_out_of_complete_recall_denominator():
    # Three flood spells: complete caught, complete missed (30 mm), incomplete missed. recall_complete = 1/2.
    s = series(("2020-01-03 02:00", 10, 5.0), ("2020-01-12 02:00", 6, 5.0), ("2020-01-22 02:00", 10, 5.0))
    s[pd.Timestamp("2020-01-22 05:00"):pd.Timestamp("2020-01-22 06:00")] = np.nan   # 40 mm recorded of 50
    rain = pd.DataFrame({"zone": "z", "station": "x", "time": s.index, "rain_mm": s.to_numpy()})
    floods = pd.DataFrame({"zone": ["z"] * 3, "date": ["2020-01-03", "2020-01-12", "2020-01-22"]})
    r = run(rain, floods, 44.0, DEFAULTS)[2].set_index(["window", "threshold"]).loc[("rolling_24h_mm", 44)]
    assert r.flood_spells_caught == "1/3" and r.complete_flood_spells_caught == "1/2"
    assert r.recall_complete == 0.5 and r.missed_with_missing_hours == 1


def write(folder, name, text):
    path = Path(folder) / name
    path.write_text(text)
    return path


def test_empty_cells_stay_missing_from_csv_to_24h_windows():
    # From the CSV file: a empty at 01 h and b has 4 mm (counts 4), both empty at 02 h (missing),
    # a 0 at 03 h (recorded zero); b row absent at 00 h and 03 h.
    with tempfile.TemporaryDirectory() as d:
        rain_csv = write(d, "rain.csv", "zone,station,time,rain_mm\n"
                         "z,a,2020-01-01 00:00,3\nz,a,2020-01-01 01:00,\nz,b,2020-01-01 01:00,4\n"
                         "z,a,2020-01-01 02:00,\nz,b,2020-01-01 02:00,\nz,a,2020-01-01 03:00,0\n")
        rain, floods, _ = read_inputs(rain_csv, write(d, "floods.csv", "zone,date\n"))
    assert rain.rain_mm.isna().sum() == 3
    st = zone_series(rain[rain.zone == "z"])
    assert np.isnan(st.loc["2020-01-01 02:00"]).all() and st.a["2020-01-01 03:00"] == 0
    sp = spells(st, [], min_spell_mm=1)
    # Station totals: a 3 mm, b 4 mm; the wettest station gives 4, the empty cells add nothing.
    assert len(sp) == 1 and sp.rolling_24h_mm[0] == 4 and sp.calendar_day_mm[0] == 4
    assert sp.missing_hours[0] == 1   # only 02 h is missing for the zone
    z = run(rain, floods, 44.0, {**DEFAULTS, "min_spell_mm": 1.0})[1].iloc[0]
    assert (z.hours_rain, z.hours_zero, z.hours_not_recorded, z.hours_no_station) == (2, 1, 1, 0)


def test_station_periods_from_file():
    # Station a: data 00-09 h on 1 Jan, 2 Jan with no value. Declared in service on "2020-01-01" only.
    t = pd.date_range("2020-01-01", "2020-01-02 23:00", freq="h")
    values = ["1" if h < 10 else "" for h in range(24)] + [""] * 23 + ["2"]
    with tempfile.TemporaryDirectory() as d:
        rain_csv = write(d, "rain.csv", "zone,station,time,rain_mm\n" +
                         "".join(f"z,a,{x:%Y-%m-%d %H:%M},{v}\n" for x, v in zip(t, values)))
        floods_csv = write(d, "floods.csv", "zone,date\n")
        stations_csv = write(d, "stations.csv", "station,start,end\na,2020-01-01,2020-01-01\n")
        rain, floods, service = read_inputs(rain_csv, floods_csv, stations_csv)
        assert service.end[0] == pd.Timestamp("2020-01-01 23:00")   # a date alone covers the whole day
        status = hour_status(zone_series(rain), service)
        # 1 Jan 10-23 h: in service, no value -> fault. 2 Jan 00-22 h: out of service -> no station.
        # 2 Jan 23 h: a value outside the declared period still counts.
        assert (status["2020-01-01 10:00":"2020-01-01 23:00"] == "not_recorded").all()
        assert (status["2020-01-02 00:00":"2020-01-02 22:00"] == "no_station").all()
        assert status["2020-01-02 23:00"] == "rain"
        # Explicit times are taken as given, both ends included.
        stations_csv = write(d, "stations.csv", "station,start,end\na,2020-01-01 00:00,2020-01-01 12:00\n")
        status = hour_status(zone_series(rain), read_inputs(rain_csv, floods_csv, stations_csv)[2])
        assert status["2020-01-01 12:00"] == "not_recorded" and status["2020-01-01 13:00"] == "no_station"
        # Empty end: in service until the last record.
        stations_csv = write(d, "stations.csv", "station,start,end\na,2020-01-01,\n")
        assert read_inputs(rain_csv, floods_csv, stations_csv)[2].end[0] == t[-1]


def test_station_missing_from_file_uses_its_records():
    t = pd.date_range("2020-01-01", periods=4, freq="h")
    rain = pd.DataFrame({"zone": "z", "station": ["a", "a", "b", "b"], "time": [t[0], t[1], t[2], t[3]],
                         "rain_mm": [0.0, 0.0, np.nan, 0.0]})
    service = pd.DataFrame({"station": ["a"], "start": [t[0]], "end": [t[1]]})
    z = run(rain, pd.DataFrame({"zone": [], "date": []}), 44.0, DEFAULTS, service)[1].iloc[0]
    assert z.hours_not_recorded == 1 and z.hours_no_station == 0   # b in service 02-03 h from its rows
    assert z.spells == 0 and z.false_triggers_per_year == 0          # a dry zone does not stop the run


def test_dry_zone_next_to_wet_zone():
    wet = series(("2020-01-10 00:00", 10, 5.0))
    rain = pd.concat([pd.DataFrame({"zone": "wet", "station": "x", "time": HOURS, "rain_mm": wet.to_numpy()}),
                      pd.DataFrame({"zone": "dry", "station": "y", "time": HOURS, "rain_mm": 0.0})])
    table, zones, res, floods, years, summary = run(rain, pd.DataFrame({"zone": ["dry"], "date": ["2020-01-10"]}),
                                                     44.0, DEFAULTS)
    assert len(table) == 1 and summary["zones"] == 2 and summary["flood_dates_unmatched"] == 1
    assert zones.set_index("zone").spells.to_dict() == {"dry": 0, "wet": 1} and years == 2 * 744 / 8766


def test_duplicates():
    t = pd.date_range("2020-01-01", periods=3, freq="h")
    rain = pd.DataFrame({"zone": "z", "station": "a", "time": [t[0], t[0], t[1], t[2], t[2]],
                         "rain_mm": [2.0, 2.0, np.nan, np.nan, np.nan]})
    clean, dropped = check_rain(rain)
    assert dropped == 2 and len(clean) == 3   # 2 mm twice, and an empty cell twice, are the same record
    out = run(rain, pd.DataFrame({"zone": [], "date": []}), 44.0, {**DEFAULTS, "min_spell_mm": 1.0})
    assert out[5]["duplicate_rows_dropped"] == 2 and out[1].hours_rain[0] == 1   # 2 mm counted once
    for values in ([2.0, 3.0], [2.0, np.nan]):   # two different values for one station and hour: stop
        bad = pd.DataFrame({"zone": "z", "station": "a", "time": [t[0], t[0]], "rain_mm": values})
        try:
            check_rain(bad)
            raise AssertionError("conflicting duplicates accepted")
        except ValueError:
            pass
    # A station serving two zones appears once per zone with the same values: accepted, nothing dropped.
    shared = pd.concat([rain.iloc[[0, 2]], rain.iloc[[0, 2]].assign(zone="y")])
    assert check_rain(shared)[1] == 0
    # The same station with different values in two zones is still an error.
    try:
        check_rain(pd.concat([rain.iloc[[0]], rain.iloc[[0]].assign(zone="y", rain_mm=5.0)]))
        raise AssertionError("conflicting values across zones accepted")
    except ValueError:
        pass

def raises(f, *args):
    try:
        f(*args)
    except ValueError:
        return True
    return False


def ten_minutes(values, start="2020-01-01 00:00", station="a"):
    t = pd.date_range(start, periods=len(values), freq="10min")
    return pd.DataFrame({"zone": "z", "station": station, "time": t, "minutes": 10, "rain_mm": values})


def test_sub_hourly_records():
    # A full hour of 10-minute records is summed.
    st = zone_series(intervals(ten_minutes([1.0, 0.5, 0, 0, 2.0, 0.5])))
    assert st.a.tolist() == [4.0]
    # One 10-minute value missing (empty or absent): the hour is missing, not 3.5 mm.
    assert np.isnan(zone_series(intervals(ten_minutes([1.0, np.nan, 0, 0, 2.0, 0.5]))).a.iloc[0])
    assert np.isnan(zone_series(intervals(ten_minutes([1.0, 0, 0, 0, 2.0]))).a.iloc[0])
    # Hourly and 10-minute records of different stations in the same zone.
    hourly = pd.DataFrame({"zone": "z", "station": "b", "time": pd.to_datetime(["2020-01-01 00:00"]),
                           "minutes": 60, "rain_mm": [7.0]})
    st = zone_series(intervals(pd.concat([ten_minutes([1.0] * 6), hourly])))
    assert st.a.iloc[0] == 6 and st.b.iloc[0] == 7


def test_overlapping_or_misaligned_records_stop():
    # An hourly total at 00:00 next to 10-minute records of the same hour would count the rain twice.
    both = pd.concat([ten_minutes([1.0] * 6), ten_minutes([6.0]).assign(minutes=60)])
    assert raises(intervals, both.drop_duplicates(["time"], keep="last"))
    assert raises(intervals, ten_minutes([1.0], start="2020-01-01 00:55"))           # crosses the hour
    assert raises(intervals, ten_minutes([1.0]).assign(minutes=90))                  # longer than an hour
    assert raises(intervals, ten_minutes([1.0], start="2020-01-01 00:10").drop(columns="minutes"))   # off the hour
    assert not raises(intervals, ten_minutes([1.0], start="2020-01-01 03:00").drop(columns="minutes"))
    # The same station in two zones is not an overlap.
    two = ten_minutes([1.0] * 6)
    assert not raises(intervals, pd.concat([two, two.assign(zone="y")]))


def test_hour_complete_only_with_60_distinct_minutes():
    # Records of uneven length that tile the hour exactly: complete.
    tiles = pd.DataFrame({"zone": "z", "station": "a", "minutes": [10, 30, 20], "rain_mm": [1.0, 2.0, 3.0],
                          "time": pd.to_datetime(["2020-01-01 00:00", "2020-01-01 00:10", "2020-01-01 00:40"])})
    assert zone_series(intervals(tiles)).a.iloc[0] == 6
    # A 10-minute hole: 50 minutes covered, the hour is missing.
    hole = tiles.assign(minutes=[10, 20, 20])
    assert np.isnan(zone_series(intervals(hole)).a.iloc[0])
    # Filling the hole by stretching a record over the next one is an overlap: stop.
    assert raises(intervals, tiles.assign(minutes=[10, 40, 20]))
    # An overlap with a record two places back is still caught (records sorted by start).
    far = pd.DataFrame({"zone": "z", "station": "a", "minutes": [50, 10, 10], "rain_mm": [1.0, 1.0, 1.0],
                        "time": pd.to_datetime(["2020-01-01 00:00", "2020-01-01 00:10", "2020-01-01 00:20"])})
    assert raises(intervals, far)


def test_restrict_to_period():
    s = series(("2020-01-05 00:00", 10, 5.0), ("2020-01-25 00:00", 10, 5.0))
    rain = pd.DataFrame({"zone": "z", "station": "x", "time": s.index, "rain_mm": s.to_numpy()})
    floods = pd.DataFrame({"zone": ["z", "z"], "date": ["2020-01-05", "2020-01-25"]})
    early = restrict(rain, floods, None, "2020-01-15")
    late = restrict(rain, floods, "2020-01-15", None)
    assert len(early[0]) + len(late[0]) == len(rain) and early[1].date.tolist() == ["2020-01-05"]
    out = run(*late, 44.0, DEFAULTS)
    assert out[5]["flood_spells"] == 1 and out[4] == (744 - 14 * 24) / 8766


def test_confidence_intervals():
    # Reference values (Wilson 95 %): 1/2 -> 0.095-0.905; 9/10 -> 0.596-0.982; 0/0 -> undefined.
    assert np.allclose(wilson(1, 2), (0.0945, 0.9055), atol=1e-3)
    assert np.allclose(wilson(9, 10), (0.5958, 0.9821), atol=1e-3)
    assert np.isnan(wilson(0, 0)).all()
    # Exact Poisson 95 %: 0 events in 1 year -> 0-3.69; 5 events in 10 years -> 0.162-1.167 per year.
    assert np.allclose(poisson_rate(0, 1.0), (0.0, 3.689), atol=1e-3)
    assert np.allclose(poisson_rate(5, 10.0), (0.1624, 1.1668), atol=1e-3)
    # In the scan: 1 complete flood caught of 2 gives a very wide interval.
    s = series(("2020-01-05 02:00", 10, 5.0), ("2020-01-20 02:00", 6, 5.0))
    rain = pd.DataFrame({"zone": "z", "station": "x", "time": s.index, "rain_mm": s.to_numpy()})
    r = run(rain, pd.DataFrame({"zone": ["z", "z"], "date": ["2020-01-05", "2020-01-20"]}), 44.0, DEFAULTS)[2]
    r = r.set_index(["window", "threshold"]).loc[("rolling_24h_mm", 44)]
    assert r.recall_complete == 0.5 and r.recall_complete_low < 0.1 and r.recall_complete_high > 0.9


def test_false_triggers_grouped_by_storm():
    # One storm over three zones at once, and a later one over a single zone: 4 false triggers, 2 storms.
    rows = []
    for zone in ["a", "b", "c"]:
        s = series(("2020-01-05 02:00", 10, 5.0)) if zone != "c" else series(("2020-01-05 06:00", 10, 5.0),
                                                                             ("2020-01-25 00:00", 10, 5.0))
        rows.append(pd.DataFrame({"zone": zone, "station": zone, "time": s.index, "rain_mm": s.to_numpy()}))
    r = run(pd.concat(rows), pd.DataFrame({"zone": [], "date": []}), 44.0, DEFAULTS)[2]
    r = r.set_index(["window", "threshold"]).loc[("rolling_24h_mm", 44)]
    assert r.spells_triggered_without_flood == "4/4" and r.false_trigger_storms == 2
    # Spells that only touch end to start are still two storms; nested ones are one.
    sp = pd.DataFrame({"start": pd.to_datetime(["2020-01-01 00:00", "2020-01-01 05:00", "2020-01-01 01:00"]),
                       "end": pd.to_datetime(["2020-01-01 04:00", "2020-01-01 06:00", "2020-01-01 02:00"])})
    assert storms(sp) == 2 and storms(sp.iloc[:0]) == 0


def test_time_label_end():
    # Records stamped at the end of their interval: 00:10 ... 01:00 is the hour starting at 00:00.
    rec = ten_minutes([1.0] * 6, start="2020-01-01 00:10")
    st = zone_series(intervals(rec, "end"))
    assert st.index.tolist() == [pd.Timestamp("2020-01-01 00:00")] and st.a.iloc[0] == 6
    # Read with the wrong label, the same records split into two incomplete hours, both missing.
    st = zone_series(intervals(rec, "start"))
    assert len(st) == 2 and st.a.isna().all()
    # Hourly records stamped at the end of the hour (no `minutes` column).
    h = pd.DataFrame({"zone": "z", "station": "a", "time": pd.to_datetime(["2020-01-01 01:00"]), "rain_mm": [3.0]})
    assert intervals(h, "end").time.iloc[0] == pd.Timestamp("2020-01-01 00:00")



def test_values_outside_declared_service_kept_and_counted():
    # The file says a was out of service on 2 Jan, but a measured 3 mm at 05 h that day: the value counts
    # (rain), the other hours of 2 Jan are "no station", and the contradiction is counted.
    t = pd.date_range("2020-01-01", "2020-01-02 23:00", freq="h")
    values = [0.0] * 24 + [np.nan] * 5 + [3.0] + [np.nan] * 18
    rain = pd.DataFrame({"zone": "z", "station": "a", "time": t, "rain_mm": values})
    service = pd.DataFrame({"station": ["a"], "start": [t[0]], "end": [pd.Timestamp("2020-01-01 23:00")]})
    z = run(rain, pd.DataFrame({"zone": [], "date": []}), 44.0, DEFAULTS, service)
    row = z[1].iloc[0]
    assert (row.hours_zero, row.hours_rain, row.hours_no_station, row.hours_not_recorded) == (24, 1, 23, 0)
    assert row.values_outside_service == 1 and z[5]["values_outside_service"] == 1


def test_run_end_to_end():
    rows = []
    for zone, s in [("nabeul", series(("2020-01-10 20:00", 8, 6.0), ("2020-01-20 10:00", 4, 3.0))),
                    ("tunis", series(("2020-01-20 10:00", 10, 5.0)))]:
        rows.append(pd.DataFrame({"zone": zone, "station": zone + "_x", "time": s.index, "rain_mm": s.to_numpy()}))
    floods = pd.DataFrame({"zone": ["nabeul", "tunis", "sfax"], "date": ["2020-01-11", "2020-01-25", "2020-01-10"]})
    table, coverage, res, floods, years, summary = run(pd.concat(rows), floods, 44.0, DEFAULTS)
    assert summary["flood_spells"] == 1 and summary["flood_dates_unmatched"] == 2
    assert floods.matched.tolist() == [True, False, False]
    r = res.set_index(["window", "threshold"])
    assert r.loc[("rolling_24h_mm", 44), "flood_spells_caught"] == "1/1"
    assert r.loc[("calendar_day_mm", 44), "flood_spells_caught"] == "0/1"
    # Tunis 50 mm without a flood: one false trigger in 2 x 31 days of records.
    assert r.loc[("rolling_24h_mm", 44), "spells_triggered_without_flood"] == "1/2"
    assert abs(r.loc[("rolling_24h_mm", 44), "false_triggers_per_zone_per_year"] - 8766 / (2 * 744)) < 1e-9
    z = coverage.set_index("zone")
    assert z.false_triggers.tolist() == [0, 1] and abs(z.false_triggers_per_year["tunis"] - 8766 / 744) < 1e-9


def test_gaps_lower_the_denominator():
    # The same zone with its first 15 days missing: the years recorded drop from 744 h to 384 h.
    s = series(("2020-01-20 10:00", 10, 5.0))
    rain = pd.DataFrame({"zone": "z", "station": "x", "time": s.index, "rain_mm": s.to_numpy()})
    no_floods = pd.DataFrame({"zone": [], "date": []})
    full = run(rain, no_floods, 44.0, DEFAULTS)
    gap = run(rain[rain.time >= "2020-01-16"], no_floods, 44.0, DEFAULTS)
    assert full[4] == 744 / 8766 and gap[4] == 384 / 8766
    assert full[1].false_triggers[0] == gap[1].false_triggers[0] == 1


if __name__ == "__main__":
    tests = [f for name, f in sorted(globals().items()) if name.startswith("test_")]
    for f in tests:
        f()
        print("ok", f.__name__)
    print(f"{len(tests)} tests passed")
