"""Check the provisional rain trigger on hourly rain records (INM gauges), with the window used in operation.

    python -m flood_risk.real.validate_trigger --rain inm_hourly.csv --floods inm_floods.csv

File formats and sources: `docs/TRIGGER_VALIDATION.md`. Every choice below is a command-line option and is
written to `<out>/settings.json`, so a result can always be traced back to its definitions.

- Zone: the area the trigger watches (an `aoi` of the model). A zone can have several stations; the 24 h
  total of the wettest station counts, as the trigger takes the wettest cell's 24 h total in operation.
- Wet spell: starts at the first hour with rain >= `wet_mmh`; ends at the last wet hour before more than
  `gap_h` hours without a wet hour. Kept if its total reaches `min_spell_mm`.
- Flood spell: each flood date of the zone goes to one spell only: the spell whose days contain it (the
  wettest that day if several do, possible only when `gap_h` < 24), or else the last spell that ended at
  most `match_days` before it (floods are often reported the day after the rain). A date with several
  candidate spells is flagged (`flood_ambiguous`) for a manual check, since missing hours can make the
  wrong spell look wettest. All other spells count as spells without a flood. Those that overlap a flood in another zone
  are flagged (`flood_other_zone`).
- Alert: a spell whose highest rolling 24 h rain reaches the threshold. A spell gives at most one alert,
  even if the rain crosses the threshold twice.
- False triggers per zone per year: alerts on spells without a flood in all zones, divided by the years of
  hourly rain recorded in all zones (an hour is recorded when at least one station of the zone has it;
  8766 hours per year). Gaps therefore lower both the count and the denominator. This pooled rate weights
  zones by their record length; `zones.csv` gives the rate of each zone.
- Time of alert: `observed_24h_reached` is the end of the first 24 h of observed rain above the threshold,
  i.e. when a trigger fed with observations only (t - 24 h to t) fires. The operational window
  (t - 12 h to t + 12 h) reaches the same total 12 h earlier only if the 12 h forecast is perfect; the
  forecast is not part of this validation, so the real alert time is not measured here.

The threshold in `models/final/trigger.json` is never changed by this script.
"""

import argparse
import json
from pathlib import Path

import pandas as pd

DEFAULTS = {"wet_mmh": 0.2, "gap_h": 24, "min_spell_mm": 5.0, "match_days": 1}
THRESHOLDS = [30, 35, 40, 44, 50, 55, 60, 70]
WINDOWS = ["rolling_24h_mm", "calendar_day_mm"]


def zone_series(rain: pd.DataFrame) -> pd.DataFrame:
    """Hourly rain of a zone, one column per station, hours without a record left as NaN."""
    hourly = rain.pivot_table(index="time", columns="station", values="rain_mm", aggfunc="sum")
    return hourly.resample("h").sum(min_count=1)


def spells(stations, flood_days, other_flood_days=(), threshold=None, wet_mmh=0.2, gap_h=24,
           min_spell_mm=5.0, match_days=1) -> pd.DataFrame:
    """Wet spells of one zone with their rolling 24 h and calendar-day maxima.

    `stations` holds the hourly rain of each station (a Series for a single one). Spells are split on the
    wettest station each hour. The 24 h and daily totals are summed per station first and the wettest
    station is taken afterwards, as the trigger takes the wettest cell's 24 h total in operation.
    """
    stations = stations.to_frame() if isinstance(stations, pd.Series) else stations
    s = stations.max(axis=1)
    wet = s[s >= wet_mmh]
    if wet.empty:
        return pd.DataFrame()
    new = wet.index.to_series().diff() > pd.Timedelta(hours=gap_h)
    # Trailing 24 h; its maximum over the spell equals the centred window's. Missing hours count as 0.
    rolling = stations.rolling("24h", min_periods=1).sum().max(axis=1)
    daily = stations.resample("D").sum(min_count=1).max(axis=1)
    blocks = [(b.index[0], b.index[-1]) for _, b in wet.groupby(new.cumsum())]
    blocks = [(a, b) for a, b in blocks if s[a:b].sum() >= min_spell_mm]
    first_day = [a.normalize() for a, _ in blocks]
    last_day = [b.normalize() for _, b in blocks]
    lag = pd.Timedelta(days=match_days)

    def owner(d):
        """The spell a flood date belongs to, and whether another spell could also claim it: the wettest
        one that day among those containing it, else the last one ended within `lag`."""
        inside = [i for i in range(len(blocks)) if first_day[i] <= d <= last_day[i]]
        before = [i for i in range(len(blocks)) if last_day[i] < d <= last_day[i] + lag]
        if inside:
            day = s[d:d + pd.Timedelta(hours=23)]
            return max(inside, key=lambda i: day[blocks[i][0]:blocks[i][1]].sum()), len(inside) + len(before) > 1
        return (before[-1], len(before) > 1) if before else (None, False)

    matched, ambiguous = {}, set()
    for d in sorted(set(flood_days)):
        i, amb = owner(d)
        matched.setdefault(i, []).append(d)
        if amb:
            ambiguous.add(i)
    others = {owner(d)[0] for d in set(other_flood_days)}
    out = []
    for i, (start, end) in enumerate(blocks):
        window = rolling[start:end + pd.Timedelta(hours=23)]
        row = {"start": start, "end": end, "total_mm": s[start:end].sum(),
               "rolling_24h_mm": window.max(),
               "calendar_day_mm": daily.reindex(pd.date_range(first_day[i], last_day[i], freq="D")).max(),
               # every hour that enters the spell's 24 h totals, so a gauge that stops mid-storm is caught
               "missing_hours": int(s[start - pd.Timedelta(hours=23):end + pd.Timedelta(hours=23)].isna().sum()),
               "flood": int(i in matched), "flood_dates": ";".join(f"{d:%Y-%m-%d}" for d in matched.get(i, [])),
               "flood_ambiguous": int(i in ambiguous), "flood_other_zone": int(i in others)}
        if threshold is not None:
            above = window[window >= threshold]
            row["observed_24h_reached"] = above.index[0] if len(above) else pd.NaT
        out.append(row)
    return pd.DataFrame(out)


