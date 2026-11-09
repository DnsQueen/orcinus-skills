#!/usr/bin/env python3
"""Generate the skill list in README.md from skills/manifest.json.

The README's skill list is grouped by lifecycle stage, not a
hand-kept bullet list: hand-kept lists drift from the manifest
silently (a renamed skill, a dropped row, a stale count). The list
is generated from the manifest — the single source of truth for the
skill inventory — and the repo validator checks it is current.

The list carries no provenance: where a skill came from lives in
that skill's ATTRIBUTION.md and in docs/MAP.md, not on the front
page.

Run: python3 scripts/generate_readme_table.py
Check (no writes): python3 scripts/generate_readme_table.py --check

Stdlib only. The output is deterministic: the same manifest always
produces the same list bytes.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
MANIFEST = ROOT / "skills" / "manifest.json"

BEGIN = "<!-- BEGIN GENERATED SKILL TABLE — do not edit by hand; run scripts/generate_readme_table.py -->"
END = "<!-- END GENERATED SKILL TABLE -->"


def _python_counts(skills_dir):
    """(total, scripts, outside): the .py files under `skills_dir`
    (round 9, FND-004) — total, under per-skill scripts/, and the
    rest as repo-relative paths ("skills/<name>/...") for the
    enumeration. A file counts as 'scripts' when 'scripts' is the
    second component of its path under skills/
    (skills/<name>/scripts/...). The counts were hand-kept before
    and drifted (42/31/11 for 43/32/11 — the extra file is the
    round-8 bundled content_digest.py); generated, they cannot.
    The enumeration uses repo-relative paths, not skill-relative
    ones: a bare "examples/..." would trip the repo validator's
    relative-path check, which requires every skills/... path in
    the README to exist."""
    total = 0
    scripts = 0
    outside = []
    for path in sorted(skills_dir.rglob("*.py")):
        rel = path.relative_to(skills_dir)
        total += 1
        if len(rel.parts) >= 2 and rel.parts[1] == "scripts":
            scripts += 1
        else:
            # Forward slashes on every platform: str(Path) uses
            # backslashes on Windows, which made the generated
            # table differ from the committed README there (CI
            # 0.10.5, windows job: "README skill table is stale").
            outside.append(f"skills/{rel.as_posix()}")
    return total, scripts, outside


def _python_counts_line(skills_dir):
    """The generated .py-counts comment for the README's generated
    section: the three numbers plus the enumeration of the files
    outside per-skill scripts/."""
    total, scripts, outside = _python_counts(skills_dir)
    enumerated = ", ".join(outside)
    return (
        f"<!-- {total} .py files under skills/ — re-verify with "
        f"`find skills -name '*.py' | wc -l`. {scripts} live under "
        f"per-skill scripts/; {total - scripts} outside per-skill "
        f"scripts/ ({enumerated}). -->"
    )


# The README groups skills by lifecycle stage, in stage order — the
# same bands docs/MAP.md uses. A skill that covers two stages
# appears under both.
STAGE_GROUPS = (
    ("0-9", "Idea"),
    ("10-19", "Architecture"),
    ("20-39", "Coding"),
    ("40-59", "Verification"),
    ("50-79", "Security & debugging"),
    ("80-100", "Finalize & publish"),
    ("0-100", "All stages"),
)


def build_skill_table(manifest, skills_dir=None):
    """Render the skill list (Markdown) from the manifest dict,
    grouped by lifecycle stage and preceded by the generated
    .py-counts comment. `skills_dir` is the skills directory the
    counts are read from (default: the skills directory beside
    this script's repo root); the repo validator passes its own
    root, so a test repo's counts are its own, not this
    checkout's. A skill covering two stages is listed under
    both."""
    if skills_dir is None:
        skills_dir = ROOT / "skills"
    skills = manifest["skills"]
    groups = []
    for stages, title in STAGE_GROUPS:
        names = sorted(n for n, s in skills.items() if stages in s["stages"])
        if not names:
            continue
        groups.append(
            f"### {title} ({stages})\n\n" + ", ".join(f"[{n}](skills/{n})" for n in names)
        )
    return _python_counts_line(skills_dir) + "\n\n" + "\n\n".join(groups) + "\n"


def table_section(readme_text):
    """The generated skill list currently in README.md (between the markers)."""
    start = readme_text.index(BEGIN) + len(BEGIN)
    if not readme_text[start:].startswith("\n"):
        raise ValueError("the generated-table BEGIN marker must be followed by a newline")
    table_start = start + 1
    table_end = readme_text.index(END, table_start)
    return readme_text[table_start:table_end]


def replace_table(readme_text, manifest):
    """README.md with its skill list replaced by a fresh generation."""
    start = readme_text.index(BEGIN) + len(BEGIN)
    if not readme_text[start:].startswith("\n"):
        raise ValueError("the generated-table BEGIN marker must be followed by a newline")
    table_start = start + 1
    table_end = readme_text.index(END, table_start)
    return readme_text[:table_start] + build_skill_table(manifest) + readme_text[table_end:]


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    check_only = "--check" in argv
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    readme_text = README.read_text(encoding="utf-8")
    try:
        current = table_section(readme_text)
    except ValueError as e:
        print(f"README skill table cannot be read: {e}", file=sys.stderr)
        return 1
    fresh = build_skill_table(manifest)
    if check_only:
        if current != fresh:
            print(
                "README skill table is stale — run scripts/generate_readme_table.py",
                file=sys.stderr,
            )
            return 1
        print("README skill table is current")
        return 0
    if current == fresh:
        print("README skill table is already current")
        return 0
    README.write_text(replace_table(readme_text, manifest), encoding="utf-8")
    print("Wrote the skill table in README.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
