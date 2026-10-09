// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";

import {IAegisEscrow, JobState} from "./interfaces/IAegisEscrow.sol";
import {IAegisRegistry} from "./interfaces/IAegisRegistry.sol";

/// @title AegisEscrow
/// @notice Holds USDC for agent-to-agent jobs, collateralised against the AEGIS credit
///         registry (SPEC.md section 3). Implements IAegisEscrow exactly -- see
///         src/interfaces/IAegisEscrow.sol, which is frozen and not touched here.
/// @dev State machine is SPEC.md section 1:
///        Created -> Funded -> Delivered -> Accepted -> Settled
///        Delivered -> Disputed -> Settled
///      `createJob` pulls collateral and funds in the same call, so a job is born Funded --
///      there is no separate `Created` state reachable on-chain, matching StubEscrow.
contract AegisEscrow is IAegisEscrow {
    struct Job {
        address hirer;
        address worker;
        uint256 value; // full job value, 6-decimal USDC units (SPEC.md section 2, "Value units")
        uint256 collateralTaken; // amount actually pulled from the hirer at createJob
        JobState state;
    }

    IAegisRegistry public immutable registry;
    IERC20 public immutable usdc;

    uint256 public jobCount;
    mapping(uint256 => Job) public jobs;

    error NotHirer();
    error NotWorker();
    error BadState(JobState current);
    error ZeroAddress();
    error SelfHire();

    constructor(IAegisRegistry registry_, IERC20 usdc_) {
        if (address(registry_) == address(0) || address(usdc_) == address(0)) revert ZeroAddress();
        registry = registry_;
        usdc = usdc_;
    }

    // ---------------------------------------------------------------------
    // Happy path
    // ---------------------------------------------------------------------

    /// @notice Open a job and pull the hirer's required collateral upfront.
    /// @dev Collateral is quoted from the registry against `msg.sender` (the hirer) at
    ///      creation time and locked into the job -- a later score change does not retroactively
    ///      change what this job already collected. Job is born Funded: there is no separate
    ///      funding step (SPEC.md section 1, matching StubEscrow).
    function createJob(address worker, uint256 value) external returns (uint256 jobId) {
        if (worker == address(0)) revert ZeroAddress();
        if (worker == msg.sender) revert SelfHire();
        uint16 bps = registry.requiredCollateralBps(msg.sender);
        uint256 collateralTaken = (value * bps) / 10000;

        jobId = ++jobCount;
        jobs[jobId] = Job({
            hirer: msg.sender,
            worker: worker,
            value: value,
            collateralTaken: collateralTaken,
            state: JobState.Funded
        });

        if (collateralTaken > 0) {
            usdc.transferFrom(msg.sender, address(this), collateralTaken);
        }

        emit JobCreated(jobId, msg.sender, worker, value, collateralTaken);
    }

    /// @notice Worker marks a funded job delivered.
    function markDelivered(uint256 jobId) external {
        Job storage job = jobs[jobId];
        if (msg.sender != job.worker) revert NotWorker();
        _advance(job, JobState.Funded, JobState.Delivered);
        emit JobDelivered(jobId);
    }

    /// @notice Hirer accepts a delivered job. Does not move funds -- settle does.
    function accept(uint256 jobId) external {
        Job storage job = jobs[jobId];
        if (msg.sender != job.hirer) revert NotHirer();
        _advance(job, JobState.Delivered, JobState.Accepted);
    }

    // ---------------------------------------------------------------------
    // Dispute path (SPEC.md section 6 + task step 4)
    // ---------------------------------------------------------------------

    /// @notice Hirer disputes a delivered job. Only reachable from Delivered, per the state
    ///         machine. No voting, no arbitrator -- a dispute always resolves against the
    ///         worker on settle.
    function dispute(uint256 jobId) external {
        Job storage job = jobs[jobId];
        if (msg.sender != job.hirer) revert NotHirer();
        _advance(job, JobState.Delivered, JobState.Disputed);
        emit JobDisputed(jobId, msg.sender);
    }

    // ---------------------------------------------------------------------
    // Settle
    // ---------------------------------------------------------------------

    /// @notice Settle an Accepted or Disputed job. Anyone may call it.
    /// @dev Accepted: the hirer owes the remaining (value - collateralTaken). We attempt to
    ///      pull it; if that succeeds the worker is paid in full. If the hirer cannot cover
    ///      the shortfall (insufficient balance/allowance), the worker is paid only the
    ///      collateral already held, and the hirer -- not the worker -- is recorded as the
    ///      one who failed to deliver on this job (task step 5). The worker still delivered
    ///      an accepted job, so its own outcome is recorded as delivered regardless of
    ///      whether the hirer covered the shortfall.
    ///
    ///      Disputed: no voting, no arbitrator. The worker gets nothing; its held collateral
    ///      returns to the hirer. Matches StubEscrow's rule and SPEC.md section 6.
    function settle(uint256 jobId) external {
        Job storage job = jobs[jobId];

        if (job.state == JobState.Accepted) {
            _settleAccepted(job, jobId);
        } else if (job.state == JobState.Disputed) {
            _settleDisputed(job, jobId);
        } else {
            revert BadState(job.state);
        }
    }

    function _settleAccepted(Job storage job, uint256 jobId) private {
        job.state = JobState.Settled;

        uint256 shortfall = job.value - job.collateralTaken;
        bool hirerCovered = true;
        if (shortfall > 0) {
            hirerCovered = _tryTransferFrom(job.hirer, address(this), shortfall);
        }

        uint256 amountToWorker = hirerCovered ? job.value : job.collateralTaken;
        if (amountToWorker > 0) {
            _transfer(job.worker, amountToWorker);
        }

        // Worker held up its end (delivered, accepted); a hirer shortfall is the hirer's
        // failure, not the worker's, so the worker's outcome is always a clean delivery.
        registry.recordOutcome(job.worker, true, false, job.value);
        if (!hirerCovered) {
            // Hirer failed to pay the remainder it owed -- recorded as the hirer's own
            // non-delivery against its profile (task step 5: "mark hirer defaulted").
            registry.recordOutcome(job.hirer, false, false, job.value);
        }

        emit JobSettled(jobId, true, amountToWorker);
    }

    function _settleDisputed(Job storage job, uint256 jobId) private {
        job.state = JobState.Settled;

        // Worker gets nothing; the hirer's held collateral returns to it.
        if (job.collateralTaken > 0) {
            _transfer(job.hirer, job.collateralTaken);
        }

        registry.recordOutcome(job.worker, false, true, job.value);

        emit JobSettled(jobId, false, 0);
    }

    // ---------------------------------------------------------------------
    // Internal helpers
    // ---------------------------------------------------------------------

    function _advance(Job storage job, JobState from, JobState to) private {
        if (job.state != from) revert BadState(job.state);
        job.state = to;
    }

    function _transfer(address to, uint256 amount) private {
        bool ok = usdc.transfer(to, amount);
        require(ok, "AegisEscrow: transfer failed");
    }

    /// @dev Swallows a revert or a `false` return from a non-compliant/insufficiently
    ///      funded ERC20 so the shortfall path can degrade gracefully instead of reverting
    ///      the whole settlement (task step 5: "if that transfer fails").
    function _tryTransferFrom(address from, address to, uint256 amount) private returns (bool) {
        try usdc.transferFrom(from, to, amount) returns (bool ok) {
            return ok;
        } catch {
            return false;
        }
    }
}
