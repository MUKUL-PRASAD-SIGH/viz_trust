"""Deploy to Base Sepolia and record the addresses in deployments/base-sepolia.json.

Same shape as deployments/local.json. Reads BASE_SEPOLIA_RPC_URL and PRIVATE_KEY from
contracts/.env (gitignored). No contract verification. Deployment only: do not point the
oracle, the agents or seed_demo.py at this chain -- the demo runs on Anvil.

Usage (from contracts/):
    python script/deploy_sepolia.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from deploy_local import CONTRACTS_DIR, _abi, _foundry

CHAIN_ID = 84532
BROADCAST = CONTRACTS_DIR / "broadcast" / "Deploy.s.sol" / str(CHAIN_ID) / "run-latest.json"
OUTPUT = CONTRACTS_DIR.parent / "deployments" / "base-sepolia.json"
EXPLORER = "https://sepolia.basescan.org/address/"


def _load_env() -> dict:
    env = dict(os.environ)
    path = CONTRACTS_DIR / ".env"
    if path.exists():
        for line in path.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                env.setdefault(key.strip(), value.strip())
    return env


def main() -> int:
    forge = _foundry("forge")
    if forge is None:
        print("forge not found on PATH. Install Foundry: https://getfoundry.sh", file=sys.stderr)
        return 1
    env = _load_env()
    rpc_url = env.get("BASE_SEPOLIA_RPC_URL")
    if not rpc_url or not env.get("PRIVATE_KEY"):
        print("Set BASE_SEPOLIA_RPC_URL and PRIVATE_KEY in contracts/.env", file=sys.stderr)
        return 1

    result = subprocess.run(
        [forge, "script", "script/Deploy.s.sol:Deploy", "--rpc-url", rpc_url, "--broadcast", "--slow"],
        cwd=CONTRACTS_DIR, env=env,
    )
    if result.returncode != 0:
        return result.returncode

    transactions = json.loads(BROADCAST.read_text())["transactions"]
    created = {tx["contractName"]: tx["contractAddress"] for tx in transactions if tx["transactionType"] == "CREATE"}
    calls = {tx["function"]: tx["arguments"][0] for tx in transactions if tx["transactionType"] == "CALL"}
    owner = transactions[0]["transaction"]["from"]

    deployment = {
        "chainId": CHAIN_ID,
        "rpcUrl": rpc_url,
        "AegisRegistry": created["AegisRegistry"],
        "AegisEscrow": created["AegisEscrow"],
        "escrowIsStub": False,
        "MockUSDC": created["MockUSDC"],
        "owner": owner,
        "scoreOracle": calls["setScoreOracle(address)"],
        "escrow": calls["setEscrow(address)"],
        "accounts": {},
        "abis": {name: _abi(name) for name in ["AegisRegistry", "AegisEscrow", "MockUSDC"]},
    }
    OUTPUT.write_text(json.dumps(deployment, indent=2) + "\n")

    print(f"\nWrote {OUTPUT}")
    for name in ("AegisRegistry", "AegisEscrow", "MockUSDC"):
        print(f"{name:<14} {EXPLORER}{deployment[name]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
