"""The one place the agents learn which escrow they are talking to.

==========================================================================================
 REAL ESCROW PLUGS IN HERE
------------------------------------------------------------------------------------------
 Agents speak only the IAegisEscrow interface (SPEC.md section 6): createJob,
 markDelivered, accept, dispute, settle and the JobCreated / JobDelivered / JobDisputed /
 JobSettled events. They never see StubEscrow's own ABI.

 deployments/local.json["AegisEscrow"] is the real AegisEscrow after a deploy, or
 StubEscrow after `select_escrow.py --stub`; "escrowIsStub" says which. The agents need no
 change either way. The one escrow-specific step, approving mUSDC before createJob, lives
 in demo_driver.py because only the hirer moves tokens.
==========================================================================================
"""

from __future__ import annotations

from chain import contract

ESCROW_ADDRESS_KEY = "AegisEscrow"  # key in deployments/local.json
ESCROW_ABI = "IAegisEscrow"  # interface ABI from contracts/out, not the stub's

USDC = 10**6  # job values are 6-decimal USDC, SPEC.md section 5


def escrow_contract(w3, deployment: dict):
    return contract(w3, deployment, ESCROW_ADDRESS_KEY, abi_name=ESCROW_ABI)


def is_stub(deployment: dict) -> bool:
    return bool(deployment.get("escrowIsStub"))


def usd(value: int) -> str:
    amount = value / USDC
    return f"${amount:,.0f}" if amount == int(amount) else f"${amount:,.2f}"
