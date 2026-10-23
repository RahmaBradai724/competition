"""Version 2: supervised model trained on a flood inventory, with calibrated probabilities."""

from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from . import v1
from .features import MONOTONIC, engineer
from .schema import (ALERT_SHARE, LABEL, LEVELS, RAW_FEATURES, TARGET_RECALL_HIGH, TARGET_RECALL_MODERATE,
                     TARGET_RECALL_VERY_HIGH)

KINDS = ["v1", "logistic", "hgb", "hgb_no_drainage"]
REFERENCE_KINDS = {"v1": "V1 multi-criteria", "v1_relative": "relative susceptibility"}
# Inputs that only vary between storms. Satellite inventories have one storm per mapped area, so
# these columns tell areas apart rather than wet and dry segments: `hgb_terrain` leaves them out.
RAIN_COLUMNS = ["rain_eta_mmh", "rain_1h_mm", "rain_3h_mm", "rain_24h_mm", "dry_spell_days",
                "rain_excess_ratio", "runoff_index", "wadi_rain"]


def features(kind: str, df: pd.DataFrame) -> pd.DataFrame:
    X = engineer(df, use_drainage=kind != "hgb_no_drainage")
    return X.drop(columns=RAIN_COLUMNS) if kind == "hgb_terrain" else X


HGB_DEFAULTS = {"max_iter": 300, "learning_rate": 0.05, "max_leaf_nodes": 15, "min_samples_leaf": 40,
                "l2_regularization": 1.0}


def make_model(kind: str, columns, seed: int = 0, params: dict | None = None):
    if kind == "logistic":
        return make_pipeline(StandardScaler(), LogisticRegression(C=0.5, max_iter=5000))
    return HistGradientBoostingClassifier(
        **{**HGB_DEFAULTS, **(params or {})}, early_stopping=False, random_state=seed,
        monotonic_cst=[MONOTONIC.get(c, 0) for c in columns],
    )


class PlattCalibrator:
    """Sigmoid calibration on the logit of the raw score; used when positives are scarce."""

    def fit(self, p, y):
        self.lr = LogisticRegression().fit(_logit(p).reshape(-1, 1), y)
        return self

    def predict(self, p):
        return self.lr.predict_proba(_logit(p).reshape(-1, 1))[:, 1]


class RankKeepingIsotonic:
    """Isotonic calibration whose flat steps keep the order of the raw score.

    Out-of-fold scores of unseen events can line up poorly with their labels, and isotonic
    regression then merges most of them into one step: every segment of a new area would get
    the same probability and the ranking would be lost. A tiny share of the raw score breaks
    those ties without moving any probability by more than 1e-4.
    """

    def fit(self, p, y):
        self.iso = IsotonicRegression(y_min=0, y_max=1, out_of_bounds="clip").fit(p, y)
        return self

    def predict(self, p):
        p = np.asarray(p, dtype=float)
        return np.clip(self.iso.predict(p) + 1e-4 * (p - 0.5), 0, 1)


def _logit(p):
    p = np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def threshold_for_recall(p, y, recall):
    """Largest threshold t such that p >= t keeps at least `recall` of the positives."""
    pos = np.sort(p[y == 1])[::-1]
    return float(pos[max(int(np.ceil(recall * len(pos))) - 1, 0)])


def threshold_for_share(p, share):
    """Threshold that puts `share` of the rows at or above it."""
    return float(np.quantile(p, 1 - share))


def choose_thresholds(p, y, mode: str = "recall") -> dict:
    """Level thresholds: by target recall (section 8) or by alert budget (ALERT_SHARE)."""
    if mode == "budget":
        return {level: threshold_for_share(p, share) for level, share in ALERT_SHARE.items()}
    high = threshold_for_recall(p, y, TARGET_RECALL_HIGH)
    return {
        "Moderate": min(threshold_for_recall(p, y, TARGET_RECALL_MODERATE), high),
        "High": high,
        "Very high": max(threshold_for_recall(p, y, TARGET_RECALL_VERY_HIGH), high),
    }


