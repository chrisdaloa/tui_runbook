"""Tests for pure / non-UI logic extracted from runbook/app.py."""

from datetime import datetime, timezone
from pathlib import Path

from runbook.app import _annotation
from runbook.models import Step, StepState, StepStatus


def _step(*, manual: bool = False, rollback: str | None = None) -> Step:
    return Step(id="s", title="S", level=2, command="echo hi", manual=manual, rollback=rollback)


def _ss(**kwargs) -> StepState:
    return StepState(**kwargs)


# ---------------------------------------------------------------------------
# _annotation — no annotations
# ---------------------------------------------------------------------------

def test_annotation_plain_step_is_empty():
    assert _annotation(_step(), _ss()) == ""


def test_annotation_command_only_no_manual_flag():
    s = _step(manual=False)
    assert "M" not in _annotation(s, _ss())


# ---------------------------------------------------------------------------
# _annotation — manual flag
# ---------------------------------------------------------------------------

def test_annotation_manual_contains_M():
    assert "M" in _annotation(_step(manual=True), _ss())


def test_annotation_manual_without_rollback_no_arrow():
    result = _annotation(_step(manual=True), _ss())
    assert "↩" not in result


# ---------------------------------------------------------------------------
# _annotation — rollback indicator
# ---------------------------------------------------------------------------

def test_annotation_rollback_not_run_contains_arrow():
    s = _step(rollback="make rollback")
    result = _annotation(s, _ss())
    assert "↩" in result


def test_annotation_rollback_not_run_is_cyan():
    s = _step(rollback="make rollback")
    result = _annotation(s, _ss())
    assert "cyan" in result


def test_annotation_rollback_succeeded_is_green():
    s = _step(rollback="make rollback")
    ss = _ss(rollback_exit_code=0, rollback_ran_at=datetime.now(timezone.utc))
    result = _annotation(s, ss)
    assert "green" in result
    assert "↩" in result


def test_annotation_rollback_failed_is_red():
    s = _step(rollback="make rollback")
    ss = _ss(rollback_exit_code=1, rollback_ran_at=datetime.now(timezone.utc))
    result = _annotation(s, ss)
    assert "red" in result
    assert "↩" in result


def test_annotation_manual_and_rollback_both_present():
    s = _step(manual=True, rollback="make rollback")
    result = _annotation(s, _ss())
    assert "M" in result
    assert "↩" in result


# ---------------------------------------------------------------------------
# _annotation — rollback_ran_at=None means not yet run (cyan), even if
# rollback_exit_code has a stale value (shouldn't happen, but guard it)
# ---------------------------------------------------------------------------

def test_annotation_rollback_ran_at_none_is_cyan_regardless_of_code():
    s = _step(rollback="cmd")
    # rollback_exit_code set but rollback_ran_at absent → treat as not run
    ss = _ss(rollback_exit_code=0, rollback_ran_at=None)
    result = _annotation(s, ss)
    assert "cyan" in result
