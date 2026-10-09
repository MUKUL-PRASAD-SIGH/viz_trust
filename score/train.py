"""Fit the AEGIS credit model on the synthetic histories and save the artifacts.

Plain logistic regression on standardized features. The choice is deliberate: the model has
to explain itself on stage ("score dropped 40 points because of one lost dispute"), and a
linear model in standardized space gives per-feature contributions for free as
coefficient * standardized_value.

Usage:
    python generate_data.py   # first
    python train.py
"""

from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    classification_report,
    confusion_matrix,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

SEED = 42
TEST_SIZE = 0.2

# The AUC band we consider healthy. Above it, the synthetic data is too clean to be
# credible; below it, the model is not carrying its weight.
AUC_MIN, AUC_MAX = 0.80, 0.88

# Score calibration, SPEC.md section 7. The raw default probability is deliberately not used
# as the score: with a ~15% base rate it crushes 79% of agents into the top band and the
# collateral tiers stop discriminating. Instead the score is linear in log-odds, which is
# standard credit-scoring practice and keeps per-feature point impacts stable rather than
# letting them saturate at the extremes.
ANCHOR_SCORE = 500  # the median agent scores 500, matching the on-chain starting score
POINTS_PER_ODDS_DOUBLING = 100

SCORE_DIR = Path(__file__).parent
DATA_PATH = SCORE_DIR / "data" / "agents.csv"
MODELS_DIR = SCORE_DIR / "models"

FEATURES = [
    "jobs_completed",
    "dispute_rate",
    "avg_job_value_usd",
    "account_age_days",
    "on_time_payment_rate",
    "prior_defaults",
    "counterparty_diversity",
]
TARGET = "defaulted"

BANDS = [("excellent", 800), ("good", 600), ("fair", 400), ("poor", 0)]


def logit_to_score(logit: np.ndarray, median_logit: float, factor: float) -> np.ndarray:
    """Map log-odds of default to the 0-1000 score. Low risk means a high score."""
    return np.clip(np.round(ANCHOR_SCORE - factor * (logit - median_logit)), 0, 1000)


def main() -> None:
    if not DATA_PATH.exists():
        raise SystemExit(f"No dataset at {DATA_PATH}. Run `python generate_data.py` first.")

    df = pd.read_csv(DATA_PATH)
    X = df[FEATURES]
    y = df[TARGET]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=TEST_SIZE, random_state=SEED, stratify=y
    )

    scaler = StandardScaler().fit(X_train)
    X_train_scaled = scaler.transform(X_train)
    X_test_scaled = scaler.transform(X_test)

    model = LogisticRegression(max_iter=1000, random_state=SEED)
    model.fit(X_train_scaled, y_train)

    test_probabilities = model.predict_proba(X_test_scaled)[:, 1]
    test_predictions = (test_probabilities >= 0.5).astype(int)

    auc = roc_auc_score(y_test, test_probabilities)
    train_auc = roc_auc_score(y_train, model.predict_proba(X_train_scaled)[:, 1])
    matrix = confusion_matrix(y_test, test_predictions)

    print()
    print("=" * 62)
    print("AEGIS credit model")
    print("=" * 62)
    print(f"Rows:            {len(df):,}  ({len(X_train):,} train / {len(X_test):,} test)")
    print(f"Default rate:    {y.mean():.1%}")
    print()
    print(f"Test ROC AUC:    {auc:.4f}")
    print(f"Train ROC AUC:   {train_auc:.4f}")

    if auc > AUC_MAX:
        print(f"  ! Above {AUC_MAX}. Data is too clean to be believable -- raise LATENT_NOISE.")
    elif auc < AUC_MIN:
        print(f"  ! Below {AUC_MIN}. Model is too weak -- lower LATENT_NOISE.")
    else:
        print(f"  Within the healthy {AUC_MIN}-{AUC_MAX} band.")

    print()
    print("Confusion matrix (threshold 0.5):")
    print("                 predicted ok   predicted default")
    print(f"  actual ok      {matrix[0][0]:>12,}   {matrix[0][1]:>17,}")
    print(f"  actual default {matrix[1][0]:>12,}   {matrix[1][1]:>17,}")
    print()
    print(classification_report(y_test, test_predictions, target_names=["ok", "defaulted"]))

    print("Coefficients (standardized space, most influential first):")
    coefficients = model.coef_[0]
    order = np.argsort(-np.abs(coefficients))
    for i in order:
        direction = "raises risk" if coefficients[i] > 0 else "lowers risk"
        print(f"  {FEATURES[i]:<24} {coefficients[i]:>+8.4f}   {direction}")
    print(f"  {'(intercept)':<24} {model.intercept_[0]:>+8.4f}")
    print()

    # Calibration is fit on the training split only, so the test AUC above stays honest.
    factor = POINTS_PER_ODDS_DOUBLING / np.log(2.0)
    median_logit = float(np.median(model.decision_function(X_train_scaled)))

    print(f"Calibration:     score = {ANCHOR_SCORE} - {factor:.4f} * (logit - {median_logit:.4f})")
    print(f"                 {POINTS_PER_ODDS_DOUBLING} points per doubling of the odds of default")
    print()

    all_scores = logit_to_score(
        model.decision_function(scaler.transform(X)), median_logit, factor
    )

    collateral_bps = {"excellent": 2000, "good": 4000, "fair": 7000, "poor": 10000}
    band_shares: dict[str, float] = {}
    unassigned = np.ones(len(all_scores), dtype=bool)

    print("Score distribution across the full population:")
    for name, floor in BANDS:
        in_band = unassigned & (all_scores >= floor)
        band_shares[name] = round(float(in_band.mean()), 4)
        unassigned &= ~in_band
        print(
            f"  {name:<10} score >= {floor:<4} "
            f"{collateral_bps[name]:>5} bps  {band_shares[name] * 100:>5.1f}%"
        )
    print(f"  median score {int(np.median(all_scores))}")
    print()

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    (MODELS_DIR / "calibration.json").write_text(
        json.dumps(
            {
                "anchor_score": ANCHOR_SCORE,
                "points_per_odds_doubling": POINTS_PER_ODDS_DOUBLING,
                "factor": round(float(factor), 6),
                "median_logit": round(median_logit, 6),
            },
            indent=2,
        )
    )
    joblib.dump(model, MODELS_DIR / "model.joblib")
    joblib.dump(scaler, MODELS_DIR / "scaler.joblib")
    (MODELS_DIR / "feature_names.json").write_text(json.dumps(FEATURES, indent=2))

    metrics = {
        "test_roc_auc": round(float(auc), 4),
        "train_roc_auc": round(float(train_auc), 4),
        "n_rows": int(len(df)),
        "n_train": int(len(X_train)),
        "n_test": int(len(X_test)),
        "default_rate": round(float(y.mean()), 4),
        "confusion_matrix": matrix.tolist(),
        "coefficients": {
            feature: round(float(coefficient), 4)
            for feature, coefficient in zip(FEATURES, coefficients)
        },
        "intercept": round(float(model.intercept_[0]), 4),
        "band_shares": band_shares,
        "median_score": int(np.median(all_scores)),
        "seed": SEED,
    }
    (MODELS_DIR / "metrics.json").write_text(json.dumps(metrics, indent=2))

    print(f"Saved model, scaler, feature names and metrics to {MODELS_DIR}")


if __name__ == "__main__":
    main()
