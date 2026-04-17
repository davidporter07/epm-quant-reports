"""
deep_analysis_worker.py — Sequential job queue for the deep analysis pipeline.

Architecture:
  - Jobs stored as JSON files in data/jobs/
  - One background thread processes jobs FIFO, one at a time
  - Each job runs: seed doc → MiroFish 7-step pipeline → report
  - App endpoints write job files; worker reads and updates them

Job lifecycle:
  queued → running → completed | failed
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests

MIROFISH_BASE = os.environ.get("MIROFISH_URL", "http://localhost:5001")
MIROFISH_HEADERS = {"Accept-Language": "en"}
OLLAMA_URL   = os.environ.get("LOCAL_OLLAMA_URL",   "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("LOCAL_OLLAMA_MODEL", "qwen2.5:14b")
JOBS_DIR = Path("data") / "jobs"

# Stage labels shown to the frontend
STAGES = {
    "queued":             ("Queued",                        0),
    "seed_doc":           ("Building analysis document",    5),
    "ontology":           ("Generating ontology",          15),
    "graph":              ("Building knowledge graph",      25),
    "simulation_create":  ("Creating simulation",          30),
    "simulation_prepare": ("Preparing agents",             35),
    "simulation_running": ("Running simulation",           55),
    "report_generate":    ("Generating report",            60),
    "report_poll":        ("Writing report sections",      65),
    "completed":          ("Complete",                    100),
    "failed":             ("Failed",                       -1),
}

_worker_thread: Optional[threading.Thread] = None
_stop_event = threading.Event()


# ---------------------------------------------------------------------------
# Zombie simulation cleanup
# ---------------------------------------------------------------------------

def _kill_zombie_sims() -> None:
    """Kill any lingering run_parallel_simulation.py processes from prior runs.

    MiroFish does not auto-clean child sim processes after a simulation
    completes or fails. Accumulated zombies compete for Ollama GPU and cause
    IPC timeouts mid-report. Kill them before starting each new pipeline run.
    """
    import subprocess
    try:
        result = subprocess.run(
            ["pgrep", "-f", "run_parallel_simulation.py"],
            capture_output=True, text=True,
        )
        pids = [p.strip() for p in result.stdout.splitlines() if p.strip()]
        if pids:
            subprocess.run(["kill", "-9"] + pids, capture_output=True)
            time.sleep(1)  # brief pause so GPU memory is released
    except Exception:
        pass  # non-fatal — log nothing, just proceed


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
# MiroFish pipeline
# ---------------------------------------------------------------------------

def _postprocess_with_llm(ticker: str, seed_text: str, raw_markdown: str) -> str:
    """
    Pass MiroFish raw report through qwen2.5:14b to produce a structured deep analysis.
    Uses a strict template so the LLM fills in sections rather than following rules it ignores.
    Falls back to raw_markdown on any error so the job never fails here.
    """
    import logging
    logger = logging.getLogger(__name__)

    # Include enough seed text to cover price data, Kronos scenarios, AND EPM forecasts
    # Kronos tables start around char 600-800, EPM models typically around 1500-2000
    seed_excerpt = seed_text[:5000]

    prompt = (
        f"You are a senior equity research analyst. Write a deep market intelligence report for "
        f"{ticker} by filling in the five sections below using the two data sources provided.\n\n"
        f"DATA SOURCE A — SEED DOCUMENT (use these numbers for ALL prices, percentages, and forecasts):\n"
        f"```\n{seed_excerpt}\n```\n\n"
        f"DATA SOURCE B — MIROFISH SWARM SIMULATION (use only for agent reasoning and qualitative "
        f"perspectives — its numbers are unreliable, use Source A numbers instead):\n"
        f"```\n{raw_markdown[:3000]}\n```\n\n"
        f"Write exactly these five sections. Do not add any other sections or text outside them.\n\n"
        f"## Quantitative Snapshot\n"
        f"Write 2-3 paragraphs covering: current price and where it sits relative to its 52-week "
        f"range and moving averages (use exact figures from Source A). RSI reading and what momentum "
        f"signals. The EPM model ensemble spread — name the most optimistic and most pessimistic "
        f"models with their exact forecast percentages and explain what a spread of that magnitude "
        f"implies about directional conviction. Volume trend vs 20-day average.\n\n"
        f"## Kronos Scenario Breakdown\n"
        f"Write one paragraph per Kronos scenario (bullish, base, bearish — use the exact labels "
        f"and price targets from Source A). Each paragraph must cover: the exact implied price "
        f"target and percentage move from Source A, what specific market conditions or catalysts "
        f"would produce that path, how retail investors and institutional players would position "
        f"differently in that scenario, and which EPM models from Source A align with that outcome.\n\n"
        f"## Swarm Simulation: Agent Perspectives & Tensions\n"
        f"Write 3-4 paragraphs on what the multi-agent simulation revealed. Focus on: where agent "
        f"perspectives disagreed rather than agreed (tension is more informative than consensus), "
        f"what asymmetric risks the macro/Fed-perspective agents flagged that technical models miss, "
        f"what the supply-chain and geopolitical perspectives argued about structural risks, and "
        f"how investor-perspective agents framed positioning under uncertainty. Write as analysis "
        f"of what the simulation produced — no quotes, no 'Expert A said', no blockquotes.\n\n"
        f"## Market Participant Reactions\n"
        f"Write 3 paragraphs of concrete behavioral predictions. Paragraph 1: if {ticker} trends "
        f"toward the bearish Kronos target over the next 10 days, what do retail momentum traders "
        f"do (at what price level does selling accelerate?), what do value-oriented institutions do, "
        f"and what narrative takes hold in financial media? Paragraph 2: same analysis for the "
        f"bullish scenario — what triggers a momentum chase, where does short covering add fuel, "
        f"and how does the options market amplify the move? Paragraph 3: what behavioral dynamic "
        f"is most likely to cause a whipsaw between the two scenarios, and what is the tell that "
        f"the dominant scenario has been decided?\n\n"
        f"## Critical Risks Beyond the Models\n"
        f"Write exactly 3 numbered risks that no quantitative model captures for {ticker}. "
        f"For each: name the specific risk, explain the exact trigger mechanism, identify which "
        f"Kronos scenario it would most accelerate, and state what a risk-aware investor would "
        f"watch as an early warning signal. Be specific to {ticker}'s business — not generic.\n\n"
        f"OUTPUT FORMAT RULES (violations invalidate the report):\n"
        f"- Use only prices and percentages from Source A\n"
        f"- No quotes attributed to 'Expert', 'Analyst', 'Spokesperson', or any named/unnamed person\n"
        f"- No blockquote markdown (no > syntax)\n"
        f"- No mention of: panorama_search, interview_agents, quick_search, insight_forge\n"
        f"- No repetition of the same statistic across sections\n"
        f"- Start immediately with ## Quantitative Snapshot — no preamble\n"
    )

    try:
        r = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            timeout=300,  # increased: 5 sections takes longer than 4
        )
        r.raise_for_status()
        enhanced = r.json().get("response", "").strip()
        # Validate: must contain at least 3 of our 5 section headers and be substantive
        required = ["## Quantitative Snapshot", "## Kronos Scenario", "## Market Participant"]
        if enhanced and len(enhanced) > 500 and all(h in enhanced for h in required):
            return enhanced
        logger.warning("LLM post-processing output failed validation (missing required sections)")
    except Exception as exc:
        logger.warning("LLM post-processing failed (using raw MiroFish output): %s", exc)

    return raw_markdown


def _mf_post(path: str, timeout: int = 180, **kwargs) -> dict:
    r = requests.post(f"{MIROFISH_BASE}{path}", headers=MIROFISH_HEADERS, timeout=timeout, **kwargs)
    r.raise_for_status()
    return r.json()


def _mf_get(path: str, timeout: int = 60) -> dict:
    r = requests.get(f"{MIROFISH_BASE}{path}", headers=MIROFISH_HEADERS, timeout=timeout)
    r.raise_for_status()
    return r.json()


def _poll(job_id: str, fn, terminal_fn, interval: int = 10,
          max_iterations: int = 120, stage: str = "", progress_start: int = 0,
          progress_end: int = 0) -> dict:
    """
    Poll fn() until terminal_fn(response) returns True or max_iterations reached.
    Updates job progress linearly between progress_start and progress_end.
    Returns last response.
    """
    for i in range(max_iterations):
        if _stop_event.is_set():
            raise RuntimeError("Worker stopped")
        time.sleep(interval)
        resp = fn()
        pct = int(progress_start + (progress_end - progress_start) * (i / max_iterations))
        _update_job(job_id, stage=stage, progress=pct)
        if terminal_fn(resp):
            return resp
    raise TimeoutError(f"Timed out waiting for stage: {stage}")


def _run_pipeline(job_id: str, ticker: str) -> None:
    """Full MiroFish pipeline for one ticker. Updates job file throughout."""
    from deep_analysis import build_seed_doc

    # Step 0: Build seed doc
    _update_job(job_id, stage="seed_doc", progress=5)
    seed_text = build_seed_doc(ticker, pred_len=10)
    _update_job(job_id, seed_text=seed_text)  # store for LLM post-processing later

    # Step 1: Upload seed doc, generate ontology
    _update_job(job_id, stage="ontology", progress=8)
    tmp_path = os.path.join(tempfile.gettempdir(), f"{job_id}_seed.txt")
    with open(tmp_path, "w") as f:
        f.write(seed_text)

    with open(tmp_path, "rb") as f:
        resp = _mf_post(
            "/api/graph/ontology/generate",
            data={
                "simulation_requirement": (
                    f"LANGUAGE: Write ALL posts exclusively in English. No other language permitted.\n"
                    f"SIMULATION MANDATE for {ticker}:\n"
                    f"Each agent must post from their specific domain perspective. Agents should "
                    f"DISAGREE with each other — the goal is productive tension, not consensus.\n"
                    f"Three things every agent must address in their posts:\n"
                    f"1. SCENARIO STANCE: Given the quantitative models show divergence between "
                    f"an optimistic and pessimistic forecast, argue which scenario your domain "
                    f"perspective finds more credible and exactly why.\n"
                    f"2. MARKET BEHAVIOR PREDICTION: How would retail investors react if the bearish "
                    f"scenario materializes? What about institutional investors? What narrative would "
                    f"dominate financial media? Be specific about price levels and behavioral triggers.\n"
                    f"3. HIDDEN RISK: Identify one structural risk specific to your domain that "
                    f"no price-based model captures. Name the trigger, the mechanism, and the impact.\n"
                    f"Engage with other agents' arguments. If another perspective is wrong, say so "
                    f"and explain why from your domain expertise."
                ),
                "project_name": f"{ticker} Deep Analysis",
            },
            files={"files": (f"{job_id}_seed.txt", f, "text/plain")},
        )

    if not resp.get("success"):
        raise RuntimeError(f"Ontology generation failed: {resp}")
    project_id = resp["data"]["project_id"]
    _update_job(job_id, stage="ontology", progress=15, project_id=project_id)

    # Step 2: Build graph
    _update_job(job_id, stage="graph", progress=16)
    resp = _mf_post("/api/graph/build", json={"project_id": project_id})
    if not resp.get("success"):
        raise RuntimeError(f"Graph build failed: {resp}")
    task_id = resp["data"]["task_id"]

    resp = _poll(
        job_id,
        fn=lambda: _mf_get(f"/api/graph/task/{task_id}"),
        terminal_fn=lambda r: r.get("data", {}).get("status") in ("completed", "failed"),
        interval=10, max_iterations=36,   # 6 min max (AAPL graph build can exceed 3 min)
        stage="graph", progress_start=16, progress_end=25,
    )
    if resp.get("data", {}).get("status") == "failed":
        raise RuntimeError(f"Graph build failed: {resp}")
    graph_id = resp["data"]["result"]["graph_id"]
    _update_job(job_id, stage="graph", progress=25, graph_id=graph_id)

    # Step 3: Create simulation — kill any lingering zombie sim processes first
    _kill_zombie_sims()
    resp = _mf_post("/api/simulation/create", json={"project_id": project_id})
    if not resp.get("success"):
        raise RuntimeError(f"Simulation create failed: {resp}")
    simulation_id = resp["data"]["simulation_id"]
    _update_job(job_id, stage="simulation_create", progress=30, simulation_id=simulation_id)

    # Step 4: Prepare simulation (up to 20 min)
    _update_job(job_id, stage="simulation_prepare", progress=31)
    resp = _mf_post("/api/simulation/prepare", json={"simulation_id": simulation_id})
    if not resp.get("success"):
        raise RuntimeError(f"Simulation prepare failed: {resp}")

    _poll(
        job_id,
        fn=lambda: _mf_post("/api/simulation/prepare/status", json={"simulation_id": simulation_id}),
        terminal_fn=lambda r: r.get("data", {}).get("status") in ("completed", "ready", "failed"),
        interval=10, max_iterations=130,   # 21 min max
        stage="simulation_prepare", progress_start=32, progress_end=54,
    )

    # Step 5: Start simulation (fire and move on — runs in background)
    resp = _mf_post("/api/simulation/start", json={"simulation_id": simulation_id, "rounds": 72})
    if not resp.get("success"):
        raise RuntimeError(f"Simulation start failed: {resp}")
    _update_job(job_id, stage="simulation_running", progress=55)

    # Brief pause to let simulation spin up before requesting report
    time.sleep(15)

    # Step 6: Generate report
    _update_job(job_id, stage="report_generate", progress=60)
    resp = _mf_post("/api/report/generate", json={"simulation_id": simulation_id})
    if not resp.get("success"):
        raise RuntimeError(f"Report generate failed: {resp}")
    report_id = resp["data"]["report_id"]
    _update_job(job_id, stage="report_generate", progress=62, report_id=report_id)

    # Step 7: Poll report progress (up to 40 min — MiroFish can stall on IPC timeouts mid-section)
    _poll(
        job_id,
        fn=lambda: _mf_get(f"/api/report/{report_id}/progress"),
        terminal_fn=lambda r: r.get("data", {}).get("status") in ("completed", "failed"),
        interval=15, max_iterations=160,   # 40 min max
        stage="report_poll", progress_start=63, progress_end=95,
    )

    # Step 8: Fetch final report
    resp = _mf_get(f"/api/report/{report_id}")
    if not resp.get("success") or resp.get("data", {}).get("status") != "completed":
        raise RuntimeError(f"Report fetch failed or not completed: {resp}")

    data = resp["data"]
    raw_markdown = data.get("markdown_content", "")

    # Step 9: LLM post-processing — enrich with quant data MiroFish dropped
    _update_job(job_id, stage="report_poll", progress=96)
    job_data     = _read_job(job_id) or {}
    seed_text    = job_data.get("seed_text", "")
    enhanced_markdown = _postprocess_with_llm(ticker, seed_text, raw_markdown)

    result = {
        "markdown_content":  raw_markdown,
        "enhanced_markdown": enhanced_markdown,
        "title":    data.get("outline", {}).get("title", f"{ticker} Deep Analysis"),
        "summary":  data.get("outline", {}).get("summary", ""),
        "sections": data.get("outline", {}).get("sections", []),
        "report_id":     report_id,
        "simulation_id": simulation_id,
        "graph_id":      graph_id,
    }
    _update_job(job_id, stage="completed", status="completed", progress=100, result=result,
                completed_at=datetime.utcnow().isoformat())

    # Cleanup temp file
    try:
        os.unlink(tmp_path)
    except Exception:
        pass


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
        _update_job(job_id, status="running", stage="seed_doc",
                    started_at=datetime.utcnow().isoformat())
        try:
            _run_pipeline(job_id, ticker)
        except Exception as exc:
            # Log full error server-side; show a clean message to the user
            import logging
            logging.getLogger(__name__).error("Deep analysis failed for %s: %s", ticker, exc)
            user_error = "Analysis could not be completed. Please try again later."
            if isinstance(exc, TimeoutError):
                user_error = "Analysis timed out. The server may be busy — please try again."
            _update_job(
                job_id,
                status="failed",
                stage="failed",
                error=user_error,
                completed_at=datetime.utcnow().isoformat(),
            )


def start_worker() -> None:
    global _worker_thread
    _stop_event.clear()
    _worker_thread = threading.Thread(target=_worker_loop, name="deep-analysis-worker", daemon=True)
    _worker_thread.start()


def stop_worker() -> None:
    _stop_event.set()


# ---------------------------------------------------------------------------
# Public API used by app.py
# ---------------------------------------------------------------------------

def enqueue(ticker: str) -> str:
    """Create a new job and return its job_id."""
    job_id = f"deep_{ticker}_{uuid.uuid4().hex[:8]}"
    job = {
        "job_id":       job_id,
        "ticker":       ticker.upper(),
        "status":       "queued",
        "stage":        "queued",
        "progress":     0,
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
    return {
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
