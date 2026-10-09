// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {IAegisEscrow, JobState} from "./interfaces/IAegisEscrow.sol";
import {IAegisRegistry} from "./interfaces/IAegisRegistry.sol";

/// @title StubEscrow -- STAND-IN, NOT THE REAL ESCROW
/// @notice Minimal IAegisEscrow kept as a fallback for the real AegisEscrow.
///         Local Anvil only. Switch with agents/select_escrow.py (SPEC.md section 6).
/// @dev What it deliberately does NOT do:
///        - move any tokens. `collateralTaken` is computed and emitted, never collected.
///        - arbitrate. A disputed job always settles against the worker.
///      What it does do faithfully: the SPEC.md section 1 state machine, the events, the
///      collateral quote from the registry, and `recordOutcome` on settle -- which is the
///      only thing the oracle and the agents actually depend on.
contract StubEscrow is IAegisEscrow {
    struct Job {
        address hirer;
        address worker;
        uint256 value;
        JobState state;
    }

    IAegisRegistry public immutable registry;

    uint256 public jobCount;
    mapping(uint256 => Job) public jobs;

    error NotHirer();
    error NotWorker();
    error BadState(JobState current);
    error ZeroAddress();
    error SelfHire();

    constructor(IAegisRegistry registry_) {
        registry = registry_;
    }

    /// @notice Job ids start at 1. There is no separate funding step, so a job is Funded on
    ///         creation; collateral is quoted against the hirer's score (SPEC.md section 3).
    function createJob(address worker, uint256 value) external returns (uint256 jobId) {
        if (worker == address(0)) revert ZeroAddress();
        if (worker == msg.sender) revert SelfHire();
        jobId = ++jobCount;
        jobs[jobId] = Job({hirer: msg.sender, worker: worker, value: value, state: JobState.Funded});

        uint256 collateralTaken = (value * registry.requiredCollateralBps(msg.sender)) / 10000;
        emit JobCreated(jobId, msg.sender, worker, value, collateralTaken);
    }

    function markDelivered(uint256 jobId) external {
        Job storage job = jobs[jobId];
        if (msg.sender != job.worker) revert NotWorker();
        _advance(job, JobState.Funded, JobState.Delivered);
        emit JobDelivered(jobId);
    }

    function accept(uint256 jobId) external {
        Job storage job = jobs[jobId];
        if (msg.sender != job.hirer) revert NotHirer();
        _advance(job, JobState.Delivered, JobState.Accepted);
    }

    function dispute(uint256 jobId) external {
        Job storage job = jobs[jobId];
        if (msg.sender != job.hirer) revert NotHirer();
        _advance(job, JobState.Delivered, JobState.Disputed);
        emit JobDisputed(jobId, msg.sender);
    }

    /// @notice Anyone may settle. Accepted pays the worker; Disputed always goes against it.
    function settle(uint256 jobId) external {
        Job storage job = jobs[jobId];

        bool workerPaid;
        if (job.state == JobState.Accepted) {
            workerPaid = true;
        } else if (job.state != JobState.Disputed) {
            revert BadState(job.state);
        }
        job.state = JobState.Settled;

        // delivered=workerPaid: a lost dispute counts as non-delivery, matching how the
        // oracle's reasons read it ("lost dispute on $500 job").
        registry.recordOutcome(job.worker, workerPaid, !workerPaid, job.value);
        emit JobSettled(jobId, workerPaid, workerPaid ? job.value : 0);
    }

    function _advance(Job storage job, JobState from, JobState to) private {
        if (job.state != from) revert BadState(job.state);
        job.state = to;
    }
}
