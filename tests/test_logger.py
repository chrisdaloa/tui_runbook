"""Tests for runbook/logger.py — file creation, header, output lines, finalize."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from runbook.logger import StepLogger, default_log_dir, default_log_path


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def test_default_log_dir(tmp_path):
    md = tmp_path / "deploy.md"
    assert default_log_dir(md) == tmp_path / ".runbook" / "logs"


def test_default_log_path_format(tmp_path):
    md = tmp_path / "deploy.md"
    started_at = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    p = default_log_path(md, "deploy-app", started_at)
    assert p == tmp_path / ".runbook" / "logs" / "deploy-app_20240601_120000.log"


def test_default_log_path_stem_is_step_id(tmp_path):
    md = tmp_path / "x.md"
    started_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    p = default_log_path(md, "my-step", started_at)
    assert p.stem.startswith("my-step")


# ---------------------------------------------------------------------------
# StepLogger — file creation and header
# ---------------------------------------------------------------------------

def _make_logger(tmp_path: Path, **kwargs) -> StepLogger:
    defaults = dict(
        path=tmp_path / ".runbook" / "logs" / "step_20240601_120000.log",
        step_id="step-1",
        title="My Step",
        command="echo hello",
        started_at=datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
    )
    defaults.update(kwargs)
    return StepLogger(**defaults)


def test_logger_creates_file(tmp_path):
    logger = _make_logger(tmp_path)
    logger.close()
    assert logger.path.exists()


def test_logger_creates_parent_dirs(tmp_path):
    path = tmp_path / "deep" / "nested" / "logs" / "step.log"
    logger = StepLogger(path, "s", "S", "cmd", datetime.now(timezone.utc))
    logger.close()
    assert path.exists()


def test_logger_header_step_id(tmp_path):
    logger = _make_logger(tmp_path, step_id="deploy-app")
    logger.close()
    content = logger.path.read_text()
    assert "# step:    deploy-app" in content


def test_logger_header_title(tmp_path):
    logger = _make_logger(tmp_path, title="Deploy application")
    logger.close()
    content = logger.path.read_text()
    assert "# title:   Deploy application" in content


def test_logger_header_command(tmp_path):
    logger = _make_logger(tmp_path, command="make deploy")
    logger.close()
    content = logger.path.read_text()
    assert "# command: make deploy" in content


def test_logger_header_started_at(tmp_path):
    started_at = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    logger = _make_logger(tmp_path, started_at=started_at)
    logger.close()
    content = logger.path.read_text()
    assert "# started: 2024-06-01T12:00:00+00:00" in content


def test_logger_header_ends_with_separator(tmp_path):
    logger = _make_logger(tmp_path)
    logger.close()
    lines = logger.path.read_text().splitlines()
    assert lines[4] == "#"


# ---------------------------------------------------------------------------
# StepLogger — write_line
# ---------------------------------------------------------------------------

def test_write_line_stdout_prefix(tmp_path):
    logger = _make_logger(tmp_path)
    logger.write_line("stdout", "hello world\n")
    logger.close()
    assert "[stdout] hello world\n" in logger.path.read_text()


def test_write_line_stderr_prefix(tmp_path):
    logger = _make_logger(tmp_path)
    logger.write_line("stderr", "error msg\n")
    logger.close()
    assert "[stderr] error msg\n" in logger.path.read_text()


def test_write_line_adds_newline_if_missing(tmp_path):
    logger = _make_logger(tmp_path)
    logger.write_line("stdout", "no newline")
    logger.close()
    content = logger.path.read_text()
    assert "[stdout] no newline\n" in content


def test_write_line_does_not_double_newline(tmp_path):
    logger = _make_logger(tmp_path)
    logger.write_line("stdout", "line\n")
    logger.close()
    content = logger.path.read_text()
    assert "[stdout] line\n\n" not in content


def test_write_multiple_lines(tmp_path):
    logger = _make_logger(tmp_path)
    logger.write_line("stdout", "line1\n")
    logger.write_line("stderr", "err\n")
    logger.write_line("stdout", "line2\n")
    logger.close()
    content = logger.path.read_text()
    assert "[stdout] line1\n" in content
    assert "[stderr] err\n" in content
    assert "[stdout] line2\n" in content


# ---------------------------------------------------------------------------
# StepLogger — finalize
# ---------------------------------------------------------------------------

def test_finalize_writes_exit_code(tmp_path):
    logger = _make_logger(tmp_path)
    ended_at = datetime(2024, 6, 1, 12, 0, 5, tzinfo=timezone.utc)
    logger.finalize(0, ended_at)
    logger.close()
    content = logger.path.read_text()
    assert "# exit_code: 0" in content


def test_finalize_writes_nonzero_exit_code(tmp_path):
    logger = _make_logger(tmp_path)
    logger.finalize(1, datetime.now(timezone.utc))
    logger.close()
    assert "# exit_code: 1" in logger.path.read_text()


def test_finalize_writes_ended_at(tmp_path):
    logger = _make_logger(tmp_path)
    ended_at = datetime(2024, 6, 1, 12, 0, 5, tzinfo=timezone.utc)
    logger.finalize(0, ended_at)
    logger.close()
    assert "# ended:     2024-06-01T12:00:05+00:00" in logger.path.read_text()


def test_finalize_writes_separator_before_footer(tmp_path):
    logger = _make_logger(tmp_path)
    logger.finalize(0, datetime.now(timezone.utc))
    logger.close()
    content = logger.path.read_text()
    footer_start = content.index("# exit_code:")
    # The separator line "#\n" appears immediately before "# exit_code:"
    assert content[footer_start - 2:footer_start] == "#\n"


# ---------------------------------------------------------------------------
# StepLogger — close without finalize (interrupted)
# ---------------------------------------------------------------------------

def test_close_without_finalize_writes_interrupted_note(tmp_path):
    logger = _make_logger(tmp_path)
    logger.close()
    content = logger.path.read_text()
    assert "interrupted" in content
    assert "no exit code" in content


def test_close_after_finalize_does_not_write_interrupted(tmp_path):
    logger = _make_logger(tmp_path)
    logger.finalize(0, datetime.now(timezone.utc))
    logger.close()
    assert "interrupted" not in logger.path.read_text()


def test_close_is_idempotent(tmp_path):
    logger = _make_logger(tmp_path)
    logger.close()
    logger.close()  # should not raise
    assert logger.path.exists()