def levels_by_share(p, area=None, shares=ALERT_SHARE) -> np.ndarray:
    """Levels from the rank of each segment inside its area: the top `shares[level]` of every area reach it.

    Probability thresholds do not travel between regions when flood rates differ by two orders of
    magnitude (0.6 % of Nabeul's roads, 27 % of Derna's). Ranking inside the scored area keeps the
    alert volume fixed (FR-24) and needs no label from the new area.
    """
    p = pd.Series(np.asarray(p, dtype=float))
    rank = (p.groupby(np.asarray(area)) if area is not None else p).rank(pct=True, ascending=False, method="first")
    idx = sum((rank <= share).astype(int) for share in shares.values()).to_numpy()
    return np.array(LEVELS)[idx]


def to_level(p, thresholds) -> np.ndarray:
    idx = (np.asarray(p)[:, None] >= np.array([thresholds[l] for l in LEVELS[1:]])).sum(axis=1)
    return np.array(LEVELS)[idx]


@dataclass
class Bundle:
    kind: str
    model: object
    calibrator: object
    thresholds: dict
    columns: list
    trained_on: dict = field(default_factory=dict)
    neg_sample: float = 1.0

    def raw(self, df):
        if self.kind == "v1":
            return v1.score(df) / 100
        if self.kind == "v1_relative":
            return v1.relative_susceptibility(df, "aoi" if "aoi" in df.columns else None) / 100
        X = features(self.kind, df)[self.columns]
        return self.model.predict_proba(X)[:, 1]

    def predict_proba(self, df):
        return prior_correct(self.calibrator.predict(self.raw(df)), getattr(self, "neg_sample", 1.0))

    def predict_level(self, df):
        return to_level(self.predict_proba(df), self.thresholds)


def prior_correct(q, neg_sample: float):
    """Undo the shift caused by keeping only a share of the negatives (King & Zeng 2001)."""
    if neg_sample >= 1:
        return q
    q = np.asarray(q, dtype=float)
    return np.clip(neg_sample * q / (neg_sample * q + 1 - q), 0, 1)


def fit(kind: str, df: pd.DataFrame, seed: int = 0, n_inner: int = 4, neg_sample: float = 1.0,
        params: dict | None = None, levels: str = "recall") -> Bundle:
    """Fit a model, its calibrator and its level thresholds without touching test events.

    Calibration and thresholds use out-of-fold predictions grouped by storm event, so a
    storm never calibrates its own predictions.
    """
    reference = df[RAW_FEATURES].median().to_dict()
    if neg_sample < 1:
        # Large inventories: keep every flooded row and a random share of the others.
        keep = (df[LABEL].to_numpy() == 1) | (np.random.default_rng(seed).random(len(df)) < neg_sample)
        df = df[keep]
    y = df[LABEL].to_numpy()
    groups = df["event_id"].to_numpy()
    if kind == "v1":
        model, columns, oof = None, [], v1.score(df) / 100
    elif kind == "v1_relative":
        model, columns = None, []
        oof = v1.relative_susceptibility(df, "aoi" if "aoi" in df.columns else None) / 100
    else:
        X = features(kind, df)
        columns = list(X.columns)
        oof = np.zeros(len(y))
        for tr, va in GroupKFold(n_splits=min(n_inner, len(set(groups)))).split(X, y, groups):
            m = make_model(kind, columns, seed, params).fit(X.iloc[tr], y[tr])
            oof[va] = m.predict_proba(X.iloc[va])[:, 1]
        model = make_model(kind, columns, seed, params).fit(X, y)
    if y.sum() >= 150:
        calibrator = RankKeepingIsotonic().fit(oof, y)
    else:
        calibrator = PlattCalibrator().fit(oof, y)
    p_oof = prior_correct(calibrator.predict(oof), neg_sample)
    if levels in ("budget", "area") and neg_sample < 1:
        # Quantiles must describe every row: give each kept negative the weight of the ones dropped.
        neg = y == 0
        p_oof = np.concatenate([p_oof[~neg], np.repeat(p_oof[neg], int(round(1 / neg_sample)))])
        y = np.concatenate([y[~neg], y[neg].repeat(int(round(1 / neg_sample)))])
    # Area mode ranks inside each scored area; the budget thresholds are kept as a fallback for single segments.
    thresholds = choose_thresholds(p_oof, y, "budget" if levels == "area" else levels)
    info = {"rows": len(df), "events": int(len(set(groups))), "positives": int(y.sum()),
            "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            # Typical values used as the neutral point of explanations.
            "reference": reference, "neg_sample": neg_sample, "params": params or {}, "levels": levels}
    return Bundle(kind, model, calibrator, thresholds, columns, info, neg_sample)
