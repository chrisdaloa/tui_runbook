"""Tests for state persistence: save/load roundtrip, missing file, hash mismatch."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from runbook.models import Runbook, RunState, Step, StepState, StepStatus
from runbook.state import (
    RunbookChangedError,
    StepRunDecision,
    create_or_resume_state,
    default_state_path,
    load_state,
    resume_summary,
    save_state,
    step_run_decision,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_runbook(tmp_path: Path, content_hash: str = "aabbcc") -> Runbook:
    md = tmp_path / "deploy.md"
    md.write_text("# Deploy\n\n## Step\n\n```bash\necho hi\n```\n")
    steps = [
        Step(id="step-0", title="Step 0", level=2, command="echo 0"),
        Step(id="step-1", title="Step 1", level=2, command="echo 1"),
    ]
    return Runbook(path=md, content_hash=content_hash, steps=steps)


# ---------------------------------------------------------------------------
# default_state_path
# ---------------------------------------------------------------------------

def test_default_state_path_location(tmp_path):
    md = tmp_path / "deploy.md"
    p = default_state_path(md)
    assert p == tmp_path / ".runbook" / "deploy.state.json"


def test_default_state_path_stem(tmp_path):
    md = tmp_path / "my-runbook.md"
    p = default_state_path(md)
    assert p.name == "my-runbook.state.json"


# ---------------------------------------------------------------------------
# save_state / load_state roundtrip
# ---------------------------------------------------------------------------

def test_roundtrip_basic(tmp_path):
    rb = _make_runbook(tmp_path)
    state = RunState.from_runbook(rb)
    sp = default_state_path(rb.path)

    save_state(state, sp)
    loaded = load_state(sp)

    assert loaded is not None
    assert loaded.content_hash == state.content_hash
    assert loaded.runbook_path == state.runbook_path
    assert set(loaded.steps) == set(state.steps)


def test_roundtrip_all_statuses(tmp_path):
    rb = _make_runbook(tmp_path)
    state = RunState.from_runbook(rb)
    state.steps["step-0"].status = StepStatus.DONE
    state.steps["step-0"].exit_code = 0
    state.steps["step-1"].status = StepStatus.FAILED
    state.steps["step-1"].exit_code = 1

    sp = default_state_path(rb.path)
    save_state(state, sp)
    loaded = load_state(sp)

    assert loaded.steps["step-0"].status == StepStatus.DONE
    assert loaded.steps["step-0"].exit_code == 0
    assert loaded.steps["step-1"].status == StepStatus.FAILED
    assert loaded.steps["step-1"].exit_code == 1


def test_roundtrip_datetime(tmp_path):
    rb = _make_runbook(tmp_path)
    state = RunState.from_runbook(rb)
    now = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    state.steps["step-0"].started_at = now
    state.steps["step-0"].ended_at = now

    sp = default_state_path(rb.path)
    save_state(state, sp)
    loaded = load_state(sp)

    assert loaded.steps["step-0"].started_at == now
    assert loaded.steps["step-0"].ended_at == now


def test_roundtrip_command_rendered(tmp_path):
    rb = _make_runbook(tmp_path)
    state = RunState.from_runbook(rb)
    state.steps["step-0"].command_rendered = "echo hello-world"

    sp = default_state_path(rb.path)
    save_state(state, sp)
    loaded = load_state(sp)

    assert loaded.steps["step-0"].command_rendered == "echo hello-world"


def test_roundtrip_variables(tmp_path):
    rb = _make_runbook(tmp_path)
    state = RunState.from_runbook(rb)
    state.variables["ENV"] = "prod"
    state.variables["VERSION"] = "1.2.3"

    sp = default_state_path(rb.path)
    save_state(state, sp)
    loaded = load_state(sp)

    assert loaded.variables == {"ENV": "prod", "VERSION": "1.2.3"}


def test_roundtrip_null_datetimes_stay_none(tmp_path):
    rb = _make_runbook(tmp_path)
    state = RunState.from_runbook(rb)

    sp = default_state_path(rb.path)
    save_state(state, sp)
    loaded = load_state(sp)

    assert loaded.steps["step-0"].started_at is None
    assert loaded.steps["step-0"].ended_at is None


def test_roundtrip_rollback_fields(tmp_path):
    from datetime import datetime, timezone
    rb = _make_runbook(tmp_path)
    state = RunState.from_runbook(rb)
    now = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    state.steps["step-0"].rollback_exit_code = 0
    state.steps["step-0"].rollback_ran_at = now

    sp = default_state_path(rb.path)
    save_state(state, sp)
    loaded = load_state(sp)

    assert loaded.steps["step-0"].rollback_exit_code == 0
    assert loaded.steps["step-0"].rollback_ran_at == now


def test_roundtrip_rollback_null_fields_stay_none(tmp_path):
    rb = _make_runbook(tmp_path)
    state = RunState.from_runbook(rb)

    sp = default_state_path(rb.path)
    save_state(state, sp)
    loaded = load_state(sp)

    assert loaded.steps["step-0"].rollback_exit_code is None
    assert loaded.steps["step-0"].rollback_ran_at is None


def test_roundtrip_log_path(tmp_path):
    rb = _make_runbook(tmp_path)
    state = RunState.from_runbook(rb)
    state.steps["step-0"].log_path = "/tmp/.runbook/logs/step-0_20240601_120000.log"

    sp = default_state_path(rb.path)
    save_state(state, sp)
    loaded = load_state(sp)

    assert loaded.steps["step-0"].log_path == "/tmp/.runbook/logs/step-0_20240601_120000.log"


def test_roundtrip_log_path_none_stays_none(tmp_path):
    rb = _make_runbook(tmp_path)
    state = RunState.from_runbook(rb)

    sp = default_state_path(rb.path)
    save_state(state, sp)
    loaded = load_state(sp)

    assert loaded.steps["step-0"].log_path is None


def test_roundtrip_rollback_failed_exit_code(tmp_path):
    from datetime import datetime, timezone
    rb = _make_runbook(tmp_path)
    state = RunState.from_runbook(rb)
    state.steps["step-1"].rollback_exit_code = 127
    state.steps["step-1"].rollback_ran_at = datetime.now(timezone.utc)

    sp = default_state_path(rb.path)
    save_state(state, sp)
    loaded = load_state(sp)

    assert loaded.steps["step-1"].rollback_exit_code == 127


def test_save_creates_parent_dir(tmp_path):
    rb = _make_runbook(tmp_path)
    state = RunState.from_runbook(rb)
    sp = default_state_path(rb.path)

    assert not sp.parent.exists()
    save_state(state, sp)
    assert sp.parent.exists()
    assert sp.exists()


# ---------------------------------------------------------------------------
# load_state — missing file
# ---------------------------------------------------------------------------

def test_load_state_missing_returns_none(tmp_path):
    result = load_state(tmp_path / "no-such-file.json")
    assert result is None


def test_load_state_corrupted_raises(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("not json at all")
    with pytest.raises(ValueError, match="Corrupted"):
        load_state(bad)


# ---------------------------------------------------------------------------
# create_or_resume_state
# ---------------------------------------------------------------------------

def test_create_fresh_when_no_state_file(tmp_path):
    rb = _make_runbook(tmp_path)
    state = create_or_resume_state(rb)
    assert all(ss.status == StepStatus.PENDING for ss in state.steps.values())


def test_resume_existing_state(tmp_path):
    rb = _make_runbook(tmp_path)
    state = RunState.from_runbook(rb)
    state.steps["step-0"].status = StepStatus.DONE
    sp = default_state_path(rb.path)
    save_state(state, sp)

    resumed = create_or_resume_state(rb)
    assert resumed.steps["step-0"].status == StepStatus.DONE


def test_resume_uses_custom_state_path(tmp_path):
    rb = _make_runbook(tmp_path)
    custom_sp = tmp_path / "custom.json"
    state = RunState.from_runbook(rb)
    state.steps["step-0"].status = StepStatus.SKIPPED
    save_state(state, custom_sp)

    resumed = create_or_resume_state(rb, state_path=custom_sp)
    assert resumed.steps["step-0"].status == StepStatus.SKIPPED


# ---------------------------------------------------------------------------
# RunbookChangedError on hash mismatch
# ---------------------------------------------------------------------------

def test_hash_mismatch_raises(tmp_path):
    rb = _make_runbook(tmp_path, content_hash="original-hash")
    sp = default_state_path(rb.path)
    save_state(RunState.from_runbook(rb), sp)

    # Simulate the runbook file having changed
    rb_changed = Runbook(path=rb.path, content_hash="different-hash", steps=rb.steps)
    with pytest.raises(RunbookChangedError):
        create_or_resume_state(rb_changed)


def test_hash_mismatch_error_mentions_filename(tmp_path):
    rb = _make_runbook(tmp_path, content_hash="aaa")
    sp = default_state_path(rb.path)
    save_state(RunState.from_runbook(rb), sp)

    rb_changed = Runbook(path=rb.path, content_hash="bbb", steps=rb.steps)
    with pytest.raises(RunbookChangedError, match="deploy.md"):
        create_or_resume_state(rb_changed)


def test_same_hash_does_not_raise(tmp_path):
    rb = _make_runbook(tmp_path, content_hash="stable")
    sp = default_state_path(rb.path)
    save_state(RunState.from_runbook(rb), sp)

    resumed = create_or_resume_state(rb)  # same hash, no error
    assert resumed.content_hash == "stable"


# ---------------------------------------------------------------------------
# resume_summary
# ---------------------------------------------------------------------------

def test_resume_summary_fresh_state_is_none(tmp_path):
    rb = _make_runbook(tmp_path)
    state = RunState.from_runbook(rb)
    assert resume_summary(state) is None


def test_resume_summary_empty_steps_is_none():
    from pathlib import Path
    state = RunState(runbook_path=Path("x.md"), content_hash="x")
    assert resume_summary(state) is None


def test_resume_summary_with_done_steps(tmp_path):
    rb = _make_runbook(tmp_path)
    state = RunState.from_runbook(rb)
    state.steps["step-0"].status = StepStatus.DONE
    summary = resume_summary(state)
    assert summary is not None
    assert "1 done" in summary
    assert "2" in summary  # total


def test_resume_summary_with_failed_steps(tmp_path):
    rb = _make_runbook(tmp_path)
    state = RunState.from_runbook(rb)
    state.steps["step-0"].status = StepStatus.FAILED
    summary = resume_summary(state)
    assert summary is not None
    assert "1 failed" in summary


def test_resume_summary_with_skipped_steps(tmp_path):
    rb = _make_runbook(tmp_path)
    state = RunState.from_runbook(rb)
    state.steps["step-1"].status = StepStatus.SKIPPED
    summary = resume_summary(state)
    assert "1 skipped" in summary


def test_resume_summary_mixed(tmp_path):
    rb = _make_runbook(tmp_path)
    state = RunState.from_runbook(rb)
    state.steps["step-0"].status = StepStatus.DONE
    state.steps["step-1"].status = StepStatus.FAILED
    summary = resume_summary(state)
    assert "1 done" in summary
    assert "1 failed" in summary


def test_resume_summary_interrupted_running(tmp_path):
    rb = _make_runbook(tmp_path)
    state = RunState.from_runbook(rb)
    state.steps["step-0"].status = StepStatus.RUNNING
    summary = resume_summary(state)
    assert summary is not None
    assert "interrupted" in summary


def test_resume_summary_starts_with_resuming(tmp_path):
    rb = _make_runbook(tmp_path)
    state = RunState.from_runbook(rb)
    state.steps["step-0"].status = StepStatus.DONE
    assert resume_summary(state).startswith("Resuming:")


# ---------------------------------------------------------------------------
# step_run_decision
# ---------------------------------------------------------------------------

def test_decision_pending_is_normal():
    assert step_run_decision(StepStatus.PENDING) == StepRunDecision.NORMAL


def test_decision_skipped_is_normal():
    assert step_run_decision(StepStatus.SKIPPED) == StepRunDecision.NORMAL


def test_decision_failed_is_retry():
    assert step_run_decision(StepStatus.FAILED) == StepRunDecision.RETRY


def test_decision_done_is_rerun():
    assert step_run_decision(StepStatus.DONE) == StepRunDecision.RERUN


def test_decision_running_is_blocked():
    assert step_run_decision(StepStatus.RUNNING) == StepRunDecision.BLOCKED
