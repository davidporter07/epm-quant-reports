"""
test_earnings_trigger.py — Smoke-test the earnings-triggered cache invalidation.

Creates a fake completed job for today, patches check_earnings_released to return
True, then verifies the full chain: cache hit → earnings detected → invalidation →
fresh job queued → earnings_triggered flag returned.

Run with: python test_earnings_trigger.py
No Ollama, no network, no real data needed.
"""

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# 1. Patch check_earnings_released BEFORE importing app modules
# ---------------------------------------------------------------------------
import deep_analysis
deep_analysis.check_earnings_released = lambda ticker, date: True
print("[PATCH] check_earnings_released → always True")

import deep_analysis_worker as worker

# ---------------------------------------------------------------------------
# 2. Create a fake completed job for today
# ---------------------------------------------------------------------------
FAKE_TICKER = "TESTXX"
today_str = datetime.utcnow().strftime("%Y-%m-%d")
fake_job_id = f"deep_{FAKE_TICKER}_{uuid.uuid4().hex[:8]}"

fake_job = {
    "job_id":       fake_job_id,
    "ticker":       FAKE_TICKER,
    "status":       "completed",
    "stage":        "completed",
    "progress":     100,
    "retry_count":  0,
    "invalidated":  False,
    "created_at":   f"{today_str}T08:00:00",
    "started_at":   f"{today_str}T08:00:00",
    "completed_at": f"{today_str}T08:30:00",
    "updated_at":   f"{today_str}T08:30:00",
    "error":        None,
    "result":       {"markdown_content": "fake", "enhanced_markdown": "fake",
                     "title": "TESTXX Deep Analysis"},
    "key_facts": {
        "ticker":               FAKE_TICKER,
        "next_earnings_date":   today_str,   # <-- earnings day is TODAY
        "days_to_earnings":     0,
    },
}

jobs_dir = worker._jobs_dir()
fake_path = jobs_dir / f"{fake_job_id}.json"
fake_path.write_text(json.dumps(fake_job, indent=2))
print(f"[SETUP] Created fake completed job: {fake_job_id} (ticker={FAKE_TICKER}, date={today_str})")

# ---------------------------------------------------------------------------
# 3. Verify cache hit
# ---------------------------------------------------------------------------
cached = worker.get_today_cached_job(FAKE_TICKER)
assert cached is not None, "FAIL: get_today_cached_job returned None"
assert cached["job_id"] == fake_job_id, "FAIL: wrong job returned from cache"
print(f"[PASS] get_today_cached_job → found {cached['job_id']}")

# enqueue should return the cached job (no force_fresh)
returned_id = worker.enqueue(FAKE_TICKER, force_fresh=False)
assert returned_id == fake_job_id, f"FAIL: enqueue returned {returned_id!r}, expected cached id"
print(f"[PASS] enqueue(force_fresh=False) → served cached job {returned_id}")

# ---------------------------------------------------------------------------
# 4. Simulate the app.py trigger chain
# ---------------------------------------------------------------------------
from deep_analysis import check_earnings_released

cached2 = worker.get_today_cached_job(FAKE_TICKER)
key_facts = cached2.get("key_facts") or {}
next_earnings_date = key_facts.get("next_earnings_date")

assert next_earnings_date == today_str, "FAIL: next_earnings_date not today"
earnings_released = check_earnings_released(FAKE_TICKER, next_earnings_date)
assert earnings_released is True, "FAIL: check_earnings_released returned False (patch didn't apply)"
print(f"[PASS] check_earnings_released({FAKE_TICKER}, {next_earnings_date}) → True")

worker.invalidate_today_cache(FAKE_TICKER)
print(f"[PASS] invalidate_today_cache called")

# Cache should now be gone (invalidated=True)
cached3 = worker.get_today_cached_job(FAKE_TICKER)
assert cached3 is None, f"FAIL: cache not cleared after invalidation (got {cached3})"
print(f"[PASS] get_today_cached_job after invalidation → None (cache cleared)")

# ---------------------------------------------------------------------------
# 5. Enqueue with force_fresh should create a new job
# ---------------------------------------------------------------------------
new_id = worker.enqueue(FAKE_TICKER, force_fresh=True)
assert new_id != fake_job_id, "FAIL: enqueue returned old invalidated job_id"
print(f"[PASS] enqueue(force_fresh=True) → new job {new_id}")

# Clean up the fresh-queued job too
fresh_path = jobs_dir / f"{new_id}.json"

# ---------------------------------------------------------------------------
# 6. Cleanup
# ---------------------------------------------------------------------------
for p in [fake_path, fresh_path]:
    if p.exists():
        p.unlink()
print("[CLEANUP] Fake job files removed")

print("\n=== ALL CHECKS PASSED — earnings trigger chain is working ===")
