"""Shared plumbing for the demo scripts: deployment file, web3, Anvil accounts.

Every address comes from deployments/local.json, written by contracts/script/deploy_local.py.
Keys are derived from Anvil's public default mnemonic by the account index recorded there,
so no secret is stored anywhere. Local chain only.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from eth_account import Account
from web3 import Web3
from web3.exceptions import Web3RPCError

REPO_ROOT = Path(__file__).resolve().parent.parent
DEPLOYMENTS_PATH = REPO_ROOT / "deployments" / "local.json"
ARTIFACTS = REPO_ROOT / "contracts" / "out"

ANVIL_MNEMONIC = "test test test test test test test test test test test junk"

Account.enable_unaudited_hdwallet_features()


def load_deployment() -> dict:
    if not DEPLOYMENTS_PATH.exists():
        raise SystemExit(
            f"{DEPLOYMENTS_PATH} not found. Start anvil, then run:\n"
            "    cd contracts && python script/deploy_local.py"
        )
    return json.loads(DEPLOYMENTS_PATH.read_text())


def connect(deployment: dict) -> Web3:
    w3 = Web3(Web3.HTTPProvider(deployment["rpcUrl"]))
    if not w3.is_connected():
        raise SystemExit(f"No chain at {deployment['rpcUrl']}. Is anvil running?")
    return w3


def abi(contract: str) -> list:
    path = ARTIFACTS / f"{contract}.sol" / f"{contract}.json"
    if not path.exists():
        raise SystemExit(f"{path} not found. Run `forge build` in contracts/.")
    return json.loads(path.read_text())["abi"]


def contract(w3: Web3, deployment: dict, name: str, abi_name: str | None = None):
    address = deployment.get(name)
    if not address or w3.eth.get_code(Web3.to_checksum_address(address)) in (b"", None):
        raise SystemExit(
            f"No {name} contract on chain (deployments/local.json: {address}). "
            "Anvil was probably restarted. Redeploy:\n    cd contracts && python script/deploy_local.py"
        )
    return w3.eth.contract(address=Web3.to_checksum_address(address), abi=abi(abi_name or name))


def account(deployment: dict, role: str):
    """The signing account for a role in deployments/local.json ("HonestAgent", "Hirer", ...)."""
    entry = deployment["accounts"][role]
    acct = Account.from_mnemonic(ANVIL_MNEMONIC, account_path=f"m/44'/60'/0'/0/{entry['anvilIndex']}")
    assert acct.address.lower() == entry["address"].lower(), f"{role} key does not match its address"
    return acct


def owner_account(deployment: dict):
    acct = Account.from_mnemonic(ANVIL_MNEMONIC, account_path="m/44'/60'/0'/0/0")
    assert acct.address.lower() == deployment["owner"].lower(), "owner is not Anvil account 0"
    return acct


def send(w3: Web3, acct, call, attempts: int = 3):
    """Sign, send and wait. Retries on nonce races: the oracle also signs as account 0."""
    for attempt in range(attempts):
        try:
            tx = call.build_transaction(
                {"from": acct.address, "nonce": w3.eth.get_transaction_count(acct.address, "pending")}
            )
            tx_hash = w3.eth.send_raw_transaction(acct.sign_transaction(tx).raw_transaction)
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)
            if receipt.status != 1:
                raise RuntimeError(f"transaction reverted: {tx_hash.hex()}")
            return receipt
        except (ValueError, Web3RPCError) as exc:
            if "nonce" not in str(exc).lower() or attempt == attempts - 1:
                raise
            time.sleep(0.5)
