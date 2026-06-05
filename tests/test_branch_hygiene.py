from scripts.check_branch_hygiene import (
    HygieneState,
    evaluate_state,
    is_local_artifact,
    model_branch_allowed,
    parse_status_paths,
)


def _state(**overrides):
    values = {
        "branch": "growth24/research-salvage",
        "base": "origin/main",
        "base_exists": True,
        "base_behind": 0,
        "base_ahead": 3,
        "upstream": "origin/growth24/research-salvage",
        "upstream_behind": 0,
        "upstream_ahead": 0,
        "dirty_paths": [],
        "staged_paths": [],
        "operations": [],
        "stash_count": 0,
        "hooks_path": ".githooks",
    }
    values.update(overrides)
    return HygieneState(**values)


def _evaluate(state, *, pre_commit=False, **overrides):
    options = {
        "allow_dirty": False,
        "allow_diverged": False,
        "allow_protected": False,
        "allow_large_commit": False,
        "max_staged_files": 20,
    }
    options.update(overrides)
    return evaluate_state(state, pre_commit=pre_commit, **options)


def test_start_check_rejects_dirty_or_stale_branch():
    result = _evaluate(
        _state(
            base_behind=2,
            dirty_paths=["models/linear_panel.pkl"],
        )
    )

    assert not result.ok
    assert any("behind origin/main" in error for error in result.errors)
    assert any("Worktree is dirty" in error for error in result.errors)


def test_pre_commit_rejects_local_and_model_artifacts_on_research_branch():
    result = _evaluate(
        _state(
            staged_paths=[
                "logs/run_daily_status.json",
                "models/linear_panel.pkl",
            ]
        ),
        pre_commit=True,
    )

    assert not result.ok
    assert any("Local/generated artifacts" in error for error in result.errors)
    assert any("Model artifacts may only" in error for error in result.errors)


def test_model_refresh_branch_can_commit_model_artifacts():
    result = _evaluate(
        _state(
            branch="model-refresh/daily-20260605",
            staged_paths=["models/linear_panel.pkl"],
        ),
        pre_commit=True,
    )

    assert result.ok
    assert model_branch_allowed("model-refresh/daily-20260605")


def test_pre_commit_blocks_protected_and_oversized_commit():
    result = _evaluate(
        _state(
            branch="main",
            staged_paths=[f"file_{index}.py" for index in range(21)],
        ),
        pre_commit=True,
    )

    assert not result.ok
    assert any("protected branch" in error for error in result.errors)
    assert any("21 files are staged" in error for error in result.errors)


def test_status_parser_and_local_artifact_rules():
    assert parse_status_paths(" M app.py\n?? logs/run_daily_status.json\n") == [
        "app.py",
        "logs/run_daily_status.json",
    ]
    assert is_local_artifact("notes/pc_health_check_2026-06-04.md")
    assert not is_local_artifact("notes/growth24_current_control_overlay_gate.md")
