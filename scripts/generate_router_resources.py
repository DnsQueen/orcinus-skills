#!/usr/bin/env python3
"""Generate the router's bundled resources from the canonical repo docs.

The router skill (skills/orcinus) must work from a standalone install,
where only the skill folders exist and the repo's docs/ does not. Two
resources travel with the router, generated from the canonical docs:

- skills/orcinus/references/skill-status.md — the status table of
  docs/MAP.md (which step is built, external-optional, or todo). The
  router's missing-skill decision procedure reads this file, never
  the repo's docs/MAP.md — in a user project docs/MAP.md is the user's
  file, not ORCINUS's.
- skills/orcinus/references/project-state.md — a byte-identical copy
  of docs/project-state.md (the .orcinus/state.json spec), like the
  bundled glossary.

Run: python3 scripts/generate_router_resources.py
Check (no writes): python3 scripts/generate_router_resources.py --check

Stdlib only. The output is deterministic: running the script twice
produces identical bytes, so the repo validator can compare the
committed files against a fresh generation.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

HEADER = """# Skill status — GENERATED, do not edit by hand

Generated from `docs/MAP.md` by `scripts/generate_router_resources.py`.
Re-run the script after any change to `docs/MAP.md`.

The canonical MAP lives in the ORCINUS repo. This copy travels with the
router skill so a standalone install — which has no `docs/` — still has
the decision table. Never read the user's own `docs/MAP.md`: that is the
user's file, not ORCINUS's.

Status: `built` (in this install), `external-optional` (not in this repo;
the fallback is in `references/rules.md`, "Fallbacks for external-optional
skills"), `todo` (not built yet: say so plainly, do the closest covered
step, record the gap).
"""


def parse_map_tables(map_text):
    """Parse the section tables (A-G) of docs/MAP.md.

    Returns an ordered {section title: {"rows": [[need, source, licence,
    integration, status], ...]}} mapping. Header and separator rows are
    skipped; only rows inside the A-G sections are read.
    """
    sections = {}
    current = None
    for line in map_text.splitlines():
        if line.startswith("## "):
            title = line[3:].strip()
            # Sections A-G are the stage tables; later sections
            # ("Must write from scratch", "Do not use", "Sources ...")
            # hold no status table.
            current = title if title and title[0] in "ABCDEFG" and title[1] == " " else None
            if current is not None:
                sections[current] = {"rows": []}
            continue
        if current is None or not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cells[0] == "Need" or set(cells[0]) <= set("-: "):
            continue
        if len(cells) != 5:
            raise ValueError(f"MAP row does not have 5 cells: {line!r}")
        sections[current]["rows"].append(cells)
    return sections


def generate_skill_status(map_text):
    """Render references/skill-status.md from the MAP text."""
    sections = parse_map_tables(map_text)
    parts = [HEADER]
    for title, section in sections.items():
        parts.append(f"\n## {title}\n\n")
        parts.append("| Need | Best source | Status |\n")
        parts.append("|---|---|---|\n")
        for need, source, _licence, _integration, status in section["rows"]:
            parts.append(f"| {need} | {source} | {status} |\n")
    return "".join(parts)


def write_router_resources(root):
    """Write both bundled files under root/skills/orcinus/references/."""
    references = root / "skills" / "orcinus" / "references"
    references.mkdir(parents=True, exist_ok=True)
    map_text = (root / "docs" / "MAP.md").read_text(encoding="utf-8")
    (references / "skill-status.md").write_text(generate_skill_status(map_text), encoding="utf-8")
    (references / "project-state.md").write_bytes((root / "docs" / "project-state.md").read_bytes())


def check_router_resources(root):
    """True when the bundled files match a fresh generation."""
    references = root / "skills" / "orcinus" / "references"
    status_file = references / "skill-status.md"
    state_file = references / "project-state.md"
    if not status_file.is_file() or not state_file.is_file():
        return False
    map_text = (root / "docs" / "MAP.md").read_text(encoding="utf-8")
    if status_file.read_text(encoding="utf-8") != generate_skill_status(map_text):
        return False
    return state_file.read_bytes() == (root / "docs" / "project-state.md").read_bytes()


def main(argv):
    check_only = "--check" in argv
    if check_only:
        return 0 if check_router_resources(ROOT) else 1
    write_router_resources(ROOT)
    print("Wrote skills/orcinus/references/skill-status.md")
    print("Wrote skills/orcinus/references/project-state.md")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
