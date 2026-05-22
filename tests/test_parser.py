"""Tests for runbook/parser.py — covers all MVP parsing rules."""

from pathlib import Path
import pytest
from runbook.parser import parse_runbook, _make_id, _slugify


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write(tmp_path: Path, source: str) -> Path:
    p = tmp_path / "runbook.md"
    p.write_text(source, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# H2 with bash
# ---------------------------------------------------------------------------

H2_BASH = """\
# My Runbook

## Check disk space

Some description.

```bash
df -h
```
"""


def test_h2_bash_creates_step(tmp_path):
    rb = parse_runbook(_write(tmp_path, H2_BASH))
    assert len(rb.steps) == 1
    step = rb.steps[0]
    assert step.title == "Check disk space"
    assert step.level == 2
    assert step.command == "df -h"
    assert step.manual is False


# ---------------------------------------------------------------------------
# H3 with bash
# ---------------------------------------------------------------------------

H3_BASH = """\
## Deploy

### Run migrations

```sh
python manage.py migrate
```
"""


def test_h3_bash_creates_step(tmp_path):
    rb = parse_runbook(_write(tmp_path, H3_BASH))
    steps = rb.steps
    # H2 "Deploy" has no bash → skipped; H3 "Run migrations" has bash → kept
    assert len(steps) == 1
    step = steps[0]
    assert step.title == "Run migrations"
    assert step.level == 3
    assert step.command == "python manage.py migrate"


# ---------------------------------------------------------------------------
# Heading without bash is ignored
# ---------------------------------------------------------------------------

NO_BASH = """\
## Step with bash

```bash
echo hello
```

## Step without bash

Just prose, no code block.

## Another with bash

```shell
ls -la
```
"""


def test_heading_without_bash_is_skipped(tmp_path):
    rb = parse_runbook(_write(tmp_path, NO_BASH))
    titles = [s.title for s in rb.steps]
    assert "Step without bash" not in titles
    assert "Step with bash" in titles
    assert "Another with bash" in titles


def test_only_bash_steps_counted(tmp_path):
    rb = parse_runbook(_write(tmp_path, NO_BASH))
    assert len(rb.steps) == 2


# ---------------------------------------------------------------------------
# Non-bash fence does not stop the search
# ---------------------------------------------------------------------------

NON_BASH_THEN_BASH = """\
## Deploy

```python
# just a helper snippet
```

```bash
make deploy
```
"""


def test_non_bash_fence_does_not_stop_search(tmp_path):
    rb = parse_runbook(_write(tmp_path, NON_BASH_THEN_BASH))
    assert len(rb.steps) == 1
    assert rb.steps[0].command == "make deploy"


# ---------------------------------------------------------------------------
# Duplicate headings get suffixed IDs
# ---------------------------------------------------------------------------

DUPLICATES = """\
## Deploy

```bash
make deploy
```

## Deploy

```bash
make deploy-staging
```

## Deploy

```bash
make deploy-prod
```
"""


def test_duplicate_ids_get_suffix(tmp_path):
    rb = parse_runbook(_write(tmp_path, DUPLICATES))
    ids = [s.id for s in rb.steps]
    assert ids == ["deploy", "deploy-2", "deploy-3"]


def test_duplicate_ids_are_unique(tmp_path):
    rb = parse_runbook(_write(tmp_path, DUPLICATES))
    ids = [s.id for s in rb.steps]
    assert len(ids) == len(set(ids))


# ---------------------------------------------------------------------------
# <!-- runbook:manual -->
# ---------------------------------------------------------------------------

MANUAL = """\
## Restart service

<!-- runbook:manual -->

```bash
systemctl restart myapp
```
"""


def test_manual_comment_sets_flag(tmp_path):
    rb = parse_runbook(_write(tmp_path, MANUAL))
    assert rb.steps[0].manual is True


def test_manual_step_still_has_command(tmp_path):
    rb = parse_runbook(_write(tmp_path, MANUAL))
    assert rb.steps[0].command == "systemctl restart myapp"


# ---------------------------------------------------------------------------
# <!-- runbook:rollback: <cmd> -->
# ---------------------------------------------------------------------------

ROLLBACK = """\
## Deploy

<!-- runbook:rollback: make rollback -->

```bash
make deploy
```
"""


def test_rollback_comment_parsed(tmp_path):
    rb = parse_runbook(_write(tmp_path, ROLLBACK))
    assert rb.steps[0].rollback == "make rollback"


def test_no_rollback_is_none(tmp_path):
    rb = parse_runbook(_write(tmp_path, H2_BASH))
    assert rb.steps[0].rollback is None


# ---------------------------------------------------------------------------
# Both manual and rollback on same step
# ---------------------------------------------------------------------------

MANUAL_ROLLBACK = """\
## Full deploy

<!-- runbook:manual -->
<!-- runbook:rollback: make rollback -->

```bash
make deploy
```
"""


def test_manual_and_rollback_together(tmp_path):
    rb = parse_runbook(_write(tmp_path, MANUAL_ROLLBACK))
    step = rb.steps[0]
    assert step.manual is True
    assert step.rollback == "make rollback"


def test_manual_without_bash_produces_no_step(tmp_path):
    # manual comment on a heading that has no bash fence → skip entirely
    source = "## Confirm deployment\n\n<!-- runbook:manual -->\n\nJust prose, no command.\n"
    rb = parse_runbook(_write(tmp_path, source))
    assert len(rb.steps) == 0


def test_rollback_command_with_spaces_and_flags(tmp_path):
    source = (
        "## Deploy\n\n"
        "<!-- runbook:rollback: kubectl rollout undo deploy/myapp --namespace prod -->\n\n"
        "```bash\nkubectl apply -f deploy.yaml\n```\n"
    )
    rb = parse_runbook(_write(tmp_path, source))
    assert rb.steps[0].rollback == "kubectl rollout undo deploy/myapp --namespace prod"


def test_manual_flag_is_false_when_comment_absent(tmp_path):
    rb = parse_runbook(_write(tmp_path, H2_BASH))
    assert rb.steps[0].manual is False


def test_manual_step_is_not_auto_manual_without_comment(tmp_path):
    # A step with a bash block and no manual comment must NOT be manual
    source = "## Run tests\n\n```bash\npytest\n```\n"
    rb = parse_runbook(_write(tmp_path, source))
    assert rb.steps[0].manual is False


# ---------------------------------------------------------------------------
# content_hash
# ---------------------------------------------------------------------------

def test_content_hash_is_stable(tmp_path):
    p = _write(tmp_path, H2_BASH)
    rb1 = parse_runbook(p)
    rb2 = parse_runbook(p)
    assert rb1.content_hash == rb2.content_hash


def test_content_hash_changes_on_edit(tmp_path):
    p = _write(tmp_path, H2_BASH)
    rb1 = parse_runbook(p)
    p.write_text(H2_BASH + "\n", encoding="utf-8")
    rb2 = parse_runbook(p)
    assert rb1.content_hash != rb2.content_hash


# ---------------------------------------------------------------------------
# path stored on Runbook
# ---------------------------------------------------------------------------

def test_path_stored(tmp_path):
    p = _write(tmp_path, H2_BASH)
    rb = parse_runbook(p)
    assert rb.path == p


# ---------------------------------------------------------------------------
# Unit tests for slug/id helpers
# ---------------------------------------------------------------------------

def test_slugify_basic():
    assert _slugify("Check disk space") == "check-disk-space"


def test_slugify_special_chars():
    assert _slugify("Deploy (prod)!") == "deploy-prod"


def test_slugify_empty_falls_back():
    assert _slugify("!!!") == "step"


def test_make_id_no_collision():
    seen: dict[str, int] = {}
    assert _make_id("Deploy", seen) == "deploy"


def test_make_id_first_collision():
    seen: dict[str, int] = {}
    _make_id("Deploy", seen)
    assert _make_id("Deploy", seen) == "deploy-2"


def test_make_id_third_collision():
    seen: dict[str, int] = {}
    for _ in range(3):
        _make_id("Deploy", seen)
    assert _make_id("Deploy", seen) == "deploy-4"


# ---------------------------------------------------------------------------
# Code fence language variants
# ---------------------------------------------------------------------------

FENCE_NO_LANG = """\
## Step

```
echo hello
```
"""


def test_fence_without_lang_is_skipped(tmp_path):
    rb = parse_runbook(_write(tmp_path, FENCE_NO_LANG))
    assert len(rb.steps) == 0


FENCE_UPPERCASE_BASH = """\
## Step

```Bash
echo hello
```
"""


def test_fence_uppercase_bash_creates_step(tmp_path):
    rb = parse_runbook(_write(tmp_path, FENCE_UPPERCASE_BASH))
    assert len(rb.steps) == 1
    assert rb.steps[0].command == "echo hello"


FENCE_ALLCAPS_BASH = """\
## Step

```BASH
echo hello
```
"""


def test_fence_allcaps_bash_creates_step(tmp_path):
    rb = parse_runbook(_write(tmp_path, FENCE_ALLCAPS_BASH))
    assert len(rb.steps) == 1


FENCE_UPPERCASE_SH = """\
## Step

```SH
echo hello
```
"""


def test_fence_uppercase_sh_creates_step(tmp_path):
    rb = parse_runbook(_write(tmp_path, FENCE_UPPERCASE_SH))
    assert len(rb.steps) == 1


FENCE_TITLECASE_SHELL = """\
## Step

```Shell
echo hello
```
"""


def test_fence_titlecase_shell_creates_step(tmp_path):
    rb = parse_runbook(_write(tmp_path, FENCE_TITLECASE_SHELL))
    assert len(rb.steps) == 1


# ---------------------------------------------------------------------------
# Info string with trailing attributes
# ---------------------------------------------------------------------------

FENCE_INFO_ATTRS = """\
## Deploy

```bash title="deploy-app"
make deploy
```
"""


def test_info_string_with_title_attribute_creates_step(tmp_path):
    rb = parse_runbook(_write(tmp_path, FENCE_INFO_ATTRS))
    assert len(rb.steps) == 1
    assert rb.steps[0].command == "make deploy"


FENCE_INFO_MULTIPLE_ATTRS = """\
## Deploy

```bash title="x" class="highlight" id="d1"
make deploy
```
"""


def test_info_string_multiple_attrs_creates_step(tmp_path):
    rb = parse_runbook(_write(tmp_path, FENCE_INFO_MULTIPLE_ATTRS))
    assert len(rb.steps) == 1


FENCE_INFO_ATTRS_UPPERCASE = """\
## Deploy

```Bash title="deploy"
make deploy
```
"""


def test_info_string_uppercase_lang_with_attrs_creates_step(tmp_path):
    rb = parse_runbook(_write(tmp_path, FENCE_INFO_ATTRS_UPPERCASE))
    assert len(rb.steps) == 1


FENCE_NON_BASH_ATTRS = """\
## Deploy

```python title="helper"
print("hi")
```
"""


def test_non_bash_info_string_is_skipped(tmp_path):
    rb = parse_runbook(_write(tmp_path, FENCE_NON_BASH_ATTRS))
    assert len(rb.steps) == 0


# ---------------------------------------------------------------------------
# Multiple HTML comments between heading and fence
# ---------------------------------------------------------------------------

MULTI_COMMENT_BLANK_LINE = """\
## Deploy

<!-- runbook:manual -->

<!-- runbook:rollback: make rollback -->

```bash
make deploy
```
"""


def test_manual_and_rollback_in_separate_comments_blank_line(tmp_path):
    rb = parse_runbook(_write(tmp_path, MULTI_COMMENT_BLANK_LINE))
    step = rb.steps[0]
    assert step.manual is True
    assert step.rollback == "make rollback"


THREE_COMMENTS = """\
## Deploy

<!-- runbook:manual -->
<!-- runbook:rollback: make rollback -->
<!-- runbook:rollback: make rollback-v2 -->

```bash
make deploy
```
"""


def test_last_rollback_comment_wins(tmp_path):
    # when multiple rollback comments exist, the last one takes precedence
    rb = parse_runbook(_write(tmp_path, THREE_COMMENTS))
    assert rb.steps[0].rollback == "make rollback-v2"


COMMENT_THEN_TEXT_THEN_FENCE = """\
## Deploy

<!-- runbook:manual -->

Some descriptive text between comment and fence.

```bash
make deploy
```
"""


def test_comment_survives_intervening_text(tmp_path):
    rb = parse_runbook(_write(tmp_path, COMMENT_THEN_TEXT_THEN_FENCE))
    step = rb.steps[0]
    assert step.manual is True
    assert step.command == "make deploy"


# ---------------------------------------------------------------------------
# Descriptive text (paragraphs, lists) between heading and fence
# ---------------------------------------------------------------------------

TEXT_BETWEEN = """\
## Check disk space

Run this to verify free space before deploying.

- check `/var`
- check `/tmp`

```bash
df -h
```
"""


def test_paragraph_between_heading_and_fence_creates_step(tmp_path):
    rb = parse_runbook(_write(tmp_path, TEXT_BETWEEN))
    assert len(rb.steps) == 1
    assert rb.steps[0].command == "df -h"


MULTI_PARA_BETWEEN = """\
## Deploy

First paragraph of description.

Second paragraph with more details.

```bash
make deploy
```
"""


def test_multiple_paragraphs_between_heading_and_fence(tmp_path):
    rb = parse_runbook(_write(tmp_path, MULTI_PARA_BETWEEN))
    assert len(rb.steps) == 1
    assert rb.steps[0].title == "Deploy"


# ---------------------------------------------------------------------------
# H2 / H3 nesting — explicit behaviour contract
# ---------------------------------------------------------------------------

# Case 1: H2 has no bash of its own; H3 children provide the steps.
# Expected: H2 is discarded; H3 steps are created.
H2_NO_BASH_H3_HAS_BASH = """\
## Deploy

General description, no bash block here.

### Run migrations

```bash
python manage.py migrate
```

### Restart service

```bash
systemctl restart myapp
```
"""


def test_h2_without_bash_discarded_h3_steps_created(tmp_path):
    rb = parse_runbook(_write(tmp_path, H2_NO_BASH_H3_HAS_BASH))
    titles = [s.title for s in rb.steps]
    assert "Deploy" not in titles
    assert "Run migrations" in titles
    assert "Restart service" in titles


def test_h2_without_bash_h3_count(tmp_path):
    rb = parse_runbook(_write(tmp_path, H2_NO_BASH_H3_HAS_BASH))
    assert len(rb.steps) == 2


# Case 2: H2 has its own bash block AND contains H3 children that also have bash.
# Expected: H2 step is created first, then each H3 step independently.
H2_AND_H3_BOTH_BASH = """\
## Deploy

```bash
echo "starting deploy"
```

### Run migrations

```bash
python manage.py migrate
```

### Restart service

```bash
systemctl restart myapp
```
"""


def test_h2_with_bash_creates_own_step(tmp_path):
    rb = parse_runbook(_write(tmp_path, H2_AND_H3_BOTH_BASH))
    titles = [s.title for s in rb.steps]
    assert titles[0] == "Deploy"


def test_h2_with_bash_and_h3_children_total_count(tmp_path):
    rb = parse_runbook(_write(tmp_path, H2_AND_H3_BOTH_BASH))
    assert len(rb.steps) == 3


def test_h2_with_bash_and_h3_order(tmp_path):
    rb = parse_runbook(_write(tmp_path, H2_AND_H3_BOTH_BASH))
    titles = [s.title for s in rb.steps]
    assert titles == ["Deploy", "Run migrations", "Restart service"]


# Case 3: H2 has no bash, H3 has no bash either.
# Expected: no steps produced.
H2_H3_NEITHER_BASH = """\
## Section

Just prose.

### Sub-section

More prose, still no bash.
"""


def test_h2_and_h3_without_bash_produces_no_steps(tmp_path):
    rb = parse_runbook(_write(tmp_path, H2_H3_NEITHER_BASH))
    assert len(rb.steps) == 0


# Case 4: H4 (and deeper) headings are always ignored.
H4_IGNORED = """\
## Deploy

```bash
make deploy
```

#### Post-deploy check

```bash
curl https://example.com/health
```
"""


def test_h4_heading_ignored(tmp_path):
    rb = parse_runbook(_write(tmp_path, H4_IGNORED))
    titles = [s.title for s in rb.steps]
    assert "Post-deploy check" not in titles
    assert len(rb.steps) == 1


# H1 is always the document title — never a step.
H1_NOT_A_STEP = """\
# My Runbook

## Deploy

```bash
make deploy
```
"""


def test_h1_is_never_a_step(tmp_path):
    rb = parse_runbook(_write(tmp_path, H1_NOT_A_STEP))
    titles = [s.title for s in rb.steps]
    assert "My Runbook" not in titles
    assert len(rb.steps) == 1


# ---------------------------------------------------------------------------
# Only the first bash fence under a heading creates a step
# ---------------------------------------------------------------------------

TWO_BASH_FENCES = """\
## Deploy

```bash
echo "first"
```

```bash
make deploy
```
"""


def test_only_first_bash_fence_creates_step(tmp_path):
    rb = parse_runbook(_write(tmp_path, TWO_BASH_FENCES))
    assert len(rb.steps) == 1
    assert rb.steps[0].command == 'echo "first"'


# ---------------------------------------------------------------------------
# _slugify edge cases
# ---------------------------------------------------------------------------

def test_slugify_numbers():
    assert _slugify("Deploy 2024") == "deploy-2024"


def test_slugify_underscores_become_hyphens():
    assert _slugify("deploy_app") == "deploy-app"


def test_slugify_leading_trailing_hyphens_stripped():
    assert _slugify("--deploy--") == "deploy"


def test_slugify_multiple_spaces_become_single_hyphen():
    assert _slugify("check  disk   space") == "check-disk-space"


def test_slugify_ampersand_removed():
    assert _slugify("A & B") == "a-b"


def test_slugify_percent_removed():
    assert _slugify("100% complete") == "100-complete"


def test_slugify_hash_removed():
    assert _slugify("Step #2") == "step-2"


def test_slugify_unicode_letters_preserved():
    # Non-ASCII letters are valid slug characters.
    result = _slugify("Déployer l'app")
    assert result.startswith("d")
    assert "ployer" in result
    assert "-" in result


def test_slugify_only_special_chars_falls_back():
    assert _slugify("!@#$%") == "step"
