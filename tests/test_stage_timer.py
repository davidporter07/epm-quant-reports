"""services.stage_timer — per-stage pipeline timing (informational, never-raising)."""
import importlib

import pytest

st = pytest.importorskip("services.stage_timer")


def test_stage_marks_write_checkpoints_with_deltas(tmp_path, monkeypatch):
    log = tmp_path / "pipeline_stages.log"
    monkeypatch.setattr(st, "_LOG_PATH", log)
    monkeypatch.setattr(st, "_clock", {"start": None, "last": None})

    st.stage_reset("unit-test")
    st.stage_mark("alpha")
    st.stage_mark("beta")

    content = log.read_text(encoding="utf-8")
    assert "RUN START: unit-test" in content
    assert "[STAGE] alpha" in content
    assert "[STAGE] beta" in content
    # delta (+Ns) and cumulative (total Ns) columns are present on each mark
    assert content.count("[STAGE]") == 2
    assert "total" in content


def test_stage_mark_self_seeds_without_reset(tmp_path, monkeypatch):
    log = tmp_path / "p.log"
    monkeypatch.setattr(st, "_LOG_PATH", log)
    monkeypatch.setattr(st, "_clock", {"start": None, "last": None})
    # First mark with no prior reset must not crash and must start the clock.
    st.stage_mark("first")
    assert st._clock["start"] is not None
    assert "[STAGE] first" in log.read_text(encoding="utf-8")


def test_stage_timer_never_raises_on_write_failure(monkeypatch):
    # A disk/permission error inside the writer must be swallowed — the timer can
    # never take down the daily pipeline.
    def boom(*_a, **_k):
        raise RuntimeError("disk full")
    monkeypatch.setattr(st, "_write", boom)
    st.stage_reset("x")   # must not raise
    st.stage_mark("y")    # must not raise
