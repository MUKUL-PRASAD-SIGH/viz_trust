"""Gemma 4 through a local Ollama server, with structured output that never raises.

Every call asks Ollama for JSON matching a Pydantic model's schema, validates the reply, retries
once if it is invalid, and otherwise gives up and returns None. Callers treat None as "no opinion",
so a dead Ollama, a slow model or a garbled reply can only make a check miss something, never crash
the engine or hang an edit.

Each call is logged (model, prompt version, latency, tokens, outcome) so the evaluation can report
latency and failure rates per model.

Environment:
    OLLAMA_URL        default http://127.0.0.1:11434
    VIZ_TRUST_MODEL   default gemma4:e4b
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

log = logging.getLogger("viz_trust.llm")

DEFAULT_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "gemma4:e4b"

# Loading e4b from cold takes ~20 s on a 6 GB laptop GPU. Keep it resident between edits.
KEEP_ALIVE = "30m"
WARMUP_TIMEOUT_S = 90.0

T = TypeVar("T", bound=BaseModel)


@dataclass
class CallRecord:
    """One model call, as written to the call log."""

    model: str
    prompt_version: str
    ok: bool
    attempts: int
    latency_ms: int
    prompt_tokens: int = 0
    output_tokens: int = 0
    error: str = ""


class GemmaClient:
    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        log_path: Path | None = None,
        transport: httpx.BaseTransport | None = None,
    ):
        self.base_url = (base_url or os.environ.get("OLLAMA_URL") or DEFAULT_URL).rstrip("/")
        self.model = model or os.environ.get("VIZ_TRUST_MODEL") or DEFAULT_MODEL
        self.log_path = log_path
        self.records: list[CallRecord] = []
        self._lock = threading.Lock()
        self._http = httpx.Client(base_url=self.base_url, transport=transport)

    def structured(
        self,
        *,
        system: str,
        user: str,
        schema: type[T],
        prompt_version: str,
        timeout_s: float,
        retries: int = 1,
    ) -> T | None:
        """Ask the model for one `schema` object. Returns None on any failure, within `timeout_s`."""
        deadline = time.monotonic() + timeout_s
        started = time.monotonic()
        attempts = 0
        error = ""
        prompt_tokens = output_tokens = 0

        while attempts <= retries:
            remaining = deadline - time.monotonic()
            if remaining <= 0.05:
                error = error or "deadline passed"
                break
            attempts += 1
            try:
                response = self._http.post(
                    "/api/chat",
                    json={
                        "model": self.model,
                        "stream": False,
                        "think": False,
                        "keep_alive": KEEP_ALIVE,
                        "format": schema.model_json_schema(),
                        "options": {"temperature": 0},
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                    },
                    timeout=remaining,
                )
                response.raise_for_status()
                body = response.json()
                prompt_tokens += body.get("prompt_eval_count", 0)
                output_tokens += body.get("eval_count", 0)
                result = schema.model_validate_json(body["message"]["content"])
            except (ValidationError, json.JSONDecodeError, KeyError, TypeError) as exc:
                error = f"invalid reply: {type(exc).__name__}"
                continue  # the model answered badly; one retry may fix it
            except httpx.TimeoutException:
                error = "timeout"
                break  # no time left for a retry
            except httpx.HTTPError as exc:
                error = f"ollama unreachable: {type(exc).__name__}"
                break  # retrying a dead server only wastes the deadline
            self._record(prompt_version, True, attempts, started, prompt_tokens, output_tokens)
            return result

        self._record(prompt_version, False, attempts, started, prompt_tokens, output_tokens, error)
        log.warning("gemma call %s failed after %d attempt(s): %s", prompt_version, attempts, error)
        return None

    def warm_up(self) -> bool:
        """Load the model into memory so the first real edit isn't slow. True if it answered."""

        class Ready(BaseModel):
            ok: bool

        reply = self.structured(
            system="Reply with JSON.",
            user='Reply {"ok": true}.',
            schema=Ready,
            prompt_version="warmup",
            timeout_s=WARMUP_TIMEOUT_S,
            retries=0,
        )
        return reply is not None

    def available(self) -> bool:
        """True if Ollama answers and has this model pulled."""
        try:
            response = self._http.post("/api/show", json={"model": self.model}, timeout=2.0)
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    def _record(self, prompt_version, ok, attempts, started, prompt_tokens, output_tokens, error=""):
        record = CallRecord(
            model=self.model,
            prompt_version=prompt_version,
            ok=ok,
            attempts=attempts,
            latency_ms=int((time.monotonic() - started) * 1000),
            prompt_tokens=prompt_tokens,
            output_tokens=output_tokens,
            error=error,
        )
        with self._lock:
            self.records.append(record)
            if self.log_path is not None:
                self.log_path.parent.mkdir(parents=True, exist_ok=True)
                with self.log_path.open("a") as handle:
                    handle.write(json.dumps(asdict(record)) + "\n")
