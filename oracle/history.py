"""Accumulated job history per agent, rebuilt from chain events.

In memory only, keyed by agent address. On startup the watcher replays every
OutcomeRecorded event from block 0, so an Anvil restart or an oracle crash loses nothing: the
chain is the database.

The collapse from job events to the seven model features (SPEC.md section 7) happens in the
score service's `derive_features`, behind POST /score/from-events. It is deliberately not
repeated here -- a second copy of the feature logic would be one more thing to drift. The
service echoes the derived features back, and the watcher logs them.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class Outcome:
    """One OutcomeRecorded event, with the block time it landed at."""

    agent: str
    delivered: bool
    disputed: bool
    value: int  # raw on-chain units
    value_usd: float
    timestamp: datetime
    block_number: int
    log_index: int
    tx_hash: str

    @property
    def position(self) -> tuple[int, int]:
        return (self.block_number, self.log_index)


class History:
    def __init__(self) -> None:
        self._outcomes: dict[str, list[Outcome]] = defaultdict(list)

    def add(self, outcome: Outcome) -> None:
        self._outcomes[outcome.agent].append(outcome)

    def agents(self) -> list[str]:
        return list(self._outcomes)

    def outcomes(self, agent: str) -> list[Outcome]:
        return self._outcomes.get(agent, [])

    def jobs_completed(self, agent: str) -> int:
        return sum(1 for outcome in self.outcomes(agent) if outcome.delivered)

    def score_request(self, agent: str, as_of: datetime, registered_at: str | None = None) -> dict:
        """Body for POST /score/from-events.

        No counterparty is sent: OutcomeRecorded does not carry one, and msg.sender is always
        the escrow. The service then estimates diversity as jobs_completed * 0.6 (SPEC.md section 7).
        """
        request = {
            "events": [
                {
                    "delivered": outcome.delivered,
                    "disputed": outcome.disputed,
                    "value_usd": outcome.value_usd,
                    "timestamp": outcome.timestamp.isoformat(),
                }
                for outcome in self.outcomes(agent)
            ],
            "as_of": as_of.astimezone(timezone.utc).isoformat(),
        }
        if registered_at:
            request["registered_at"] = registered_at
        return request
