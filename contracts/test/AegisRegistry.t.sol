// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Test} from "forge-std/Test.sol";
import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";

import {AegisRegistry} from "../src/AegisRegistry.sol";
import {AgentProfile} from "../src/interfaces/IAegisRegistry.sol";

contract AegisRegistryTest is Test {
    // Redeclared so `vm.expectEmit` can encode the expectation.
    event AgentRegistered(address indexed agent);
    event ScoreUpdated(address indexed agent, uint16 oldScore, uint16 newScore, string reason);
    event OutcomeRecorded(address indexed agent, bool delivered, bool disputed, uint256 value);

    AegisRegistry internal registry;

    address internal owner = makeAddr("owner");
    address internal oracle = makeAddr("oracle");
    address internal escrow = makeAddr("escrow");
    address internal agent = makeAddr("agent");
    address internal stranger = makeAddr("stranger");

    function setUp() public {
        registry = new AegisRegistry(owner);

        vm.startPrank(owner);
        registry.setScoreOracle(oracle);
        registry.setEscrow(escrow);
        vm.stopPrank();
    }

    /// @dev Register `who` and move them to an exact score, so tier boundaries can be probed.
    function _setScore(address who, uint16 score) internal {
        registry.register(who);
        vm.prank(oracle);
        registry.updateScore(who, score, "test fixture");
    }

    // ---------------------------------------------------------------------
    // Registration
    // ---------------------------------------------------------------------

    function test_Register_CreatesProfileWithStartingScore() public {
        registry.register(agent);

        AgentProfile memory profile = registry.getProfile(agent);
        assertEq(profile.addr, agent);
        assertEq(profile.score, 500, "new agents start at 500");
        assertEq(profile.jobsCompleted, 0);
        assertEq(profile.jobsDisputed, 0);
        assertEq(profile.defaults, 0);
        assertEq(profile.totalValueHandled, 0);
        assertTrue(profile.exists);
    }

    function test_Register_EmitsAgentRegistered() public {
        vm.expectEmit(true, false, false, false);
        emit AgentRegistered(agent);
        registry.register(agent);
    }

    function test_Register_IsIdempotent_DoesNotResetExistingProfile() public {
        registry.register(agent);

        // Build up some history and a non-default score.
        vm.prank(oracle);
        registry.updateScore(agent, 880, "strong history");
        vm.prank(escrow);
        registry.recordOutcome(agent, true, false, 1_500e6);

        // Re-registering must not wipe any of it.
        registry.register(agent);

        AgentProfile memory profile = registry.getProfile(agent);
        assertEq(profile.score, 880, "score survived re-registration");
        assertEq(profile.jobsCompleted, 1, "counters survived re-registration");
        assertEq(profile.totalValueHandled, 1_500e6, "value handled survived re-registration");
    }

    function test_Register_SecondCallEmitsNothing() public {
        registry.register(agent);

        vm.recordLogs();
        registry.register(agent);
        assertEq(vm.getRecordedLogs().length, 0, "idempotent re-register is silent");
    }

    function test_Register_RevertsOnZeroAddress() public {
        vm.expectRevert(AegisRegistry.ZeroAddress.selector);
        registry.register(address(0));
    }

    function test_UnknownAgent_ProfileIsZeroed() public view {
        AgentProfile memory profile = registry.getProfile(stranger);
        assertFalse(profile.exists, "never registered");
        assertEq(profile.score, 0, "zeroed, not 500; exists is what distinguishes them");
    }

    // ---------------------------------------------------------------------
    // Collateral curve — SPEC.md section 3
    // ---------------------------------------------------------------------

    function test_Collateral_UnknownAgentPaysFull() public view {
        assertEq(registry.requiredCollateralBps(stranger), 10000, "no history, no credit");
    }

    function test_Collateral_NewlyRegisteredAgentIsMidTier() public {
        registry.register(agent);
        // Starting score is 500, which falls in the >= 400 band.
        assertEq(registry.requiredCollateralBps(agent), 7000);
    }

    function test_Collateral_BoundaryAt800() public {
        _setScore(agent, 799);
        assertEq(registry.requiredCollateralBps(agent), 4000, "799 is still the >= 600 band");

        _setScore(agent, 800);
        assertEq(registry.requiredCollateralBps(agent), 2000, "800 unlocks the top band");
    }

    function test_Collateral_BoundaryAt600() public {
        _setScore(agent, 599);
        assertEq(registry.requiredCollateralBps(agent), 7000, "599 is still the >= 400 band");

        _setScore(agent, 600);
        assertEq(registry.requiredCollateralBps(agent), 4000);
    }

    function test_Collateral_BoundaryAt400() public {
        _setScore(agent, 399);
        assertEq(registry.requiredCollateralBps(agent), 10000, "399 has no credit");

        _setScore(agent, 400);
        assertEq(registry.requiredCollateralBps(agent), 7000);
    }

    function test_Collateral_ExtremesOfRange() public {
        _setScore(agent, 0);
        assertEq(registry.requiredCollateralBps(agent), 10000);

        _setScore(agent, 1000);
        assertEq(registry.requiredCollateralBps(agent), 2000);
    }

    /// @dev The whole step table in one pass, so a stray edit to any tier fails loudly.
    function testFuzz_Collateral_MatchesStepTable(uint16 score) public {
        score = uint16(bound(score, 0, 1000));
        _setScore(agent, score);

        uint16 expected;
        if (score >= 800) expected = 2000;
        else if (score >= 600) expected = 4000;
        else if (score >= 400) expected = 7000;
        else expected = 10000;

        assertEq(registry.requiredCollateralBps(agent), expected);
    }

    // ---------------------------------------------------------------------
    // updateScore — oracle only
    // ---------------------------------------------------------------------

    function test_UpdateScore_RejectsNonOracle() public {
        registry.register(agent);

        vm.expectRevert(abi.encodeWithSelector(AegisRegistry.NotScoreOracle.selector, stranger));
        vm.prank(stranger);
        registry.updateScore(agent, 900, "should not work");
    }

    function test_UpdateScore_RejectsOwner() public {
        registry.register(agent);

        // Even the owner cannot write a score. Only the oracle can.
        vm.expectRevert(abi.encodeWithSelector(AegisRegistry.NotScoreOracle.selector, owner));
        vm.prank(owner);
        registry.updateScore(agent, 900, "owner is not the oracle");
    }

    function test_UpdateScore_RejectsEscrow() public {
        registry.register(agent);

        vm.expectRevert(abi.encodeWithSelector(AegisRegistry.NotScoreOracle.selector, escrow));
        vm.prank(escrow);
        registry.updateScore(agent, 900, "escrow is not the oracle");
    }

    function test_UpdateScore_OracleCanWrite() public {
        registry.register(agent);

        vm.prank(oracle);
        registry.updateScore(agent, 742, "clean history, 12 jobs delivered");

        assertEq(registry.getProfile(agent).score, 742);
    }

    function test_UpdateScore_ClampsAbove1000() public {
        registry.register(agent);

        vm.prank(oracle);
        registry.updateScore(agent, 65535, "absurd input");

        assertEq(registry.getProfile(agent).score, 1000, "clamped to MAX_SCORE");
    }

    function test_UpdateScore_ClampedValueIsWhatGetsEmitted() public {
        registry.register(agent);

        vm.expectEmit(true, false, false, true);
        emit ScoreUpdated(agent, 500, 1000, "absurd input");

        vm.prank(oracle);
        registry.updateScore(agent, 5000, "absurd input");
    }

    function test_UpdateScore_EmitsCorrectOldAndNewValues() public {
        registry.register(agent);

        // 500 -> 820
        vm.expectEmit(true, false, false, true);
        emit ScoreUpdated(agent, 500, 820, "delivered 9 jobs, no disputes");
        vm.prank(oracle);
        registry.updateScore(agent, 820, "delivered 9 jobs, no disputes");

        // 820 -> 780, the drop a lost dispute causes
        vm.expectEmit(true, false, false, true);
        emit ScoreUpdated(agent, 820, 780, "lost dispute on a $500 job");
        vm.prank(oracle);
        registry.updateScore(agent, 780, "lost dispute on a $500 job");

        assertEq(registry.getProfile(agent).score, 780);
    }

    function test_UpdateScore_AutoRegistersUnknownAgent() public {
        // Oracle scores an agent that never called register().
        vm.expectEmit(true, false, false, true);
        emit ScoreUpdated(stranger, 500, 910, "imported history");

        vm.prank(oracle);
        registry.updateScore(stranger, 910, "imported history");

        AgentProfile memory profile = registry.getProfile(stranger);
        assertTrue(profile.exists);
        assertEq(profile.score, 910);
    }

    function test_UpdateScore_DoesNotTouchCounters() public {
        registry.register(agent);
        vm.prank(escrow);
        registry.recordOutcome(agent, true, false, 900e6);

        vm.prank(oracle);
        registry.updateScore(agent, 700, "rescored");

        AgentProfile memory profile = registry.getProfile(agent);
        assertEq(profile.jobsCompleted, 1);
        assertEq(profile.totalValueHandled, 900e6);
    }

    // ---------------------------------------------------------------------
    // recordOutcome — escrow only
    // ---------------------------------------------------------------------

    function test_RecordOutcome_RejectsNonEscrow() public {
        registry.register(agent);

        vm.expectRevert(abi.encodeWithSelector(AegisRegistry.NotEscrow.selector, stranger));
        vm.prank(stranger);
        registry.recordOutcome(agent, true, false, 100);
    }

    function test_RecordOutcome_RejectsOracle() public {
        registry.register(agent);

        vm.expectRevert(abi.encodeWithSelector(AegisRegistry.NotEscrow.selector, oracle));
        vm.prank(oracle);
        registry.recordOutcome(agent, true, false, 100);
    }

    function test_RecordOutcome_RejectsOwner() public {
        registry.register(agent);

        vm.expectRevert(abi.encodeWithSelector(AegisRegistry.NotEscrow.selector, owner));
        vm.prank(owner);
        registry.recordOutcome(agent, true, false, 100);
    }

    function test_RecordOutcome_DeliveredIncrementsCompleted() public {
        registry.register(agent);

        vm.prank(escrow);
        registry.recordOutcome(agent, true, false, 250e6);

        AgentProfile memory profile = registry.getProfile(agent);
        assertEq(profile.jobsCompleted, 1);
        assertEq(profile.defaults, 0);
        assertEq(profile.jobsDisputed, 0);
        assertEq(profile.totalValueHandled, 250e6);
    }

    function test_RecordOutcome_NotDeliveredIncrementsDefaults() public {
        registry.register(agent);

        vm.prank(escrow);
        registry.recordOutcome(agent, false, false, 250e6);

        AgentProfile memory profile = registry.getProfile(agent);
        assertEq(profile.jobsCompleted, 0);
        assertEq(profile.defaults, 1);
        assertEq(profile.totalValueHandled, 250e6);
    }

    function test_RecordOutcome_DisputedIncrementsDisputes() public {
        registry.register(agent);

        // A disputed job that the worker still delivered on.
        vm.prank(escrow);
        registry.recordOutcome(agent, true, true, 500e6);

        AgentProfile memory profile = registry.getProfile(agent);
        assertEq(profile.jobsCompleted, 1);
        assertEq(profile.jobsDisputed, 1);
        assertEq(profile.defaults, 0);
    }

    function test_RecordOutcome_DisputedAndUndelivered() public {
        registry.register(agent);

        vm.prank(escrow);
        registry.recordOutcome(agent, false, true, 500e6);

        AgentProfile memory profile = registry.getProfile(agent);
        assertEq(profile.jobsCompleted, 0);
        assertEq(profile.jobsDisputed, 1);
        assertEq(profile.defaults, 1);
    }

    function test_RecordOutcome_AccumulatesAcrossJobs() public {
        registry.register(agent);

        vm.startPrank(escrow);
        registry.recordOutcome(agent, true, false, 100e6);
        registry.recordOutcome(agent, true, false, 200e6);
        registry.recordOutcome(agent, false, true, 300e6);
        vm.stopPrank();

        AgentProfile memory profile = registry.getProfile(agent);
        assertEq(profile.jobsCompleted, 2);
        assertEq(profile.defaults, 1);
        assertEq(profile.jobsDisputed, 1);
        assertEq(profile.totalValueHandled, 600e6);
    }

    function test_RecordOutcome_NeverChangesScore() public {
        registry.register(agent);

        vm.startPrank(escrow);
        registry.recordOutcome(agent, false, true, 400e6);
        registry.recordOutcome(agent, false, true, 400e6);
        vm.stopPrank();

        assertEq(registry.getProfile(agent).score, 500, "outcomes are raw history; only the oracle rescores");
    }

    function test_RecordOutcome_EmitsEvent() public {
        registry.register(agent);

        vm.expectEmit(true, false, false, true);
        emit OutcomeRecorded(agent, false, true, 777e6);

        vm.prank(escrow);
        registry.recordOutcome(agent, false, true, 777e6);
    }

    function test_RecordOutcome_AutoRegistersUnknownAgent() public {
        vm.prank(escrow);
        registry.recordOutcome(stranger, true, false, 50e6);

        AgentProfile memory profile = registry.getProfile(stranger);
        assertTrue(profile.exists);
        assertEq(profile.score, 500);
        assertEq(profile.jobsCompleted, 1);
    }

    // ---------------------------------------------------------------------
    // Admin
    // ---------------------------------------------------------------------

    function test_SetScoreOracle_OnlyOwner() public {
        vm.expectRevert(abi.encodeWithSelector(Ownable.OwnableUnauthorizedAccount.selector, stranger));
        vm.prank(stranger);
        registry.setScoreOracle(stranger);
    }

    function test_SetEscrow_OnlyOwner() public {
        vm.expectRevert(abi.encodeWithSelector(Ownable.OwnableUnauthorizedAccount.selector, stranger));
        vm.prank(stranger);
        registry.setEscrow(stranger);
    }

    function test_SetScoreOracle_RevertsOnZeroAddress() public {
        vm.expectRevert(AegisRegistry.ZeroAddress.selector);
        vm.prank(owner);
        registry.setScoreOracle(address(0));
    }

    function test_SetEscrow_RevertsOnZeroAddress() public {
        vm.expectRevert(AegisRegistry.ZeroAddress.selector);
        vm.prank(owner);
        registry.setEscrow(address(0));
    }

    function test_SetScoreOracle_RotatesAuthority() public {
        address newOracle = makeAddr("newOracle");

        vm.prank(owner);
        registry.setScoreOracle(newOracle);

        // Old oracle is locked out.
        vm.expectRevert(abi.encodeWithSelector(AegisRegistry.NotScoreOracle.selector, oracle));
        vm.prank(oracle);
        registry.updateScore(agent, 900, "stale oracle");

        vm.prank(newOracle);
        registry.updateScore(agent, 900, "fresh oracle");
        assertEq(registry.getProfile(agent).score, 900);
    }

    function test_Constructor_SetsOwner() public view {
        assertEq(registry.owner(), owner);
    }

    function test_OracleAndEscrowStartUnset() public {
        AegisRegistry fresh = new AegisRegistry(owner);
        assertEq(fresh.scoreOracle(), address(0));
        assertEq(fresh.escrow(), address(0));

        // With no oracle set, nobody can write a score.
        vm.expectRevert(abi.encodeWithSelector(AegisRegistry.NotScoreOracle.selector, stranger));
        vm.prank(stranger);
        fresh.updateScore(agent, 900, "no oracle configured");
    }

    // ---------------------------------------------------------------------
    // Batch view
    // ---------------------------------------------------------------------

    function test_GetProfiles_BatchRead() public {
        address other = makeAddr("other");
        registry.register(agent);
        registry.register(other);

        vm.prank(oracle);
        registry.updateScore(other, 850, "excellent");

        address[] memory addrs = new address[](3);
        addrs[0] = agent;
        addrs[1] = other;
        addrs[2] = stranger; // never registered

        AgentProfile[] memory profiles = registry.getProfiles(addrs);

        assertEq(profiles.length, 3);
        assertEq(profiles[0].score, 500);
        assertTrue(profiles[0].exists);
        assertEq(profiles[1].score, 850);
        assertTrue(profiles[1].exists);
        assertFalse(profiles[2].exists, "unknown agent comes back zeroed");
    }

    function test_GetProfiles_EmptyArray() public view {
        address[] memory addrs = new address[](0);
        assertEq(registry.getProfiles(addrs).length, 0);
    }
}
