from pathlib import Path
from runbook.models import Runbook, RunState, Step, StepState, StepStatus


def _make_runbook(n: int = 3) -> Runbook:
    steps = [
        Step(id=f"step-{i}", title=f"Step {i}", level=2, command=f"echo {i}")
        for i in range(n)
    ]
    return Runbook(path=Path("rb.md"), content_hash="abc123", steps=steps)


# --- StepState defaults ---

def test_step_state_default_pending():
    ss = StepState()
    assert ss.status == StepStatus.PENDING
    assert ss.exit_code is None
    assert ss.started_at is None
    assert ss.ended_at is None
    assert ss.command_rendered is None


# --- RunState.from_runbook ---

def test_run_state_initialises_all_steps():
    rb = _make_runbook(3)
    state = RunState.from_runbook(rb)
    assert set(state.steps.keys()) == {"step-0", "step-1", "step-2"}


def test_run_state_all_pending():
    rb = _make_runbook(3)
    state = RunState.from_runbook(rb)
    assert all(ss.status == StepStatus.PENDING for ss in state.steps.values())


def test_run_state_stores_path_and_hash():
    rb = _make_runbook()
    state = RunState.from_runbook(rb)
    assert state.runbook_path == rb.path
    assert state.content_hash == rb.content_hash


def test_run_state_empty_variables():
    rb = _make_runbook()
    state = RunState.from_runbook(rb)
    assert state.variables == {}


# --- reset_steps ---

def test_reset_steps_clears_progress():
    rb = _make_runbook(2)
    state = RunState.from_runbook(rb)
    state.steps["step-0"].status = StepStatus.DONE
    state.steps["step-0"].exit_code = 0

    state.reset_steps(rb)

    assert state.steps["step-0"].status == StepStatus.PENDING
    assert state.steps["step-0"].exit_code is None


def test_reset_steps_restores_missing_step():
    rb = _make_runbook(2)
    state = RunState.from_runbook(rb)
    del state.steps["step-1"]

    state.reset_steps(rb)
    assert "step-1" in state.steps


# --- is_stale ---

def test_is_stale_false_when_hash_matches():
    rb = _make_runbook()
    state = RunState.from_runbook(rb)
    assert state.is_stale(rb) is False


def test_is_stale_true_when_hash_differs():
    rb = _make_runbook()
    state = RunState.from_runbook(rb)
    rb2 = Runbook(path=rb.path, content_hash="different", steps=rb.steps)
    assert state.is_stale(rb2) is True


# --- Step fields ---

def test_step_manual_default_false():
    s = Step(id="x", title="X", level=2, command="ls")
    assert s.manual is False


def test_step_rollback_default_none():
    s = Step(id="x", title="X", level=2, command="ls")
    assert s.rollback is None


# --- StepState rollback fields ---

def test_step_state_rollback_defaults_none():
    ss = StepState()
    assert ss.rollback_exit_code is None
    assert ss.rollback_ran_at is None


def test_step_state_rollback_fields_set():
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    ss = StepState(rollback_exit_code=0, rollback_ran_at=now)
    assert ss.rollback_exit_code == 0
    assert ss.rollback_ran_at == now


def test_step_state_rollback_failed_exit_code():
    ss = StepState(rollback_exit_code=1)
    assert ss.rollback_exit_code == 1
