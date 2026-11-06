#!/usr/bin/env python3
"""Generate the skill table in README.md from skills/manifest.json.

The README's skill list is a table, not a hand-kept bullet list:
hand-kept lists drift from the manifest silently (a renamed skill, a
dropped row, a stale count). The table is generated from the manifest
— the single source of truth for the skill inventory — and the repo
validator checks it is current.

Run: python3 scripts/generate_readme_table.py
Check (no writes): python3 scripts/generate_readme_table.py --check

Stdlib only. The output is deterministic: the same manifest always
produces the same table bytes.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
MANIFEST = ROOT / "skills" / "manifest.json"

BEGIN = "<!-- BEGIN GENERATED SKILL TABLE — do not edit by hand; run scripts/generate_readme_table.py -->"
END = "<!-- END GENERATED SKILL TABLE -->"


def _source_cell(source):
    if source == "from-scratch":
        return "from-scratch"
    if source.startswith("https://github.com/"):
        repo = source[len("https://github.com/") :]
        return f"[{repo}]({source})"
    return source


def build_skill_table(manifest):
    """Render the skill table (Markdown) from the manifest dict."""
    lines = [
        "| Skill | Stages | Licence | Integration | Source |",
        "|---|---|---|---|---|",
    ]
    for name in sorted(manifest["skills"]):
        skill = manifest["skills"][name]
        stages = ", ".join(skill["stages"])
        lines.append(
            f"| [{name}](skills/{name}) | {stages} | {skill['license']} | "
            f"{skill.get('integration', '')} | {_source_cell(skill.get('source', ''))} |"
        )
    return "\n".join(lines) + "\n"


def table_section(readme_text):
    """The table currently in README.md (between the markers)."""
    start = readme_text.index(BEGIN) + len(BEGIN)
    if not readme_text[start:].startswith("\n"):
        raise ValueError("the generated-table BEGIN marker must be followed by a newline")
    table_start = start + 1
    table_end = readme_text.index(END, table_start)
    return readme_text[table_start:table_end]


def replace_table(readme_text, manifest):
    """README.md with its skill table replaced by a fresh generation."""
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
