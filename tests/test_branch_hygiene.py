from scripts.check_branch_hygiene import (
    HygieneState,
    _operation_names,
    evaluate_state,
    is_growth24_scoped_path,
    is_local_artifact,
    model_branch_allowed,
    parse_status_paths,
)


def _state(**overrides):
    values = {
        "root": r"D:\fund_monitor_research",
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
    if "root" not in overrides and values["branch"] != "growth24/research-salvage":
        values["root"] = r"D:\task_worktree"
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


def test_worktree_contract_blocks_live_commits_and_wrong_research_branch():
    live_result = _evaluate(
        _state(
            root=r"D:\fund_monitor",
            branch="feature/unsafe-live-edit",
            staged_paths=["app.py"],
        ),
        pre_commit=True,
    )
    wrong_research_branch = _evaluate(
        _state(
            root=r"D:\fund_monitor_research",
            branch="feature/not-growth24",
        )
    )

    assert not live_result.ok
    assert any("must stay on main" in error for error in live_result.errors)
    assert any("Commits are disabled in live worktree" in error for error in live_result.errors)
    assert not wrong_research_branch.ok
    assert any("Research worktree must stay on" in error for error in wrong_research_branch.errors)


def test_growth24_scope_rejects_pipeline_paths_and_allows_research_paths():
    result = _evaluate(
        _state(
            staged_paths=[
                "dl_growth24_candidate_contract_eval.py",
                "notes/growth24_candidate_contract.md",
                "tests/test_growth24_candidate_contract_eval.py",
                "scripts/check_branch_hygiene.py",
                "run_daily.py",
                "models/linear_panel.pkl",
            ],
        ),
        pre_commit=True,
    )

    assert not result.ok
    assert is_growth24_scoped_path("dl_growth24_candidate_contract_eval.py")
    assert is_growth24_scoped_path("notes/growth24_candidate_contract.md")
    assert is_growth24_scoped_path("scripts/check_branch_hygiene.py")
    assert not is_growth24_scoped_path("run_daily.py")
    assert not is_growth24_scoped_path("models/linear_panel.pkl")
    assert any("run_daily.py" in error for error in result.errors)
    assert any("models/linear_panel.pkl" in error for error in result.errors)


def test_operation_detection_ignores_stale_rebase_head():
    calls = []

    def run_git(args, allow_failure):
        calls.append(args)
        return ""

    assert _operation_names(run_git, lambda name: False) == []
    assert not any("REBASE_HEAD" in args for args in calls)
    assert _operation_names(run_git, lambda name: name == "rebase-merge") == ["rebase"]
