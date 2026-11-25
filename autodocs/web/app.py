"""Web UI:  uvicorn autodocs.web.app:app --reload   then open http://localhost:8000

Each job runs in a background thread; the page polls for progress and shows the docs
(with rendered Mermaid diagrams) when it's done.
"""
from __future__ import annotations

import io
import threading
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from autodocs import __version__
from autodocs.config import Settings
from autodocs.fetch import parse_github

STATIC = Path(__file__).parent / "static"
MAX_RUNNING = 2
JOB_TTL_SECONDS = 3600

app = FastAPI(title="Auto-Docs Agent", version=__version__)
_slots = threading.BoundedSemaphore(MAX_RUNNING)


@dataclass
class Job:
    id: str
    repo: str
    offline: bool
    status: str = "queued"     # queued | running | done | error
    events: list[dict] = field(default_factory=list)
    docs: dict[str, str] = field(default_factory=dict)
    report: dict = field(default_factory=dict)
    error: str = ""
    created: float = field(default_factory=time.time)


JOBS: dict[str, Job] = {}


class JobIn(BaseModel):
    repo: str = Field(min_length=3, max_length=300, description="GitHub URL or owner/repo")
    offline: bool = False


def _cleanup() -> None:
    now = time.time()
    for jid in [j for j, job in JOBS.items() if now - job.created > JOB_TTL_SECONDS]:
        JOBS.pop(jid, None)


def _work(job: Job) -> None:
    from autodocs.pipeline import run

    with _slots:
        job.status = "running"
        try:
            res = run(job.repo, Settings.from_env(), offline=job.offline,
                      on_event=lambda stage, msg: job.events.append({"stage": stage, "message": msg, "t": time.time()}))
            job.docs = {**res.docs, "QUALITY_REPORT.md": (res.out_dir / "QUALITY_REPORT.md").read_text(encoding="utf-8")}
            job.report = {**res.report.to_dict(), "meta": res.meta}
            job.status = "done"
        except Exception as e:  # noqa: BLE001 - show any failure to the user
            job.error = str(e)[:500]
            job.status = "error"


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/health")
def health():
    s = Settings.from_env()
    has_key = bool(s.gemini_api_key or s.groq_api_key or s.anthropic_api_key or s.llm_provider == "openai_compatible")
    return {"status": "ok", "version": __version__, "ai_configured": has_key, "model": f"{s.llm_provider}:{s.llm_model}"}


@app.post("/api/jobs", status_code=202)
def create_job(body: JobIn):
    # The web UI only accepts GitHub repos, never paths on the server's own disk.
    if parse_github(body.repo) is None:
        raise HTTPException(422, "Enter a GitHub repository, like https://github.com/owner/repo")
    _cleanup()
    job = Job(id=uuid.uuid4().hex[:12], repo=body.repo.strip(), offline=body.offline)
    JOBS[job.id] = job
    threading.Thread(target=_work, args=(job,), daemon=True).start()
    return {"id": job.id, "status": job.status}


def _get(job_id: str) -> Job:
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found (jobs are kept for 1 hour)")
    return job


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    j = _get(job_id)
    return {"id": j.id, "repo": j.repo, "status": j.status, "events": j.events, "error": j.error,
            "docs": j.docs if j.status == "done" else {}, "report": j.report if j.status == "done" else {}}


@app.get("/api/jobs/{job_id}/download")
def download(job_id: str):
    j = _get(job_id)
    if j.status != "done":
        raise HTTPException(409, "Docs aren't ready yet")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, md in j.docs.items():
            zf.writestr(name, md)
    buf.seek(0)
    name = (parse_github(j.repo) or ("", "docs", None))[1]
    return StreamingResponse(buf, media_type="application/zip",
                             headers={"Content-Disposition": f'attachment; filename="{name}-docs.zip"'})
