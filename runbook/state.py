"""State persistence: save/load RunState as JSON, and session helpers."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from runbook.models import Runbook, RunState, StepState, StepStatus


# ---------------------------------------------------------------------------
# Public exception
# ---------------------------------------------------------------------------

class RunbookChangedError(Exception):
    """Raised when a saved state's content_hash doesn't match the live runbook."""


# ---------------------------------------------------------------------------
# Path convention
# ---------------------------------------------------------------------------

def default_state_path(markdown_path: Path) -> Path:
    """Return `.runbook/<stem>.state.json` next to *markdown_path*."""
    return markdown_path.parent / ".runbook" / f"{markdown_path.stem}.state.json"


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------

def _serialize(state: RunState) -> dict[str, Any]:
    return {
        "runbook_path": str(state.runbook_path),
        "content_hash": state.content_hash,
        "variables": state.variables,
        "steps": {
            step_id: {
                "status": ss.status.value,
                "exit_code": ss.exit_code,
                "started_at": ss.started_at.isoformat() if ss.started_at else None,
                "ended_at": ss.ended_at.isoformat() if ss.ended_at else None,
                "command_rendered": ss.command_rendered,
                "rollback_exit_code": ss.rollback_exit_code,
                "rollback_ran_at": ss.rollback_ran_at.isoformat() if ss.rollback_ran_at else None,
                "log_path": ss.log_path,
            }
            for step_id, ss in state.steps.items()
        },
    }


def _deserialize(data: dict[str, Any]) -> RunState:
    steps: dict[str, StepState] = {}
    for step_id, raw in data["steps"].items():
        steps[step_id] = StepState(
            status=StepStatus(raw["status"]),
            exit_code=raw.get("exit_code"),
            started_at=datetime.fromisoformat(raw["started_at"]) if raw.get("started_at") else None,
            ended_at=datetime.fromisoformat(raw["ended_at"]) if raw.get("ended_at") else None,
            command_rendered=raw.get("command_rendered"),
            rollback_exit_code=raw.get("rollback_exit_code"),
            rollback_ran_at=datetime.fromisoformat(raw["rollback_ran_at"]) if raw.get("rollback_ran_at") else None,
            log_path=raw.get("log_path"),
        )
    return RunState(
        runbook_path=Path(data["runbook_path"]),
        content_hash=data["content_hash"],
        variables=data.get("variables", {}),
        steps=steps,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_state(path: Path) -> RunState | None:
    """Return the persisted RunState at *path*, or None if the file doesn't exist.

    Raises ValueError if the file exists but cannot be parsed.
    """
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return _deserialize(data)
    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        raise ValueError(f"Corrupted state file {path}: {exc}") from exc


def save_state(state: RunState, path: Path) -> None:
    """Serialise *state* to *path*, creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_serialize(state), indent=2), encoding="utf-8")


def create_or_resume_state(
    runbook: Runbook,
    state_path: Path | None = None,
) -> RunState:
    """Load existing state or create a fresh one.

    Raises RunbookChangedError if a saved state exists but its content_hash
    no longer matches *runbook* — the caller must decide whether to reset.
    """
    if state_path is None:
        state_path = default_state_path(runbook.path)

    existing = load_state(state_path)
    if existing is None:
        return RunState.from_runbook(runbook)

    if existing.content_hash != runbook.content_hash:
        raise RunbookChangedError(
            f"{runbook.path.name} has changed since the last run "
            f"(saved hash {existing.content_hash[:8]}…, current {runbook.content_hash[:8]}…)."
        )

    return existing


# ---------------------------------------------------------------------------
# Session helpers (stateless, operate on RunState values)
# ---------------------------------------------------------------------------

def current_step_state(runbook: Runbook, state: RunState) -> tuple[str, StepState] | None:
    """Return (step_id, StepState) for the first PENDING step, or None."""
    for step in runbook.steps:
        ss = state.steps.get(step.id)
        if ss and ss.status == StepStatus.PENDING:
            return step.id, ss
    return None


def is_complete(state: RunState) -> bool:
    return all(
        ss.status in (StepStatus.DONE, StepStatus.SKIPPED)
        for ss in state.steps.values()
    )


def resume_summary(state: RunState) -> str | None:
    """Return a one-line resume banner, or None when the state is entirely fresh."""
    if not state.steps:
        return None
    counts: dict[StepStatus, int] = {s: 0 for s in StepStatus}
    for ss in state.steps.values():
        counts[ss.status] += 1
    if counts[StepStatus.PENDING] == len(state.steps):
        return None  # nothing done yet — treat as fresh
    total = len(state.steps)
    parts: list[str] = []
    if counts[StepStatus.DONE]:
        parts.append(f"{counts[StepStatus.DONE]} done")
    if counts[StepStatus.FAILED]:
        parts.append(f"{counts[StepStatus.FAILED]} failed")
    if counts[StepStatus.SKIPPED]:
        parts.append(f"{counts[StepStatus.SKIPPED]} skipped")
    if counts[StepStatus.RUNNING]:
        # A RUNNING step survived a crash — show it as pending on resume.
        parts.append(f"{counts[StepStatus.RUNNING]} interrupted")
    return f"Resuming: {', '.join(parts)} of {total} steps"


# ---------------------------------------------------------------------------
# Step-run decision helpers
# ---------------------------------------------------------------------------

class StepRunDecision:
    """Possible outcomes of asking «can the user run this step?»."""
    BLOCKED = "blocked"   # step is currently running — hard block
    NORMAL  = "normal"    # pending or skipped — standard confirm
    RETRY   = "retry"     # previously failed — allow retry, normal confirm
    RERUN   = "rerun"     # already done — requires stronger confirm


def step_run_decision(status: StepStatus) -> str:
    """Return the StepRunDecision constant appropriate for *status*."""
    if status == StepStatus.RUNNING:
        return StepRunDecision.BLOCKED
    if status == StepStatus.DONE:
        return StepRunDecision.RERUN
    if status == StepStatus.FAILED:
        return StepRunDecision.RETRY
    return StepRunDecision.NORMAL  # PENDING or SKIPPED
