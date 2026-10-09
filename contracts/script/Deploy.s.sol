// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Script} from "forge-std/Script.sol";
import {console2} from "forge-std/console2.sol";

import {AegisRegistry} from "../src/AegisRegistry.sol";
import {AegisEscrow} from "../src/AegisEscrow.sol";
import {MockUSDC} from "../src/MockUSDC.sol";

/// @notice Base Sepolia deployment: AegisRegistry, MockUSDC and AegisEscrow, wired the same way
///         as DeployLocal. Run it through `python script/deploy_sepolia.py`, which records the
///         addresses in deployments/base-sepolia.json.
/// @dev The deployer becomes owner AND scoreOracle (a single signer, as on Anvil). MockUSDC is a
///      test token with public mint, deployed because there is no testnet USDC to hand; it is
///      not Circle's USDC. Nothing is minted here: the demo runs on Anvil, not on this chain.
contract Deploy is Script {
    function run() external returns (AegisRegistry registry, AegisEscrow escrow, MockUSDC usdc) {
        uint256 deployerKey = vm.envUint("PRIVATE_KEY");
        address deployer = vm.addr(deployerKey);

        vm.startBroadcast(deployerKey);
        registry = new AegisRegistry(deployer);
        registry.setScoreOracle(deployer);
        usdc = new MockUSDC();
        escrow = new AegisEscrow(registry, usdc);
        // Without this, recordOutcome reverts with NotEscrow and no score ever updates.
        registry.setEscrow(address(escrow));
        vm.stopBroadcast();

        console2.log("AegisRegistry:", address(registry));
        console2.log("scoreOracle:  ", deployer);
        console2.log("MockUSDC:     ", address(usdc));
        console2.log("AegisEscrow:  ", address(escrow));
    }
}
