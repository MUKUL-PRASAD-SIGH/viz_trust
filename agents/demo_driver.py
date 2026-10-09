"""STAND-IN HIRER. Drives one job end to end. It is a script, not a real hiring
agent.

    post job -> wait for delivery -> judge it -> accept or dispute -> settle -> show rescore

The judgement is a stand-in too: a delivery that lands less than MIN_WORK_SECONDS after the
job was created (by block time) is treated as "no work was done" and disputed. HonestAgent
works for ~3s; SloppyAgent delivers at once.

Works against either escrow, following deployments/local.json "escrowIsStub":
  - real AegisEscrow: real mUSDC moves. The hirer approves the FULL job value up front,
    because the escrow takes the collateral at createJob and the remainder at settle.
    Approving only the collateral does not fail -- settle succeeds, pays the worker the
    collateral, and records the HIRER as defaulted. So after every settle this script checks
    the hirer was not recorded as a default, and exits loudly if it was.
  - StubEscrow: no tokens exist; balances are not shown.

Usage (from the repo root; anvil, deploy, score service, oracle and the agent running):
    agents/.venv/Scripts/python agents/demo_driver.py --worker HonestAgent
    agents/.venv/Scripts/python agents/demo_driver.py --worker SloppyAgent --value 500
"""

from __future__ import annotations

import argparse
import sys
import time

from web3.logs import DISCARD

from chain import abi, account, connect, contract, load_deployment, send
from escrow import USDC, escrow_contract, is_stub, usd

MIN_WORK_SECONDS = 2
DELIVERY_TIMEOUT = 30
RESCORE_TIMEOUT = 30


def say(message: str) -> None:
    print(f"Hirer: {message}", flush=True)


def signed_usd(amount: int) -> str:
    return ("+" if amount > 0 else "-" if amount < 0 else "") + usd(abs(amount))


class HirerDefaulted(SystemExit):
    pass


def fail_if_hirer_defaulted(registry, settle_receipt, hirer: str, defaults_before: int) -> None:
    """The one silent failure in the real escrow: an under-approved hirer is recorded as a
    default while settle succeeds. Checked two ways, and never with `assert` (python -O)."""
    recorded = registry.events.OutcomeRecorded().process_receipt(settle_receipt, errors=DISCARD)
    hirer_defaults = [e for e in recorded if e.args.agent == hirer and not e.args.delivered]
    defaults_after = registry.functions.getProfile(hirer).call()[4]

    if hirer_defaults or defaults_after != defaults_before:
        banner = "!" * 72
        raise HirerDefaulted(chr(10).join([
            "",
            banner,
            "FAIL: the HIRER was recorded as a default by this settle.",
            f"  OutcomeRecorded(hirer, delivered=false) in settle tx: {len(hirer_defaults)}",
            f"  hirer defaults counter: {defaults_before} -> {defaults_after}",
            "The escrow could not draw the remainder of the job value from the hirer (allowance",
            "or balance too low), paid the worker only the deposit, and blamed the hirer.",
            "Its score will decay run over run and the 20% deposit headline will disappear.",
            banner,
        ]))


