"""Per-step execution log files written to .runbook/logs/."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import IO


def default_log_dir(markdown_path: Path) -> Path:
    """Return `.runbook/logs/` next to *markdown_path*."""
    return markdown_path.parent / ".runbook" / "logs"


def default_log_path(markdown_path: Path, step_id: str, started_at: datetime) -> Path:
    """Return a timestamped log path for one step execution.

    Example: ``.runbook/logs/deploy-app_20240601_120000.log``
    """
    ts = started_at.strftime("%Y%m%d_%H%M%S")
    return default_log_dir(markdown_path) / f"{step_id}_{ts}.log"


class StepLogger:
    """Write a single step execution to a plain-text log file.

    Usage::

        logger = StepLogger(path, step_id, title, command, started_at)
        try:
            for line, stream in output:
                logger.write_line(stream, line)
            logger.finalize(exit_code, ended_at)
        finally:
            logger.close()

    Log format::

        # step:    deploy-app
        # title:   Deploy application
        # command: make deploy
        # started: 2024-06-01T12:00:00+00:00
        #
        [stdout] Deploying…
        [stderr] Warning: slow connection
        #
        # exit_code: 0
        # ended:     2024-06-01T12:00:05+00:00
    """

    def __init__(
        self,
        path: Path,
        step_id: str,
        title: str,
        command: str,
        started_at: datetime,
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._fh: IO[str] = path.open("w", encoding="utf-8", buffering=1)
        self._finalized = False
        self._fh.write(f"# step:    {step_id}\n")
        self._fh.write(f"# title:   {title}\n")
        self._fh.write(f"# command: {command}\n")
        self._fh.write(f"# started: {started_at.isoformat()}\n")
        self._fh.write("#\n")

    def write_line(self, stream: str, text: str) -> None:
        """Write one chunk of output, prefixed with the stream name."""
        line = text if text.endswith("\n") else text + "\n"
        self._fh.write(f"[{stream}] {line}")

    def finalize(self, exit_code: int, ended_at: datetime) -> None:
        """Write the closing footer with exit code and end timestamp."""
        self._fh.write("#\n")
        self._fh.write(f"# exit_code: {exit_code}\n")
        self._fh.write(f"# ended:     {ended_at.isoformat()}\n")
        self._finalized = True

    def close(self) -> None:
        """Flush and close the log file.

        If *finalize* was never called (e.g. the process was interrupted),
        write a brief note so the file is not silently truncated.
        """
        if not self._fh.closed:
            if not self._finalized:
                self._fh.write("#\n# (execution interrupted — no exit code)\n")
            self._fh.close()
