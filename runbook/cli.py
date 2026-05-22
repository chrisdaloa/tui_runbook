"""Entry point: parse → load/create state → prompt variables → launch TUI."""

from __future__ import annotations

import sys
from pathlib import Path


_USAGE = "Usage: runbook [--reset] <path/to/runbook.md>"


def _parse_args(args: list[str]) -> tuple[bool, Path | None]:
    """Return (reset_flag, path).  path is None when args are invalid."""
    reset = "--reset" in args
    positional = [a for a in args if not a.startswith("--")]
    if not positional:
        return reset, None
    return reset, Path(positional[0])


def _prompt_variables(names: set[str], existing: dict[str, str]) -> dict[str, str]:
    """Ask for any variable in *names* not already in *existing*."""
    result = dict(existing)
    missing = sorted(names - result.keys())
    if not missing:
        return result

    print(f"\nThis runbook requires {len(missing)} variable(s):")
    for name in missing:
        while True:
            try:
                value = input(f"  ${{{name}}}: ").strip()
            except EOFError:
                print(f"\nError: no value provided for ${{{name}}}", file=sys.stderr)
                sys.exit(1)
            if value:
                result[name] = value
                break
            print("  Value cannot be empty.")
    return result


def main(argv: list[str] | None = None) -> None:
    args = argv if argv is not None else sys.argv[1:]

    reset, path = _parse_args(args)

    if path is None:
        print(_USAGE, file=sys.stderr)
        sys.exit(1)

    if not path.exists():
        print(f"Error: file not found: {path}", file=sys.stderr)
        sys.exit(1)

    if not path.is_file():
        print(f"Error: not a file: {path}", file=sys.stderr)
        sys.exit(1)

    from runbook.models import RunState
    from runbook.parser import parse_runbook
    from runbook.state import (
        RunbookChangedError,
        create_or_resume_state,
        default_state_path,
        resume_summary,
        save_state,
    )
    from runbook.variables import extract_variables

    runbook = parse_runbook(path)
    state_path = default_state_path(path)

    step_word = "step" if len(runbook.steps) == 1 else "steps"
    print(f"\nrunbook · {path.name} · {len(runbook.steps)} {step_word}")

    try:
        if reset:
            state = RunState.from_runbook(runbook)
            print("State reset.")
        else:
            state = create_or_resume_state(runbook, state_path=state_path)
    except RunbookChangedError as exc:
        print(f"\nWarning: {exc}")
        print(
            "The runbook has changed since the last run.\n"
            "Re-run with --reset to discard saved progress, or answer 'y' below."
        )
        try:
            answer = input("Reset state and start from scratch? [y/N] ").strip().lower()
        except EOFError:
            answer = "n"
        if answer != "y":
            print("Aborted.", file=sys.stderr)
            sys.exit(1)
        state = RunState.from_runbook(runbook)
    except ValueError as exc:
        print(f"\nError reading state file ({state_path}): {exc}", file=sys.stderr)
        print("Delete or repair the state file and try again.", file=sys.stderr)
        sys.exit(1)

    summary = resume_summary(state)
    if summary:
        print(summary)

    required = extract_variables(runbook)

    # Show variables already known from a previous run so the user is not
    # surprised that they are not prompted again.
    restored = sorted(required & state.variables.keys())
    if restored:
        print("\nVariables restored from previous run:")
        for name in restored:
            print(f"  ${{{name}}} = {state.variables[name]}")

    state.variables = _prompt_variables(required, state.variables)

    # Persist variables before the TUI starts so they survive a Ctrl-C.
    save_state(state, state_path)

    from runbook.app import RunbookApp
    RunbookApp(runbook, state, state_path).run()
