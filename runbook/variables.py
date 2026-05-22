"""Variable extraction and command rendering for ${VAR} substitution."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from runbook.models import Runbook

# Matches ${VAR} where VAR is [A-Za-z_][A-Za-z0-9_]*
# A negative lookahead rejects forms with operator chars right after the name
# (:-  :?  /  :+  :%  :#) so bash expansions like ${VAR:-default} are skipped.
_SIMPLE_VAR = re.compile(
    r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?![:\-?/+%#=^,@!])}"
)

# Matches any ${...} token — used to detect advanced expansions we intentionally ignore.
_ANY_BRACE_EXPAND = re.compile(r"\$\{[^}]+}")


class MissingVariableError(ValueError):
    """Raised when render_command needs a variable that is not in *variables*."""

    def __init__(self, name: str, command: str) -> None:
        self.name = name
        self.command = command
        super().__init__(f"Variable ${{{name}}} is not defined (in command: {command!r})")


def extract_variables(runbook: Runbook) -> set[str]:
    """Return the set of simple ${VAR} names referenced across all step commands."""
    found: set[str] = set()
    for step in runbook.steps:
        if step.command:
            found.update(_SIMPLE_VAR.findall(step.command))
    return found


def render_command(command: str, variables: dict[str, str]) -> str:
    """Replace every ${VAR} in *command* with its value from *variables*.

    Raises MissingVariableError for any simple ${VAR} not present in *variables*.
    Advanced bash expansions (${VAR:-x}, ${VAR/a/b}, …) are left untouched.
    """
    missing = [name for name in _SIMPLE_VAR.findall(command) if name not in variables]
    if missing:
        raise MissingVariableError(missing[0], command)

    def _replace(m: re.Match[str]) -> str:
        return variables[m.group(1)]

    return _SIMPLE_VAR.sub(_replace, command)
