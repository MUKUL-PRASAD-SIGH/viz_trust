"""Concurrent jobs against one worker, for the `parallel` and `swarm` demo beats.

    parallel  the demo Hirer opens 5 jobs at once with the worker
    swarm     5 different, never-scored hirer wallets (Anvil accounts 4-8) each open one job
              with the same worker, at once. Unknown hirers post 100% collateral.

Each job runs in its own thread: open, wait for delivery, accept or dispute (same 2s rule as
demo_driver.py), settle. A hirer's transactions go out one at a time from a locally tracked
nonce, so concurrent jobs from one wallet never collide. demo_driver.py (`honest`, `sloppy`)
is not used or changed.

Usage (from the repo root):
    agents/.venv/Scripts/python agents/multi_driver.py parallel [--worker HonestAgent]
    agents/.venv/Scripts/python agents/multi_driver.py swarm    [--worker HonestAgent]
"""

from __future__ import annotations

import argparse
import sys
import threading
import time

from eth_account import Account
from web3.logs import DISCARD

from chain import ANVIL_MNEMONIC, abi, account, connect, contract, load_deployment
from demo_driver import MIN_WORK_SECONDS
from escrow import USDC, escrow_contract, is_stub, usd

JOBS = 5
STAGGER_SECONDS = 0.3
DELIVERY_TIMEOUT = 60
RESCORE_TIMEOUT = 60
SWARM_ACCOUNTS = [4, 5, 6, 7, 8]  # unused by the demo; 9 is the seeder

print_lock = threading.Lock()


def say(message: str) -> None:
    with print_lock:
        print(message, flush=True)


class Sender:
    """One wallet's transactions, strictly one at a time, from a locally tracked nonce."""

    def __init__(self, w3, acct) -> None:
        self.w3, self.acct = w3, acct
        self.lock = threading.Lock()
        self.nonce = w3.eth.get_transaction_count(acct.address, "pending")

    def send(self, call):
        with self.lock:
            tx = call.build_transaction({"from": self.acct.address, "nonce": self.nonce})
            tx_hash = self.w3.eth.send_raw_transaction(self.acct.sign_transaction(tx).raw_transaction)
            self.nonce += 1
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)
        if receipt.status != 1:
            raise RuntimeError(f"transaction reverted: {tx_hash.hex()}")
        return receipt


