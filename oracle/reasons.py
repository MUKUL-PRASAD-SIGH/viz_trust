"""Human-readable reason strings for ScoreUpdated.

Built from the event that triggered the rescore plus the model's top factor, always with the
point delta the chain will show:

    "lost dispute on $500 job (-64); top factor: dispute rate far above peers"
    "completed job #12, clean settlement (+18); top factor: clean settlement almost without exception"
    "payment default on $1000 job (-140); top factor: many prior defaults on record"
"""

from __future__ import annotations

from history import Outcome


def _money(value_usd: float) -> str:
    return f"${value_usd:.0f}" if value_usd == int(value_usd) else f"${value_usd:.2f}"


def describe_event(outcome: Outcome, job_number: int) -> str:
    """What happened, in the words the dashboard shows.

    `job_number` is the agent's count of delivered jobs including this one. "Clean settlement" follows
    the score service's proxy: delivered and never disputed is a clean settlement.
    """
    value = _money(outcome.value_usd)

    if outcome.delivered and not outcome.disputed:
        return f"completed job #{job_number}, clean settlement"
    if outcome.delivered and outcome.disputed:
        return f"won dispute on {value} job"
    if outcome.disputed:
        return f"lost dispute on {value} job"
    return f"payment default on {value} job"


def event_type(outcome: Outcome) -> str:
    """Machine-readable twin of describe_event, for the dashboard feed."""
    if outcome.delivered:
        return "dispute_won" if outcome.disputed else "job_completed"
    return "dispute_lost" if outcome.disputed else "payment_default"


def build_reason(outcome: Outcome, job_number: int, delta: int, top_factor: dict | None) -> str:
    reason = f"{describe_event(outcome, job_number)} ({delta:+d})"
    if top_factor:
        reason += f"; top factor: {top_factor['explanation'].lower()}"
    return reason
