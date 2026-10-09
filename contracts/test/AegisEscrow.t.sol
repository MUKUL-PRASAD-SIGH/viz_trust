// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Test} from "forge-std/Test.sol";

import {AegisRegistry} from "../src/AegisRegistry.sol";
import {AegisEscrow} from "../src/AegisEscrow.sol";
import {MockUSDC} from "../src/MockUSDC.sol";
import {JobState} from "../src/interfaces/IAegisEscrow.sol";
import {AgentProfile} from "../src/interfaces/IAegisRegistry.sol";

contract AegisEscrowTest is Test {
    event JobCreated(
        uint256 indexed jobId, address indexed hirer, address indexed worker, uint256 value, uint256 collateralTaken
    );
    event JobDelivered(uint256 indexed jobId);
    event JobDisputed(uint256 indexed jobId, address raisedBy);
    event JobSettled(uint256 indexed jobId, bool workerPaid, uint256 amountToWorker);

    AegisRegistry internal registry;
    AegisEscrow internal escrow;
    MockUSDC internal usdc;

    address internal hirer = makeAddr("hirer");
    address internal worker = makeAddr("worker");
    address internal oracle = makeAddr("oracle");

    uint256 internal constant VALUE = 500e6; // $500

    function setUp() public {
        registry = new AegisRegistry(address(this));
        usdc = new MockUSDC();
        escrow = new AegisEscrow(registry, usdc);
        registry.setEscrow(address(escrow));
        registry.setScoreOracle(oracle);

        usdc.mint(hirer, 1_000_000e6);
        vm.prank(hirer);
        usdc.approve(address(escrow), type(uint256).max);
    }

    function _setScore(address who, uint16 score) internal {
        registry.register(who);
        vm.prank(oracle);
        registry.updateScore(who, score, "test fixture");
    }

    // ---------------------------------------------------------------------
    // Happy path
    // ---------------------------------------------------------------------

    function test_createJob_unknownHirerPullsFullCollateral() public {
        vm.expectEmit(true, true, true, true);
        emit JobCreated(1, hirer, worker, VALUE, VALUE);

        vm.prank(hirer);
        uint256 jobId = escrow.createJob(worker, VALUE);

        (address h, address w, uint256 value, uint256 collateralTaken, JobState state) = escrow.jobs(jobId);
        assertEq(h, hirer);
        assertEq(w, worker);
        assertEq(value, VALUE);
        assertEq(collateralTaken, VALUE);
        assertEq(uint8(state), uint8(JobState.Funded));
        assertEq(usdc.balanceOf(address(escrow)), VALUE);
        assertEq(usdc.balanceOf(hirer), 1_000_000e6 - VALUE);
    }

    function test_createJob_scoredHirerPullsPartialCollateral() public {
        _setScore(hirer, 850); // >= 800 -> 20% (2000 bps)
        uint256 expectedCollateral = (VALUE * 2000) / 10000;

        vm.expectEmit(true, true, true, true);
        emit JobCreated(1, hirer, worker, VALUE, expectedCollateral);

        vm.prank(hirer);
        uint256 jobId = escrow.createJob(worker, VALUE);

        (,,, uint256 collateralTaken,) = escrow.jobs(jobId);
        assertEq(collateralTaken, expectedCollateral);
        assertEq(usdc.balanceOf(address(escrow)), expectedCollateral);
    }

    function test_createJob_rejectsSelfHireAndZeroWorker() public {
        vm.expectRevert(AegisEscrow.SelfHire.selector);
        vm.prank(hirer);
        escrow.createJob(hirer, VALUE);

        vm.expectRevert(AegisEscrow.ZeroAddress.selector);
        vm.prank(hirer);
        escrow.createJob(address(0), VALUE);
    }

    function _fullFlow() internal returns (uint256 jobId) {
        vm.prank(hirer);
        jobId = escrow.createJob(worker, VALUE);
        vm.prank(worker);
        escrow.markDelivered(jobId);
        vm.prank(hirer);
        escrow.accept(jobId);
    }

    function test_settle_acceptedPaysWorkerInFull_unknownHirer() public {
        // Unknown hirer already posted 100% at createJob, so settle owes no shortfall.
        uint256 jobId = _fullFlow();

        uint256 workerBefore = usdc.balanceOf(worker);
        vm.expectEmit(true, true, true, true);
        emit JobSettled(jobId, true, VALUE);
        escrow.settle(jobId);

        assertEq(usdc.balanceOf(worker), workerBefore + VALUE);
        (,,,, JobState state) = escrow.jobs(jobId);
        assertEq(uint8(state), uint8(JobState.Settled));

        AgentProfile memory profile = registry.getProfile(worker);
        assertEq(profile.jobsCompleted, 1);
        assertEq(profile.defaults, 0);
        assertEq(profile.totalValueHandled, VALUE);
    }

    function test_settle_acceptedPullsRemainderFromScoredHirer() public {
        _setScore(hirer, 850); // 20% collateral upfront
        uint256 jobId = _fullFlow();

        uint256 collateral = (VALUE * 2000) / 10000;
        uint256 remainder = VALUE - collateral;
        uint256 hirerBefore = usdc.balanceOf(hirer);
        uint256 workerBefore = usdc.balanceOf(worker);

        escrow.settle(jobId);

        assertEq(usdc.balanceOf(hirer), hirerBefore - remainder);
        assertEq(usdc.balanceOf(worker), workerBefore + VALUE);

        AgentProfile memory workerProfile = registry.getProfile(worker);
        assertEq(workerProfile.jobsCompleted, 1);
        assertEq(workerProfile.defaults, 0);

        // Hirer covered the shortfall, so it is not recorded as a default.
        AgentProfile memory hirerProfile = registry.getProfile(hirer);
        assertEq(hirerProfile.defaults, 0);
    }

    function test_markDelivered_emitsEvent() public {
        vm.prank(hirer);
        uint256 jobId = escrow.createJob(worker, VALUE);

        vm.expectEmit(true, true, true, true);
        emit JobDelivered(jobId);
        vm.prank(worker);
        escrow.markDelivered(jobId);
    }

    // ---------------------------------------------------------------------
    // Access control
    // ---------------------------------------------------------------------

    function test_onlyWorkerCanMarkDelivered() public {
        vm.prank(hirer);
        uint256 jobId = escrow.createJob(worker, VALUE);

        vm.expectRevert(AegisEscrow.NotWorker.selector);
        vm.prank(hirer);
        escrow.markDelivered(jobId);
    }

    function test_onlyHirerCanAccept() public {
        vm.prank(hirer);
        uint256 jobId = escrow.createJob(worker, VALUE);
        vm.prank(worker);
        escrow.markDelivered(jobId);

        vm.expectRevert(AegisEscrow.NotHirer.selector);
        vm.prank(worker);
        escrow.accept(jobId);
    }

    function test_onlyHirerCanDispute() public {
        vm.prank(hirer);
        uint256 jobId = escrow.createJob(worker, VALUE);
        vm.prank(worker);
        escrow.markDelivered(jobId);

        vm.expectRevert(AegisEscrow.NotHirer.selector);
        vm.prank(worker);
        escrow.dispute(jobId);
    }

    // ---------------------------------------------------------------------
    // Invalid state transitions -- every one must revert
    // ---------------------------------------------------------------------

    function test_cannotMarkDeliveredTwice() public {
        vm.prank(hirer);
        uint256 jobId = escrow.createJob(worker, VALUE);
        vm.prank(worker);
        escrow.markDelivered(jobId);

        vm.expectRevert(abi.encodeWithSelector(AegisEscrow.BadState.selector, JobState.Delivered));
        vm.prank(worker);
        escrow.markDelivered(jobId);
    }

    function test_cannotAcceptUndeliveredJob() public {
        vm.prank(hirer);
        uint256 jobId = escrow.createJob(worker, VALUE);

        vm.expectRevert(abi.encodeWithSelector(AegisEscrow.BadState.selector, JobState.Funded));
        vm.prank(hirer);
        escrow.accept(jobId);
    }

    function test_cannotDisputeUndeliveredJob() public {
        vm.prank(hirer);
        uint256 jobId = escrow.createJob(worker, VALUE);

        vm.expectRevert(abi.encodeWithSelector(AegisEscrow.BadState.selector, JobState.Funded));
        vm.prank(hirer);
        escrow.dispute(jobId);
    }

    function test_cannotDisputeAcceptedJob() public {
        uint256 jobId = _fullFlow();

        vm.expectRevert(abi.encodeWithSelector(AegisEscrow.BadState.selector, JobState.Accepted));
        vm.prank(hirer);
        escrow.dispute(jobId);
    }

    function test_cannotAcceptDisputedJob() public {
        vm.prank(hirer);
        uint256 jobId = escrow.createJob(worker, VALUE);
        vm.prank(worker);
        escrow.markDelivered(jobId);
        vm.prank(hirer);
        escrow.dispute(jobId);

        vm.expectRevert(abi.encodeWithSelector(AegisEscrow.BadState.selector, JobState.Disputed));
        vm.prank(hirer);
        escrow.accept(jobId);
    }

    function test_cannotSettleFundedJob() public {
        vm.prank(hirer);
        uint256 jobId = escrow.createJob(worker, VALUE);

        vm.expectRevert(abi.encodeWithSelector(AegisEscrow.BadState.selector, JobState.Funded));
        escrow.settle(jobId);
    }

    function test_cannotSettleDeliveredJob() public {
        vm.prank(hirer);
        uint256 jobId = escrow.createJob(worker, VALUE);
        vm.prank(worker);
        escrow.markDelivered(jobId);

        vm.expectRevert(abi.encodeWithSelector(AegisEscrow.BadState.selector, JobState.Delivered));
        escrow.settle(jobId);
    }

    function test_cannotSettleTwice() public {
        uint256 jobId = _fullFlow();
        escrow.settle(jobId);

        vm.expectRevert(abi.encodeWithSelector(AegisEscrow.BadState.selector, JobState.Settled));
        escrow.settle(jobId);
    }

    function test_cannotMarkDeliveredOnSettledJob() public {
        uint256 jobId = _fullFlow();
        escrow.settle(jobId);

        vm.expectRevert(abi.encodeWithSelector(AegisEscrow.BadState.selector, JobState.Settled));
        vm.prank(worker);
        escrow.markDelivered(jobId);
    }

    // ---------------------------------------------------------------------
    // Dispute path
    // ---------------------------------------------------------------------

    function _disputedJob() internal returns (uint256 jobId) {
        vm.prank(hirer);
        jobId = escrow.createJob(worker, VALUE);
        vm.prank(worker);
        escrow.markDelivered(jobId);
        vm.prank(hirer);
        escrow.dispute(jobId);
    }

    function test_dispute_emitsEvent() public {
        vm.prank(hirer);
        uint256 jobId = escrow.createJob(worker, VALUE);
        vm.prank(worker);
        escrow.markDelivered(jobId);

        vm.expectEmit(true, true, true, true);
        emit JobDisputed(jobId, hirer);
        vm.prank(hirer);
        escrow.dispute(jobId);
    }

    function test_settle_disputedRefundsHirerAndPaysWorkerNothing() public {
        uint256 jobId = _disputedJob();

        uint256 hirerBefore = usdc.balanceOf(hirer);
        uint256 workerBefore = usdc.balanceOf(worker);

        vm.expectEmit(true, true, true, true);
        emit JobSettled(jobId, false, 0);
        escrow.settle(jobId);

        assertEq(usdc.balanceOf(hirer), hirerBefore + VALUE); // full collateral (100%) returned
        assertEq(usdc.balanceOf(worker), workerBefore);

        AgentProfile memory profile = registry.getProfile(worker);
        assertEq(profile.jobsCompleted, 0);
        assertEq(profile.jobsDisputed, 1);
        assertEq(profile.defaults, 1);
    }

    function test_settle_disputedRefundsPartialCollateral() public {
        _setScore(hirer, 850); // 20% collateral
        uint256 collateral = (VALUE * 2000) / 10000;
        uint256 jobId = _disputedJob();

        uint256 hirerBefore = usdc.balanceOf(hirer);
        escrow.settle(jobId);

        // Only the collateral actually held returns -- the hirer never paid the remainder.
        assertEq(usdc.balanceOf(hirer), hirerBefore + collateral);
    }

    // ---------------------------------------------------------------------
    // Shortfall / default case (task step 5)
    // ---------------------------------------------------------------------

    function test_settle_shortfallPaysWorkerCollateralOnlyAndMarksHirerDefaulted() public {
        _setScore(hirer, 850); // 20% collateral posted upfront
        uint256 collateral = (VALUE * 2000) / 10000;
        uint256 jobId = _fullFlow();

        // Hirer cannot cover the remaining 80%: drain balance below the shortfall and
        // revoke the allowance so transferFrom fails cleanly instead of reverting the tx.
        vm.startPrank(hirer);
        usdc.transfer(address(0xdead), usdc.balanceOf(hirer));
        usdc.approve(address(escrow), 0);
        vm.stopPrank();

        uint256 workerBefore = usdc.balanceOf(worker);

        vm.expectEmit(true, true, true, true);
        emit JobSettled(jobId, true, collateral);
        escrow.settle(jobId);

        assertEq(usdc.balanceOf(worker), workerBefore + collateral);

        // Worker still delivered and was accepted -- the shortfall is the hirer's failure.
        AgentProfile memory workerProfile = registry.getProfile(worker);
        assertEq(workerProfile.jobsCompleted, 1);
        assertEq(workerProfile.defaults, 0);
        assertEq(workerProfile.totalValueHandled, VALUE);

        // Hirer is recorded as having failed to deliver on its payment obligation.
        AgentProfile memory hirerProfile = registry.getProfile(hirer);
        assertEq(hirerProfile.defaults, 1);

        (,,,, JobState state) = escrow.jobs(jobId);
        assertEq(uint8(state), uint8(JobState.Settled));
    }

    function test_settle_shortfallJobIsSettledEvenThoughHirerDefaulted() public {
        _setScore(hirer, 850);
        uint256 jobId = _fullFlow();

        vm.startPrank(hirer);
        usdc.transfer(address(0xdead), usdc.balanceOf(hirer));
        usdc.approve(address(escrow), 0);
        vm.stopPrank();

        escrow.settle(jobId);

        vm.expectRevert(abi.encodeWithSelector(AegisEscrow.BadState.selector, JobState.Settled));
        escrow.settle(jobId);
    }
}
