from __future__ import annotations

import pytest

from engine import scoring
from engine.models import Finding


def finding(check="reality_check", severity="medium") -> Finding:
    return Finding(check=check, severity=severity, file="a.py", line=1, message="m")


def test_new_agent_starts_at_500_on_probation():
    assert scoring.START_SCORE == 500 and scoring.tier_for(500) == "probation"


@pytest.mark.parametrize("score,tier", [
    (0, "probation"), (599, "probation"), (600, "standard"), (799, "standard"), (800, "trusted"), (1000, "trusted"),
])
def test_tier_boundaries(score, tier):
    assert scoring.tier_for(score) == tier


@pytest.mark.parametrize("score,band", [(850, "excellent"), (650, "good"), (450, "fair"), (100, "poor")])
def test_bands_match_the_aegis_breakpoints(score, band):
    assert scoring.band_for(score) == band


def test_points_table():
    assert scoring.POINTS["clean_edit_approved"] == 14
    assert scoring.POINTS["clean_edit_allowed"] == 8
    assert scoring.POINTS["finding_dismissed"] == 2
    assert scoring.POINTS["confirmed_high"] == -60
    assert scoring.POINTS["confirmed_medium"] == -30
    assert scoring.POINTS["broken_caller"] == -20


def test_full_size_edit_earns_the_full_gain():
    assert scoring.clean_edit_points("clean_edit_approved", 12, 3) == 14
    assert scoring.clean_edit_points("clean_edit_allowed", 12, 3) == 8


def test_one_line_edit_barely_counts():
    assert scoring.clean_edit_points("clean_edit_approved", 1, 0) <= 3
    assert scoring.clean_edit_points("clean_edit_approved", 1, 0) >= 1   # never zero


def test_gain_grows_with_size_and_blast_radius():
    small = scoring.clean_edit_points("clean_edit_approved", 2, 0)
    bigger = scoring.clean_edit_points("clean_edit_approved", 6, 0)
    wider = scoring.clean_edit_points("clean_edit_approved", 2, 3)
    assert small < bigger and small < wider


def test_weight_is_capped_at_one():
    assert scoring.edit_weight(500, 50) == 1.0


@pytest.mark.parametrize("check,severity,factor,delta", [
    ("reality_check", "medium", "confirmed_medium", -30),
    ("scope_guard", "low", "confirmed_low", -10),
    ("test_guardian", "high", "confirmed_high", -60),
    ("impact_analyst", "medium", "broken_caller", -20),
    ("hardcode_hunter", "high", "secret_leak", -60),
])
def test_confirm_penalties(check, severity, factor, delta):
    assert scoring.confirm_penalty(finding(check, severity)) == (factor, delta)


def test_secret_leak_is_only_a_high_hardcode_finding():
    assert scoring.is_secret_leak(finding("hardcode_hunter", "high"))
    assert not scoring.is_secret_leak(finding("hardcode_hunter", "medium"))
    assert not scoring.is_secret_leak(finding("test_guardian", "high"))


def test_scores_clamp_to_range():
    assert scoring.apply_delta(995, 14) == 1000
    assert scoring.apply_delta(10, -60) == 0


@pytest.mark.parametrize("score", [550, 700, 900, 1000])
def test_secret_leak_caps_at_probation(score):
    new = scoring.apply_delta(score, -60, secret_leak=True)
    assert new <= scoring.LEAK_CAP and scoring.tier_for(new) == "probation"


def test_leak_never_raises_a_low_score():
    assert scoring.apply_delta(100, -60, secret_leak=True) == 40


def test_explanations_pluralise():
    assert scoring.explain("clean_edit_approved", 1).startswith("1 clean edit approved")
    assert scoring.explain("clean_edit_approved", 4).startswith("4 clean edits approved")
