// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// @notice An agent's portable credit profile.
/// @dev Mirrors SPEC.md section 2 exactly. Do not add or rename fields — SPEC.md is the
///      single source of truth and the off-chain score service depends on this shape.
struct AgentProfile {
    address addr;
    uint16 score; // 0-1000, new agents start at 500
    uint32 jobsCompleted;
    uint32 jobsDisputed;
    uint32 defaults;
    uint256 totalValueHandled;
    bool exists;
}

/// @notice The AEGIS credit registry: who an agent is, and how much collateral they must post.
interface IAegisRegistry {
    event AgentRegistered(address indexed agent);
    event ScoreUpdated(address indexed agent, uint16 oldScore, uint16 newScore, string reason);
    event OutcomeRecorded(address indexed agent, bool delivered, bool disputed, uint256 value);

    function register(address agent) external;

    function getProfile(address agent) external view returns (AgentProfile memory);

    function requiredCollateralBps(address agent) external view returns (uint16);

    function updateScore(address agent, uint16 newScore, string calldata reason) external;

    function recordOutcome(address agent, bool delivered, bool disputed, uint256 value) external;
}
