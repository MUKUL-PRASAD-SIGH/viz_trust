"""Tests for the AEGIS score service.

The most important thing in here is `TestCollateralTable`: the step function is duplicated
on-chain in `contracts/src/AegisRegistry.sol` and off-chain in `app.py`. If those ever drift,
the service quotes a collateral requirement the chain refuses to honour. The expected values
below are written out by hand, mirroring the boundary assertions in
`contracts/test/AegisRegistry.t.sol`, so an edit to either copy fails loudly here.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import (
    SCORING_MODEL,
    AgentFeatures,
    EventsRequest,
    JobEvent,
    app,
    derive_features,
    required_collateral_bps,
    score_agent,
    score_band,
)

client = TestClient(app)

needs_model = pytest.mark.skipif(
    SCORING_MODEL is None,
    reason="No model artifacts. Run `python generate_data.py` then `python train.py`.",
)


# An agent with a solid clean record. Should be cheap to transact with. Deliberately kept
# short of the 1000 ceiling: a clamped agent hides score movement and makes sensitivity
# tests pass for the wrong reason.
CLEAN_AGENT = {
    "jobs_completed": 30,
    "dispute_rate": 0.0,
    "avg_job_value_usd": 90.0,
    "account_age_days": 400,
    "on_time_payment_rate": 0.95,
    "prior_defaults": 0,
    "counterparty_diversity": 20,
}

# An unremarkable agent near the middle of the population, with headroom in both directions.
TYPICAL_AGENT = {
    "jobs_completed": 18,
    "dispute_rate": 0.05,
    "avg_job_value_usd": 100.0,
    "account_age_days": 220,
    "on_time_payment_rate": 0.90,
    "prior_defaults": 0,
    "counterparty_diversity": 11,
}

# A new agent that disputes constantly and has already defaulted. Should prepay in full.
DISPUTING_AGENT = {
    "jobs_completed": 3,
    "dispute_rate": 0.6,
    "avg_job_value_usd": 800.0,
    "account_age_days": 20,
    "on_time_payment_rate": 0.5,
    "prior_defaults": 4,
    "counterparty_diversity": 1,
}


class TestCollateralTable:
    """The off-chain table must equal the on-chain table exactly. SPEC.md section 3."""

    # (score, expected bps, expected band) written out by hand, not derived from the code
    # under test.
    EXPECTED = [
        (0, 10000, "poor"),
        (1, 10000, "poor"),
        (399, 10000, "poor"),
        (400, 7000, "fair"),
        (500, 7000, "fair"),  # the on-chain starting score
        (599, 7000, "fair"),
        (600, 4000, "good"),
        (799, 4000, "good"),
        (800, 2000, "excellent"),
        (999, 2000, "excellent"),
        (1000, 2000, "excellent"),
    ]

    @pytest.mark.parametrize("score,expected_bps,expected_band", EXPECTED)
    def test_matches_contract_step_table(self, score, expected_bps, expected_band):
        assert required_collateral_bps(score) == expected_bps
        assert score_band(score) == expected_band

    def test_starting_score_is_mid_tier(self):
        """A freshly registered agent scores 500 on-chain and must land in the 7000 band."""
        assert required_collateral_bps(500) == 7000

    def test_only_four_tiers_exist(self):
        assert {required_collateral_bps(s) for s in range(0, 1001)} == {2000, 4000, 7000, 10000}

    def test_collateral_never_rises_as_score_rises(self):
        values = [required_collateral_bps(s) for s in range(0, 1001)]
        assert all(a >= b for a, b in zip(values, values[1:])), "curve must be monotonic"

    def test_breakpoints_are_exactly_where_spec_says(self):
        for boundary, below, above in [(800, 4000, 2000), (600, 7000, 4000), (400, 10000, 7000)]:
            assert required_collateral_bps(boundary - 1) == below
            assert required_collateral_bps(boundary) == above


@needs_model
class TestScoring:
    def test_clean_agent_scores_high(self):
        response = client.post("/score", json=CLEAN_AGENT)
        assert response.status_code == 200

        body = response.json()
        assert body["score"] >= 800
        assert body["band"] == "excellent"
        assert body["required_collateral_bps"] == 2000
        assert body["default_probability"] < 0.1

    def test_disputing_agent_scores_low(self):
        response = client.post("/score", json=DISPUTING_AGENT)
        assert response.status_code == 200

        body = response.json()
        assert body["score"] < 400
        assert body["band"] == "poor"
        assert body["required_collateral_bps"] == 10000
        assert body["default_probability"] > 0.5

    def test_clean_agent_beats_disputing_agent(self):
        clean = client.post("/score", json=CLEAN_AGENT).json()
        disputing = client.post("/score", json=DISPUTING_AGENT).json()

        assert clean["score"] > disputing["score"]
        assert clean["required_collateral_bps"] < disputing["required_collateral_bps"]

    def test_response_is_internally_consistent(self):
        """Band and bps in the response must agree with the score in the same response."""
        for payload in (CLEAN_AGENT, DISPUTING_AGENT):
            body = client.post("/score", json=payload).json()
            assert body["band"] == score_band(body["score"])
            assert body["required_collateral_bps"] == required_collateral_bps(body["score"])

    def test_score_stays_in_range(self):
        for payload in (CLEAN_AGENT, DISPUTING_AGENT):
            body = client.post("/score", json=payload).json()
            assert 0 <= body["score"] <= 1000

    def test_more_disputes_lower_the_score(self):
        previous = None
        for dispute_rate in (0.0, 0.1, 0.3, 0.6, 0.9):
            body = client.post("/score", json={**TYPICAL_AGENT, "dispute_rate": dispute_rate}).json()
            if previous is not None:
                assert body["score"] <= previous, "more disputes must never raise the score"
            previous = body["score"]

    def test_more_prior_defaults_lower_the_score(self):
        none = client.post("/score", json={**TYPICAL_AGENT, "prior_defaults": 0}).json()
        several = client.post("/score", json={**TYPICAL_AGENT, "prior_defaults": 5}).json()
        assert several["score"] < none["score"]

    def test_the_three_archetypes_land_in_different_collateral_tiers(self):
        """The product only works if the curve actually separates agents."""
        tiers = [
            client.post("/score", json=payload).json()["required_collateral_bps"]
            for payload in (CLEAN_AGENT, TYPICAL_AGENT, DISPUTING_AGENT)
        ]
        assert len(set(tiers)) == 3, f"expected three distinct tiers, got {tiers}"
        assert tiers == sorted(tiers), "a better agent must never post more collateral"


@needs_model
class TestTopFactors:
    def test_returns_three_ranked_factors(self):
        body = client.post("/score", json=DISPUTING_AGENT).json()
        factors = body["top_factors"]

        assert len(factors) == 3
        magnitudes = [abs(factor["impact"]) for factor in factors]
        assert magnitudes == sorted(magnitudes, reverse=True), "must be ranked by size"

    def test_factors_name_real_features_with_real_values(self):
        body = client.post("/score", json=DISPUTING_AGENT).json()
        for factor in body["top_factors"]:
            assert factor["feature"] in DISPUTING_AGENT
            assert factor["value"] == pytest.approx(DISPUTING_AGENT[factor["feature"]])
            assert factor["explanation"]

    def test_bad_history_produces_negative_impacts(self):
        """The demo line: 'score dropped N points because of the disputes'."""
        body = client.post("/score", json=DISPUTING_AGENT).json()
        impacts = {factor["feature"]: factor["impact"] for factor in body["top_factors"]}

        assert any(impact < 0 for impact in impacts.values())
        for risky_feature in ("dispute_rate", "prior_defaults"):
            if risky_feature in impacts:
                assert impacts[risky_feature] < 0, f"{risky_feature} should cost points here"

    def test_clean_history_produces_positive_impacts(self):
        body = client.post("/score", json=CLEAN_AGENT).json()
        impacts = [factor["impact"] for factor in body["top_factors"]]
        assert any(impact > 0 for impact in impacts)

    def test_a_single_dispute_costs_a_visible_number_of_points(self):
        """Impacts must not saturate to zero, or the explanation is worthless."""
        before = client.post("/score", json={**TYPICAL_AGENT, "dispute_rate": 0.0}).json()
        after = client.post("/score", json={**TYPICAL_AGENT, "dispute_rate": 0.25}).json()
        assert before["score"] - after["score"] >= 10


@needs_model
class TestFromEvents:
    EVENTS = {
        "events": [
            {
                "delivered": True,
                "disputed": False,
                "value_usd": 100.0,
                "timestamp": "2026-01-10T00:00:00Z",
                "counterparty": "0xaaa",
            },
            {
                "delivered": True,
                "disputed": False,
                "value_usd": 200.0,
                "timestamp": "2026-02-10T00:00:00Z",
                "counterparty": "0xbbb",
            },
            {
                "delivered": False,
                "disputed": True,
                "value_usd": 300.0,
                "timestamp": "2026-03-10T00:00:00Z",
                "counterparty": "0xccc",
            },
        ],
        "as_of": "2026-06-10T00:00:00Z",
    }

    def test_derives_features_from_events(self):
        features = derive_features(EventsRequest(**self.EVENTS))

        assert features.jobs_completed == 2
        assert features.prior_defaults == 1
        assert features.dispute_rate == pytest.approx(1 / 3)
        assert features.avg_job_value_usd == pytest.approx(200.0)
        assert features.on_time_payment_rate == pytest.approx(2 / 3)
        assert features.counterparty_diversity == 3
        assert features.account_age_days == 151  # 2026-01-10 to 2026-06-10

    def test_endpoint_scores_and_reports_what_it_derived(self):
        response = client.post("/score/from-events", json=self.EVENTS)
        assert response.status_code == 200

        body = response.json()
        assert 0 <= body["score"] <= 1000
        assert body["required_collateral_bps"] == required_collateral_bps(body["score"])
        assert len(body["top_factors"]) == 3
        assert body["derived_features"]["jobs_completed"] == 2
        assert body["derived_features"]["prior_defaults"] == 1

    def test_matches_scoring_the_same_features_directly(self):
        features = derive_features(EventsRequest(**self.EVENTS))
        direct = score_agent(features, SCORING_MODEL)
        via_events = client.post("/score/from-events", json=self.EVENTS).json()

        assert via_events["score"] == direct.score
        assert via_events["default_probability"] == direct.default_probability

    def test_clean_event_history_beats_disputed_event_history(self):
        def event(delivered, disputed, day):
            return {
                "delivered": delivered,
                "disputed": disputed,
                "value_usd": 100.0,
                "timestamp": f"2026-01-{day:02d}T00:00:00Z",
                "counterparty": f"0x{day:03d}",
            }

        clean = {"events": [event(True, False, d) for d in range(1, 11)], "as_of": "2026-09-01T00:00:00Z"}
        messy = {"events": [event(False, True, d) for d in range(1, 11)], "as_of": "2026-09-01T00:00:00Z"}

        assert (
            client.post("/score/from-events", json=clean).json()["score"]
            > client.post("/score/from-events", json=messy).json()["score"]
        )

    @staticmethod
    def _unlabelled(delivered_jobs: int, defaults: int = 0) -> EventsRequest:
        event = {"disputed": False, "value_usd": 50.0, "timestamp": "2026-01-01T00:00:00Z"}
        return EventsRequest(events=[{**event, "delivered": True}] * delivered_jobs
                             + [{**event, "delivered": False}] * defaults)

    def test_missing_counterparties_are_estimated_from_completed_jobs(self):
        assert derive_features(self._unlabelled(1)).counterparty_diversity == 1
        assert derive_features(self._unlabelled(10)).counterparty_diversity == pytest.approx(6.0)
        assert derive_features(self._unlabelled(21)).counterparty_diversity == pytest.approx(12.6)

    def test_estimated_diversity_ignores_defaults_and_never_drops_below_one(self):
        assert derive_features(self._unlabelled(0, defaults=3)).counterparty_diversity == 1
        assert derive_features(self._unlabelled(10, defaults=5)).counterparty_diversity == pytest.approx(6.0)

    def test_one_more_clean_job_raises_the_score_without_counterparties(self):
        def score(jobs: int) -> int:
            return client.post("/score/from-events",
                               json=self._unlabelled(jobs).model_dump(mode="json")).json()["score"]

        assert score(21) > score(20)

    def test_consecutive_clean_jobs_each_raise_the_score_by_a_similar_amount(self):
        """No alternating: rounding the estimate once made this +11, +1, +11, +1."""
        def score(jobs: int) -> int:
            return client.post("/score/from-events",
                               json=self._unlabelled(jobs).model_dump(mode="json")).json()["score"]

        gains = [score(n + 1) - score(n) for n in range(20, 26)]
        assert all(gain > 0 for gain in gains), gains
        assert max(gains) - min(gains) <= 2, gains

    def test_naive_timestamps_are_accepted(self):
        events = {
            "events": [
                {"delivered": True, "disputed": False, "value_usd": 50.0, "timestamp": "2026-01-01T00:00:00"}
            ],
            "as_of": "2026-01-31T00:00:00",
        }
        assert derive_features(EventsRequest(**events)).account_age_days == 30

    def test_registered_at_sets_account_age_instead_of_first_event(self):
        events = {
            "events": [
                {"delivered": True, "disputed": False, "value_usd": 50.0, "timestamp": "2026-01-01T00:00:00Z"}
            ],
            "as_of": "2026-01-01T00:01:00Z",
            "registered_at": "2024-01-02T00:01:00Z",
        }
        assert derive_features(EventsRequest(**events)).account_age_days == 730

    def test_empty_event_list_is_rejected(self):
        """An agent with no history is unknown, and the chain already charges it 100%."""
        assert client.post("/score/from-events", json={"events": []}).status_code == 422


class TestValidation:
    @pytest.mark.parametrize(
        "field,value",
        [
            ("dispute_rate", 1.5),
            ("dispute_rate", -0.1),
            ("on_time_payment_rate", 2.0),
            ("jobs_completed", -1),
            ("prior_defaults", -1),
            ("avg_job_value_usd", 0),
            ("account_age_days", -5),
            ("counterparty_diversity", -1),
        ],
    )
    def test_rejects_out_of_range_features(self, field, value):
        assert client.post("/score", json={**CLEAN_AGENT, field: value}).status_code == 422

    def test_rejects_missing_features(self):
        incomplete = {key: value for key, value in CLEAN_AGENT.items() if key != "dispute_rate"}
        assert client.post("/score", json=incomplete).status_code == 422

    def test_accepts_all_seven_features(self):
        assert set(AgentFeatures.model_fields) == set(CLEAN_AGENT), "SPEC.md section 7 is seven features"


class TestHealth:
    def test_health_responds(self):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["model_loaded"] is (SCORING_MODEL is not None)

    @needs_model
    def test_health_reports_the_trained_model(self):
        body = client.get("/health").json()
        assert body["status"] == "ok"
        assert 0.5 < body["test_roc_auc"] < 1.0
        assert len(body["features"]) == 7
