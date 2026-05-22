"""Textual TUI — step list, output log, and interactive execution."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from rich.markup import escape
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Header, Label, RichLog

from runbook.executor import CommandExited, CommandOutput, CommandStarted, run_step
from runbook.logger import StepLogger, default_log_path
from runbook.models import Runbook, RunState, Step, StepState, StepStatus
from runbook.state import StepRunDecision, save_state, step_run_decision
from runbook.variables import MissingVariableError, render_command


# ---------------------------------------------------------------------------
# Status and annotation helpers
# ---------------------------------------------------------------------------

_ICON: dict[StepStatus, str] = {
    StepStatus.PENDING: "[dim]○[/dim]",
    StepStatus.RUNNING: "[yellow]►[/yellow]",
    StepStatus.DONE:    "[green]✓[/green]",
    StepStatus.FAILED:  "[red]✗[/red]",
    StepStatus.SKIPPED: "[dim]—[/dim]",
}


def _annotation(step: Step, ss: StepState) -> str:
    """Return a 1-2 char Rich string: 'M' for manual, '↩' for rollback."""
    parts: list[str] = []
    if step.manual:
        parts.append("[dim]M[/dim]")
    if step.rollback:
        if ss.rollback_ran_at is None:
            parts.append("[cyan]↩[/cyan]")
        elif ss.rollback_exit_code == 0:
            parts.append("[green]↩[/green]")
        else:
            parts.append("[red]↩[/red]")
    return "".join(parts)


# ---------------------------------------------------------------------------
# Confirmation modal
# ---------------------------------------------------------------------------

class ConfirmScreen(ModalScreen[bool]):
    """Overlay asking the user to confirm or cancel an action.

    Pass ``strong=True`` when re-running an already-completed step so the
    user sees an explicit warning before overwriting prior results.
    """

    BINDINGS = [
        ("enter,r,y", "confirm", ""),
        ("escape,n", "cancel", ""),
    ]

    def __init__(
        self,
        title: str,
        preview: str | None = None,
        *,
        strong: bool = False,
    ) -> None:
        super().__init__()
        self._title = title
        self._preview = preview
        self._strong = strong

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            if self._strong:
                yield Label("[yellow bold]⚠  Re-run already-completed step?[/yellow bold]")
            yield Label(f"[bold]{escape(self._title)}[/bold]")
            if self._preview:
                yield Label(f"\n[dim]$ {escape(self._preview[:160])}[/dim]")
            yield Label("\n[bold]Enter[/bold] confirm   [bold]Esc[/bold] cancel")

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


# ---------------------------------------------------------------------------
# Main application
# ---------------------------------------------------------------------------

class RunbookApp(App[None]):
    """Interactive TUI for stepping through a runbook."""

    CSS = """
    #main {
        height: 1fr;
    }
    #steps-panel {
        width: 40%;
        min-width: 26;
        border: solid $primary;
    }
    .panel-title {
        background: $primary 60%;
        color: $text;
        padding: 0 1;
        height: 1;
        width: 100%;
    }
    DataTable {
        height: 1fr;
    }
    #output-panel {
        width: 1fr;
        border: solid $primary;
    }
    RichLog {
        height: 1fr;
        padding: 0 1;
    }
    ConfirmScreen {
        align: center middle;
    }
    #dialog {
        width: 64;
        height: auto;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }
    """

    BINDINGS = [
        Binding("r", "run_step",      "Run",      show=True),
        Binding("s", "skip_step",     "Skip",     show=True),
        Binding("b", "rollback_step", "Rollback", show=True),
        Binding("q", "quit",          "Quit",     show=True),
    ]

    def __init__(self, runbook: Runbook, state: RunState, state_path: Path) -> None:
        super().__init__()
        self.runbook = runbook
        self.run_state = state
        self.state_path = state_path
        self._running_step_id: str | None = None

    # ------------------------------------------------------------------
    # Compose + mount
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main"):
            with Vertical(id="steps-panel"):
                yield Label("Steps", classes="panel-title")
                yield DataTable(
                    id="steps-table",
                    show_header=False,
                    cursor_type="row",
                    zebra_stripes=True,
                )
            with Vertical(id="output-panel"):
                yield Label("Output", classes="panel-title")
                yield RichLog(
                    id="output-log",
                    highlight=True,
                    markup=True,
                    wrap=True,
                    max_lines=500,
                )
        yield Footer()

    def on_mount(self) -> None:
        self.title = f"runbook — {self.runbook.path.name}"
        table = self.query_one("#steps-table", DataTable)
        table.add_column("",      key="icon",  width=3)
        table.add_column("",      key="annot", width=3)
        table.add_column("title", key="title")
        for step in self.runbook.steps:
            ss = self.run_state.steps[step.id]
            table.add_row(
                _ICON[ss.status],
                _annotation(step, ss),
                step.title,
                key=step.id,
            )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _current_step(self) -> Step | None:
        if not self.runbook.steps:
            return None
        row = self.query_one("#steps-table", DataTable).cursor_row
        return self.runbook.steps[row]

    def _refresh_icon(self, step_id: str) -> None:
        ss = self.run_state.steps[step_id]
        table = self.query_one("#steps-table", DataTable)
        table.update_cell(step_id, "icon", _ICON[ss.status])

    def _refresh_annot(self, step_id: str) -> None:
        step = next(s for s in self.runbook.steps if s.id == step_id)
        ss = self.run_state.steps[step_id]
        self.query_one("#steps-table", DataTable).update_cell(
            step_id, "annot", _annotation(step, ss)
        )

    def _log(self, text: str) -> None:
        self.query_one("#output-log", RichLog).write(text)

    def _persist(self) -> None:
        save_state(self.run_state, self.state_path)

    def _focus_step(self, step_id: str) -> None:
        table = self.query_one("#steps-table", DataTable)
        for idx, step in enumerate(self.runbook.steps):
            if step.id == step_id:
                table.move_cursor(row=idx)
                return

    # ------------------------------------------------------------------
    # Actions — sync stubs; workers needed for push_screen_wait
    # ------------------------------------------------------------------

    def action_run_step(self) -> None:
        self._run_step_worker()

    def action_skip_step(self) -> None:
        step = self._current_step()
        if step is None:
            return
        if self._running_step_id == step.id:
            self._log("[yellow]Cannot skip a running step.[/yellow]")
            return
        ss = self.run_state.steps[step.id]
        ss.status = StepStatus.SKIPPED
        self._refresh_icon(step.id)
        self._persist()
        self._log(f"[dim]── {escape(step.title)}: skipped[/dim]")

    def action_rollback_step(self) -> None:
        step = self._current_step()
        if step is None:
            return
        if not step.rollback:
            self._log("[dim]This step has no rollback command.[/dim]")
            return
        self._rollback_step_worker()

    # ------------------------------------------------------------------
    # Run worker
    # ------------------------------------------------------------------

    @work(exclusive=False)
    async def _run_step_worker(self) -> None:
        step = self._current_step()
        if step is None:
            return

        ss = self.run_state.steps[step.id]
        decision = step_run_decision(ss.status)

        if decision == StepRunDecision.BLOCKED:
            self._log("[yellow]This step is currently running.[/yellow]")
            return

        if self._running_step_id is not None:
            self._log("[yellow]Another step is running — wait for it to finish.[/yellow]")
            return

        if step.manual:
            self._log(f"[dim]── {escape(step.title)} is a [bold]manual[/bold] step[/dim]")
            confirmed = await self.push_screen_wait(
                ConfirmScreen(f"Mark as done: {step.title}")
            )
            if confirmed:
                self._mark_manual_done(step)
            return

        try:
            command = render_command(step.command, self.run_state.variables)
        except MissingVariableError as exc:
            self._log(f"[red]Missing variable: ${{{escape(exc.name)}}}[/red]")
            return

        strong = decision == StepRunDecision.RERUN
        confirmed = await self.push_screen_wait(
            ConfirmScreen(step.title, command, strong=strong)
        )
        if confirmed:
            self._execute(step, command)

    # ------------------------------------------------------------------
    # Rollback worker
    # ------------------------------------------------------------------

    @work(exclusive=False)
    async def _rollback_step_worker(self) -> None:
        step = self._current_step()
        if step is None or not step.rollback:
            return

        if self._running_step_id is not None:
            self._log("[yellow]Another step is running — wait for it to finish.[/yellow]")
            return

        try:
            rollback_cmd = render_command(step.rollback, self.run_state.variables)
        except MissingVariableError as exc:
            self._log(f"[red]Missing variable in rollback: ${{{escape(exc.name)}}}[/red]")
            return

        confirmed = await self.push_screen_wait(
            ConfirmScreen(f"↩ Rollback: {step.title}", rollback_cmd)
        )
        if not confirmed:
            return

        # Use a synthetic Step so run_step can write the temp script.
        # We do NOT touch the main step's status — rollback is advisory.
        synthetic = Step(
            id=f"{step.id}--rollback",
            title=f"↩ Rollback: {step.title}",
            level=step.level,
            command=rollback_cmd,
        )
        cwd = self.runbook.path.parent
        ss = self.run_state.steps[step.id]
        self._running_step_id = synthetic.id

        try:
            self._log(f"[bold yellow]↩ Rollback: {escape(step.title)}[/bold yellow]")
            self._log(f"[dim]$ {escape(rollback_cmd)}[/dim]")

            async for event in run_step(synthetic, rollback_cmd, cwd):
                if isinstance(event, CommandOutput):
                    line = event.text.rstrip("\n")
                    if line:
                        if event.stream == "stderr":
                            self._log(f"[red]{escape(line)}[/red]")
                        else:
                            self._log(escape(line))
                elif isinstance(event, CommandExited):
                    ss.rollback_exit_code = event.exit_code
                    ss.rollback_ran_at = datetime.now(timezone.utc)
                    if event.exit_code == 0:
                        self._log("[green]↩ rollback exit 0[/green]")
                    else:
                        self._log(f"[red]↩ rollback exit {event.exit_code}[/red]")
                    self._refresh_annot(step.id)
                    self._persist()

        except Exception as exc:  # noqa: BLE001
            self._log(f"[red]Rollback error: {escape(str(exc))}[/red]")

        finally:
            self._running_step_id = None

    # ------------------------------------------------------------------
    # Manual-done helper
    # ------------------------------------------------------------------

    def _mark_manual_done(self, step: Step) -> None:
        now = datetime.now(timezone.utc)
        ss = self.run_state.steps[step.id]
        ss.status = StepStatus.DONE
        ss.started_at = now
        ss.ended_at = now
        self._refresh_icon(step.id)
        self._persist()
        self._log(f"[bold]── {escape(step.title)}[/bold]")
        self._log("[dim](manual step — marked as done)[/dim]")

    # ------------------------------------------------------------------
    # Execution worker
    # ------------------------------------------------------------------

    @work(exclusive=False)
    async def _execute(self, step: Step, command: str) -> None:
        ss = self.run_state.steps[step.id]
        cwd = self.runbook.path.parent
        self._running_step_id = step.id
        step_logger: StepLogger | None = None

        try:
            async for event in run_step(step, command, cwd):
                if isinstance(event, CommandStarted):
                    started_at = datetime.now(timezone.utc)
                    ss.status = StepStatus.RUNNING
                    ss.started_at = started_at
                    ss.command_rendered = command
                    log_path = default_log_path(self.runbook.path, step.id, started_at)
                    step_logger = StepLogger(log_path, step.id, step.title, command, started_at)
                    ss.log_path = str(log_path)
                    self._refresh_icon(step.id)
                    self._persist()
                    self._log(f"[bold]── {escape(step.title)}[/bold]")
                    self._log(f"[dim]$ {escape(command)}[/dim]")

                elif isinstance(event, CommandOutput):
                    if step_logger is not None:
                        step_logger.write_line(event.stream, event.text)
                    line = event.text.rstrip("\n")
                    if line:
                        if event.stream == "stderr":
                            self._log(f"[red]{escape(line)}[/red]")
                        else:
                            self._log(escape(line))

                elif isinstance(event, CommandExited):
                    ended_at = datetime.now(timezone.utc)
                    ss.ended_at = ended_at
                    ss.exit_code = event.exit_code
                    if step_logger is not None:
                        step_logger.finalize(event.exit_code, ended_at)
                    if event.exit_code == 0:
                        ss.status = StepStatus.DONE
                        self._log("[green]✓ exit 0[/green]")
                    else:
                        ss.status = StepStatus.FAILED
                        self._log(f"[red]✗ exit {event.exit_code}[/red]")
                        self._focus_step(step.id)
                    self._refresh_icon(step.id)
                    self._persist()

        except Exception as exc:  # noqa: BLE001
            ss.status = StepStatus.FAILED
            ss.ended_at = datetime.now(timezone.utc)
            self._refresh_icon(step.id)
            self._persist()
            self._log(f"[red]Unexpected error: {escape(str(exc))}[/red]")

        finally:
            if step_logger is not None:
                step_logger.close()
            self._running_step_id = None
