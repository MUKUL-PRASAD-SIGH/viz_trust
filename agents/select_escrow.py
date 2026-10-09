"""Switch the local demo between the real AegisEscrow and the StubEscrow fallback.

    agents/.venv/Scripts/python agents/select_escrow.py           # show which is active
    agents/.venv/Scripts/python agents/select_escrow.py --stub    # fall back to StubEscrow
    agents/.venv/Scripts/python agents/select_escrow.py --real    # back to AegisEscrow

The deploy (contracts/script/deploy_local.py) always wires in the real escrow. --stub deploys
StubEscrow against the same Registry the first time, then points BOTH the Registry
(`setEscrow`) and deployments/local.json ("AegisEscrow", "escrowIsStub") at it. They must
never disagree: if the Registry's escrow is not the one the agents watch, recordOutcome
reverts or goes unrecorded and it looks like an oracle bug (SPEC.md section 6). Both
addresses are kept in the file ("AegisEscrowReal", "StubEscrow"), so switching back and forth
is instant after the first time.

Restart the oracle and agents after switching; they read the escrow address at startup.
Local Anvil only. A fresh deploy resets to the real escrow.
"""

from __future__ import annotations

import argparse
import json
import sys

from chain import ARTIFACTS, DEPLOYMENTS_PATH, connect, contract, load_deployment, owner_account, send


def deploy_stub(w3, deployment: dict, registry) -> str:
    artifact = json.loads((ARTIFACTS / "StubEscrow.sol" / "StubEscrow.json").read_text())
    factory = w3.eth.contract(abi=artifact["abi"], bytecode=artifact["bytecode"]["object"])
    receipt = send(w3, owner_account(deployment), factory.constructor(registry.address))
    return receipt.contractAddress


def has_code(w3, address: str | None) -> bool:
    return bool(address) and w3.eth.get_code(w3.to_checksum_address(address)) not in (b"", None)


def status(w3, deployment: dict, registry) -> int:
    on_chain = registry.functions.escrow().call()
    in_file = w3.to_checksum_address(deployment["AegisEscrow"])
    kind = "StubEscrow (stand-in)" if deployment.get("escrowIsStub") else "AegisEscrow (real)"
    print(f"deployments/local.json: {kind} at {in_file}")
    print(f"Registry.escrow():      {on_chain}")
    if on_chain != in_file:
        print("MISMATCH: recordOutcome from the escrow the agents use will revert. "
              "Run --real or --stub to re-align.")
        return 1
    print("In agreement.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--stub", action="store_true", help="use StubEscrow")
    group.add_argument("--real", action="store_true", help="use the real AegisEscrow")
    args = parser.parse_args()

    deployment = load_deployment()
    w3 = connect(deployment)
    registry = contract(w3, deployment, "AegisRegistry")

    if not (args.stub or args.real):
        return status(w3, deployment, registry)

    # First switch away from the fresh deploy: remember the real escrow's address.
    if not deployment.get("escrowIsStub") and "AegisEscrowReal" not in deployment:
        deployment["AegisEscrowReal"] = deployment["AegisEscrow"]

    if args.stub:
        if not has_code(w3, deployment.get("StubEscrow")):
            deployment["StubEscrow"] = deploy_stub(w3, deployment, registry)
            print(f"Deployed StubEscrow at {deployment['StubEscrow']}")
        target, is_stub = deployment["StubEscrow"], True
    else:
        target, is_stub = deployment.get("AegisEscrowReal", deployment["AegisEscrow"]), False
        if not has_code(w3, target):
            raise SystemExit(f"No real escrow at {target}. Redeploy: cd contracts && python script/deploy_local.py")

    target = w3.to_checksum_address(target)
    send(w3, owner_account(deployment), registry.functions.setEscrow(target))
    deployment.update({"AegisEscrow": target, "escrowIsStub": is_stub, "escrow": target})
    DEPLOYMENTS_PATH.write_text(json.dumps(deployment, indent=2) + "\n")

    print(f"Now using {'StubEscrow (stand-in)' if is_stub else 'AegisEscrow (real)'}. "
          "Restart the oracle and both agents.")
    return status(w3, deployment, registry)


if __name__ == "__main__":
    sys.exit(main())
