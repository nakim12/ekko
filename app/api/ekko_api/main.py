"""HTTP API for the personal report.

    uvicorn ekko_api.main:default_app --factory --reload --port 8000

POST /api/lookups {"riot_id": "name#tag"}  -> {"job_id", "status"}   (joins an active lookup)
GET  /api/lookups/{job_id}                 -> job status
GET  /api/lookups/{job_id}/events          -> server-sent events with progress until done/failed
GET  /api/reports/{report_id}              -> the report JSON

Reports are addressed by a random ID, never by PUUID, and only describe the Riot ID that was
entered (PROJECT_PLAN.md 8.3).
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from crawler.config import load_settings
from crawler.riot import RiotClient

from .lookup import load_priors, worker_loop
from .store import Store

RIOT_ID = re.compile(r"^.{3,16}#[^#]{2,5}$")
PUBLIC_JOB_FIELDS = (
    "id",
    "display_riot_id",
    "status",
    "stage",
    "done",
    "total",
    "message",
    "report_id",
)
WORKERS = 2


class LookupRequest(BaseModel):
    riot_id: str


def _public(job: dict) -> dict:
    return {k: job[k] for k in PUBLIC_JOB_FIELDS}


def create_app(
    store: Store,
    riot,
    priors: dict,
    workers: int = WORKERS,
    poll_seconds: float = 0.5,
    coach_client=None,
) -> FastAPI:
    """`coach_client`: an Anthropic client for the written summary; None leaves it out."""

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        tasks = [
            asyncio.create_task(worker_loop(store, riot, priors, coach_client=coach_client))
            for _ in range(workers)
        ]
        yield
        for t in tasks:
            t.cancel()

    app = FastAPI(title="Ekko", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=os.environ.get("EKKO_WEB_ORIGINS", "http://localhost:3000").split(","),
        allow_methods=["GET", "POST"],
        allow_headers=["content-type"],
    )

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True}

    @app.post("/api/lookups")
    def request_lookup(body: LookupRequest) -> dict:
        riot_id = body.riot_id.strip()
        if not RIOT_ID.match(riot_id):
            raise HTTPException(422, "Riot IDs look like name#tag.")
        return _public(store.request_lookup(riot_id))

    @app.get("/api/lookups/{job_id}")
    def get_lookup(job_id: str) -> dict:
        job = store.get_job(job_id)
        if job is None:
            raise HTTPException(404, "No such lookup.")
        return _public(job)

    @app.get("/api/lookups/{job_id}/events")
    async def lookup_events(job_id: str) -> StreamingResponse:
        if store.get_job(job_id) is None:
            raise HTTPException(404, "No such lookup.")

        async def stream():
            last = None
            while True:
                job = _public(store.get_job(job_id))
                if job != last:
                    yield f"data: {json.dumps(job)}\n\n"
                    last = job
                if job["status"] in ("done", "failed"):
                    return
                await asyncio.sleep(poll_seconds)

        return StreamingResponse(
            stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"}
        )

    @app.get("/api/reports/{report_id}")
    def get_report(report_id: str) -> dict:
        report = store.get_report(report_id)
        if report is None:
            raise HTTPException(404, "No such report.")
        return report

    return app


def default_app() -> FastAPI:
    """The real app: Riot key from .env, SQLite at EKKO_APP_DB (default data/app.sqlite).

    The coach runs only when ANTHROPIC_API_KEY is set (load_settings reads .env first).
    """
    settings = load_settings()
    db = os.environ.get("EKKO_APP_DB") or str(settings.data_dir / "app.sqlite")
    coach_client = None
    if os.environ.get("ANTHROPIC_API_KEY"):
        import anthropic

        coach_client = anthropic.Anthropic()
    return create_app(Store(db), RiotClient(settings), load_priors(), coach_client=coach_client)
