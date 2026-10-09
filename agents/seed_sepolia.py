"""Seed the Base Sepolia deployment with the same demo history as seed_demo.py.

Base Sepolia has one wallet (contracts/.env PRIVATE_KEY): it is owner AND scoreOracle. So this
script borrows the Registry's escrow slot for that wallet, records the PLANS outcomes, hands the
slot back to AegisEscrow, then scores each agent once through the local score service (with
the same registeredAt rule as seed_demo.py) and writes updateScore. No oracle runs on this
chain; nothing here replays logs.

The agents are the same addresses as on Anvil (no keys needed: only the owner writes).

Usage (from the repo root, score service running on 127.0.0.1:8000):
    agents/.venv/Scripts/python agents/seed_sepolia.py
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from eth_account import Account
from web3 import Web3

from chain import REPO_ROOT, abi
from seed_demo import DAY, PLANS, USDC, schedule

DEPLOYMENT_PATH = REPO_ROOT / "deployments" / "base-sepolia.json"
ENV_PATH = REPO_ROOT / "contracts" / ".env"
SCORE_URL = "http://127.0.0.1:8000/score/from-events"
# Same addresses as Anvil accounts 1-3 (deployments/local.json).
AGENTS = {
    "HonestAgent": "0x70997970C51812dc3A010C7d01b50e0d17dc79C8",
    "SloppyAgent": "0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC",
    "Hirer": "0x90F79bf6EB2c4f870365E785982E1f101E93b906",
}
GAS_PER_OUTCOME = 130_000  # upper bound; a first outcome also registers the agent


def env() -> dict:
    values = {}
    for line in Path(ENV_PATH).read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def rpc(call, attempts: int = 6):
    """Public RPC: back off on rate limits and transient errors."""
    for attempt in range(attempts):
        try:
            return call()
        except Exception as exc:  # noqa: BLE001 -- retry anything transient, then give up loudly
            if attempt == attempts - 1:
                raise
            print(f"\n  RPC retry ({type(exc).__name__}: {str(exc)[:80]})", flush=True)
            time.sleep(2 * (attempt + 1))


class Sender:
    """Sequential sends with a locally tracked nonce, so no two transactions share one."""

    def __init__(self, w3: Web3, acct) -> None:
        self.w3, self.acct = w3, acct
        self.nonce = rpc(lambda: w3.eth.get_transaction_count(acct.address, "pending"))

    def send(self, call):
        tx = rpc(lambda: call.build_transaction({"from": self.acct.address, "nonce": self.nonce}))
        raw = self.acct.sign_transaction(tx).raw_transaction
        tx_hash = rpc(lambda: self.w3.eth.send_raw_transaction(raw))
        receipt = rpc(lambda: self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120, poll_latency=1.5))
        if receipt.status != 1:
            raise RuntimeError(f"reverted: {tx_hash.hex()}")
        self.nonce += 1
        return receipt


def main() -> int:
    deployment = json.loads(DEPLOYMENT_PATH.read_text())
    config = env()
    w3 = Web3(Web3.HTTPProvider(config["BASE_SEPOLIA_RPC_URL"], request_kwargs={"timeout": 20}))
    acct = Account.from_key(config["PRIVATE_KEY"])
    registry = w3.eth.contract(address=Web3.to_checksum_address(deployment["AegisRegistry"]), abi=abi("AegisRegistry"))
    escrow_address = Web3.to_checksum_address(deployment["AegisEscrow"])

    if rpc(lambda: registry.functions.owner().call()) != acct.address:
        raise SystemExit("contracts/.env PRIVATE_KEY is not the Registry owner.")
    if rpc(lambda: registry.functions.scoreOracle().call()) != acct.address:
        raise SystemExit("contracts/.env PRIVATE_KEY is not the Registry scoreOracle.")

    for plan in PLANS:
        profile = rpc(lambda: registry.functions.getProfile(AGENTS[plan.role]).call())
        if profile[6]:
            raise SystemExit(f"{plan.role} already has a profile on Base Sepolia. Refusing to seed twice.")

    events = schedule(start=0)
    tx_count = len(events) + 2 + len(PLANS)
    fee = rpc(lambda: w3.eth.gas_price) * 2
    needed = tx_count * GAS_PER_OUTCOME * fee
    balance = rpc(lambda: w3.eth.get_balance(acct.address))
    print(f"{tx_count} transactions, up to {needed / 1e18:.8f} ETH needed, wallet has {balance / 1e18:.8f} ETH")
    if balance < needed:
        raise SystemExit(f"Not enough ETH: need about {(needed - balance) / 1e18:.8f} more.")

    now = rpc(lambda: w3.eth.get_block("latest")).timestamp
    registered = {
        plan.role: datetime.fromtimestamp(now - (plan.span_days - 1) * DAY, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        for plan in PLANS
    }
    deployment["accounts"] = {
        role: {"address": AGENTS[role], "registeredAt": registered[role]} for role in AGENTS
    }
    DEPLOYMENT_PATH.write_text(json.dumps(deployment, indent=2) + "\n")

    sender = Sender(w3, acct)
    print(f"Borrowing the escrow slot for {acct.address}")
    sender.send(registry.functions.setEscrow(acct.address))
    try:
        print("Recording seed history", end="", flush=True)
        for _, plan, outcome in events:
            sender.send(registry.functions.recordOutcome(
                AGENTS[plan.role], outcome.delivered, outcome.disputed, outcome.value_usd * USDC))
            print(".", end="", flush=True)
        print(f" {len(events)} outcomes recorded")
    finally:
        sender.send(registry.functions.setEscrow(escrow_address))
        print(f"Escrow restored to {escrow_address}")

    as_of = datetime.fromtimestamp(rpc(lambda: w3.eth.get_block("latest")).timestamp, tz=timezone.utc).isoformat()
    for plan in PLANS:
        body = {
            "events": [
                {"delivered": o.delivered, "disputed": o.disputed, "value_usd": o.value_usd, "timestamp": as_of}
                for o in plan.outcomes
            ],
            "as_of": as_of,
            "registered_at": registered[plan.role],
        }
        response = requests.post(SCORE_URL, json=body, timeout=10)
        response.raise_for_status()
        score = response.json()["score"]
        sender.send(registry.functions.updateScore(
            AGENTS[plan.role], score, f"seeded history: {len(plan.outcomes)} outcomes"))
        print(f"{plan.role}: wrote score {score}")

    spent = balance - rpc(lambda: w3.eth.get_balance(acct.address))
    print(f"Spent {spent / 1e18:.8f} ETH")
    return 0


if __name__ == "__main__":
    sys.exit(main())
