"""Score the segments of a route at their ETA with a trained V2 model (FR-11 to FR-15).

    python -m flood_risk.predict --demo
    python -m flood_risk.predict --route my_route.csv

The route CSV has one row per segment with the raw features of schema.py at the segment's
ETA, plus `segment_id`, `eta_min`, `rain_interpolated` and `data_age_min`.
"""

import argparse
from datetime import datetime, timezone

import joblib
import numpy as np
import pandas as pd

from .features import FACTOR_GROUPS, drainage_vulnerability
from .schema import HISTORY_FEATURES, RAW_FEATURES


def confidence(df: pd.DataFrame) -> pd.DataFrame:
    """Rule-based confidence (section 7.3); the model probability says nothing about data quality."""
    c = pd.Series(1.0, index=df.index)
    reasons = [[] for _ in range(len(df))]

    def apply(mask, delta, why):
        nonlocal c
        c = c + np.where(mask, delta, 0.0)
        for i in np.flatnonzero(np.asarray(mask)):
            reasons[i].append(why)

    apply(df["rain_interpolated"] == 1, -0.20, "rainfall interpolated from hourly forecast")
    apply(df["data_age_min"] > 15, -0.20, "rainfall data older than 15 min")
    apply(df["data_age_min"] > 60, -0.15, "rainfall data older than 1 h")
    apply(df["osm_completeness"] < 0.5, -0.15, "area poorly mapped")
    apply(df["impervious_frac"] > 0.6, -0.10, "dense urban area, drain state unknown")
    apply(drainage_vulnerability(df) > 0.6, -0.10, "high estimated drainage vulnerability")
    apply(df["black_spot_count"] > 0, 0.10, "documented past floods here")
    c = c.clip(0.1, 1.0)
    label = np.select([c >= 0.7, c >= 0.45], ["High", "Medium"], "Low")
    return pd.DataFrame({"confidence": c.round(2), "confidence_level": label,
                         "confidence_notes": ["; ".join(r) for r in reasons]}, index=df.index)


def explain(bundle, df: pd.DataFrame, reference: pd.Series, top: int = 3) -> list:
    """Main contributing factors: probability drop when a factor group is set to a typical value."""
    base = bundle.predict_proba(df)
    drops = {}
    for name, cols in FACTOR_GROUPS.items():
        neutral = df.copy()
        for col in cols:
            if col in neutral.columns:
                neutral[col] = reference.get(col, 0.0)
        drops[name] = base - bundle.predict_proba(neutral)
    drops = pd.DataFrame(drops, index=df.index)
    return [", ".join(f"{k} (+{100 * v:.0f})" for k, v in row.nlargest(top).items() if v > 0.005) or "none dominant"
            for _, row in drops.iterrows()]


def display_score(p, thresholds) -> np.ndarray:
    """0..100 score anchored on the levels (25 Moderate, 50 High, 75 Very high).

    Floods are rare, so a calibrated probability of a few percent can already be High; showing
    it raw as "7/100" would read as safe. The probability is reported next to the score.
    """
    knots = [0, thresholds["Moderate"], thresholds["High"], thresholds["Very high"], 1]
    return np.round(np.interp(p, knots, [0, 25, 50, 75, 100])).astype(int)


def score_route(bundle, route: pd.DataFrame, data_time: str) -> pd.DataFrame:
    p = bundle.predict_proba(route)
    known = [c for c in RAW_FEATURES + HISTORY_FEATURES if c in route.columns]
    reference = pd.Series(bundle.trained_on.get("reference", {}), dtype=float).reindex(known)
    # Missing history means "no report": the neutral value is 0.
    reference = reference.fillna(route[known].median()).fillna(0.0)
    out = pd.DataFrame({
        "segment_id": route["segment_id"], "eta_min": route["eta_min"].round(1),
        "risk_score": display_score(p, bundle.thresholds),
        "flood_prob_pct": np.round(100 * p, 1),
        "level": bundle.predict_level(route),
    }, index=route.index)
    out = out.join(confidence(route))
    out["main_factors"] = explain(bundle, route, reference)
    out["data_timestamp"] = data_time
    return out


def demo_route(rng) -> pd.DataFrame:
    """A 25-min trip across the synthetic area during a storm that was never seen in training."""
    from .synth import make_event, make_segments, rain_at
    seg = make_segments(800, np.random.default_rng(42))  # same segments as the inventory
    pts = np.linspace([2, 3], [17, 15], 120)
    idx = pd.unique(np.array([int(np.argmin(np.hypot(seg.x_km - x, seg.y_km - y))) for x, y in pts]))
    route = seg.iloc[idx].reset_index(drop=True)
    route["eta_min"] = np.linspace(0, 25, len(route))
    ev = make_event(rng, "DEMO")
    ev.update(peak_mmh=45.0, cx=10.0, cy=10.0, radius_km=7.0, dry_spell_days=130.0, width_min=40.0)
    # The storm peaks over the city 15 minutes after departure.
    return pd.concat([route, rain_at(route, ev, route["eta_min"].to_numpy() - 15, rng)], axis=1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="models/v2_hgb.joblib")
    ap.add_argument("--route")
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--alert-level", default="High")
    args = ap.parse_args()

    bundle = joblib.load(args.model)
    route = demo_route(np.random.default_rng(7)) if args.demo else pd.read_csv(args.route)
    now = datetime.now(timezone.utc).isoformat(timespec="minutes")
    res = score_route(bundle, route, now)

    pd.set_option("display.width", 200, "display.max_colwidth", 70)
    print(f"model {bundle.kind}, trained {bundle.trained_on.get('trained_at')} on "
          f"{bundle.trained_on.get('events')} events; thresholds {bundle.thresholds}")
    print("Risk = possibility of flooding, not certainty. This complements official warnings: "
          "never drive into a flooded road.\n")
    print(res["level"].value_counts().reindex(["Low", "Moderate", "High", "Very high"], fill_value=0).to_string())
    order = ["Low", "Moderate", "High", "Very high"]
    alerts = res[res["level"].map(order.index) >= order.index(args.alert_level)]
    print(f"\n{len(alerts)} segment(s) at {args.alert_level} or above:")
    print(alerts.drop(columns=["data_timestamp", "confidence_notes"]).to_string(index=False) if len(alerts)
          else "none")
    if len(alerts):
        print(f"\nconfidence notes for first alert: {alerts.iloc[0]['confidence_notes']}")
    res.to_csv("reports/route_scores.csv", index=False)
    print("\nall segments: reports/route_scores.csv")


if __name__ == "__main__":
    main()
