// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";

/// @title MockUSDC -- TEST TOKEN ONLY
/// @notice 6-decimal ERC20 standing in for USDC on Anvil/testnet. `mint` is public so any
///         test or demo script can fund itself. Never deploy this to a chain with real value.
contract MockUSDC is ERC20 {
    constructor() ERC20("Mock USDC", "mUSDC") {}

    function decimals() public pure override returns (uint8) {
        return 6;
    }

    /// @notice Mint `amount` (6-decimal base units) to `to`. Unrestricted on purpose --
    ///         this is a test fixture, not a production token.
    function mint(address to, uint256 amount) external {
        _mint(to, amount);
    }
}
