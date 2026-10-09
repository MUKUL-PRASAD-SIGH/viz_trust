from __future__ import annotations

import random
from pathlib import Path

import httpx
import pytest

from engine.checks import gemma_checks, packages
from engine.core import Engine
from engine.llm.client import GemmaClient
from engine.models import Edit

REPO = Path(__file__).resolve().parents[2] / "demo" / "sample_repo"


@pytest.fixture(autouse=True)
def no_gemma_no_network(monkeypatch):
    """Engine tests run as if Ollama were stopped and PyPI unreachable: fast, offline, and the same
    as the old stub. test_gemma_checks.py swaps in a fake Ollama for the tests that need one."""

    def refuse(request):
        raise httpx.ConnectError("no Ollama in tests")

    gemma_checks.set_client(GemmaClient(base_url="http://ollama.invalid", transport=httpx.MockTransport(refuse)))
    monkeypatch.setattr(packages, "exists_on_index", lambda name, language: None)
    yield
    gemma_checks.set_client(None)


class Clock:
    def __init__(self, t: float = 1_800_000_000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        self.t += 1.0  # every event gets its own second
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def engine(tmp_path, clock) -> Engine:
    return Engine(tmp_path / "log.db", REPO, clock=clock, rng=random.Random(1), hold_timeout_s=120.0)


def source(path: str) -> str:
    return (REPO / path).read_text()


def make_edit(file: str = "app/signup.py", after: str | None = None, before: str | None = None,
              prompt: str = "improve signup", agent: str = "aider", model: str = "gemma4:e4b") -> Edit:
    before = source(file) if before is None else before
    return Edit(agent=agent, model=model, prompt=prompt, file=file, before=before,
                after=before + "\n# touched\n" if after is None else after)


def clean_signup_edit() -> Edit:
    """A big enough edit to a function with callers that it earns the full gain (weight 1)."""
    before = source("app/signup.py")
    after = before.replace(
        "    user = create_user(email, name)\n",
        "    user = create_user(email, name)\n"
        "    user['plan'] = 'free'\n    user['verified'] = False\n    user['tags'] = []\n"
        "    user['visits'] = 0\n    user['notes'] = ''\n    user['locale'] = 'en'\n"
        "    user['referrer'] = None\n    user['flags'] = {}\n    user['history'] = []\n",
    )
    return make_edit(after=after, before=before)


def promote(engine: Engine, to_score: int = 600) -> str:
    """Approve clean edits until the agent reaches `to_score`. Returns the agent id."""
    agent_id = "aider:gemma4:e4b"
    for _ in range(40):
        result = engine.submit_edit(clean_signup_edit())
        if result.decision == "hold":
            engine.decide(result.edit_id, "approve")
        if engine.state.agents[agent_id].score >= to_score:
            return agent_id
    raise AssertionError("agent never reached the target score")
