"""Hourly gauge rain of Tunisian synoptic stations, in the input format of `validate_trigger`.

    python -m flood_risk.real.synop_tn --start 2014-09-01 --end 2025-09-01

INM synoptic stations send their observations to the WMO network (SYNOP messages). NOAA archives them in the
Integrated Surface Database, freely available without a request:
https://noaa-global-hourly-pds.s3.amazonaws.com/<year>/<station>.csv

Rain comes in groups `AA1`-`AA4`: "hours,depth in 0.1 mm,condition,quality". Stations report different
periods (3, 6, 12, 18 or 24 h), and many 3-hour reports are missing. Each station's record is rebuilt on a
3-hour grid:

1. A 3-hour report gives its slot directly.
2. A longer total whose slots are all known but one gives that slot (total minus the others).
3. Repeated until nothing changes. Then a total whose remaining slots are still unknown is spread evenly
   over them, and those slots are marked with the length of that total (`resolution_h`).
4. Slots that no report covers stay missing.

Each 3-hour slot is spread evenly over its three hours. A 24 h total therefore lands within about 3 h of its
true window (or within the coarser resolution, where `resolution_h` says so), and the highest rolling 24 h rain
is slightly underestimated.

These are a few airport and town gauges, not the full INM and DGRE networks.
"""

import argparse
import glob
from pathlib import Path

import numpy as np
import pandas as pd

from .areas import raw_dir

S3 = "https://noaa-global-hourly-pds.s3.amazonaws.com/{year}/{station}.csv"
OUT = Path("data/tn_trigger")
SLOT = pd.Timedelta(hours=3)


def reports(station: str, folder: Path) -> pd.DataFrame:
    """Every rain total of a station: end time, length (h) and amount (mm); traces count as 0."""
    rows = []
    for f in sorted(glob.glob(str(folder / f"*_{station}.csv"))):
        d = pd.read_csv(f, dtype=str, usecols=lambda c: c == "DATE" or c.startswith("AA"))
        for c in [c for c in d.columns if c.startswith("AA")]:
            x = d[["DATE", c]].dropna(subset=[c])
            p = x[c].str.split(",", expand=True)
            rows.append(pd.DataFrame({"end": pd.to_datetime(x.DATE), "hours": p[0].astype(int),
                                      "mm": p[1].astype(int) / 10, "cond": p[2]}))
    if not rows:
        return pd.DataFrame(columns=["end", "hours", "mm"])
    r = pd.concat(rows)
    r = r[(r.mm < 999) & r.hours.isin([3, 6, 9, 12, 15, 18, 21, 24])]
    r = r[(r.end.dt.minute == 0) & (r.end.dt.hour % 3 == 0)]
    r.loc[r.cond == "2", "mm"] = 0.0
    # The same total can come twice (SYNOP and another message type): keep one.
    return r.groupby(["end", "hours"], as_index=False).mm.max()


def slots(rep: pd.DataFrame, start, end) -> pd.DataFrame:
    """3-hour slots (labelled by their end) with rain and the resolution it is known at."""
    grid = pd.date_range(pd.Timestamp(start) + SLOT, end, freq="3h")
    index = {t: i for i, t in enumerate(grid)}
    mm = np.full(len(grid), np.nan)
    res = np.full(len(grid), np.nan)
    totals = []
    for r in rep.sort_values("hours").itertuples():
        ids = [index.get(r.end - k * SLOT) for k in range(r.hours // 3)]
        if None not in ids:
            totals.append((r.hours, r.mm, ids))
    for h, total, ids in totals:
        if h == 3:
            mm[ids[0]], res[ids[0]] = total, 3
    changed = True
    while changed:
        changed = False
        for h, total, ids in totals:
            unknown = [i for i in ids if np.isnan(mm[i])]
            if len(unknown) == 1:
                mm[unknown[0]] = max(total - np.nansum(mm[ids]), 0.0)
                res[unknown[0]] = 3
                changed = True
    for h, total, ids in totals:
        unknown = [i for i in ids if np.isnan(mm[i])]
        if unknown:
            mm[unknown] = max(total - np.nansum(mm[ids]), 0.0) / len(unknown)
            res[unknown] = h
    return pd.DataFrame({"end": grid, "mm": mm, "resolution_h": res})


def hourly(sl: pd.DataFrame) -> pd.DataFrame:
    """Spread each slot over its three hours, labelled by the start of the hour."""
    out = []
    for k in (3, 2, 1):
        out.append(pd.DataFrame({"time": sl.end - pd.Timedelta(hours=k), "rain_mm": sl.mm / 3,
                                 "resolution_h": sl.resolution_h}))
    return pd.concat(out).sort_values("time").reset_index(drop=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stations", default=str(OUT / "synop_stations.csv"))
    ap.add_argument("--start", default="2014-09-01")
    ap.add_argument("--end", default="2025-09-01")
    ap.add_argument("--out", default=str(OUT / "synop_hourly.csv.gz"))
    args = ap.parse_args()
    folder = raw_dir("synop_tn")
    stations = pd.read_csv(args.stations, dtype={"station": str})
    frames, summary = [], []
    for st in stations.station.unique():
        sl = slots(reports(st, folder), args.start, args.end)
        h = hourly(sl)
        h = h[(h.time >= args.start) & (h.time < args.end)]
        known = sl.mm.notna()
        summary.append({"station": st, "name": stations.loc[stations.station == st, "name"].iloc[0],
                        "slots_known": known.mean(),
                        **{f"share_res_{r}h": (sl.resolution_h[known] == r).mean() for r in (3, 6, 12, 24)}})
        for zone in stations.loc[stations.station == st, "zone"]:
            frames.append(h.assign(zone=zone, station=st))
    out = pd.concat(frames)[["zone", "station", "time", "rain_mm", "resolution_h"]]
    out.to_csv(args.out, index=False, float_format="%.3f")
    summary = pd.DataFrame(summary)
    summary.to_csv(Path(args.out).with_name("synop_coverage.csv"), index=False, float_format="%.3f")
    print(summary.round(2).to_string(index=False))
    print(f"{len(out):,} rows -> {args.out}")


if __name__ == "__main__":
    main()
