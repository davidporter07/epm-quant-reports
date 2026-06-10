"""PR 0/1: daily wrapper orchestration + live-site freshness check (fully mocked).
PR A: dirty-code guard."""
import os

import run_daily
import check_site_freshness as csf


# --- run_daily orchestration -----------------------------------------------

def _recording_runner(results):
    calls = []

    def runner(cmd):
        calls.append(cmd)
        # Return the queued result for this step (default 0).
        return results.pop(0) if results else 0

    runner.calls = calls
    return runner


def test_happy_path_runs_email_then_sync_then_verifies():
    runner = _recording_runner([0, 0])
    rc = run_daily.main([], runner=runner, fresh_checker=lambda: (True, "fresh"))
    assert rc == 0
    joined = [" ".join(c) for c in runner.calls]
    assert any("send_email.py" in c for c in joined)
    assert any("post_run.py" in c for c in joined)
    # Order: email before sync.
    assert next(i for i, c in enumerate(joined) if "send_email.py" in c) \
        < next(i for i, c in enumerate(joined) if "post_run.py" in c)


def test_failed_email_aborts_before_sync():
    runner = _recording_runner([1])  # send_email.py fails
    rc = run_daily.main([], runner=runner, fresh_checker=lambda: (True, "fresh"))
    assert rc == 1
    joined = [" ".join(c) for c in runner.calls]
    assert any("send_email.py" in c for c in joined)
    assert not any("post_run.py" in c for c in joined), "must not deploy after a failed report"


def test_stale_site_after_sync_returns_nonzero():
    runner = _recording_runner([0, 0])
    rc = run_daily.main([], runner=runner, fresh_checker=lambda: (False, "STALE"))
    assert rc == 2


# --- branch guard -----------------------------------------------------------

def test_research_branch_is_refused_before_any_work():
    runner = _recording_runner([0, 0])
    rc = run_daily.main(
        [], runner=runner, fresh_checker=lambda: (True, "fresh"),
        branch_checker=lambda: "growth24/research-salvage")
    assert rc == 3
    assert runner.calls == [], "must not generate/email/deploy from a research branch"


def test_main_branch_proceeds_normally():
    runner = _recording_runner([0, 0])
    rc = run_daily.main(
        [], runner=runner, fresh_checker=lambda: (True, "fresh"),
        branch_checker=lambda: "main")
    assert rc == 0
    assert any("send_email.py" in " ".join(c) for c in runner.calls)


def test_allow_branch_flag_bypasses_guard():
    runner = _recording_runner([0, 0])
    rc = run_daily.main(
        ["--allow-branch"], runner=runner, fresh_checker=lambda: (True, "fresh"),
        branch_checker=lambda: "some-feature-branch")
    assert rc == 0


def test_undeterminable_branch_does_not_block():
    runner = _recording_runner([0, 0])
    rc = run_daily.main(
        [], runner=runner, fresh_checker=lambda: (True, "fresh"),
        branch_checker=lambda: "")
    assert rc == 0


# --- dirty-code guard (PR A) ------------------------------------------------

def test_dirty_tree_refuses_run_exit_4():
    runner = _recording_runner([0, 0])
    rc = run_daily.main(
        [], runner=runner, fresh_checker=lambda: (True, "fresh"),
        dirty_checker=lambda: ["app.py"],
    )
    assert rc == 4
    assert runner.calls == [], "must not generate/email/deploy when tree is dirty"


def test_post_run_failure_with_fresh_site_exits_5(monkeypatch):
    """post_run fails (deploy error) but site is fresh → exit 5 + alert sent."""
    alerts = []
    monkeypatch.setattr(run_daily, "_send_alert", lambda stage, detail: alerts.append(stage))
    monkeypatch.setattr(run_daily, "_record_status", lambda *a, **k: None)
    runner = _recording_runner([0, 1])  # email ok, post_run fails
    rc = run_daily.main([], runner=runner, fresh_checker=lambda: (True, "fresh"))
    assert rc == 5
    assert "post_run" in alerts


def test_allow_dirty_flag_bypasses_guard(monkeypatch):
    from post_run import _ALLOW_DIRTY_ENV
    monkeypatch.delenv(_ALLOW_DIRTY_ENV, raising=False)
    runner = _recording_runner([0, 0])
    rc = run_daily.main(
        ["--allow-dirty"], runner=runner, fresh_checker=lambda: (True, "fresh"),
        dirty_checker=lambda: ["app.py"],
    )
    assert rc == 0
    assert any("send_email.py" in " ".join(c) for c in runner.calls)
    assert os.environ.get(_ALLOW_DIRTY_ENV) == "1"


# --- check_site_freshness logic --------------------------------------------

def test_market_closed_is_always_fresh():
    fresh, _ = csf.is_site_fresh(market_open=False)
    assert fresh is True


def test_matching_report_date_is_fresh():
    fresh, _ = csf.is_site_fresh(
        today="2026-05-28", market_open=True, fetch=lambda url: "2026-05-28")
    assert fresh is True


def test_stale_report_date_is_not_fresh():
    fresh, detail = csf.is_site_fresh(
        today="2026-05-28", market_open=True, fetch=lambda url: "2026-05-21")
    assert fresh is False
    assert "STALE" in detail


def test_unreachable_site_is_not_fresh():
    fresh, detail = csf.is_site_fresh(
        today="2026-05-28", market_open=True, fetch=lambda url: None)
    assert fresh is False


def test_extract_report_date_handles_nested_commentary_shape():
    # /api/commentary returns the date NESTED under "commentary".
    payload = {"ok": True, "commentary": {"report_date": "2026-05-29", "x": 1}}
    assert csf._extract_report_date(payload) == "2026-05-29"


def test_extract_report_date_top_level_fallback():
    assert csf._extract_report_date({"report_date": "2026-05-29"}) == "2026-05-29"


def test_extract_report_date_missing_returns_none():
    assert csf._extract_report_date({"ok": True, "commentary": {}}) is None
    assert csf._extract_report_date("not a dict") is None
