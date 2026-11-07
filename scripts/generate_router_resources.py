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

import re
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

Status: `built` (the need is covered in this install), `external-optional`
(not in this repo; the fallback is in `references/rules.md`, "Fallbacks for
external-optional skills"), `todo` (not built yet: say so plainly, do the
closest covered step, record the gap).

`Best source` is the source of inspiration for the need — it may be an
external tool that is not installed here. `Implemented in` names the
ORCINUS skill folder(s) that cover the need in this install (for an
external-optional row, the skill the router falls back to; `—` when
nothing covers it yet). A `built` row always names a real folder: the
validator checks it.
"""

# MAP rows whose covering skill the MAP text never names: the
# Integration and Best source columns name an upstream tool, not the
# ORCINUS skill that implements the need. Keyed by the MAP Need cell.
# Two rows only — every other row names its skill in the text.
_IMPLEMENTED_IN_FALLBACK = {
    "Mutation (JS/TS)": ["mutation-testing"],
    "Mutation beyond JS/TS": ["mutation-testing-python"],
    "Incomplete refactoring": ["incomplete-refactor"],
}


def _skills_named_in(text, skill_names):
    """Skill-folder names mentioned in `text`, in order of appearance,
    deduplicated. A name matches only as a whole hyphen-separated
    token, so `monitoring` does not match inside
    `monitoring-observability`."""
    hits = []
    for name in skill_names:
        pattern = r"(?<![A-Za-z0-9-])" + re.escape(name) + r"(?![A-Za-z0-9-])"
        for match in re.finditer(pattern, text):
            hits.append((match.start(), name))
    seen = []
    for _, name in sorted(hits):
        if name not in seen:
            seen.append(name)
    return seen


def _skill_named_in_need(need, skill_names):
    """The skill named by the Need cell itself, if any: the need
    hyphenated equals a skill (`Visual regression`), starts with one
    at a hyphen boundary (`Breaking-change detection`), or one of its
    words starts with a skill name (`Generic refactoring` ->
    `refactor`). Returns the longest match, or [] when nothing
    matches."""
    slug = re.sub(r"[^a-z0-9]+", "-", need.lower()).strip("-")
    candidates = []
    for name in skill_names:
        if slug == name or slug.startswith(name + "-"):
            candidates.append(name)
        elif any(w.startswith(name) and w != name for w in slug.split("-")):
            candidates.append(name)
    return [max(candidates, key=len)] if candidates else []


def implemented_in(need, source, integration, status, skill_names):
    """The ORCINUS skill folder(s) that cover one MAP need, derived
    from the MAP row itself: the Best source first (its trailing
    component is usually the skill — `monitoring`, not the
    `monitoring-observability` mentioned later in Integration), then
    the Integration column, then the Need cell, then the explicit
    fallback above. A `todo` row is covered by nothing. An
    external-optional row resolves to the skill the router falls back
    to, named in its Integration text."""
    if status == "todo":
        return []
    found = _skills_named_in(source, skill_names)
    if found:
        return found
    found = _skills_named_in(integration, skill_names)
    if found:
        return found
    found = _skill_named_in_need(need, skill_names)
    if found:
        return found
    return list(_IMPLEMENTED_IN_FALLBACK.get(need, []))


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


def generate_skill_status(map_text, skill_names=None):
    """Render references/skill-status.md from the MAP text."""
    if skill_names is None:
        skill_names = {p.name for p in (ROOT / "skills").iterdir() if p.is_dir()}
    sections = parse_map_tables(map_text)
    parts = [HEADER]
    for title, section in sections.items():
        parts.append(f"\n## {title}\n\n")
        parts.append("| Need | Best source | Implemented in | Status |\n")
        parts.append("|---|---|---|---|\n")
        for need, source, _licence, integration, status in section["rows"]:
            covered = ", ".join(implemented_in(need, source, integration, status, skill_names))
            parts.append(f"| {need} | {source} | {covered or '—'} | {status} |\n")
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
