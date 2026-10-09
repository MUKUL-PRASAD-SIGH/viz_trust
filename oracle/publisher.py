"""The dashboard's view of every agent, held in the oracle's memory and pushed to the score
service, which serves it as GET /agents/state.

The oracle already knows everything the dashboard shows -- it just wrote it on-chain -- so the
dashboard never touches web3 and the score service never reads the chain. Raw facts only go
out from here (scores, events, factors); band and collateral are derived by the score service,
which owns those tables.

The full snapshot is re-sent on a heartbeat, so a restarted score service is repopulated
within seconds, and a missed push is never permanent.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field

import requests

from history import Outcome
from reasons import event_type

log = logging.getLogger("oracle")

RECENT_EVENTS = 10
HEARTBEAT_SECONDS = 3.0


@dataclass
class AgentCard:
    address: str
    name: str
    score: int
    previous_score: int
    top_factors: list[dict] = field(default_factory=list)
    events: deque = field(default_factory=lambda: deque(maxlen=RECENT_EVENTS))  # newest first


class Board:
    def __init__(self, score_url: str, chain_id: int, names: dict[str, str], starting_score: int) -> None:
        self.url = f"{score_url}/internal/agents/state"
        self.chain_id = chain_id
        self.names = names
        self.starting_score = starting_score
        self.cards: dict[str, AgentCard] = {}
        self.jobs: list[dict] = []  # escrow job facts, for advisory risk flags only
        self.block = 0
        self._dirty = True
        self._last_push = 0.0
        self._push_failing = False

    def _card(self, agent: str) -> AgentCard:
        if agent not in self.cards:
            name = self.names.get(agent, f"{agent[:6]}...{agent[-4:]}")
            self.cards[agent] = AgentCard(agent, name, self.starting_score, self.starting_score)
        return self.cards[agent]

    def record(
        self,
        trigger: Outcome,
        old_score: int,
        new_score: int,
        reason: str,
        job_id: int | None,
        top_factors: list[dict] | None = None,
    ) -> None:
        """One ScoreUpdated, attributed to the outcome that caused it."""
        card = self._card(trigger.agent)
        card.previous_score, card.score = old_score, new_score
        if top_factors is not None:
            card.top_factors = top_factors
        card.events.appendleft(
            {
                "type": event_type(trigger),
                "job_id": job_id,
                "value_usd": round(trigger.value_usd, 2),
                "reason": reason,
                "delta": new_score - old_score,
                "timestamp": trigger.timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        )
        self._dirty = True

    def set_top_factors(self, agent: str, top_factors: list[dict]) -> None:
        self._card(agent).top_factors = top_factors
        self._dirty = True

    def set_jobs(self, jobs: list[dict]) -> None:
        if jobs != self.jobs:
            self.jobs = jobs
            self._dirty = True

    def missing_factors(self) -> list[str]:
        return [agent for agent, card in self.cards.items() if not card.top_factors]

    def mark_block(self, block: int) -> None:
        if block != self.block:
            self.block = block
            self._dirty = True

    def snapshot(self) -> dict:
        # Named demo agents first, in deployments/local.json order, then anyone else by arrival.
        order = [a for a in self.names if a in self.cards] + [a for a in self.cards if a not in self.names]
        return {
            "chain_id": self.chain_id,
            "block": self.block,
            "agents": [
                {
                    "address": card.address,
                    "name": card.name,
                    "score": card.score,
                    "previous_score": card.previous_score,
                    "top_factors": card.top_factors,
                    "recent_events": list(card.events),
                }
                for card in (self.cards[a] for a in order)
            ],
            "jobs": self.jobs,
        }

    def publish(self, force: bool = False) -> None:
        """Push if anything changed or the heartbeat is due. Never raises: the dashboard is a
        viewer, and a down score service must not stop scores being written on-chain."""
        due = time.monotonic() - self._last_push >= HEARTBEAT_SECONDS
        if not (force or self._dirty or due):
            return
        try:
            requests.put(self.url, json=self.snapshot(), timeout=5).raise_for_status()
        except requests.RequestException as exc:
            if not self._push_failing:
                log.warning("Could not publish dashboard state to %s: %s (will keep retrying)", self.url, exc)
            self._push_failing = True
            return
        if self._push_failing:
            log.info("Dashboard state publishing again")
        self._push_failing = False
        self._dirty = False
        self._last_push = time.monotonic()
