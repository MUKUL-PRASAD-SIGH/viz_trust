"""AEGIS score oracle.

Loop: poll the Registry for OutcomeRecorded since the last processed block -> take that
agent's accumulated history -> POST /score/from-events -> updateScore(agent, score, reason).

Plain polling, no websocket subscriptions: Anvil restarts constantly during development and a
poll loop recovers from that by itself. On any restart, crash or dropped connection the
oracle starts a fresh session, which replays history from block 0 and rescores any agent
whose latest outcome is newer than its latest score update. Nothing is lost because the chain
is the only store.

Usage (from the repo root, with anvil, the score service and a local deploy running):
    oracle/.venv/Scripts/python oracle/watcher.py      # Windows
    oracle/.venv/bin/python oracle/watcher.py          # macOS / Linux
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

import requests
from web3 import Web3
from web3.logs import DISCARD

from config import Config, ConfigError, load_config, registered_at
from history import History, Outcome
from publisher import RECENT_EVENTS, Board
from reasons import build_reason, describe_event
from writer import ScoreWriter

log = logging.getLogger("oracle")

RETRY_SECONDS = 3.0


class ChainReset(Exception):
    """The chain under us is not the one we replayed. Anvil restarted."""


class ScoreServiceError(Exception):
    """POST /score/from-events failed. Kept apart from requests errors web3 raises for RPC."""


class Session:
    """One connection to one chain. Discarded wholesale on any reset."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.w3 = Web3(Web3.HTTPProvider(config.rpc_url, request_kwargs={"timeout": 10}))
        if not self.w3.is_connected():
            raise ConnectionError(f"no RPC at {config.rpc_url}")

        address = Web3.to_checksum_address(config.registry_address)
        if self.w3.eth.get_code(address) in (b"", None):
            raise ConfigError(
                f"No contract at {address} (from deployments/local.json). Anvil was probably "
                "restarted. Redeploy:\n    cd contracts && python script/deploy_local.py"
            )

        self.registry = self.w3.eth.contract(address=address, abi=config.registry_abi)
        self.writer = ScoreWriter(self.w3, self.registry, config.oracle_private_key)
        self.writer.verify_oracle()

        self.history = History()
        self.board = Board(config.score_url, config.chain_id, config.names, self.writer.starting_score)
        self.escrow = None
        if config.escrow_address:
            escrow_address = Web3.to_checksum_address(config.escrow_address)
            if self.w3.eth.get_code(escrow_address) not in (b"", None):
                self.escrow = self.w3.eth.contract(address=escrow_address, abi=config.escrow_abi)
        self._job_ids: dict[str, int | None] = {}
        # Escrow job facts, forwarded for the score service's advisory risk flags only.
        self.jobs: dict[int, dict] = {}
        self._timestamps: dict[int, datetime] = {}
        self.last_block = -1
        self.last_block_hash: bytes | None = None

    # -- chain reads ------------------------------------------------------

    def _block_time(self, number: int) -> datetime:
        if number not in self._timestamps:
            block = self.w3.eth.get_block(number)
            self._timestamps[number] = datetime.fromtimestamp(block.timestamp, tz=timezone.utc)
        return self._timestamps[number]

    def _outcomes(self, from_block: int, to_block: int) -> list[Outcome]:
        logs = self.registry.events.OutcomeRecorded().get_logs(
            from_block=from_block, to_block=to_block
        )
        scale = 10**self.config.value_decimals
        return [
            Outcome(
                agent=entry.args.agent,
                delivered=entry.args.delivered,
                disputed=entry.args.disputed,
                value=entry.args.value,
                # The service requires a positive value; a zero-value job becomes one unit.
                value_usd=max(entry.args.value, 1) / scale,
                timestamp=self._block_time(entry.blockNumber),
                block_number=entry.blockNumber,
                log_index=entry.logIndex,
                tx_hash=Web3.to_hex(entry.transactionHash),
            )
            for entry in logs
        ]

    def _mark(self, head: int) -> None:
        self.last_block = head
        self.last_block_hash = bytes(self.w3.eth.get_block(head).hash)

    def _check_same_chain(self, head: int) -> None:
        # A restarted Anvil can overtake our height again within seconds, so a height check
        # alone misses resets. The hash of the last block we processed must still match.
        if head < self.last_block:
            raise ChainReset(f"head {head} is behind last processed block {self.last_block}")
        if bytes(self.w3.eth.get_block(self.last_block).hash) != self.last_block_hash:
            raise ChainReset(f"block {self.last_block} changed hash")

    def _job_id(self, outcome: Outcome) -> int | None:
        """The escrow job behind an outcome: JobSettled in the same transaction. None for
        outcomes recorded directly (seed history), which never went through the escrow."""
        if self.escrow is None:
            return None
        if outcome.tx_hash not in self._job_ids:
            receipt = self.w3.eth.get_transaction_receipt(outcome.tx_hash)
            settled = self.escrow.events.JobSettled().process_receipt(receipt, errors=DISCARD)
            self._job_ids[outcome.tx_hash] = settled[0].args.jobId if settled else None
        return self._job_ids[outcome.tx_hash]

    def _scan_jobs(self, from_block: int, to_block: int) -> None:
        """Record escrow jobs (hirer, worker, disputed, settled) for the risk flags. Never
        raises: a failure here must not stop scores being written."""
        if self.escrow is None:
            return
        try:
            events = self.escrow.events
            for entry in events.JobCreated().get_logs(from_block=from_block, to_block=to_block):
                self.jobs[entry.args.jobId] = {
                    "job_id": entry.args.jobId,
                    "hirer": entry.args.hirer,
                    "worker": entry.args.worker,
                    "value_usd": entry.args.value / 10**self.config.value_decimals,
                    "created_at": self._block_time(entry.blockNumber).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "disputed": False,
                    "settled": False,
                }
            for entry in events.JobDisputed().get_logs(from_block=from_block, to_block=to_block):
                if entry.args.jobId in self.jobs:
                    self.jobs[entry.args.jobId]["disputed"] = True
            for entry in events.JobSettled().get_logs(from_block=from_block, to_block=to_block):
                if entry.args.jobId in self.jobs:
                    self.jobs[entry.args.jobId]["settled"] = True
        except Exception as exc:  # noqa: BLE001 -- advisory data only
            log.warning("Could not read escrow jobs for risk flags: %s", exc)
            return
        self.board.set_jobs(list(self.jobs.values()))

    # -- scoring ----------------------------------------------------------

    def _score(self, agent: str, as_of: datetime) -> dict:
        url = f"{self.config.score_url}/score/from-events"
        try:
            body = self.history.score_request(agent, as_of=as_of, registered_at=registered_at(agent))
            response = requests.post(url, json=body, timeout=10)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise ScoreServiceError(f"{url}: {exc}") from exc
        return response.json()

    def rescore(self, trigger: Outcome) -> None:
        agent = trigger.agent
        result = self._score(agent, as_of=trigger.timestamp)

        old_score = self.writer.current_score(agent)
        new_score = result["score"]
        top_factor = result["top_factors"][0] if result["top_factors"] else None
        reason = build_reason(
            trigger,
            job_number=self.history.jobs_completed(agent),
            delta=new_score - old_score,
            top_factor=top_factor,
        )

        tx_hash = self.writer.update_score(agent, new_score, reason)
        self.board.record(trigger, old_score, new_score, reason, self._job_id(trigger), result["top_factors"])
        self.board.publish()

        log.info("%s  %d -> %d  %s", agent, old_score, new_score, reason)
        log.info("    features %s", result["derived_features"])
        log.info("    tx %s", tx_hash)

    # -- lifecycle --------------------------------------------------------

    def replay(self) -> None:
        """Rebuild history from block 0, then catch up agents the oracle missed."""
        head = self.w3.eth.block_number
        outcomes = self._outcomes(0, head)
        for outcome in outcomes:
            self.history.add(outcome)

        score_updates = self.registry.events.ScoreUpdated().get_logs(from_block=0, to_block=head)
        last_scored: dict[str, tuple[int, int]] = {}
        for entry in score_updates:
            last_scored[entry.args.agent] = (entry.blockNumber, entry.logIndex)
        self._rebuild_board(score_updates)

        stale = [
            self.history.outcomes(agent)[-1]
            for agent in self.history.agents()
            if self.history.outcomes(agent)[-1].position > last_scored.get(agent, (-1, -1))
        ]

        log.info(
            "Registry %s  oracle %s  replayed %d outcomes for %d agents up to block %d",
            self.registry.address, self.writer.account.address,
            len(outcomes), len(self.history.agents()), head,
        )
        for latest in stale:
            log.info("catching up %s (outcome at block %d never scored)", latest.agent, latest.block_number)
            self.rescore(latest)

        # Replayed agents have scores and events but no factors yet; ask the model, write nothing.
        for agent in self.board.missing_factors():
            if self.history.outcomes(agent):
                latest = self.history.outcomes(agent)[-1]
                self.board.set_top_factors(agent, self._score(agent, as_of=latest.timestamp)["top_factors"])

        self._scan_jobs(0, head)
        self._mark(head)
        self.board.mark_block(head)
        self.board.publish(force=True)

    def _rebuild_board(self, score_updates) -> None:
        """Dashboard state from logs replay already read, attributing each ScoreUpdated to the
        outcome that triggered it.

        Position alone is not enough: while the oracle works through a backlog, the update for
        job #21 can land after job #22 was recorded. But the reason the oracle wrote on-chain
        names its trigger ("completed job #21, ...", "lost dispute on $500 job ..."), so the
        trigger is the earliest not-yet-attributed outcome whose description matches. A
        catch-up rescore covers several outcomes at once; matching its trigger also retires
        the older ones it covered.
        """
        by_agent: dict[str, list] = {}
        for entry in score_updates:
            by_agent.setdefault(entry.args.agent, []).append(entry)

        for agent, entries in by_agent.items():
            outcomes = self.history.outcomes(agent)
            descriptions, delivered = [], 0
            for outcome in outcomes:
                delivered += outcome.delivered
                descriptions.append(describe_event(outcome, job_number=delivered) + " (")

            attributed: list[tuple[object, Outcome]] = []
            floor = 0  # outcomes before this index are already attributed or covered
            for entry in entries:
                position = (entry.blockNumber, entry.logIndex)
                candidates = [i for i in range(floor, len(outcomes)) if outcomes[i].position < position]
                if not candidates:
                    continue  # a score written with no outcome behind it (e.g. by hand)
                matched = next((i for i in candidates if entry.args.reason.startswith(descriptions[i])),
                               candidates[-1])
                attributed.append((entry, outcomes[matched]))
                floor = matched + 1

            for entry, trigger in attributed[-RECENT_EVENTS:]:
                self.board.record(
                    trigger, entry.args.oldScore, entry.args.newScore, entry.args.reason, self._job_id(trigger)
                )

    def poll_forever(self) -> None:
        log.info("Watching for OutcomeRecorded every %.1fs", self.config.poll_interval)
        while True:
            time.sleep(self.config.poll_interval)
            self.board.publish()  # no-op unless something changed or the heartbeat is due
            head = self.w3.eth.block_number
            self._check_same_chain(head)
            if head == self.last_block:
                continue

            for outcome in self._outcomes(self.last_block + 1, head):
                self.history.add(outcome)
                self.rescore(outcome)

            self._scan_jobs(self.last_block + 1, head)

            # Mark only what was scanned. Our own updateScore blocks get rescanned next tick,
            # harmlessly; marking the newer head could skip an outcome that landed meanwhile.
            self._mark(head)
            self.board.mark_block(head)


def main() -> None:
    logging.basicConfig(format="%(asctime)s  %(message)s", datefmt="%H:%M:%S", level=logging.INFO)

    last_error = None
    while True:
        try:
            session = Session(load_config())
            session.replay()
            last_error = None
            session.poll_forever()
        except ChainReset as exc:
            log.info("Chain reset (%s). Replaying from block 0.", exc)
            continue
        except ConfigError as exc:
            error = str(exc)
        except ScoreServiceError as exc:
            error = f"Score service unreachable or failing: {exc}"
        except (ConnectionError, requests.exceptions.ConnectionError) as exc:
            error = f"RPC unreachable: {exc}"
        except KeyboardInterrupt:
            return
        except Exception as exc:  # noqa: BLE001 -- the loop must survive anything and retry
            error = f"{type(exc).__name__}: {exc}"

        # Say it once, then retry quietly until something changes.
        if error != last_error:
            log.error("%s\nRetrying every %.0fs.", error, RETRY_SECONDS)
            last_error = error
        time.sleep(RETRY_SECONDS)


if __name__ == "__main__":
    main()
