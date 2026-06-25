"""Lightweight, never-raising per-stage timing for the daily pipeline.

The daily pipeline (run_daily.py -> send_email.py -> monitor.py) emits its stage
output to the console, which the Windows scheduler does NOT capture to a
timestamped file — so when a run is slow (e.g. the 2026-06-25 run took ~1h53m vs
the ~40min norm) there is no record of WHICH stage was slow. This module writes
per-stage checkpoints — each with an absolute timestamp plus the elapsed time
since the previous checkpoint — to logs/pipeline_stages.log.

Informational only: every function swallows its own errors and can never affect
the run. Callers also guard the import with a no-op fallback, so a missing module
never breaks the pipeline either.

Usage:
    from services.stage_timer import stage_mark, stage_reset
    stage_reset("monitor.py")              # writes a run header, resets the clock
    ...
    stage_mark("data_arbiter + features")  # logs +<delta>s since the previous mark

logs/ is laptop-local and never synced to the server (it can hold subscriber
data elsewhere), so this diagnostic stays off the public health surface.
"""
from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

_LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "pipeline_stages.log"

# Per-process clock. run_daily.py / send_email.py / monitor.py each run as their
# own process, so the deltas are meaningful WITHIN a process; the absolute
# timestamps let you stitch stages across the process chain in the shared log.
_clock: dict[str, float | None] = {"start": None, "last": None}


def _write(line: str) -> None:
    print(line)
    _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_LOG_PATH, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def stage_reset(label: str = "") -> None:
    """Begin a new timed section: write a header and reset the per-process clock.
    Never raises."""
    try:
        now = time.time()
        _clock["start"] = now
        _clock["last"] = now
        ts = datetime.now().astimezone().isoformat(timespec="seconds")
        _write(f"\n===== {ts}  RUN START: {label} =====")
    except Exception:
        pass


def stage_mark(name: str) -> None:
    """Record a stage checkpoint with the elapsed time since the previous mark.

    Self-seeding: if called before stage_reset, the first mark starts the clock.
    Never raises."""
    try:
        now = time.time()
        if _clock["start"] is None:
            _clock["start"] = now
            _clock["last"] = now
        delta = now - _clock["last"]
        total = now - _clock["start"]
        _clock["last"] = now
        ts = datetime.now().astimezone().isoformat(timespec="seconds")
        _write(f"{ts}  [STAGE] {str(name):<34} +{delta:8.1f}s   (total {total:8.1f}s)")
    except Exception:
        pass
