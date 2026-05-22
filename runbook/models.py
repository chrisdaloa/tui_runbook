"""Domain models for a runbook and its steps."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class Step:
    id: str
    title: str
    level: int          # heading depth: 2 for ##, 3 for ###, …
    command: str        # empty string for manual steps
    manual: bool = False
    rollback: str | None = None


@dataclass
class Runbook:
    path: Path
    content_hash: str   # sha256 hex of raw source, used to detect drift
    steps: list[Step] = field(default_factory=list)


@dataclass
class StepState:
    status: StepStatus = StepStatus.PENDING
    exit_code: int | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    command_rendered: str | None = None    # command after variable substitution
    rollback_exit_code: int | None = None  # exit code of last rollback run
    rollback_ran_at: datetime | None = None
    log_path: str | None = None            # path to the most recent log file


@dataclass
class RunState:
    runbook_path: Path
    content_hash: str
    variables: dict[str, str] = field(default_factory=dict)
    steps: dict[str, StepState] = field(default_factory=dict)

    @classmethod
    def from_runbook(cls, runbook: Runbook) -> RunState:
        """Create a fresh RunState with all steps set to PENDING."""
        state = cls(runbook_path=runbook.path, content_hash=runbook.content_hash)
        state.steps = {step.id: StepState() for step in runbook.steps}
        return state

    def reset_steps(self, runbook: Runbook) -> None:
        """Re-initialise every step to PENDING, discarding prior results."""
        self.steps = {step.id: StepState() for step in runbook.steps}

    def is_stale(self, runbook: Runbook) -> bool:
        """True when the runbook on disk has changed since this state was created."""
        return self.content_hash != runbook.content_hash
