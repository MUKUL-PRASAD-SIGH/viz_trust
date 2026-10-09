"""viz_trust engine: the service every edit goes through.

    uvicorn engine.app:app --port 8100

Environment:
    VIZ_TRUST_REPO   repo the call graph is built from (default demo/sample_repo)
    VIZ_TRUST_DB     SQLite event log (default engine/data/viz_trust.db)
    VIZ_TRUST_SEED   fixes the random spot-check, for reproducible demos
    VIZ_TRUST_HOLD_TIMEOUT_S   how long a held edit waits (default 120)

The dashboard reads GET /agents/state and is opened with
    http://127.0.0.1:5173/dashboard?api=http://127.0.0.1:8100
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import random
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from engine.core import Engine, EngineError
from engine.models import (
    AgentsStateResponse, DecisionRequest, Edit, EditResult, EditStatus, HealthResponse, VerdictRequest,
)

ROOT = Path(__file__).resolve().parent.parent
HOLD_SWEEP_S = 5.0


def build_engine() -> Engine:
    seed = os.environ.get("VIZ_TRUST_SEED")
    return Engine(
        db_path=os.environ.get("VIZ_TRUST_DB", ROOT / "engine" / "data" / "viz_trust.db"),
        repo_root=os.environ.get("VIZ_TRUST_REPO", ROOT / "demo" / "sample_repo"),
        rng=random.Random(int(seed)) if seed else None,
        hold_timeout_s=float(os.environ.get("VIZ_TRUST_HOLD_TIMEOUT_S", "120")),
    )


def create_app(engine: Engine | None = None) -> FastAPI:
    engine = engine or build_engine()

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI):
        async def sweep() -> None:
            while True:  # time out held edits even when nobody is polling
                await asyncio.sleep(HOLD_SWEEP_S)
                engine.expire_holds()

        task = asyncio.create_task(sweep())
        yield
        task.cancel()

    app = FastAPI(title="viz_trust engine", version="0.1.0", lifespan=lifespan)
    app.state.engine = engine
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    @app.exception_handler(EngineError)
    async def engine_error(_, exc: EngineError):
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": str(exc)}, status_code=exc.status)

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return engine.health()

    @app.get("/agents/state", response_model=AgentsStateResponse)
    def agents_state() -> AgentsStateResponse:
        return engine.state_response()

    @app.post("/edits", response_model=EditResult)
    def post_edit(edit: Edit) -> EditResult:
        return engine.submit_edit(edit)

    @app.get("/edits/{edit_id}", response_model=EditStatus)
    def get_edit(edit_id: str) -> EditStatus:
        return EditStatus(edit_id=edit_id, decision=engine.get_edit_decision(edit_id))

    @app.post("/decisions", response_model=EditStatus)
    def post_decision(body: DecisionRequest) -> EditStatus:
        return EditStatus(edit_id=body.edit_id, decision=engine.decide(body.edit_id, body.decision))

    @app.post("/findings/{finding_id}/verdict")
    def post_verdict(finding_id: str, body: VerdictRequest) -> dict:
        return {"finding_id": finding_id, "status": engine.verdict(finding_id, body.verdict)}

    @app.post("/admin/reset", status_code=204)
    def reset() -> None:
        """Demo only: wipe the event log. The driver's `reset` command calls this."""
        engine.reset()

    return app


app = create_app()
