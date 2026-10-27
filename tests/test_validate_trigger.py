"""Tests of the trigger validation on small hand-built rain series.

    python -m tests.test_validate_trigger      (or pytest, if installed)
"""

import numpy as np
import pandas as pd

from flood_risk.real.validate_trigger import DEFAULTS, run, spells, zone_series

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


def test_run_end_to_end():
    rows = []
    for zone, s in [("nabeul", series(("2020-01-10 20:00", 8, 6.0), ("2020-01-20 10:00", 4, 3.0))),
                    ("tunis", series(("2020-01-20 10:00", 10, 5.0)))]:
        rows.append(pd.DataFrame({"zone": zone, "station": "x", "time": s.index, "rain_mm": s.to_numpy()}))
    floods = pd.DataFrame({"zone": ["nabeul", "tunis", "sfax"], "date": ["2020-01-11", "2020-01-25", "2020-01-10"]})
    table, coverage, res, floods, years = run(pd.concat(rows), floods, 44.0, DEFAULTS)
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
