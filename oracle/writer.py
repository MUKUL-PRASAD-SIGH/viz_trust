"""Sends updateScore transactions from the oracle account."""

from __future__ import annotations

from eth_account import Account
from web3 import Web3

from config import ConfigError


class ScoreWriter:
    def __init__(self, w3: Web3, registry, private_key: str) -> None:
        self.w3 = w3
        self.registry = registry
        self.account = Account.from_key(private_key)
        self.starting_score = registry.functions.STARTING_SCORE().call()

    def verify_oracle(self) -> None:
        """updateScore is oracle-gated. Fail loudly now rather than on the first revert."""
        oracle = self.registry.functions.scoreOracle().call()
        if oracle == self.account.address:
            return

        owner = self.registry.functions.owner().call()
        raise ConfigError(
            "The Registry's scoreOracle is not this oracle's account.\n"
            f"    Registry:        {self.registry.address}\n"
            f"    scoreOracle:     {oracle}\n"
            f"    oracle account:  {self.account.address}\n"
            "Set it from the owner account:\n"
            f"    cast send {self.registry.address} 'setScoreOracle(address)' {self.account.address} "
            f"--private-key <key of owner {owner}> --rpc-url {self.w3.provider.endpoint_uri}"
        )

    def current_score(self, agent: str) -> int:
        """The on-chain score. An unregistered agent reads as the starting score, which is
        what updateScore's auto-registration will report as oldScore."""
        profile = self.registry.functions.getProfile(agent).call()
        score, exists = profile[1], profile[6]
        return score if exists else self.starting_score

    def update_score(self, agent: str, new_score: int, reason: str) -> str:
        tx = self.registry.functions.updateScore(agent, new_score, reason).build_transaction(
            {
                "from": self.account.address,
                "nonce": self.w3.eth.get_transaction_count(self.account.address, "pending"),
            }
        )
        signed = self.account.sign_transaction(tx)
        tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)
        if receipt.status != 1:
            raise RuntimeError(f"updateScore reverted: {tx_hash.hex()}")
        return tx_hash.hex()
