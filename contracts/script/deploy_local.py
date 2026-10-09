"""Deploy to a running `anvil` and record the addresses in deployments/local.json.

Foundry refuses to write outside contracts/, so the Solidity script only deploys. This wrapper
reads the addresses back out of Foundry's own broadcast record rather than parsing console
output, then writes the file every off-chain component reads. Re-run after every anvil restart.

Usage (from contracts/):
    python script/deploy_local.py
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

RPC_URL = "http://127.0.0.1:8545"
CHAIN_ID = 31337
ANVIL_MNEMONIC = "test test test test test test test test test test test junk"

# Demo roles on Anvil's default accounts. Keys are derived from the public Anvil mnemonic by
# index, so no secret is ever written to disk. Account 0 is owner + oracle.
ACCOUNTS = {"HonestAgent": 1, "SloppyAgent": 2, "Hirer": 3, "Seeder": 9}

CONTRACTS_DIR = Path(__file__).resolve().parent.parent
BROADCAST = CONTRACTS_DIR / "broadcast" / "DeployLocal.s.sol" / str(CHAIN_ID) / "run-latest.json"
OUTPUT = CONTRACTS_DIR.parent / "deployments" / "local.json"

# Contracts whose ABI gets embedded in deployments/local.json for the off-chain scripts to read.
ABI_CONTRACTS = ["AegisRegistry", "AegisEscrow", "MockUSDC"]


def _abi(contract_name: str) -> list:
    path = CONTRACTS_DIR / "out" / f"{contract_name}.sol" / f"{contract_name}.json"
    return json.loads(path.read_text())["abi"]


def _foundry(tool: str) -> str | None:
    # foundryup's default install dir is often on the shell's PATH but not the OS one.
    return shutil.which(tool) or shutil.which(tool, path=str(Path.home() / ".foundry" / "bin"))


def _anvil_address(cast: str, index: int) -> str:
    return subprocess.run(
        [cast, "wallet", "address", "--mnemonic", ANVIL_MNEMONIC, "--mnemonic-index", str(index)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def main() -> int:
    forge, cast = _foundry("forge"), _foundry("cast")
    if forge is None or cast is None:
        print("forge/cast not found on PATH. Install Foundry: https://getfoundry.sh", file=sys.stderr)
        return 1

    result = subprocess.run(
        [forge, "script", "script/DeployLocal.s.sol:DeployLocal", "--rpc-url", RPC_URL, "--broadcast"],
        cwd=CONTRACTS_DIR,
    )
    if result.returncode != 0:
        print("forge script failed. Is anvil running on " + RPC_URL + "?", file=sys.stderr)
        return result.returncode

    transactions = json.loads(BROADCAST.read_text())["transactions"]

    created = {
        tx["contractName"]: tx["contractAddress"]
        for tx in transactions
        if tx["transactionType"] == "CREATE"
    }
    calls = {tx["function"]: tx["arguments"][0] for tx in transactions if tx["transactionType"] == "CALL"}
    owner = transactions[0]["transaction"]["from"]

    deployment = {
        "chainId": CHAIN_ID,
        "rpcUrl": RPC_URL,
        "AegisRegistry": created["AegisRegistry"],
        "AegisEscrow": created["AegisEscrow"],
        "escrowIsStub": False,
        "MockUSDC": created["MockUSDC"],
        "owner": owner,
        "scoreOracle": calls["setScoreOracle(address)"],
        "escrow": calls["setEscrow(address)"],
        "accounts": {
            name: {"address": _anvil_address(cast, index), "anvilIndex": index}
            for name, index in ACCOUNTS.items()
        },
        "abis": {name: _abi(name) for name in ABI_CONTRACTS},
    }

    OUTPUT.parent.mkdir(exist_ok=True)
    OUTPUT.write_text(json.dumps(deployment, indent=2) + "\n")

    summary = {k: v for k, v in deployment.items() if k != "abis"}
    print(f"\nWrote {OUTPUT}")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
