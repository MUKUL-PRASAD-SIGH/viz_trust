// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// @notice Lifecycle of a job held in escrow.
/// @dev Mirrors SPEC.md section 1 exactly. Valid transitions:
///        Created -> Funded -> Delivered -> Accepted -> Settled
///        Delivered -> Disputed -> Settled
///      No other transition is legal.
enum JobState {
    Created,
    Funded,
    Delivered,
    Accepted,
    Disputed,
    Settled
}

/// @notice Escrow for agent-to-agent jobs, collateralised against the AEGIS credit registry.
/// @dev Implemented by AegisEscrow (and the StubEscrow fallback). See SPEC.md section 6.
interface IAegisEscrow {
    event JobCreated(
        uint256 indexed jobId, address indexed hirer, address indexed worker, uint256 value, uint256 collateralTaken
    );
    event JobDelivered(uint256 indexed jobId);
    event JobDisputed(uint256 indexed jobId, address raisedBy);
    event JobSettled(uint256 indexed jobId, bool workerPaid, uint256 amountToWorker);

    function createJob(address worker, uint256 value) external returns (uint256 jobId);

    function markDelivered(uint256 jobId) external;

    function accept(uint256 jobId) external;

    function dispute(uint256 jobId) external;

    function settle(uint256 jobId) external;
}
