"""
deep_analysis_worker.py — Sequential job queue for the deep analysis pipeline.

Pipeline (post-MiroFish):
  Step 0: build_seed_doc  -> seed_text + key_facts
  Step 1: run_council     -> 7 persona Ollama calls + 1 synthesis call

Jobs are stored as JSON files in data/jobs/; one background thread processes
them FIFO. App endpoints write job files; the worker reads and updates them.

Job lifecycle: queued -> running -> completed | failed
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

JOBS_DIR = Path("data") / "jobs"

# Stage labels shown to the frontend. Keep keys in sync with
# static/js/deep_analysis.js STAGE_LABELS.
STAGES = {
    "queued":             ("Queued",                     0),
    "seed_doc":           ("Building analysis document", 5),
    "council_personas":   ("Council deliberating",      15),
    "council_synthesis":  ("Synthesizing report",       85),
    "completed":          ("Complete",                 100),
    "failed":             ("Failed",                    -1),
}

_worker_thread: Optional[threading.Thread] = None
_stop_event = threading.Event()


# ---------------------------------------------------------------------------
# Job file helpers
# ---------------------------------------------------------------------------

def _jobs_dir() -> Path:
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    return JOBS_DIR


def _job_path(job_id: str) -> Path:
    return _jobs_dir() / f"{job_id}.json"


def _write_job(job: dict) -> None:
    job["updated_at"] = datetime.utcnow().isoformat()
    path = _job_path(job["job_id"])
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(job, indent=2))
    tmp.replace(path)


def _read_job(job_id: str) -> Optional[dict]:
    path = _job_path(job_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _update_job(job_id: str, **kwargs) -> dict:
    job = _read_job(job_id) or {}
    job.update(kwargs)
    _write_job(job)
    return job


def _get_queue_info(job_id: str) -> dict:
    """Return queue position and estimated wait minutes for a queued job."""
    active = []
    for p in _jobs_dir().glob("*.json"):
        try:
            j = json.loads(p.read_text())
            if j.get("status") in ("queued", "running"):
                active.append(j)
        except Exception:
            continue
    active.sort(key=lambda j: j.get("created_at", ""))
    position = next((i + 1 for i, j in enumerate(active) if j["job_id"] == job_id), 1)
    ahead = position - 1
    # Local Council averages ~7 minutes per ticker (7 personas + synthesis).
    return {
        "queue_position": position,
        "queue_ahead":    ahead,
        "queue_wait_min": ahead * 7,
    }


def _next_queued_job() -> Optional[dict]:
    """Return oldest queued job by created_at, or None."""
    candidates = []
    for p in _jobs_dir().glob("*.json"):
        try:
            j = json.loads(p.read_text())
            if j.get("status") == "queued":
                candidates.append(j)
        except Exception:
            continue
    if not candidates:
        return None
    return min(candidates, key=lambda j: j.get("created_at", ""))


def _reset_interrupted_jobs() -> None:
    """On startup: reset any jobs stuck in 'running' back to 'queued'."""
    for p in _jobs_dir().glob("*.json"):
        try:
            j = json.loads(p.read_text())
            if j.get("status") == "running":
                j["status"] = "queued"
                j["stage"] = "queued"
                j["progress"] = 0
                j["started_at"] = None
                _write_job(j)
        except Exception:
            continue


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def _run_pipeline(job_id: str, ticker: str) -> None:
    """Run the full deep analysis pipeline for one ticker."""
    import logging
    from deep_analysis import build_seed_doc
    from local_council import PERSONAS, run_council

    logger = logging.getLogger(__name__)

    # Step 0 — Build seed doc + key_facts
    _update_job(job_id, stage="seed_doc", progress=5)
    t0 = time.time()
    seed_text, key_facts = build_seed_doc(ticker, pred_len=10)
    _update_job(job_id, seed_text=seed_text, key_facts=key_facts, progress=12)
    logger.info("Seed doc for %s: %d chars, %d facts, %.1fs",
                ticker, len(seed_text), len(key_facts), time.time() - t0)

    # Step 1 — Run the local analyst council.
    # Council portion maps to progress 15 -> 85 (persona phase),
    # then 85 -> 95 (synthesis phase) which run_council advances at ~88% of its range.
    _update_job(job_id, stage="council_personas", progress=15)
    n_personas = len(PERSONAS)

    def _progress_cb(pct: int, label: str) -> None:
        if _stop_event.is_set():
            raise RuntimeError("Worker stopped")
        # pct is 0-100 scaled within the council portion.
        # Map: 0..(n/(n+1))*100 -> persona stage (15..85),
        #      (n/(n+1))*100..100 -> synthesis stage (85..95).
        persona_cutoff = 100 * n_personas / (n_personas + 1)
        if pct < persona_cutoff:
            mapped = 15 + int((pct / persona_cutoff) * (85 - 15))
            stage = "council_personas"
        else:
            frac = (pct - persona_cutoff) / (100 - persona_cutoff) if 100 > persona_cutoff else 1.0
            mapped = 85 + int(frac * (95 - 85))
            stage = "council_synthesis"
        _update_job(job_id, stage=stage, progress=min(95, mapped))

    result = run_council(ticker, seed_text, key_facts, progress_cb=_progress_cb)

    enhanced_markdown = result.get("enhanced_markdown", "")
    raw_markdown      = result.get("raw_markdown", "")
    takes             = result.get("takes", [])

    if not enhanced_markdown:
        # Synthesis failed — fall back to raw transcript so the user sees something.
        logger.warning("Synthesis produced no output for %s; falling back to raw transcript", ticker)
        enhanced_markdown = raw_markdown

    # Step 2 — Persist result
    _update_job(job_id, stage="council_synthesis", progress=98)
    final_result = {
        "markdown_content":  raw_markdown,        # council transcript (per-persona)
        "enhanced_markdown": enhanced_markdown,   # synthesized 6-section report
        "title":   f"{ticker} Deep Analysis",
        "summary": "",
        "sections": [],
        "takes":    takes,                         # structured persona submissions
    }
    _update_job(
        job_id,
        stage="completed",
        status="completed",
        progress=100,
        result=final_result,
        completed_at=datetime.utcnow().isoformat(),
    )


# ---------------------------------------------------------------------------
# Background worker thread
# ---------------------------------------------------------------------------

def _worker_loop() -> None:
    _reset_interrupted_jobs()
    while not _stop_event.is_set():
        job = _next_queued_job()
        if job is None:
            _stop_event.wait(timeout=5)
            continue

        job_id = job["job_id"]
        ticker  = job["ticker"]
        retry_count = job.get("retry_count", 0)
        _update_job(
            job_id,
            status="running",
            stage="seed_doc",
            started_at=datetime.utcnow().isoformat(),
        )
        try:
            _run_pipeline(job_id, ticker)
        except Exception as exc:
            import logging
            logging.getLogger(__name__).error(
                "Deep analysis failed for %s (attempt %d): %s",
                ticker, retry_count + 1, exc,
            )
            if retry_count < 1 and not _stop_event.is_set():
                _update_job(
                    job_id,
                    status="queued",
                    stage="queued",
                    progress=0,
                    retry_count=retry_count + 1,
                    started_at=None,
                    error=None,
                )
            else:
                _update_job(
                    job_id,
                    status="failed",
                    stage="failed",
                    error="Analysis could not be completed. Please try again later.",
                    completed_at=datetime.utcnow().isoformat(),
                )


def start_worker() -> None:
    global _worker_thread
    _stop_event.clear()
    _worker_thread = threading.Thread(
        target=_worker_loop,
        name="deep-analysis-worker",
        daemon=True,
    )
    _worker_thread.start()


def stop_worker() -> None:
    _stop_event.set()


# ---------------------------------------------------------------------------
# Public API used by app.py
# ---------------------------------------------------------------------------

def enqueue(ticker: str) -> str:
    """Create a new job and return its job_id. If an active job already exists
    for this ticker, return that job_id instead of stacking duplicates."""
    ticker = ticker.upper()
    for p in _jobs_dir().glob("*.json"):
        try:
            j = json.loads(p.read_text())
            if j.get("ticker") == ticker and j.get("status") in ("queued", "running"):
                return j["job_id"]
        except Exception:
            continue

    job_id = f"deep_{ticker}_{uuid.uuid4().hex[:8]}"
    job: Dict[str, Any] = {
        "job_id":       job_id,
        "ticker":       ticker,
        "status":       "queued",
        "stage":        "queued",
        "progress":     0,
        "retry_count":  0,
        "created_at":   datetime.utcnow().isoformat(),
        "started_at":   None,
        "completed_at": None,
        "updated_at":   None,
        "error":        None,
        "result":       None,
    }
    _write_job(job)
    return job_id


def get_job_status(job_id: str) -> Optional[dict]:
    """Return public-facing job status dict, or None if not found."""
    job = _read_job(job_id)
    if job is None:
        return None

    stage_label, _ = STAGES.get(job.get("stage", "queued"), ("Unknown", 0))
    result = {
        "job_id":       job["job_id"],
        "ticker":       job.get("ticker"),
        "status":       job.get("status"),
        "stage":        job.get("stage"),
        "stage_label":  stage_label,
        "progress":     job.get("progress", 0),
        "created_at":   job.get("created_at"),
        "started_at":   job.get("started_at"),
        "completed_at": job.get("completed_at"),
        "error":        job.get("error"),
        "result":       job.get("result") if job.get("status") == "completed" else None,
    }
    if job.get("status") == "queued":
        result.update(_get_queue_info(job_id))
    return result