def run_job(n: int, label: str, sender: Sender, escrow, worker: str, worker_name: str,
            value: int, results: list) -> None:
    w3 = sender.w3
    try:
        receipt = sender.send(escrow.functions.createJob(worker, value))
        created = escrow.events.JobCreated().process_receipt(receipt, errors=DISCARD)[0]
        job_id, posted = created.args.jobId, created.args.collateralTaken
        tag = f"[job #{job_id}]"
        say(f"{tag} {label} opened a {usd(value)} job for {worker_name}, posted {usd(posted)} "
            f"({posted * 100 // value}%)")
        created_at = w3.eth.get_block(receipt.blockNumber).timestamp

        deadline, delivered = time.time() + DELIVERY_TIMEOUT, None
        while time.time() < deadline and delivered is None:
            logs = escrow.events.JobDelivered().get_logs(
                from_block=receipt.blockNumber, argument_filters={"jobId": job_id})
            delivered = logs[0] if logs else None
            if delivered is None:
                time.sleep(0.5)
        if delivered is None:
            say(f"{tag} FAIL: no delivery within {DELIVERY_TIMEOUT}s. Is {worker_name} running?")
            results.append((job_id, False))
            return

        took = w3.eth.get_block(delivered.blockNumber).timestamp - created_at
        if took < MIN_WORK_SECONDS:
            say(f"{tag} delivered after {took}s, too fast to be real work: disputing")
            sender.send(escrow.functions.dispute(job_id))
        else:
            say(f"{tag} delivered after {took}s: accepting")
            sender.send(escrow.functions.accept(job_id))

        settled_receipt = sender.send(escrow.functions.settle(job_id))
        settled = escrow.events.JobSettled().process_receipt(settled_receipt, errors=DISCARD)[0]
        outcome = f"paid {usd(settled.args.amountToWorker)}" if settled.args.workerPaid else "settled against the worker"
        say(f"{tag} settled: {worker_name} {outcome}")
        results.append((job_id, True))
    except Exception as exc:  # noqa: BLE001 -- report every job, never hide one
        say(f"[job ?] {label} FAIL: {type(exc).__name__}: {exc}")
        results.append((None, False))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["parallel", "swarm"])
    parser.add_argument("--worker", default="HonestAgent")
    parser.add_argument("--value", type=float, default=500)
    args = parser.parse_args()

    deployment = load_deployment()
    if is_stub(deployment):
        raise SystemExit("multi_driver needs the real AegisEscrow (mUSDC moves). Run select_escrow.py --real.")
    w3 = connect(deployment)
    escrow = escrow_contract(w3, deployment)
    registry = contract(w3, deployment, "AegisRegistry")
    usdc = w3.eth.contract(address=w3.to_checksum_address(deployment["MockUSDC"]), abi=abi("MockUSDC"))
    worker = deployment["accounts"][args.worker]["address"]
    value = int(round(args.value * USDC))

    if args.mode == "parallel":
        hirer = account(deployment, "Hirer")
        sender = Sender(w3, hirer)
        # Every job draws collateral now and the remainder at settle: approve all of it.
        sender.send(usdc.functions.approve(escrow.address, value * JOBS))
        plan = [(f"Hirer", sender) for _ in range(JOBS)]
        watched = [hirer.address]
        say(f"Hirer opens {JOBS} jobs at once with {args.worker} "
            f"(score {registry.functions.getProfile(hirer.address).call()[1]}, "
            f"{registry.functions.requiredCollateralBps(hirer.address).call() // 100}% deposit)")
    else:
        plan, watched = [], []
        for index in SWARM_ACCOUNTS:
            acct = Account.from_mnemonic(ANVIL_MNEMONIC, account_path=f"m/44'/60'/0'/0/{index}")
            sender = Sender(w3, acct)
            if usdc.functions.balanceOf(acct.address).call() < value:
                sender.send(usdc.functions.mint(acct.address, value))  # MockUSDC: public test mint
            sender.send(usdc.functions.approve(escrow.address, value))
            plan.append((f"Hirer-{index} ({acct.address[:6]}…)", sender))
            watched.append(acct.address)
        say(f"{len(plan)} different, never-scored hirers each open a job with {args.worker} at once")

    defaults_before = {a: registry.functions.getProfile(a).call()[4] for a in watched}
    score_before = registry.functions.getProfile(worker).call()[1]
    start_block = w3.eth.block_number

    results: list = []
    threads = []
    for n, (label, sender) in enumerate(plan, start=1):
        thread = threading.Thread(target=run_job, args=(n, label, sender, escrow, worker, args.worker, value, results))
        thread.start()
        threads.append(thread)
        time.sleep(STAGGER_SECONDS)
    for thread in threads:
        thread.join()

    ok = [job for job, good in results if good]
    say(f"\n{len(ok)} of {len(plan)} jobs settled")

    defaulted = [a for a in watched if registry.functions.getProfile(a).call()[4] != defaults_before[a]]
    if defaulted:
        say(f"FAIL: hirer(s) recorded as a default: {defaulted}")
        return 1

    # The oracle rescores each settled job, one at a time. Wait until it has done all of them.
    deadline = time.time() + RESCORE_TIMEOUT
    updates = []
    while time.time() < deadline:
        updates = registry.events.ScoreUpdated().get_logs(from_block=start_block, argument_filters={"agent": worker})
        if len(updates) >= len(ok):
            break
        time.sleep(1)
    if len(updates) < len(ok):
        say(f"FAIL: oracle rescored {len(updates)} of {len(ok)} jobs within {RESCORE_TIMEOUT}s")
        return 1

    for update in updates:
        say(f"  rescore {update.args.oldScore} -> {update.args.newScore}: {update.args.reason}")
    final = registry.functions.getProfile(worker).call()[1]
    bps = registry.functions.requiredCollateralBps(worker).call()
    say(f"\n{args.worker} credit score {score_before} -> {final} over {len(ok)} concurrent jobs "
        f"({bps // 100}% deposit)")
    return 0 if len(ok) == len(plan) else 1


if __name__ == "__main__":
    sys.exit(main())
