"""Tests for runbook/executor.py."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from runbook.executor import CommandExited, CommandOutput, CommandStarted, run_step
from runbook.models import Step


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _step(command: str = "echo hi") -> Step:
    return Step(id="test-step", title="Test", level=2, command=command)


async def _collect(step: Step, command: str, cwd: Path) -> list:
    return [e async for e in run_step(step, command, cwd)]


def run(step: Step, command: str, cwd: Path) -> list:
    return asyncio.run(_collect(step, command, cwd))


# ---------------------------------------------------------------------------
# Event structure invariants
# ---------------------------------------------------------------------------

def test_first_event_is_started(tmp_path):
    events = run(_step(), "echo hi", tmp_path)
    assert isinstance(events[0], CommandStarted)
    assert events[0].step_id == "test-step"


def test_last_event_is_exited(tmp_path):
    events = run(_step(), "echo hi", tmp_path)
    assert isinstance(events[-1], CommandExited)
    assert events[-1].step_id == "test-step"


def test_output_events_between_start_and_exit(tmp_path):
    events = run(_step(), "echo hi", tmp_path)
    interior = events[1:-1]
    assert all(isinstance(e, CommandOutput) for e in interior)


# ---------------------------------------------------------------------------
# Success
# ---------------------------------------------------------------------------

def test_success_exit_code_zero(tmp_path):
    events = run(_step(), "echo hello", tmp_path)
    exited = events[-1]
    assert exited.exit_code == 0


def test_success_stdout_text(tmp_path):
    events = run(_step(), "echo hello", tmp_path)
    texts = [e.text for e in events if isinstance(e, CommandOutput)]
    assert any("hello" in t for t in texts)


def test_success_stdout_stream_label(tmp_path):
    events = run(_step(), "echo hello", tmp_path)
    out_events = [e for e in events if isinstance(e, CommandOutput)]
    assert all(e.stream in ("stdout", "stderr") for e in out_events)


# ---------------------------------------------------------------------------
# Failure
# ---------------------------------------------------------------------------

def test_failure_exit_code_nonzero(tmp_path):
    events = run(_step(), "exit 1", tmp_path)
    assert events[-1].exit_code == 1


def test_failure_specific_code(tmp_path):
    events = run(_step(), "exit 42", tmp_path)
    assert events[-1].exit_code == 42


def test_false_command_exits_one(tmp_path):
    events = run(_step(), "false", tmp_path)
    assert events[-1].exit_code == 1


# ---------------------------------------------------------------------------
# stdout vs stderr
# ---------------------------------------------------------------------------

def test_stdout_captured(tmp_path):
    events = run(_step(), "echo to-stdout", tmp_path)
    stdout_texts = [e.text for e in events if isinstance(e, CommandOutput) and e.stream == "stdout"]
    assert any("to-stdout" in t for t in stdout_texts)


def test_stderr_captured(tmp_path):
    events = run(_step(), "echo to-stderr >&2", tmp_path)
    stderr_texts = [e.text for e in events if isinstance(e, CommandOutput) and e.stream == "stderr"]
    assert any("to-stderr" in t for t in stderr_texts)


def test_both_streams_captured(tmp_path):
    events = run(_step(), "echo out; echo err >&2", tmp_path)
    streams = {e.stream for e in events if isinstance(e, CommandOutput)}
    assert streams == {"stdout", "stderr"}


def test_stderr_does_not_appear_in_stdout(tmp_path):
    events = run(_step(), "echo err-only >&2", tmp_path)
    stdout_texts = [e.text for e in events if isinstance(e, CommandOutput) and e.stream == "stdout"]
    assert not any("err-only" in t for t in stdout_texts)


# ---------------------------------------------------------------------------
# Multiline command
# ---------------------------------------------------------------------------

MULTILINE = """\
echo line1
echo line2
echo line3
"""


def test_multiline_all_lines_emitted(tmp_path):
    events = run(_step(), MULTILINE, tmp_path)
    texts = "".join(e.text for e in events if isinstance(e, CommandOutput))
    assert "line1" in texts
    assert "line2" in texts
    assert "line3" in texts


def test_multiline_success(tmp_path):
    events = run(_step(), MULTILINE, tmp_path)
    assert events[-1].exit_code == 0


MULTILINE_HEREDOC = """\
cat <<'EOF'
hello from heredoc
EOF
"""


def test_heredoc_output(tmp_path):
    events = run(_step(), MULTILINE_HEREDOC, tmp_path)
    texts = "".join(e.text for e in events if isinstance(e, CommandOutput))
    assert "hello from heredoc" in texts


# ---------------------------------------------------------------------------
# Working directory
# ---------------------------------------------------------------------------

def test_cwd_is_respected(tmp_path):
    sentinel = tmp_path / "marker.txt"
    sentinel.write_text("found")
    events = run(_step(), "cat marker.txt", tmp_path)
    texts = "".join(e.text for e in events if isinstance(e, CommandOutput))
    assert "found" in texts


def test_cwd_wrong_dir_fails(tmp_path):
    other = tmp_path / "sub"
    other.mkdir()
    sentinel = tmp_path / "marker.txt"
    sentinel.write_text("found")
    # Run from sub/ — marker.txt is not there
    events = run(_step(), "cat marker.txt", other)
    assert events[-1].exit_code != 0


# ---------------------------------------------------------------------------
# Temp file cleanup
# ---------------------------------------------------------------------------

def test_tmp_file_removed_on_success(tmp_path):
    import glob, os
    before = set(glob.glob("/tmp/tmp*.sh"))
    run(_step(), "echo hi", tmp_path)
    after = set(glob.glob("/tmp/tmp*.sh"))
    assert after == before


def test_tmp_file_removed_on_failure(tmp_path):
    import glob
    before = set(glob.glob("/tmp/tmp*.sh"))
    run(_step(), "exit 1", tmp_path)
    after = set(glob.glob("/tmp/tmp*.sh"))
    assert after == before


# ---------------------------------------------------------------------------
# step_id propagated to every event
# ---------------------------------------------------------------------------

def test_step_id_in_all_events(tmp_path):
    step = Step(id="my-unique-id", title="T", level=2, command="echo x")
    events = asyncio.run(_collect(step, "echo x", tmp_path))
    for e in events:
        assert e.step_id == "my-unique-id"
