"""Parse a Markdown file into a Runbook using mistune AST."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

import mistune

from runbook.models import Runbook, Step


_BASH_LANGS = frozenset({"bash", "sh", "shell"})
_RE_MANUAL = re.compile(r"<!--\s*runbook:manual\s*-->")
_RE_ROLLBACK = re.compile(r"<!--\s*runbook:rollback:\s*(.+?)\s*-->")

# Language matching rules
# - The info string may have trailing attributes: ```bash title="deploy"
#   → only the first whitespace-delimited word is used.
# - Matching is case-insensitive: Bash, BASH, Shell are all accepted.
# - A fence with no language tag (empty info string) is not a bash block.


def parse_runbook(path: Path) -> Runbook:
    source = path.read_text(encoding="utf-8")
    content_hash = hashlib.sha256(source.encode()).hexdigest()
    md = mistune.create_markdown(renderer="ast")
    tokens: list[dict[str, Any]] = md(source)
    steps = _extract_steps(tokens)
    return Runbook(path=path, content_hash=content_hash, steps=steps)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _heading_text(token: dict[str, Any]) -> str:
    """Collect plain text from a heading token's children (recursive)."""
    parts: list[str] = []
    for child in token.get("children") or []:
        if "raw" in child:
            parts.append(child["raw"])
        else:
            parts.append(_heading_text(child))
    return "".join(parts)


def _slugify(text: str) -> str:
    slug = text.lower()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug).strip("-")
    return slug or "step"


def _make_id(title: str, seen: dict[str, int]) -> str:
    """Return a stable, collision-free slug for *title*."""
    base = _slugify(title)
    count = seen.get(base, 0) + 1
    seen[base] = count
    return base if count == 1 else f"{base}-{count}"


def _code_lang(token: dict[str, Any]) -> str:
    """Return the normalised language tag from a code token, or ''."""
    info: str = ((token.get("attrs") or {}).get("info") or "").strip()
    return info.split()[0].lower() if info else ""


def _extract_steps(tokens: list[dict[str, Any]]) -> list[Step]:  # noqa: C901
    """Walk the flat mistune AST token list and collect Steps.

    H2/H3 nesting behaviour
    -----------------------
    mistune emits a flat token list regardless of heading depth.  The parser
    treats every H2 or H3 as the start of a potential step and discards any
    heading that is never followed by a bash fence before the next heading.

    Concretely, when an H2 has H3 sub-sections:

    * If the H2 itself has a bash fence, it becomes a step.  The subsequent H3
      headings are then processed independently.
    * If the H2 has *no* bash fence, it is silently discarded when the first H3
      (or any following heading) is encountered.  Only H3 blocks that have their
      own bash fence become steps.

    H1 headings are always ignored (document title).
    H4+ headings flush any open heading but never start a new step.

    Multiple HTML directives
    ------------------------
    Each <!-- runbook:… --> comment is a separate block_html token.  The parser
    accumulates directives (manual, rollback) across all block_html tokens that
    appear between the heading and the bash fence.

    Text / non-bash fences between heading and bash fence
    ------------------------------------------------------
    Paragraph text, lists, non-bash code fences, and other tokens that appear
    between a heading and its bash fence are ignored — they do not interrupt the
    search for the bash fence.

    Only the *first* bash fence under a heading creates a step; any additional
    bash fences within the same heading scope are unreachable (state is reset).
    """
    steps: list[Step] = []
    seen_slugs: dict[str, int] = {}

    # Accumulated state for the heading currently in scope.
    current_title: str | None = None
    current_level: int | None = None
    pending_manual: bool = False
    pending_rollback: str | None = None

    def flush() -> None:
        nonlocal current_title, current_level, pending_manual, pending_rollback
        current_title = None
        current_level = None
        pending_manual = False
        pending_rollback = None

    for token in tokens:
        t = token["type"]

        if t == "heading":
            level: int = token["attrs"]["level"]
            # Discard any heading that produced no bash block before this one.
            flush()
            if level in (2, 3):
                current_title = _heading_text(token)
                current_level = level
            # H1 and H4+ are ignored after the flush above.

        elif t == "block_code" and current_title is not None:
            if _code_lang(token) in _BASH_LANGS:
                command = token["raw"].rstrip("\n")
                steps.append(Step(
                    id=_make_id(current_title, seen_slugs),
                    title=current_title,
                    level=current_level,  # type: ignore[arg-type]
                    command=command,
                    manual=pending_manual,
                    rollback=pending_rollback,
                ))
                flush()
            # Non-bash fence: keep scanning for a bash one under the same heading.

        elif t == "block_html" and current_title is not None:
            raw: str = token.get("raw", "")
            if _RE_MANUAL.search(raw):
                pending_manual = True
            m = _RE_ROLLBACK.search(raw)
            if m:
                pending_rollback = m.group(1).strip()

    return steps
