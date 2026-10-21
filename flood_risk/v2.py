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
from .schema import (LABEL, LEVELS, RAW_FEATURES, TARGET_RECALL_HIGH, TARGET_RECALL_MODERATE,
                     TARGET_RECALL_VERY_HIGH)

KINDS = ["v1", "logistic", "hgb", "hgb_no_drainage"]


def make_model(kind: str, columns, seed: int = 0):
    if kind == "logistic":
        return make_pipeline(StandardScaler(), LogisticRegression(C=0.5, max_iter=5000))
    return HistGradientBoostingClassifier(
        max_iter=300, learning_rate=0.05, max_leaf_nodes=15, min_samples_leaf=40,
        l2_regularization=1.0, early_stopping=False, random_state=seed,
        monotonic_cst=[MONOTONIC.get(c, 0) for c in columns],
    )


class PlattCalibrator:
    """Sigmoid calibration on the logit of the raw score; used when positives are scarce."""

    def fit(self, p, y):
        self.lr = LogisticRegression().fit(_logit(p).reshape(-1, 1), y)
        return self

    def predict(self, p):
        return self.lr.predict_proba(_logit(p).reshape(-1, 1))[:, 1]


def _logit(p):
    p = np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def threshold_for_recall(p, y, recall):
    """Largest threshold t such that p >= t keeps at least `recall` of the positives."""
    pos = np.sort(p[y == 1])[::-1]
    return float(pos[max(int(np.ceil(recall * len(pos))) - 1, 0)])


def choose_thresholds(p, y) -> dict:
    high = threshold_for_recall(p, y, TARGET_RECALL_HIGH)
    return {
        "Moderate": min(threshold_for_recall(p, y, TARGET_RECALL_MODERATE), high),
        "High": high,
        "Very high": max(threshold_for_recall(p, y, TARGET_RECALL_VERY_HIGH), high),
    }


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

    def raw(self, df):
        if self.kind == "v1":
            return v1.score(df) / 100
        X = engineer(df, use_drainage=self.kind != "hgb_no_drainage")[self.columns]
        return self.model.predict_proba(X)[:, 1]

    def predict_proba(self, df):
        return self.calibrator.predict(self.raw(df))

    def predict_level(self, df):
        return to_level(self.predict_proba(df), self.thresholds)


def fit(kind: str, df: pd.DataFrame, seed: int = 0, n_inner: int = 4) -> Bundle:
    """Fit a model, its calibrator and its level thresholds without touching test events.

    Calibration and thresholds use out-of-fold predictions grouped by storm event, so a
    storm never calibrates its own predictions.
    """
    y = df[LABEL].to_numpy()
    groups = df["event_id"].to_numpy()
    if kind == "v1":
        model, columns, oof = None, [], v1.score(df) / 100
    else:
        X = engineer(df, use_drainage=kind != "hgb_no_drainage")
        columns = list(X.columns)
        oof = np.zeros(len(y))
        for tr, va in GroupKFold(n_splits=min(n_inner, len(set(groups)))).split(X, y, groups):
            m = make_model(kind, columns, seed).fit(X.iloc[tr], y[tr])
            oof[va] = m.predict_proba(X.iloc[va])[:, 1]
        model = make_model(kind, columns, seed).fit(X, y)
    if y.sum() >= 150:
        calibrator = IsotonicRegression(y_min=0, y_max=1, out_of_bounds="clip").fit(oof, y)
    else:
        calibrator = PlattCalibrator().fit(oof, y)
    thresholds = choose_thresholds(calibrator.predict(oof), y)
    info = {"rows": len(df), "events": int(len(set(groups))), "positives": int(y.sum()),
            "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            # Typical values used as the neutral point of explanations.
            "reference": df[RAW_FEATURES].median().to_dict()}
    return Bundle(kind, model, calibrator, thresholds, columns, info)