def wait_for(fetch, timeout: float):
    deadline = time.time() + timeout
    while time.time() < deadline:
        found = fetch()
        if found:
            return found[0]
        time.sleep(0.5)
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", required=True, help="Agent name from deployments/local.json")
    parser.add_argument("--value", type=float, default=500, help="Job value in USD (default: 500)")
    args = parser.parse_args()

    deployment = load_deployment()
    if args.worker not in deployment["accounts"]:
        raise SystemExit(f"No account named {args.worker} in deployments/local.json")

    w3 = connect(deployment)
    hirer = account(deployment, "Hirer")
    escrow = escrow_contract(w3, deployment)
    registry = contract(w3, deployment, "AegisRegistry")
    worker = deployment["accounts"][args.worker]["address"]
    value = int(round(args.value * USDC))

    usdc = None
    if not is_stub(deployment):
        if "MockUSDC" not in deployment:
            raise SystemExit("Real escrow in deployments/local.json but no MockUSDC address. Redeploy.")
        usdc = w3.eth.contract(address=w3.to_checksum_address(deployment["MockUSDC"]), abi=abi("MockUSDC"))

    def balance(address: str) -> int:
        return usdc.functions.balanceOf(address).call()

    bps_before = registry.functions.requiredCollateralBps(worker).call()
    hirer_defaults_before = registry.functions.getProfile(hirer.address).call()[4]

    if usdc is not None:
        # The full value, not just the collateral: see the module docstring.
        send(w3, hirer, usdc.functions.approve(escrow.address, value))
        hirer_start, worker_start = balance(hirer.address), balance(worker)
        say(f"wallet {usd(hirer_start)} mUSDC; approved the escrow to draw up to {usd(value)}")

    say(f"posting a {usd(value)} job for {args.worker}")
    receipt = send(w3, hirer, escrow.functions.createJob(worker, value))
    created = escrow.events.JobCreated().process_receipt(receipt, errors=DISCARD)[0]
    job_id = created.args.jobId
    created_at = w3.eth.get_block(receipt.blockNumber).timestamp
    hirer_score = registry.functions.getProfile(hirer.address).call()[1]
    posted = created.args.collateralTaken
    say(f"job #{job_id} is open. Posted {usd(posted)} upfront: "
        f"{posted * 100 // value}% of {usd(value)}, not 100%, on my credit score of {hirer_score}")
    if usdc is not None:
        hirer_after_create = balance(hirer.address)
        say(f"wallet {usd(hirer_start)} -> {usd(hirer_after_create)} "
            f"({signed_usd(hirer_after_create - hirer_start)} locked in escrow)")

    delivered = wait_for(
        lambda: escrow.events.JobDelivered().get_logs(
            from_block=receipt.blockNumber, argument_filters={"jobId": job_id}),
        DELIVERY_TIMEOUT,
    )
    if delivered is None:
        say(f"no delivery within {DELIVERY_TIMEOUT}s. Is {args.worker} running?")
        return 1

    took = w3.eth.get_block(delivered.blockNumber).timestamp - created_at
    if took < MIN_WORK_SECONDS:
        say(f"job #{job_id} came back after {took}s, too fast to be real work. Disputing.")
        send(w3, hirer, escrow.functions.dispute(job_id))
    else:
        say(f"job #{job_id} came back after {took}s and checks out. Accepting.")
        send(w3, hirer, escrow.functions.accept(job_id))

    settle_receipt = send(w3, hirer, escrow.functions.settle(job_id))
    # The settle receipt also carries the Registry's OutcomeRecorded; DISCARD skips it quietly.
    settled = escrow.events.JobSettled().process_receipt(settle_receipt, errors=DISCARD)[0]
    if settled.args.workerPaid:
        say(f"job #{job_id} settled, {args.worker} paid {usd(settled.args.amountToWorker)}")
    else:
        say(f"job #{job_id} settled against {args.worker}, not paid")
    say(f"JobSettled(workerPaid={settled.args.workerPaid}, amountToWorker={usd(settled.args.amountToWorker)})")

    if usdc is not None:
        hirer_end, worker_end = balance(hirer.address), balance(worker)
        say(f"wallet {usd(hirer_after_create)} -> {usd(hirer_end)} at settle "
            f"({signed_usd(hirer_end - hirer_after_create)}); "
            f"{args.worker} wallet {signed_usd(worker_end - worker_start)}")
        say(f"net for this job: hirer {signed_usd(hirer_end - hirer_start)}, "
            f"{args.worker} {signed_usd(worker_end - worker_start)}")

    fail_if_hirer_defaulted(registry, settle_receipt, hirer.address, hirer_defaults_before)
    say("check passed: hirer was not recorded as a default")

    rescored = wait_for(
        lambda: registry.events.ScoreUpdated().get_logs(
            from_block=settle_receipt.blockNumber, argument_filters={"agent": worker}),
        RESCORE_TIMEOUT,
    )
    if rescored is None:
        say(f"no rescore within {RESCORE_TIMEOUT}s. Is the oracle running?")
        return 1

    bps_after = registry.functions.requiredCollateralBps(worker).call()
    print()
    print(f"{args.worker} credit score {rescored.args.oldScore} -> {rescored.args.newScore}")
    print(f"  deposit required: {bps_before // 100}% -> {bps_after // 100}% upfront")
    print(f"  reason: {rescored.args.reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