def scan(table: pd.DataFrame, col: str, years: float, thresholds) -> pd.DataFrame:
    pos, neg = table[table.flood == 1], table[table.flood == 0]
    return pd.DataFrame([{"window": col, "threshold": t,
                          "flood_spells_caught": f"{(pos[col] >= t).sum()}/{len(pos)}",
                          "recall": (pos[col] >= t).mean(),
                          # missed floods whose spell has missing hours: the miss may come from the gap
                          "missed_with_missing_hours": int(((pos[col] < t) & (pos.missing_hours > 0)).sum()),
                          "spells_triggered_without_flood": f"{(neg[col] >= t).sum()}/{len(neg)}",
                          "of_which_flood_other_zone": int(((neg[col] >= t) & (neg.flood_other_zone == 1)).sum()),
                          "false_triggers_per_zone_per_year": (neg[col] >= t).sum() / years}
                         for t in thresholds])


def run(rain: pd.DataFrame, floods: pd.DataFrame, threshold: float, settings: dict):
    """Spell table, per-zone coverage and threshold scan."""
    floods = floods.assign(date=pd.to_datetime(floods.date).dt.normalize())
    rows, coverage = [], []
    for zone, z in rain.groupby("zone"):
        st = zone_series(z)
        s = st.max(axis=1)   # an hour counts as recorded when at least one station recorded it
        coverage.append({"zone": zone, "stations": st.shape[1], "first": s.index[0], "last": s.index[-1],
                         "hours": len(s), "hours_with_data": int(s.notna().sum()), "coverage": s.notna().mean()})
        sp = spells(st, floods.loc[floods.zone == zone, "date"], floods.loc[floods.zone != zone, "date"],
                    threshold, **settings)
        rows.append(sp.assign(zone=zone))
    table = pd.concat(rows, ignore_index=True)
    coverage = pd.DataFrame(coverage)
    alert = table.rolling_24h_mm >= threshold
    per_zone = table.assign(caught=alert & (table.flood == 1), false=alert & (table.flood == 0)).groupby("zone").agg(
        spells=("flood", "size"), flood_spells=("flood", "sum"), caught=("caught", "sum"), false_triggers=("false", "sum"))
    coverage = coverage.merge(per_zone, left_on="zone", right_index=True, how="left")
    coverage["false_triggers_per_year"] = coverage.false_triggers / (coverage.hours_with_data / 8766)
    years = coverage.hours_with_data.sum() / 8766
    res = pd.concat([scan(table, c, years, sorted(set(THRESHOLDS) | {threshold})) for c in WINDOWS])

    matched = {(z, d) for z, ds in zip(table.zone, table.flood_dates) for d in ds.split(";") if d}
    floods["matched"] = [(z, f"{d:%Y-%m-%d}") in matched for z, d in zip(floods.zone, floods.date)]
    return table, coverage, res, floods, years


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rain", required=True)
    ap.add_argument("--floods", required=True)
    ap.add_argument("--trigger", default="models/final/trigger.json")
    ap.add_argument("--out", default="reports/tn_trigger")
    for k, v in DEFAULTS.items():
        ap.add_argument("--" + k.replace("_", "-"), type=type(v), default=v)
    args = ap.parse_args()
    settings = {k: getattr(args, k) for k in DEFAULTS}
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    threshold = json.loads(Path(args.trigger).read_text())["threshold_mm"]

    rain = pd.read_csv(args.rain, parse_dates=["time"])
    floods = pd.read_csv(args.floods)
    table, coverage, res, floods, years = run(rain, floods, threshold, settings)
    table.to_csv(out / "spells.csv", index=False)
    coverage.to_csv(out / "zones.csv", index=False)
    floods.to_csv(out / "floods_matched.csv", index=False)
    res.to_csv(out / "thresholds.csv", index=False)
    (out / "settings.json").write_text(json.dumps({**settings, "threshold_mm": threshold,
                                                   "rain": args.rain, "floods": args.floods}, indent=2))

    print(f"{table.zone.nunique()} zones, {years:.1f} zone-years of hourly rain, "
          f"{table.flood.sum()} flood spells, {(table.flood == 0).sum()} spells without flood")
    if (~floods.matched).any():
        print(f"\n{(~floods.matched).sum()} flood dates match no wet spell (zone absent, rain missing or wrong date):")
        print(floods[~floods.matched].to_string(index=False))
    if (coverage.coverage < 0.9).any():
        print("\nzones with less than 90 % of hours recorded:")
        print(coverage[coverage.coverage < 0.9].round(3).to_string(index=False))
    if table.missing_hours.sum():
        print(f"\nwarning: {int((table.missing_hours > 0).sum())} spells have missing hours "
              f"({int(((table.missing_hours > 0) & (table.flood == 1)).sum())} of them flood spells)")
    if table.flood_ambiguous.sum():
        print(f"\ncheck by hand: {int(table.flood_ambiguous.sum())} flood spells could also be a neighbouring spell")
    print("\n" + res.round(3).to_string(index=False))
    print(f"\nPer zone at {threshold} mm (rolling window):")
    print(coverage.drop(columns=["first", "last", "hours"]).round(3).to_string(index=False))
    print(f"\nCurrent threshold {threshold} mm (rolling window, as in operation):")
    print(res[(res.threshold == threshold) & (res.window == "rolling_24h_mm")].round(3).to_string(index=False))


if __name__ == "__main__":
    main()
