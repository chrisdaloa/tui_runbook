"""Tests for runbook/variables.py."""

from pathlib import Path

import pytest

from runbook.models import Runbook, Step
from runbook.variables import MissingVariableError, extract_variables, render_command


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _runbook(*commands: str) -> Runbook:
    steps = [
        Step(id=f"s{i}", title=f"S{i}", level=2, command=cmd)
        for i, cmd in enumerate(commands)
    ]
    return Runbook(path=Path("rb.md"), content_hash="x", steps=steps)


# ---------------------------------------------------------------------------
# extract_variables
# ---------------------------------------------------------------------------

def test_extract_simple():
    rb = _runbook("echo ${GREETING}")
    assert extract_variables(rb) == {"GREETING"}


def test_extract_multiple_in_one_command():
    rb = _runbook("deploy --env ${ENV} --version ${VERSION}")
    assert extract_variables(rb) == {"ENV", "VERSION"}


def test_extract_across_steps():
    rb = _runbook("echo ${FOO}", "echo ${BAR}")
    assert extract_variables(rb) == {"FOO", "BAR"}


def test_extract_deduplicates():
    rb = _runbook("echo ${HOST}", "ping ${HOST}")
    assert extract_variables(rb) == {"HOST"}


def test_extract_underscore_name():
    rb = _runbook("echo ${MY_VAR_1}")
    assert extract_variables(rb) == {"MY_VAR_1"}


def test_extract_empty_command():
    rb = _runbook("")
    assert extract_variables(rb) == set()


def test_extract_no_variables():
    rb = _runbook("echo hello")
    assert extract_variables(rb) == set()


# ---------------------------------------------------------------------------
# Advanced bash expansions are ignored (not extracted, not rendered)
# ---------------------------------------------------------------------------

def test_ignore_default_expansion():
    rb = _runbook("echo ${VAR:-fallback}")
    assert extract_variables(rb) == set()


def test_ignore_error_expansion():
    rb = _runbook("echo ${VAR?must be set}")
    assert extract_variables(rb) == set()


def test_ignore_replace_expansion():
    rb = _runbook("echo ${VAR/foo/bar}")
    assert extract_variables(rb) == set()


def test_ignore_prefix_expansion():
    rb = _runbook("echo ${VAR#prefix}")
    assert extract_variables(rb) == set()


def test_ignore_assign_expansion():
    rb = _runbook("echo ${VAR:=default}")
    assert extract_variables(rb) == set()


def test_advanced_expansion_left_verbatim_in_render():
    result = render_command("echo ${VAR:-fallback}", {})
    assert result == "echo ${VAR:-fallback}"


def test_simple_and_advanced_in_same_command():
    rb = _runbook("echo ${SIMPLE} ${COMPLEX:-x}")
    assert extract_variables(rb) == {"SIMPLE"}


# ---------------------------------------------------------------------------
# render_command — happy path
# ---------------------------------------------------------------------------

def test_render_single_variable():
    result = render_command("echo ${GREETING}", {"GREETING": "hello"})
    assert result == "echo hello"


def test_render_multiple_variables():
    result = render_command(
        "deploy --env ${ENV} --version ${VERSION}",
        {"ENV": "prod", "VERSION": "1.2.3"},
    )
    assert result == "deploy --env prod --version 1.2.3"


def test_render_same_variable_twice():
    result = render_command("${HOST}:${PORT} -> ${HOST}", {"HOST": "db", "PORT": "5432"})
    assert result == "db:5432 -> db"


def test_render_no_variables_unchanged():
    cmd = "ls -la /tmp"
    assert render_command(cmd, {}) == cmd


def test_render_extra_variables_ignored():
    result = render_command("echo ${A}", {"A": "1", "B": "2"})
    assert result == "echo 1"


# ---------------------------------------------------------------------------
# render_command — missing variable
# ---------------------------------------------------------------------------

def test_render_missing_raises():
    with pytest.raises(MissingVariableError):
        render_command("echo ${MISSING}", {})


def test_render_missing_error_contains_name():
    with pytest.raises(MissingVariableError) as exc_info:
        render_command("echo ${MY_VAR}", {})
    assert "MY_VAR" in str(exc_info.value)


def test_render_missing_error_contains_command():
    cmd = "deploy ${TARGET}"
    with pytest.raises(MissingVariableError) as exc_info:
        render_command(cmd, {})
    assert cmd in str(exc_info.value)


def test_render_missing_error_has_name_attribute():
    with pytest.raises(MissingVariableError) as exc_info:
        render_command("echo ${GONE}", {})
    assert exc_info.value.name == "GONE"


def test_render_partial_missing_raises():
    with pytest.raises(MissingVariableError):
        render_command("${A} ${B}", {"A": "ok"})
