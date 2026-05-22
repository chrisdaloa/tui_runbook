"""Tests for runbook/cli.py — covers argument validation and setup pipeline."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from runbook.cli import main


def test_missing_arg(capsys):
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 1
    assert "Usage:" in capsys.readouterr().err


def test_missing_file(capsys, tmp_path):
    with pytest.raises(SystemExit) as exc:
        main([str(tmp_path / "nonexistent.md")])
    assert exc.value.code == 1
    assert "not found" in capsys.readouterr().err


def test_not_a_file(capsys, tmp_path):
    with pytest.raises(SystemExit) as exc:
        main([str(tmp_path)])          # directory, not a file
    assert exc.value.code == 1


def _write_md(tmp_path: Path, source: str = "") -> Path:
    default = "# Test\n\n## Step 1\n\n```bash\necho hi\n```\n"
    f = tmp_path / "sample.md"
    f.write_text(source or default)
    return f


def _run_mocked(args: list[str]) -> MagicMock:
    """Run main() with RunbookApp.run mocked; return the mock."""
    with patch("runbook.app.RunbookApp.run") as mock_run:
        main(args)
    return mock_run


def test_valid_file_launches_tui(tmp_path):
    f = _write_md(tmp_path)
    mock_run = _run_mocked([str(f)])
    mock_run.assert_called_once()


def test_state_file_created_before_tui(tmp_path):
    f = _write_md(tmp_path)
    with patch("runbook.app.RunbookApp.run"):
        main([str(f)])
    state_file = tmp_path / ".runbook" / "sample.state.json"
    assert state_file.exists()


def test_runbook_with_no_steps_launches_tui(tmp_path):
    f = _write_md(tmp_path, "# Minimal\n\nNo steps here.\n")
    mock_run = _run_mocked([str(f)])
    mock_run.assert_called_once()


def test_hash_mismatch_aborts_on_no(tmp_path, capsys):
    """If the runbook changed and user says no, exit(1)."""
    f = _write_md(tmp_path)

    # First run: create state file
    with patch("runbook.app.RunbookApp.run"):
        main([str(f)])

    # Modify the runbook so the hash changes
    f.write_text(f.read_text() + "\n## Extra step\n\n```bash\necho extra\n```\n")

    with patch("builtins.input", return_value="n"):
        with pytest.raises(SystemExit) as exc:
            main([str(f)])
    assert exc.value.code == 1


def test_hash_mismatch_resets_on_yes(tmp_path):
    """If the runbook changed and user says yes, reset and launch TUI."""
    f = _write_md(tmp_path)

    with patch("runbook.app.RunbookApp.run"):
        main([str(f)])

    f.write_text(f.read_text() + "\n## Extra\n\n```bash\necho extra\n```\n")

    with patch("builtins.input", return_value="y"):
        with patch("runbook.app.RunbookApp.run") as mock_run:
            main([str(f)])
    mock_run.assert_called_once()


def test_resume_banner_shown_when_progress_exists(tmp_path, capsys):
    """After partial execution, the resume summary is printed on next launch."""
    f = _write_md(tmp_path)

    # First run: create state, mark step as done manually
    with patch("runbook.app.RunbookApp.run"):
        main([str(f)])

    from runbook.state import default_state_path, load_state, save_state
    from runbook.models import StepStatus
    sp = default_state_path(f)
    state = load_state(sp)
    state.steps[list(state.steps)[0]].status = StepStatus.DONE
    save_state(state, sp)

    capsys.readouterr()  # discard first-run output

    with patch("runbook.app.RunbookApp.run"):
        main([str(f)])

    out = capsys.readouterr().out
    assert "Resuming:" in out


def test_no_resume_banner_on_fresh_state(tmp_path, capsys):
    """On first run (no prior state), the resume banner must not appear."""
    f = _write_md(tmp_path)
    with patch("runbook.app.RunbookApp.run"):
        main([str(f)])
    out = capsys.readouterr().out
    assert "Resuming:" not in out


# ---------------------------------------------------------------------------
# Startup banner
# ---------------------------------------------------------------------------

def test_startup_banner_contains_filename(tmp_path, capsys):
    f = _write_md(tmp_path)
    _run_mocked([str(f)])
    out = capsys.readouterr().out
    assert "sample.md" in out


def test_startup_banner_contains_step_count(tmp_path, capsys):
    f = _write_md(tmp_path)
    _run_mocked([str(f)])
    out = capsys.readouterr().out
    assert "1 step" in out


def test_startup_banner_plural_steps(tmp_path, capsys):
    source = (
        "## A\n\n```bash\necho a\n```\n\n"
        "## B\n\n```bash\necho b\n```\n"
    )
    f = _write_md(tmp_path, source)
    _run_mocked([str(f)])
    out = capsys.readouterr().out
    assert "2 steps" in out


# ---------------------------------------------------------------------------
# --reset flag
# ---------------------------------------------------------------------------

def test_reset_flag_skips_interactive_prompt(tmp_path):
    """--reset must not trigger the y/N prompt even when hash changed."""
    f = _write_md(tmp_path)

    with patch("runbook.app.RunbookApp.run"):
        main([str(f)])

    # Modify the runbook so the hash changes
    f.write_text(f.read_text() + "\n## Extra\n\n```bash\necho extra\n```\n")

    # With --reset there should be no input() call; if there were, it would
    # block the test (or raise RuntimeError) because we haven't mocked it.
    with patch("runbook.app.RunbookApp.run") as mock_run:
        main(["--reset", str(f)])
    mock_run.assert_called_once()


def test_reset_flag_clears_prior_state(tmp_path):
    """After --reset, all steps are PENDING even if prior state had DONE steps."""
    f = _write_md(tmp_path)

    with patch("runbook.app.RunbookApp.run"):
        main([str(f)])

    from runbook.models import StepStatus
    from runbook.state import default_state_path, load_state, save_state

    sp = default_state_path(f)
    state = load_state(sp)
    state.steps[list(state.steps)[0]].status = StepStatus.DONE
    save_state(state, sp)

    with patch("runbook.app.RunbookApp.run"):
        main(["--reset", str(f)])

    reloaded = load_state(sp)
    assert all(ss.status == StepStatus.PENDING for ss in reloaded.steps.values())


# ---------------------------------------------------------------------------
# Restored variables hint
# ---------------------------------------------------------------------------

def test_restored_variables_shown_on_resume(tmp_path, capsys):
    """Variables saved from a previous run are shown before the TUI launches."""
    source = "## S\n\n```bash\necho ${NAME}\n```\n"
    f = _write_md(tmp_path, source)

    from runbook.state import default_state_path, load_state, save_state

    with patch("runbook.app.RunbookApp.run"):
        with patch("builtins.input", return_value="alice"):
            main([str(f)])

    capsys.readouterr()  # discard first-run output

    with patch("runbook.app.RunbookApp.run"):
        main([str(f)])

    out = capsys.readouterr().out
    assert "restored" in out.lower()
    assert "NAME" in out
