// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Script} from "forge-std/Script.sol";
import {console2} from "forge-std/console2.sol";

import {AegisRegistry} from "../src/AegisRegistry.sol";
import {AegisEscrow} from "../src/AegisEscrow.sol";
import {MockUSDC} from "../src/MockUSDC.sol";

/// @notice Local Anvil deployment. Deploys MockUSDC, AegisRegistry and the real AegisEscrow,
///         and wires the oracle and the escrow. Run it through `python script/deploy_local.py`,
///         which records the addresses in deployments/local.json -- Foundry refuses to write
///         outside contracts/. Nothing downstream hardcodes an address; everything reads that
///         file.
/// @dev Uses Anvil's default mnemonic, so the accounts are the ones `anvil` prints:
///        account 0  owner + scoreOracle (the oracle service signs with this key)
///        account 1  HonestAgent      account 2  SloppyAgent      account 3  demo hirer
///        account 9  seeder; agents/seed_demo.py borrows the escrow slot for it
///      Mints a large MockUSDC balance to accounts 1-3 so the demo agents can fund jobs
///      without a separate faucet step.
contract DeployLocal is Script {
    string internal constant ANVIL_MNEMONIC = "test test test test test test test test test test test junk";
    uint256 internal constant DEMO_MINT = 1_000_000e6; // $1,000,000 mUSDC per demo account

    function run() external returns (AegisRegistry registry, AegisEscrow escrow, MockUSDC usdc) {
        uint256 ownerKey = vm.deriveKey(ANVIL_MNEMONIC, 0);
        address owner = vm.addr(ownerKey);

        vm.startBroadcast(ownerKey);
        registry = new AegisRegistry(owner);
        registry.setScoreOracle(owner);
        usdc = new MockUSDC();
        escrow = new AegisEscrow(registry, usdc);
        registry.setEscrow(address(escrow));

        for (uint32 i = 1; i <= 3; i++) {
            usdc.mint(vm.addr(vm.deriveKey(ANVIL_MNEMONIC, i)), DEMO_MINT);
        }
        vm.stopBroadcast();

        console2.log("AegisRegistry:", address(registry));
        console2.log("scoreOracle:  ", owner);
        console2.log("MockUSDC:     ", address(usdc));
        console2.log("AegisEscrow:  ", address(escrow));
    }
}
