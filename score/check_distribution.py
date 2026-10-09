"""Verify the logit-linear score mapping produces a usable spread across bands.

Why this exists: the collateral curve in SPEC.md section 3 only creates visible contrast if
agents actually land in different bands. If one band swallows most of the population, every
agent quotes the same collateral and the product has nothing to show.

This script changes nothing. It reports, and if the spread looks wrong it proposes numbers
for a human to approve.

Usage:
    python check_distribution.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

# Imported rather than reimplemented on purpose. The collateral step table (SPEC.md
# section 3) is already duplicated on-chain in contracts/src/AegisRegistry.sol; a third copy
# here would be a third thing to keep in sync. _logit_to_points is private but is the exact
# mapping the live service uses, and this script is worthless if it measures anything else.
from app import (
    SCORING_MODEL,
    AgentFeatures,
    _logit_to_points,
    required_collateral_bps,
    score_agent,
    score_band,
)

DATA_PATH = Path(__file__).parent / "data" / "agents.csv"

# Bands from SPEC.md section 4, with the collateral each implies from SPEC.md section 3.
BANDS = [
    ("excellent", 800, 2000),
    ("good", 600, 4000),
    ("fair", 400, 7000),
    ("poor", 0, 10000),
]

# What the demo wants: a real spread, no band dominating. Stated as a target by the repo
# owner, not derived from the model.
TARGET_SHARES = {"excellent": 0.15, "good": 0.35, "fair": 0.35, "poor": 0.15}
DOMINANCE_LIMIT = 0.50

# A long clean record versus a short disastrous one. These two must not come out inverted.
CLEAN_AGENT = AgentFeatures(
    jobs_completed=90,
    dispute_rate=0.0,
    avg_job_value_usd=120.0,
    account_age_days=600,
    on_time_payment_rate=1.0,
    prior_defaults=0,
    counterparty_diversity=45,
)
BAD_AGENT = AgentFeatures(
    jobs_completed=3,
    dispute_rate=0.65,
    avg_job_value_usd=700.0,
    account_age_days=25,
    on_time_payment_rate=0.45,
    prior_defaults=4,
    counterparty_diversity=1,
)

# Ordinary agents built around the population medians (jobs 7, disputes 0.016, value $60,
# age 159d, on-time 0.87, defaults 0, counterparties 4). The clean/bad pair above are
# deliberate extremes; these are the ones that must NOT pile up at 0 or 1000.
MID_RANGE_AGENTS: list[tuple[str, AgentFeatures]] = [
    (
        "population median",
        AgentFeatures(
            jobs_completed=7,
            dispute_rate=0.016,
            avg_job_value_usd=60.0,
            account_age_days=159,
            on_time_payment_rate=0.87,
            prior_defaults=0,
            counterparty_diversity=4,
        ),
    ),
    (
        "a bit below average",
        AgentFeatures(
            jobs_completed=4,
            dispute_rate=0.10,
            avg_job_value_usd=80.0,
            account_age_days=90,
            on_time_payment_rate=0.80,
            prior_defaults=0,
            counterparty_diversity=3,
        ),
    ),
    (
        "a bit above average",
        AgentFeatures(
            jobs_completed=20,
            dispute_rate=0.01,
            avg_job_value_usd=110.0,
            account_age_days=280,
            on_time_payment_rate=0.92,
            prior_defaults=0,
            counterparty_diversity=12,
        ),
    ),
    (
        "new but clean",
        AgentFeatures(
            jobs_completed=3,
            dispute_rate=0.0,
            avg_job_value_usd=45.0,
            account_age_days=30,
            on_time_payment_rate=0.95,
            prior_defaults=0,
            counterparty_diversity=3,
        ),
    ),
    (
        "experienced, one dispute",
        AgentFeatures(
            jobs_completed=40,
            dispute_rate=0.025,
            avg_job_value_usd=150.0,
            account_age_days=420,
            on_time_payment_rate=0.90,
            prior_defaults=0,
            counterparty_diversity=22,
        ),
    ),
    (
        "one past default",
        AgentFeatures(
            jobs_completed=12,
            dispute_rate=0.08,
            avg_job_value_usd=95.0,
            account_age_days=200,
            on_time_payment_rate=0.85,
            prior_defaults=1,
            counterparty_diversity=7,
        ),
    ),
]


def band_of(score: int) -> str:
    return score_band(score)


def population_scores(model) -> tuple[np.ndarray, np.ndarray]:
    """Score every synthetic agent. Returns (scores, logits)."""
    frame = pd.read_csv(DATA_PATH)
    features = frame[model.feature_names]

    logits = model.model.decision_function(model.scaler.transform(features))
    points = _logit_to_points(logits, model.calibration)
    scores = np.clip(np.round(points), 0, 1000).astype(int)

    return scores, logits


def verify_bulk_matches_service(scores: np.ndarray, model) -> bool:
    """The vectorised path above must agree with what the API would actually return."""
    frame = pd.read_csv(DATA_PATH)
    sample = frame.sample(n=25, random_state=0)

    for position, (_, row) in zip(sample.index, sample.iterrows()):
        features = AgentFeatures(**{name: row[name] for name in model.feature_names})
        if score_agent(features, model).score != scores[position]:
            return False
    return True


def print_band_distribution(scores: np.ndarray) -> dict[str, float]:
    print("Band distribution")
    print("-" * 64)
    print(f"{'band':<12}{'range':<14}{'collateral':<13}{'count':>8}{'share':>9}")

    shares: dict[str, float] = {}
    unassigned = np.ones(len(scores), dtype=bool)

    for name, floor, bps in BANDS:
        in_band = unassigned & (scores >= floor)
        count = int(in_band.sum())
        share = count / len(scores)
        shares[name] = share
        unassigned &= ~in_band

        higher_floors = [f for _, f, _ in BANDS if f > floor]
        ceiling = min(higher_floors) - 1 if higher_floors else 1000
        span = f"{floor}-{ceiling}"
        print(f"{name:<12}{span:<14}{bps:>6} bps{count:>9,}{share * 100:>8.1f}%")

    print()
    return shares


def print_collateral_distribution(scores: np.ndarray) -> None:
    print("Required collateral (what the chain would actually charge)")
    print("-" * 64)

    bps_values = np.array([required_collateral_bps(int(s)) for s in scores])
    for bps in sorted(set(bps_values.tolist())):
        count = int((bps_values == bps).sum())
        print(
            f"  {bps:>5} bps ({bps / 100:>5.1f}% upfront)   "
            f"{count:>8,}{count / len(scores) * 100:>8.1f}%"
        )

    print(f"\n  mean collateral across population: {bps_values.mean():.0f} bps")
    print()


def print_score_summary(scores: np.ndarray) -> None:
    print("Score summary")
    print("-" * 64)
    print(f"  min     {scores.min():>6}")
    print(f"  p05     {int(np.percentile(scores, 5)):>6}")
    print(f"  p25     {int(np.percentile(scores, 25)):>6}")
    print(f"  median  {int(np.median(scores)):>6}")
    print(f"  p75     {int(np.percentile(scores, 75)):>6}")
    print(f"  p95     {int(np.percentile(scores, 95)):>6}")
    print(f"  max     {scores.max():>6}")
    print(f"  clamped at 0: {int((scores == 0).sum()):,}   at 1000: {int((scores == 1000).sum()):,}")
    print()


def print_archetypes(model) -> tuple[int, int]:
    print("Archetype check")
    print("-" * 64)

    results = {}
    for label, features in (("clean", CLEAN_AGENT), ("bad", BAD_AGENT)):
        result = score_agent(features, model)
        results[label] = result
        print(
            f"  {label:<6} score={result.score:<5} band={result.band:<10} "
            f"collateral={result.required_collateral_bps} bps  "
            f"p(default)={result.default_probability}"
        )
        for factor in result.top_factors:
            print(f"           {factor.impact:>+6}  {factor.feature:<24} {factor.explanation}")
    print()

    return results["clean"].score, results["bad"].score


def print_mid_range(model) -> list[int]:
    """Ordinary agents must land across the middle, not at the rails."""
    print("Mid-range agents (these are the ones that must not clamp)")
    print("-" * 64)

    scores = []
    for label, features in MID_RANGE_AGENTS:
        result = score_agent(features, model)
        scores.append(result.score)
        rail = "  <-- CLAMPED" if result.score in (0, 1000) else ""
        print(
            f"  {label:<26} score={result.score:<5} {result.band:<10} "
            f"{result.required_collateral_bps:>5} bps{rail}"
        )

    print()
    return scores


def suggest_calibration(logits: np.ndarray, model) -> None:
    """Work out what it would take to hit the target spread. Suggests only."""
    calibration = model.calibration
    anchor = calibration["anchor_score"]
    factor = calibration["factor"]
    median_logit = calibration["median_logit"]

    print("Calibration analysis")
    print("-" * 64)
    print(f"  current ANCHOR = {anchor}, FACTOR = {factor:.4f}, MEDIAN_LOGIT = {median_logit:.4f}")
    print()

    # Low logit means low risk means high score, so the best agents sit in the left tail.
    cumulative_excellent = TARGET_SHARES["excellent"]
    cumulative_good = cumulative_excellent + TARGET_SHARES["good"]

    logit_at_excellent = float(np.percentile(logits, cumulative_excellent * 100))
    logit_at_good = float(np.percentile(logits, cumulative_good * 100))

    # ANCHOR pins the median agent's score, so P(score >= ANCHOR) is 50% by construction.
    # Hitting 50% of agents at or above 600 therefore requires ANCHOR itself to move to 600;
    # no value of FACTOR can do it alone.
    print("  Hitting 15/35/35/15 needs BOTH constants to move:")
    print(f"    ANCHOR pins the median agent at {anchor}, so exactly 50% of agents score >= {anchor}.")
    print(f"    The target puts 50% of agents at >= 600, which forces ANCHOR = 600.")
    print()

    factor_for_excellent = (600 - 800) / (logit_at_excellent - median_logit)
    print("  Option A - move both (hits the target spread):")
    print(f"    ANCHOR = 600, FACTOR = {factor_for_excellent:.1f}")
    print("    Cost: the median agent would score 600 while a newly registered agent starts")
    print("    at 500 on-chain (SPEC.md section 2), so a new agent would sit below median.")
    print("    That is a SPEC.md change and needs team sign-off.")
    print()

    factor_only = (anchor - 800) / (logit_at_excellent - median_logit)
    print("  Option B - keep ANCHOR = 500, change FACTOR only:")
    print(f"    FACTOR = {factor_only:.1f}  (up from {factor:.1f})")
    projected = project_shares(logits, anchor, factor_only, median_logit)
    for name, _, _ in BANDS:
        print(f"      {name:<12}{projected[name] * 100:>6.1f}%")
    print("    Keeps 'new agent starts at 500 = median' intact. No SPEC.md change.")
    print(f"    Costs {factor_only / factor:.2f}x the points per doubling of odds, so score")
    print("    swings per job get correspondingly larger.")
    print()


def project_shares(
    logits: np.ndarray, anchor: float, factor: float, median_logit: float
) -> dict[str, float]:
    scores = np.clip(np.round(anchor - factor * (logits - median_logit)), 0, 1000)

    shares: dict[str, float] = {}
    unassigned = np.ones(len(scores), dtype=bool)
    for name, floor, _ in BANDS:
        in_band = unassigned & (scores >= floor)
        shares[name] = float(in_band.mean())
        unassigned &= ~in_band
    return shares


def main() -> int:
    if SCORING_MODEL is None:
        print("No model artifacts. Run `python generate_data.py` then `python train.py`.")
        return 1
    if not DATA_PATH.exists():
        print(f"No dataset at {DATA_PATH}. Run `python generate_data.py`.")
        return 1

    model = SCORING_MODEL
    scores, logits = population_scores(model)

    print()
    print("=" * 64)
    print(f"AEGIS score distribution over {len(scores):,} synthetic agents")
    print(f"model test AUC {model.metrics.get('test_roc_auc')}")
    print("=" * 64)
    print()

    shares = print_band_distribution(scores)
    print_collateral_distribution(scores)
    print_score_summary(scores)
    clean_score, bad_score = print_archetypes(model)
    mid_scores = print_mid_range(model)

    print("Verdict")
    print("-" * 64)
    failures: list[str] = []

    if not verify_bulk_matches_service(scores, model):
        failures.append("bulk scoring disagrees with what the /score endpoint returns")
    else:
        print("  ok    bulk scoring matches the live /score path on a 25-agent sample")

    # A sign error in the probability-to-score mapping would show up here first.
    if clean_score <= bad_score:
        failures.append(
            f"INVERTED: clean agent ({clean_score}) does not outscore bad agent ({bad_score}). "
            "Check the sign in the probability-to-score mapping."
        )
    else:
        print(f"  ok    clean agent outscores bad agent ({clean_score} vs {bad_score})")

    if clean_score < 600:
        failures.append(f"clean agent only scored {clean_score}, expected a high score")
    if bad_score >= 400:
        failures.append(f"bad agent scored {bad_score}, expected a low score")

    clamped_mid = [score for score in mid_scores if score in (0, 1000)]
    if clamped_mid:
        failures.append(
            f"{len(clamped_mid)} of {len(mid_scores)} mid-range agents clamped at a rail; "
            "ordinary agents should land in the middle of the range"
        )
    else:
        print(
            f"  ok    no mid-range agent clamped "
            f"(span {min(mid_scores)}-{max(mid_scores)})"
        )

    rail_share = float(((scores == 0) | (scores == 1000)).mean())
    print(f"  note  {rail_share * 100:.1f}% of the population sits at a rail (0 or 1000)")

    dominant = max(shares, key=shares.get)
    if shares[dominant] > DOMINANCE_LIMIT:
        print(
            f"  WARN  '{dominant}' holds {shares[dominant] * 100:.1f}% of agents, "
            f"above the {DOMINANCE_LIMIT * 100:.0f}% limit"
        )
    else:
        print(f"  ok    no band exceeds {DOMINANCE_LIMIT * 100:.0f}% "
              f"(largest is '{dominant}' at {shares[dominant] * 100:.1f}%)")

    drift = {name: shares[name] - TARGET_SHARES[name] for name in TARGET_SHARES}
    worst = max(drift, key=lambda n: abs(drift[n]))
    print(
        f"  note  furthest from target: '{worst}' at {shares[worst] * 100:.1f}% "
        f"vs {TARGET_SHARES[worst] * 100:.0f}% wanted ({drift[worst] * 100:+.1f} points)"
    )
    print()

    suggest_calibration(logits, model)

    if failures:
        print("FAILED")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    print("No sign errors. Calibration numbers above are suggestions only; nothing was changed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
