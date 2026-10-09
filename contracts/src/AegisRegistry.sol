// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";

import {IAegisRegistry, AgentProfile} from "./interfaces/IAegisRegistry.sol";

/// @title AegisRegistry
/// @notice The credit layer for the AI agent economy. Holds every agent's profile and
///         answers the one question the escrow needs: how much collateral must this
///         address post upfront?
/// @dev Separation of authority is the point of this contract:
///        - `scoreOracle` (off-chain model) is the only writer of `score`.
///        - `escrow` is the only writer of outcome counters, and it can never touch `score`.
///      Both addresses are set by `owner`.
contract AegisRegistry is IAegisRegistry, Ownable {
    /// @notice Score assigned to an agent on first registration.
    uint16 public constant STARTING_SCORE = 500;

    /// @notice Upper bound of the score range. Scores are clamped to [0, MAX_SCORE].
    uint16 public constant MAX_SCORE = 1000;

    /// @notice Only this address may call `updateScore`.
    address public scoreOracle;

    /// @notice Only this address may call `recordOutcome`.
    address public escrow;

    mapping(address => AgentProfile) private _profiles;

    event ScoreOracleUpdated(address indexed oldOracle, address indexed newOracle);
    event EscrowUpdated(address indexed oldEscrow, address indexed newEscrow);

    error NotScoreOracle(address caller);
    error NotEscrow(address caller);
    error ZeroAddress();

    modifier onlyScoreOracle() {
        if (msg.sender != scoreOracle) revert NotScoreOracle(msg.sender);
        _;
    }

    modifier onlyEscrow() {
        if (msg.sender != escrow) revert NotEscrow(msg.sender);
        _;
    }

    constructor(address initialOwner) Ownable(initialOwner) {}

    // ---------------------------------------------------------------------
    // Admin
    // ---------------------------------------------------------------------

    function setScoreOracle(address newOracle) external onlyOwner {
        if (newOracle == address(0)) revert ZeroAddress();
        emit ScoreOracleUpdated(scoreOracle, newOracle);
        scoreOracle = newOracle;
    }

    function setEscrow(address newEscrow) external onlyOwner {
        if (newEscrow == address(0)) revert ZeroAddress();
        emit EscrowUpdated(escrow, newEscrow);
        escrow = newEscrow;
    }

    // ---------------------------------------------------------------------
    // Registration
    // ---------------------------------------------------------------------

    /// @notice Create a profile for `agent` with the starting score.
    /// @dev Idempotent: a second call for an already-registered agent is a no-op and
    ///      leaves the existing profile untouched.
    function register(address agent) public {
        if (agent == address(0)) revert ZeroAddress();
        if (_profiles[agent].exists) return;

        _profiles[agent] = AgentProfile({
            addr: agent,
            score: STARTING_SCORE,
            jobsCompleted: 0,
            jobsDisputed: 0,
            defaults: 0,
            totalValueHandled: 0,
            exists: true
        });

        emit AgentRegistered(agent);
    }

    // ---------------------------------------------------------------------
    // Collateral curve
    // ---------------------------------------------------------------------

    /// @notice Collateral an agent must post upfront, in basis points of job value.
    /// @dev Step function from SPEC.md section 3. 10000 bps = 100% prepaid.
    ///
    ///        score >= 800  ->  2000
    ///        score >= 600  ->  4000
    ///        score >= 400  ->  7000
    ///        otherwise     -> 10000
    ///        unknown agent -> 10000
    ///
    ///      WARNING: this table is duplicated off-chain in `score/app.py`. If the two ever
    ///      disagree, the score service quotes a collateral requirement this contract will
    ///      refuse to honour. Change both together, or neither. See SPEC.md section 3.
    function requiredCollateralBps(address agent) public view returns (uint16) {
        AgentProfile storage profile = _profiles[agent];

        // An unknown agent is maximum risk: no history, so no credit.
        if (!profile.exists) return 10000;

        uint16 score = profile.score;
        if (score >= 800) return 2000;
        if (score >= 600) return 4000;
        if (score >= 400) return 7000;
        return 10000;
    }

    // ---------------------------------------------------------------------
    // Score — oracle only
    // ---------------------------------------------------------------------

    /// @notice Overwrite an agent's score. Clamped to [0, MAX_SCORE].
    /// @dev Auto-registers an unknown agent first, so `oldScore` reports the real starting
    ///      score of 500 rather than a misleading 0.
    function updateScore(address agent, uint16 newScore, string calldata reason) external onlyScoreOracle {
        register(agent);

        uint16 clamped = newScore > MAX_SCORE ? MAX_SCORE : newScore;

        AgentProfile storage profile = _profiles[agent];
        uint16 oldScore = profile.score;
        profile.score = clamped;

        emit ScoreUpdated(agent, oldScore, clamped, reason);
    }

    // ---------------------------------------------------------------------
    // Outcomes — escrow only
    // ---------------------------------------------------------------------

    /// @notice Record the result of a settled job against an agent.
    /// @dev Deliberately does NOT change `score`. The on-chain record is raw history; the
    ///      off-chain oracle reads it and writes back a score via `updateScore`.
    function recordOutcome(address agent, bool delivered, bool disputed, uint256 value) external onlyEscrow {
        register(agent);

        AgentProfile storage profile = _profiles[agent];

        if (delivered) {
            profile.jobsCompleted += 1;
        } else {
            profile.defaults += 1;
        }

        if (disputed) {
            profile.jobsDisputed += 1;
        }

        profile.totalValueHandled += value;

        emit OutcomeRecorded(agent, delivered, disputed, value);
    }

    // ---------------------------------------------------------------------
    // Views
    // ---------------------------------------------------------------------

    /// @notice Read one agent's profile. An unknown agent returns a zeroed struct with
    ///         `exists == false`.
    function getProfile(address agent) external view returns (AgentProfile memory) {
        return _profiles[agent];
    }

    /// @notice Batch read for the dashboard.
    function getProfiles(address[] calldata agents) external view returns (AgentProfile[] memory profiles) {
        profiles = new AgentProfile[](agents.length);
        for (uint256 i = 0; i < agents.length; i++) {
            profiles[i] = _profiles[agents[i]];
        }
    }
}
