"""Tests for the README skill table generator (round 5, T10) and
for the README wording fixes (R3 #14, #15, #20; G3).

The skill list in README.md is a grouped list generated from
skills/manifest.json (scripts/generate_readme_table.py), not a
hand-kept bullet list: the two drift apart silently otherwise. The
repo validator checks the list is current.

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
    # FND-004: the first line is the generated .py counts comment;
    # the grouped list follows it.
    assert table.splitlines()[0].startswith("<!-- ")
    # The list carries no provenance: no source column, no licence
    # column, no upstream links — those live in each skill's
    # ATTRIBUTION.md and in docs/MAP.md, not on the front page.
    assert "github.com" not in table
    assert "Licence" not in table and "Source" not in table
    assert "12 stars" not in table
    # Every skill is listed once per stage it covers: 36 skills,
    # 37 links (visual-regression covers 40-59 and 80-100).
    links = re.findall(r"\[([a-z0-9-]+)\]\(skills/[a-z0-9-]+\)", table)
    assert len(links) == 37
    assert len(set(links)) == 36
    assert set(links) == set(manifest["skills"])
    # Group headings, in stage order.
    headings = [line for line in table.splitlines() if line.startswith("### ")]
    assert headings == [
        "### Idea (0-9)",
        "### Architecture (10-19)",
        "### Coding (20-39)",
        "### Verification (40-59)",
        "### Security & debugging (50-79)",
        "### Finalize & publish (80-100)",
        "### All stages (0-100)",
    ]
    assert "[orcinus-verify](skills/orcinus-verify)" in table
    assert "[visual-regression](skills/visual-regression)" in table


def test_build_skill_table_counts_python_files():
    """FND-004 (round 9): the generated section carries the .py
    counts, recomputed from the tree — total, under per-skill
    scripts/, and outside them — so they cannot drift again (the
    hand-kept comment said 42/31/11 for 43/32/11; the extra file
    is the round-8 bundled content_digest.py)."""
    manifest = json.loads((REPO / "skills" / "manifest.json").read_text())
    table = grt.build_skill_table(manifest)
    counts = table.splitlines()[0]
    skills_dir = REPO / "skills"
    py_files = sorted(skills_dir.rglob("*.py"))
    total = len(py_files)
    scripts = len(
        [
            p
            for p in py_files
            if len(p.relative_to(skills_dir).parts) >= 2
            and p.relative_to(skills_dir).parts[1] == "scripts"
        ]
    )
    assert counts.startswith(f"<!-- {total} .py files under skills/")
    assert f"{scripts} live under per-skill scripts/" in counts
    assert f"{total - scripts} outside per-skill scripts/" in counts
    # The enumeration lists the files outside scripts/ by their
    # repo-relative paths (a bare "examples/..." would trip the
    # repo validator's relative-path check).
    assert "skills/database-designer/index_optimizer.py" in counts
    assert "skills/webapp-testing/examples/console_logging.py" in counts


def test_python_counts_paths_use_forward_slashes_on_windows():
    """CI 0.10.5, windows job: the generated .py-counts comment
    differed from the committed README on Windows only, so the
    validator reported the skill table stale ("README skill table
    is stale — run scripts/generate_readme_table.py"). The
    enumeration was built with f"skills/{rel}" — and str(Path)
    uses backslashes on Windows, while the committed README has
    forward slashes. (.gitattributes forces LF everywhere, so
    line endings were not it.) The paths must be formatted with
    as_posix() on every platform. PureWindowsPath simulates the
    Windows str() without a Windows machine: on the old code
    this test fails with backslashes in `outside`."""
    from pathlib import PureWindowsPath

    class _WindowsSkillsDir(PureWindowsPath):
        def rglob(self, pattern):
            return [
                self / "database-designer" / "index_optimizer.py",
                self / "orcinus-verify" / "scripts" / "content_digest.py",
            ]

    total, scripts, outside = grt._python_counts(_WindowsSkillsDir("skills"))
    assert total == 2
    assert scripts == 1
    assert outside == ["skills/database-designer/index_optimizer.py"]
    assert "\\" not in ", ".join(outside)


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
    assert "npx skills@1.7.6 add DnsQueen/orcinus-skills --all" not in text
    assert "npx skills@1.7.6 add DnsQueen/orcinus-skills" in text
    assert "skills@latest" not in text  # round 8, FND-027: pin, don't float
    assert "--all" in text  # still documented as the non-interactive option


def test_readme_install_states_tty_and_real_confirmation():
    """B1 + B3 (0.12.2, arena): the plain install command needs an
    interactive terminal — on a non-TTY runner it exits 1 and
    installs nothing — and the README never said so; and the
    confirmation string `✓ <skill> (copied)` does not exist in
    skills@1.7.6 output (0 matches; 36 `✓` lines shaped
    `✓ ~/<path>/.agents/skills/<name>`)."""
    install = "\n".join(_section(_readme(), "Install"))
    assert "npx skills@1.7.6 add DnsQueen/orcinus-skills" in install
    assert "interactive" in install
    assert "--agent '*' -y" in install
    assert "(copied)" not in install
    assert ".agents/skills/<name>" in install


def test_readme_install_names_old_node_syntax_error():
    """B2 (0.12.2, arena): on Node < 22.20 the installer fails with
    a SyntaxError about fs/promises — the README must name the
    symptom so a user on old Node reads it as 'your Node is too
    old', not a corrupt install."""
    install = "\n".join(_section(_readme(), "Install"))
    assert "SyntaxError" in install
    assert "fs/promises" in install


def test_readme_quick_start_points_non_tty_to_install():
    """0.12.3: Quick start listed the plain npx install with no TTY
    pointer, so a reader copying from Quick start hit the same
    non-TTY failure the Install section documents. It must point
    to the Install section's non-interactive form."""
    quick = " ".join(_section(_readme(), "Quick start"))
    assert "npx skills@1.7.6 add DnsQueen/orcinus-skills" in quick
    assert "non-interactive" in quick
    assert "Install below" in quick


def test_readme_hermes_has_pre_test_verify_step():
    """H-A1 (0.12.2, Hermes): the installed mutation-testing skill
    was silently rewritten mid-test (67 -> 37 lines) and nothing in
    the repo told the operator to check the installed skills match
    the release copy before a live test. The Hermes section must
    carry that step: diff the installed dir against the release
    checkout and stop on any difference."""
    install = " ".join(_section(_readme(), "Install"))
    assert "diff -r" in install
    assert "live test" in install
    assert "Any difference is a stop" in install


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


def test_status_section_states_agent_evaluation_not_demonstrated():
    """FND-007 (round 9): Agent Evaluation is designed but not yet
    demonstrated — the Status section must say so in words, until
    a real-executor run exists."""
    section = "\n".join(_section(_readme(), "Status"))
    assert "designed but not yet demonstrated" in section
    assert "no evaluation of a live agent" in section


def test_scope_states_five_trials_plan():
    """N-A (round 9): the README's "At least 5 trials per task
    with a real executor is future work (see SCOPE.md)" must land
    on a real plan in SCOPE.md, not a dangling pointer."""
    scope = (REPO / "SCOPE.md").read_text(encoding="utf-8")
    assert "5 trials" in scope
    assert "real executor" in scope
    assert "demonstrated" in scope


def test_hermes_section_states_verification_status():
    """FND-010 + N-C (round 9), updated 0.12.5: the README's Hermes install
    section must carry its own verification-status caveat in-section — the
    disclosure in SCOPE.md alone does not reach a reader
    following the install steps. The November 2026 live tests loaded the
    bundle via external_dirs, so the section now states that (with the
    34/36 limit and the 2 name collisions); the install-steps caveat
    stays, because the steps below are the documented procedure,
    not a verified run."""
    text = _readme()
    start = text.index("Hermes (Nous Research)")
    end = text.index("\n## ", start)
    # Join wrapped lines: the caveat's phrases span line breaks.
    section = " ".join(text[start:end].split())
    assert "Loaded by real Hermes sessions in live tests" in section
    assert "34 of 36" in section
    assert "not a verified run" in section
