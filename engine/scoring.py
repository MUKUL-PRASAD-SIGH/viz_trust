"""v0 trust scoring: a points table, a reason for every change.

Deliberately not a model. Every move is one line of this table, so "why is this agent on
probation" always has a literal answer. The shape follows score/app.py (0-1000, bands, ranked
factors with explanations) so the dashboard cards work unchanged.

    new agent                      500, probation
    clean edit approved            +14
    clean edit allowed             +8
    dismissed finding (false alarm) +2
    confirmed finding              high -60, medium -30, low -10
    broken caller (impact finding) -20
    secret leak (high Hardcode Hunter finding confirmed)
                                   -60 and the score is capped at 550: back to probation

Gains are scaled by edit size and blast radius, so a one-line edit barely counts (anti-gaming).
Penalties are never scaled.
"""

from __future__ import annotations

from engine.models import Finding, Tier

START_SCORE = 500
MIN_SCORE, MAX_SCORE = 0, 1000
LEAK_CAP = 550  # below the 600 standard threshold: a leak always lands on probation
TRUSTED_AT, STANDARD_AT = 800, 600

POINTS = {
    "clean_edit_approved": 14,
    "clean_edit_allowed": 8,
    "finding_dismissed": 2,
    "confirmed_high": -60,
    "confirmed_medium": -30,
    "confirmed_low": -10,
    "broken_caller": -20,
}

# Weight of a gain = clamp(BASE + PER_LINE * changed lines + PER_CALLER * blast, 0, 1).
# A 1-line edit with no callers is worth 17% of the table value; ~10 lines or 3 callers is full.
WEIGHT_BASE, WEIGHT_PER_LINE, WEIGHT_PER_CALLER = 0.10, 0.07, 0.10


def tier_for(score: int) -> Tier:
    if score >= TRUSTED_AT:
        return "trusted"
    if score >= STANDARD_AT:
        return "standard"
    return "probation"


def band_for(score: int) -> str:
    """Same breakpoints as score/app.py's score_band, so the card colours still work."""
    if score >= 800:
        return "excellent"
    if score >= 600:
        return "good"
    if score >= 400:
        return "fair"
    return "poor"


# What the card's existing percentage field shows, per tier. See PROJECT notes: for standard
# there is no honest percentage (every edit is checked, only high-severity ones are held).
REVIEW_SHARE = {
    "trusted": (2000, "20%"),
    "standard": (4000, "high severity"),
    "probation": (10000, "100%"),
}


def edit_weight(changed_lines: int, blast_count: int) -> float:
    raw = WEIGHT_BASE + WEIGHT_PER_LINE * changed_lines + WEIGHT_PER_CALLER * blast_count
    return max(0.0, min(1.0, raw))


def clean_edit_points(factor: str, changed_lines: int, blast_count: int) -> int:
    """Scaled gain for a clean edit; always at least 1 so a clean edit never reads as zero."""
    return max(1, round(POINTS[factor] * edit_weight(changed_lines, blast_count)))


def is_secret_leak(finding: Finding) -> bool:
    return finding.check == "hardcode_hunter" and finding.severity == "high"


def confirm_penalty(finding: Finding) -> tuple[str, int]:
    """(factor label, delta) for a confirmed finding."""
    if finding.check == "impact_analyst":
        return "broken_caller", POINTS["broken_caller"]
    if is_secret_leak(finding):
        return "secret_leak", POINTS["confirmed_high"]
    factor = f"confirmed_{finding.severity}"
    return factor, POINTS[factor]


def apply_delta(score: int, delta: int, secret_leak: bool = False) -> int:
    new = max(MIN_SCORE, min(MAX_SCORE, score + delta))
    return min(new, LEAK_CAP) if secret_leak else new


def _plural(count: int, singular: str, plural: str) -> str:
    return f"{count} {singular if count == 1 else plural}"


def explain(factor: str, count: int) -> str:
    return {
        "clean_edit_approved": _plural(count, "clean edit approved by a reviewer", "clean edits approved by a reviewer"),
        "clean_edit_allowed": _plural(count, "clean edit allowed automatically", "clean edits allowed automatically"),
        "finding_dismissed": _plural(count, "finding dismissed as a false alarm", "findings dismissed as false alarms"),
        "confirmed_high": _plural(count, "confirmed high-severity finding", "confirmed high-severity findings"),
        "confirmed_medium": _plural(count, "confirmed medium-severity finding", "confirmed medium-severity findings"),
        "confirmed_low": _plural(count, "confirmed low-severity finding", "confirmed low-severity findings"),
        "broken_caller": _plural(count, "confirmed broken caller", "confirmed broken callers"),
        "secret_leak": _plural(count, "confirmed secret leak, reset to probation", "confirmed secret leaks, reset to probation"),
    }.get(factor, f"{count} x {factor}")
