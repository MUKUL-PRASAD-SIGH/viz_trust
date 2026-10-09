"""Where the oracle finds everything: chain, contract, key, score service.

Contract addresses come only from deployments/local.json, written by
`python contracts/script/deploy_local.py`. Nothing here hardcodes an address. The file is
re-read on every (re)start, so a fresh Anvil plus a fresh deploy is picked up automatically.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from web3 import Web3

ORACLE_DIR = Path(__file__).resolve().parent
REPO_ROOT = ORACLE_DIR.parent

DEPLOYMENTS_PATH = REPO_ROOT / "deployments" / "local.json"
REGISTRY_ARTIFACT = REPO_ROOT / "contracts" / "out" / "AegisRegistry.sol" / "AegisRegistry.json"
# The oracle reads the escrow only to label dashboard events with a job id, and only through
# the interface, so the real escrow drops in without changes here.
ESCROW_ARTIFACT = REPO_ROOT / "contracts" / "out" / "IAegisEscrow.sol" / "IAegisEscrow.json"

load_dotenv(ORACLE_DIR / ".env")


class ConfigError(Exception):
    """Something the human has to fix before the oracle can run."""


@dataclass(frozen=True)
class Config:
    rpc_url: str
    registry_address: str
    registry_abi: list
    oracle_private_key: str
    score_url: str
    poll_interval: float
    chain_id: int
    # Display names from deployments/local.json "accounts", in that order. Checksummed keys.
    names: dict[str, str]
    escrow_address: str | None
    escrow_abi: list
    # Decimals of the unit `recordOutcome(..., value)` is denominated in. The escrow will
    # settle in a USDC-style 6-decimal token, so 500_000_000 is a $500 job.
    value_decimals: int


def registered_at(agent: str) -> str | None:
    """The agent's `registeredAt` from deployments/local.json, or None.

    Re-read on every call, not cached in Config: seed_demo.py writes it after the oracle has
    already started, and account age is measured from it (SPEC.md section 7).
    """
    try:
        accounts = json.loads(DEPLOYMENTS_PATH.read_text()).get("accounts", {})
    except (OSError, ValueError):
        return None
    for entry in accounts.values():
        if entry.get("address", "").lower() == agent.lower():
            return entry.get("registeredAt")
    return None


def load_config() -> Config:
    if not DEPLOYMENTS_PATH.exists():
        raise ConfigError(
            f"{DEPLOYMENTS_PATH} not found. Start anvil, then run:\n"
            "    cd contracts && python script/deploy_local.py"
        )
    deployment = json.loads(DEPLOYMENTS_PATH.read_text())

    if not REGISTRY_ARTIFACT.exists():
        raise ConfigError(f"{REGISTRY_ARTIFACT} not found. Run `forge build` in contracts/.")
    abi = json.loads(REGISTRY_ARTIFACT.read_text())["abi"]

    key = os.environ.get("ORACLE_PRIVATE_KEY")
    if not key:
        raise ConfigError(
            f"ORACLE_PRIVATE_KEY is not set. Copy {ORACLE_DIR / '.env.example'} to "
            f"{ORACLE_DIR / '.env'} (it holds Anvil account 0's key)."
        )

    escrow_abi = json.loads(ESCROW_ARTIFACT.read_text())["abi"] if ESCROW_ARTIFACT.exists() else []
    names = {
        Web3.to_checksum_address(entry["address"]): name
        for name, entry in deployment.get("accounts", {}).items()
        if name != "Seeder"
    }

    return Config(
        rpc_url=os.environ.get("RPC_URL") or deployment.get("rpcUrl", "http://127.0.0.1:8545"),
        registry_address=deployment["AegisRegistry"],
        registry_abi=abi,
        oracle_private_key=key,
        score_url=os.environ.get("SCORE_URL", "http://127.0.0.1:8000").rstrip("/"),
        poll_interval=float(os.environ.get("POLL_INTERVAL", "1.0")),
        value_decimals=int(os.environ.get("VALUE_DECIMALS", "6")),
        chain_id=int(deployment.get("chainId", 31337)),
        names=names,
        escrow_address=deployment.get("AegisEscrow") if escrow_abi else None,
        escrow_abi=escrow_abi,
    )
