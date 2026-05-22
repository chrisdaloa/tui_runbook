"""Execute step commands via a temporary bash script, streaming events."""

from __future__ import annotations

import asyncio
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator, Literal, Union

from runbook.models import Step


# ---------------------------------------------------------------------------
# Event types
# ---------------------------------------------------------------------------

@dataclass
class CommandStarted:
    step_id: str


@dataclass
class CommandOutput:
    step_id: str
    stream: Literal["stdout", "stderr"]
    text: str  # single line, newline included when present


@dataclass
class CommandExited:
    step_id: str
    exit_code: int


CommandEvent = Union[CommandStarted, CommandOutput, CommandExited]


# ---------------------------------------------------------------------------
# Internal: drain one stream into a shared queue
# ---------------------------------------------------------------------------

async def _drain(
    stream: asyncio.StreamReader,
    step_id: str,
    stream_name: Literal["stdout", "stderr"],
    queue: asyncio.Queue[CommandOutput | None],
) -> None:
    while True:
        line = await stream.readline()
        if not line:
            break
        await queue.put(CommandOutput(
            step_id=step_id,
            stream=stream_name,
            text=line.decode(errors="replace"),
        ))
    await queue.put(None)  # EOF sentinel


# ---------------------------------------------------------------------------
# Public async generator
# ---------------------------------------------------------------------------

async def run_step(
    step: Step,
    command: str,
    cwd: Path,
) -> AsyncIterator[CommandEvent]:
    """Run *command* as a bash script and yield events in real time.

    Events are yielded in arrival order from stdout/stderr; exit event is last.
    The temporary script file is removed on exit whether or not the command
    succeeds.
    """
    yield CommandStarted(step_id=step.id)

    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".sh", delete=False, encoding="utf-8"
        ) as fh:
            fh.write(command)
            tmp_path = Path(fh.name)

        proc = await asyncio.create_subprocess_exec(
            "bash", str(tmp_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        assert proc.stdout is not None and proc.stderr is not None

        queue: asyncio.Queue[CommandOutput | None] = asyncio.Queue()
        tasks = [
            asyncio.create_task(
                _drain(proc.stdout, step.id, "stdout", queue)
            ),
            asyncio.create_task(
                _drain(proc.stderr, step.id, "stderr", queue)
            ),
        ]

        # Yield output events until both streams signal EOF
        pending = len(tasks)
        while pending:
            event = await queue.get()
            if event is None:
                pending -= 1
            else:
                yield event

        await asyncio.gather(*tasks)
        await proc.wait()

        yield CommandExited(step_id=step.id, exit_code=proc.returncode)

    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
