"""Tests for the README skill table generator (round 5, T10) and
for the README wording fixes (R3 #14, #15, #20; G3).

The skill list in README.md is a table generated from
skills/manifest.json (scripts/generate_readme_table.py), not a
hand-kept bullet list: the two drift apart silently otherwise. The
repo validator checks the table is current.

The secret-shaped-string test scans every tracked file for a
realistic key shape (sk- at a word boundary + 16 or more key
characters) and reports file:line only — it never prints a value.

Run: python3 -m pytest scripts/test_readme_table.py -q
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import generate_readme_table as grt  # noqa: E402

REPO = Path(__file__).resolve().parent.parent

SECRET_RE = re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{16,}")


def _readme():
    return (REPO / "README.md").read_text(encoding="utf-8")


def _section(text, heading):
    """The lines of the ## section named heading (without the heading)."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == f"## {heading}")
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")),
        len(lines),
    )
    return lines[start + 1 : end]


def test_build_skill_table_from_manifest():
    manifest = json.loads((REPO / "skills" / "manifest.json").read_text())
    table = grt.build_skill_table(manifest)
    rows = [line for line in table.splitlines() if line.startswith("| [")]
    assert len(rows) == 36
    assert table.splitlines()[0] == "| Skill | Stages | Licence | Integration | Source |"
    assert any("| [orcinus-verify](skills/orcinus-verify) | 40-59 |" in r for r in rows)
    assert any("| [refactor](skills/refactor) | 50-79 | MIT | verbatim |" in r for r in rows)
    assert "12 stars" not in table


def test_build_skill_table_is_deterministic():
    manifest = json.loads((REPO / "skills" / "manifest.json").read_text())
    assert grt.build_skill_table(manifest) == grt.build_skill_table(manifest)


def test_readme_table_matches_manifest():
    manifest = json.loads((REPO / "skills" / "manifest.json").read_text())
    assert grt.table_section(_readme()) == grt.build_skill_table(manifest)


def test_readme_install_has_no_all_default():
    """The default Agent Skills install is the interactive pick, not
    --all to every agent without prompting (R3 #14)."""
    text = _readme()
    assert "npx skills@latest add DnsQueen/orcinus-skills --all" not in text
    assert "npx skills@latest add DnsQueen/orcinus-skills" in text
    assert "--all" in text  # still documented as the non-interactive option


def test_readme_quick_start_is_short():
    """A quick start the reader can scan in seconds (R3 #20)."""
    lines = [line for line in _section(_readme(), "Quick start") if line.strip()]
    assert lines, "no Quick start section"
    assert len(lines) <= 10, f"quick start is {len(lines)} lines, not 10 or fewer"


def test_readme_status_sentences_are_short():
    """The Status section's 141-word sentence is split (R3 #20)."""
    for line in _section(_readme(), "Status"):
        for sentence in line.split(". "):
            words = sentence.split()
            assert len(words) <= 60, f"Status sentence has {len(words)} words: {sentence[:60]}..."


def test_readme_guided_workflow_wording():
    """ORCINUS is presented as a guided workflow, and reviewer
    independence is reported with its level (G3)."""
    text = _readme()
    assert "guided workflow" in text
    assert "same agent session" in text


def test_readme_has_no_stars_citation():
    """Star counts go stale; the README must not cite them (R3 #20)."""
    assert "12 stars" not in _readme()


def test_no_secret_shaped_strings_in_repo():
    """No file in the repo may contain a realistic secret shape
    (R3 #15). Only file:line is reported, never a value. The scan
    walks the working tree (not `git ls-files`), so it also runs in
    a clean copy, which has no .git directory."""
    excluded = {
        ".git",
        "__pycache__",
        ".ruff_cache",
        "node_modules",
        ".pytest_cache",
        ".stryker-tmp",
        ".venv",
        "venv",
        ".mypy_cache",
    }
    offenders = []
    for path in sorted(REPO.rglob("*")):
        if not path.is_file():
            continue
        if any(part in excluded for part in path.relative_to(REPO).parts):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="strict")
        except (UnicodeDecodeError, OSError):
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if SECRET_RE.search(line):
                offenders.append(f"{path.relative_to(REPO)}:{i}")
    assert offenders == [], f"secret-shaped strings in: {offenders}"


def test_status_section_is_honest_about_evals():
    """Round-6 E-claim / 2-E5 / Rec6: README's "all with a scored
    eval" was false. The Status section must state the counts as
    they are in this repo (computed live, not hard-coded), name the
    agent suite unproven, and say it never ran — never claim every
    skill has a scored eval."""
    section = "\n".join(_section(_readme(), "Status"))
    assert "all with a scored eval" not in section
    eval_files = sorted((REPO / "evals").glob("*.md"))
    assert str(len(eval_files)) in section, "Status must state how many evals/*.md files exist"
    manifest = json.loads((REPO / "skills" / "manifest.json").read_text(encoding="utf-8"))
    skills = sorted(manifest["skills"])
    without_eval = [s for s in skills if not (REPO / "evals" / f"{s}-01.md").is_file()]
    assert str(len(without_eval)) in section, (
        "Status must state how many skills lack a *-01.md eval"
    )
    assert "unproven" in section, "Status must label the never-run agent suite unproven"
    assert "never run" in section, "Status must say the agent suite never ran"
