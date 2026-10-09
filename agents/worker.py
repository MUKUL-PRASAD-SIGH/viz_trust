"""The worker loop both demo agents share. They differ only in how they do the work.

Output is for a projector, not a log file: one plain sentence per thing that happens, prefixed
with the agent's name.
"""

from __future__ import annotations

import argparse
import threading
import time
from typing import Callable

from chain import account, connect, contract, load_deployment, send
from escrow import escrow_contract, is_stub, usd

POLL_SECONDS = 0.5
BAND_BY_BPS = {2000: "excellent", 4000: "good", 7000: "fair", 10000: "poor"}


def parse_args(default_name: str) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--name", default=default_name,
        help="Agent name; must be an account in deployments/local.json (default: %(default)s)",
    )
    return parser.parse_args()


class Worker:
    def __init__(self, name: str) -> None:
        self.name = name
        self.deployment = load_deployment()
        if name not in self.deployment["accounts"]:
            known = ", ".join(self.deployment["accounts"])
            raise SystemExit(f"No account named {name} in deployments/local.json. Known: {known}")

        self.w3 = connect(self.deployment)
        self.account = account(self.deployment, name)
        self.escrow = escrow_contract(self.w3, self.deployment)
        self.registry = contract(self.w3, self.deployment, "AegisRegistry")
        self.my_jobs: set[int] = set()
        # Jobs may be worked concurrently; their transactions go out one at a time (one nonce).
        self._send_lock = threading.Lock()

    def say(self, message: str) -> None:
        print(f"{self.name}: {message}", flush=True)

    def standing(self) -> str:
        profile = self.registry.functions.getProfile(self.account.address).call()
        bps = self.registry.functions.requiredCollateralBps(self.account.address).call()
        score = profile[1] if profile[6] else "unscored"
        return f"score {score}, {BAND_BY_BPS[bps]}, {bps // 100}% deposit"

    def _logs(self, event, start: int, end: int, **filters):
        return event().get_logs(from_block=start, to_block=end, argument_filters=filters or None)

    def run(self, do_work: Callable[[int, int], None]) -> None:
        stub = " (StubEscrow stand-in)" if is_stub(self.deployment) else ""
        self.say(f"online as {self.account.address}, {self.standing()}")
        self.say(f"watching escrow {self.escrow.address}{stub} for jobs")

        last = self.w3.eth.block_number
        while True:
            time.sleep(POLL_SECONDS)
            head = self.w3.eth.block_number
            if head < last:
                raise SystemExit(f"{self.name}: chain restarted under me. Redeploy, reseed, restart me.")
            if head == last:
                continue
            start, last = last + 1, head

            for entry in self._logs(self.escrow.events.JobCreated, start, head, worker=self.account.address):
                job_id, value = entry.args.jobId, entry.args.value
                self.my_jobs.add(job_id)
                do_work(job_id, value)

            for entry in self._logs(self.escrow.events.JobDisputed, start, head):
                if entry.args.jobId in self.my_jobs:
                    self.say(f"job #{entry.args.jobId} was disputed by the hirer")

            for entry in self._logs(self.escrow.events.JobSettled, start, head):
                if entry.args.jobId in self.my_jobs:
                    if entry.args.workerPaid:
                        self.say(f"job #{entry.args.jobId} settled, paid {usd(entry.args.amountToWorker)}")
                    else:
                        self.say(f"job #{entry.args.jobId} settled against me, not paid")

            for entry in self._logs(self.registry.events.ScoreUpdated, start, head, agent=self.account.address):
                old, new = entry.args.oldScore, entry.args.newScore
                self.say(f"credit score {old} -> {new}: {entry.args.reason}")
                self.say(f"now {self.standing()}")

    def deliver(self, job_id: int) -> None:
        with self._send_lock:
            send(self.w3, self.account, self.escrow.functions.markDelivered(job_id))
        self.say(f"delivered job #{job_id}")
