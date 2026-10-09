// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Test} from "forge-std/Test.sol";

import {AegisRegistry} from "../src/AegisRegistry.sol";
import {StubEscrow} from "../src/StubEscrow.sol";
import {JobState} from "../src/interfaces/IAegisEscrow.sol";
import {AgentProfile} from "../src/interfaces/IAegisRegistry.sol";

/// @notice Only enough to trust the stand-in in a demo: state machine, access, and that
///         settling reaches the registry.
contract StubEscrowTest is Test {
    AegisRegistry internal registry;
    StubEscrow internal escrow;

    address internal hirer = makeAddr("hirer");
    address internal worker = makeAddr("worker");

    uint256 internal constant VALUE = 500e6;

    function setUp() public {
        registry = new AegisRegistry(address(this));
        escrow = new StubEscrow(registry);
        registry.setEscrow(address(escrow));
    }

    function _deliveredJob() internal returns (uint256 jobId) {
        vm.prank(hirer);
        jobId = escrow.createJob(worker, VALUE);
        vm.prank(worker);
        escrow.markDelivered(jobId);
    }

    function test_acceptedJobRecordsDelivery() public {
        uint256 jobId = _deliveredJob();
        vm.prank(hirer);
        escrow.accept(jobId);
        escrow.settle(jobId);

        AgentProfile memory profile = registry.getProfile(worker);
        assertEq(profile.jobsCompleted, 1);
        assertEq(profile.defaults, 0);
        assertEq(profile.totalValueHandled, VALUE);
    }

    function test_disputedJobRecordsLostDispute() public {
        uint256 jobId = _deliveredJob();
        vm.prank(hirer);
        escrow.dispute(jobId);
        escrow.settle(jobId);

        AgentProfile memory profile = registry.getProfile(worker);
        assertEq(profile.jobsCompleted, 0);
        assertEq(profile.jobsDisputed, 1);
        assertEq(profile.defaults, 1);
    }

    function test_onlyWorkerDelivers() public {
        vm.prank(hirer);
        uint256 jobId = escrow.createJob(worker, VALUE);
        vm.expectRevert(StubEscrow.NotWorker.selector);
        vm.prank(hirer);
        escrow.markDelivered(jobId);
    }

    function test_cannotSettleUndeliveredJob() public {
        vm.prank(hirer);
        uint256 jobId = escrow.createJob(worker, VALUE);
        vm.expectRevert(abi.encodeWithSelector(StubEscrow.BadState.selector, JobState.Funded));
        escrow.settle(jobId);
    }

    function test_unknownHirerPostsFullCollateral() public {
        vm.prank(hirer);
        escrow.createJob(worker, VALUE);
        (,, uint256 value,) = escrow.jobs(1);
        assertEq(value, VALUE);
        assertEq(registry.requiredCollateralBps(hirer), 10000);
    }

    function test_createJob_rejectsSelfHireAndZeroWorker() public {
        vm.expectRevert(StubEscrow.SelfHire.selector);
        vm.prank(hirer);
        escrow.createJob(hirer, VALUE);

        vm.expectRevert(StubEscrow.ZeroAddress.selector);
        vm.prank(hirer);
        escrow.createJob(address(0), VALUE);
    }
}
