"""Generate synthetic agent credit histories for training the AEGIS model.

No real agent-economy data exists yet, so we simulate it. The goal is a dataset with
*genuine irreducible noise*: a model that separates defaulters perfectly would be evidence
the data is fake, not that the model is good. We target roughly 0.80-0.88 AUC.

Feature definitions are frozen in SPEC.md section 7. Everything here is seeded.

Usage:
    python generate_data.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

SEED = 42
N_AGENTS = 5000

TARGET_DEFAULT_RATE = 0.15

# Standard deviation of the noise added to the latent risk score before sampling the
# outcome. This is the main dial for model quality: raise it and AUC falls. Tuned so a
# logistic regression lands in the 0.80-0.88 band.
LATENT_NOISE = 0.9

OUTPUT_PATH = Path(__file__).parent / "data" / "agents.csv"

# The seven features from SPEC.md section 7, in a fixed order.
FEATURES = [
    "jobs_completed",
    "dispute_rate",
    "avg_job_value_usd",
    "account_age_days",
    "on_time_payment_rate",
    "prior_defaults",
    "counterparty_diversity",
]


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


def generate_features(rng: np.random.Generator, n: int) -> pd.DataFrame:
    """Draw the seven observable features for n agents."""

    # Heavy-tailed: most agents have done a handful of jobs, a few have done hundreds.
    jobs_completed = np.round(rng.lognormal(mean=2.0, sigma=1.15, size=n)).astype(int)
    jobs_completed = np.clip(jobs_completed, 0, 600)

    # Most agents sit near zero disputes; a minority are genuinely disputatious.
    is_disputatious = rng.random(n) < 0.18
    dispute_rate = np.where(
        is_disputatious,
        rng.beta(2.2, 5.0, size=n),
        rng.beta(0.6, 30.0, size=n),
    )
    dispute_rate = np.clip(dispute_rate, 0.0, 1.0)

    avg_job_value_usd = rng.lognormal(mean=4.1, sigma=1.05, size=n)
    avg_job_value_usd = np.round(np.clip(avg_job_value_usd, 1.0, 50_000.0), 2)

    account_age_days = np.round(rng.gamma(shape=2.0, scale=95.0, size=n)).astype(int)
    account_age_days = np.clip(account_age_days, 1, 1500)

    # Skewed high: most agents pay on time nearly always.
    on_time_payment_rate = np.round(np.clip(rng.beta(11.0, 1.7, size=n), 0.0, 1.0), 4)

    # Mostly zero, with a small group of repeat offenders.
    prior_defaults = rng.poisson(0.28, size=n)
    repeat_offender = rng.random(n) < 0.04
    prior_defaults = prior_defaults + repeat_offender * rng.poisson(2.5, size=n)
    prior_defaults = np.clip(prior_defaults, 0, 25).astype(int)

    # Distinct counterparties can never exceed jobs done. Some agents work repeatedly for
    # one partner (low diversity), others spread across many.
    diversity_fraction = rng.beta(4.0, 3.0, size=n)
    counterparty_diversity = np.round(jobs_completed * diversity_fraction).astype(int)
    counterparty_diversity = np.minimum(counterparty_diversity, jobs_completed)
    counterparty_diversity = np.where(
        jobs_completed > 0, np.maximum(counterparty_diversity, 1), 0
    ).astype(int)

    return pd.DataFrame(
        {
            "jobs_completed": jobs_completed,
            "dispute_rate": np.round(dispute_rate, 4),
            "avg_job_value_usd": avg_job_value_usd,
            "account_age_days": account_age_days,
            "on_time_payment_rate": on_time_payment_rate,
            "prior_defaults": prior_defaults,
            "counterparty_diversity": counterparty_diversity,
        }
    )


def latent_risk(df: pd.DataFrame) -> np.ndarray:
    """The true (unobservable) risk score driving default.

    Directions are fixed by the spec: higher dispute_rate and prior_defaults raise risk;
    lower on_time_payment_rate, account_age_days, jobs_completed and counterparty_diversity
    raise risk. Job value gets a mild positive weight -- bigger jobs are slightly riskier --
    so the feature carries some signal rather than being dead weight.

    Counts and values enter through logs, so the difference between 1 and 5 jobs matters
    far more than between 200 and 204.
    """
    log_value = np.log(df["avg_job_value_usd"].to_numpy())

    return (
        6.5 * df["dispute_rate"].to_numpy()
        + 1.10 * df["prior_defaults"].to_numpy()
        - 6.0 * df["on_time_payment_rate"].to_numpy()
        - 0.55 * np.log1p(df["account_age_days"].to_numpy())
        - 0.45 * np.log1p(df["jobs_completed"].to_numpy())
        - 0.35 * np.log1p(df["counterparty_diversity"].to_numpy())
        + 0.20 * (log_value - log_value.mean())
    )


def _solve_intercept(latent: np.ndarray, target_rate: float) -> float:
    """Find the intercept b such that mean(sigmoid(latent + b)) == target_rate.

    Keeps the overall default rate on target no matter how the feature weights are tuned.
    """
    low, high = -50.0, 50.0
    for _ in range(200):
        mid = (low + high) / 2.0
        if _sigmoid(latent + mid).mean() < target_rate:
            low = mid
        else:
            high = mid
    return (low + high) / 2.0


def main() -> None:
    rng = np.random.default_rng(SEED)

    df = generate_features(rng, N_AGENTS)

    # Genuine irreducible noise: two agents with identical observable histories can still
    # land on different outcomes. Without this the model looks suspiciously perfect.
    noisy_latent = latent_risk(df) + rng.normal(0.0, LATENT_NOISE, size=N_AGENTS)

    intercept = _solve_intercept(noisy_latent, TARGET_DEFAULT_RATE)
    default_probability = _sigmoid(noisy_latent + intercept)

    df["defaulted"] = (rng.random(N_AGENTS) < default_probability).astype(int)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT_PATH, index=False)

    rate = df["defaulted"].mean()
    print(f"Wrote {len(df):,} agent histories to {OUTPUT_PATH}")
    print(f"Default rate: {rate:.1%}  (target {TARGET_DEFAULT_RATE:.0%})")
    print(f"Latent noise: {LATENT_NOISE}")
    print()
    print("Feature summary:")
    print(df[FEATURES].describe().T[["mean", "std", "min", "50%", "max"]].round(3))


if __name__ == "__main__":
    main()
