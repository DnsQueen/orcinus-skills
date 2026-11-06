#!/usr/bin/env python3
"""Regenerate skills/manifest.json from its sources.

The manifest is a registry, not a hand-edited file: its derived
fields are copied from their sources, and its curated fields are
preserved from the existing manifest. Run after adding, removing,
re-staging, or re-licensing a skill:

    python3 scripts/generate_manifest.py

Derived (overwritten every run):
  description — the skill's SKILL.md frontmatter description,
    with surrounding whitespace stripped (a folded scalar ends in
    a newline; the manifest stores the description without it).
  license — the SKILL.md frontmatter license.
  stages — skills/stages.json, the single stage registry.

Curated (preserved from the existing manifest; edit them there):
  integration — how the skill relates to its upstream: verbatim,
    wrapper, merged, or from-scratch (see scripts/validate_repo.py
    check_manifest for the definitions). Required: a skill without a
    valid integration fails the generator, so a new skill must be
    classified when it is added.
  supported_frameworks — the frameworks a framework-scoped skill
    applies to (for example ["React", "React Native"] for the three
    frontend skills). Optional; when present it must be a non-empty
    list of names. The router's rules.md carries the applicability
    guard; this field is the machine-readable record of it.
  source — the upstream repo as a full github.com URL, or
    "from-scratch". owner/repo is not accepted.
  upstream_commit — the upstream commit the skill was copied from,
    or null (null exactly when integration is "from-scratch"; a
    40-hex SHA is required otherwise).
  status — built, external-optional, or todo.

The manifest version is 2 (v2 adds the required integration field).

Exit 0 when the manifest was written; exit 1 when a skill folder
has no stages entry (or vice versa), or a frontmatter field is
missing. The validator (scripts/validate_repo.py) checks the same
invariants, so a hand-edited manifest that disagrees with its
sources fails the build.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import validate_repo as vr  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = ROOT / "skills" / "manifest.json"
STAGES_PATH = ROOT / "skills" / "stages.json"


def main():
    try:
        stages_data = json.loads(STAGES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"cannot read {STAGES_PATH}: {e}", file=sys.stderr)
        return 1
    stages = stages_data.get("stages")
    if not isinstance(stages, dict):
        print(f"{STAGES_PATH} has no 'stages' object", file=sys.stderr)
        return 1
    try:
        old = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"cannot read {MANIFEST_PATH}: {e}", file=sys.stderr)
        return 1
    old_entries = old.get("skills", {})
    if not isinstance(old_entries, dict):
        print(f"{MANIFEST_PATH} has no 'skills' object", file=sys.stderr)
        return 1

    folders = {d.name for d in (ROOT / "skills").iterdir() if d.is_dir()}
    errors = []
    for name in sorted(folders - set(stages)):
        errors.append(f"skill folder skills/{name} has no entry in skills/stages.json")
    for name in sorted(set(stages) - folders):
        errors.append(f"skills/stages.json lists {name}, but there is no skills/{name} folder")
    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 1

    entries = {}
    for name in sorted(folders):
        fields, err = vr.parse_frontmatter(ROOT / "skills" / name / "SKILL.md")
        if err:
            errors.append(f"{name}/SKILL.md: {err}")
            continue
        if not isinstance(fields.get("description"), str):
            errors.append(f"{name}/SKILL.md: frontmatter description is missing or not a string")
            continue
        if not isinstance(fields.get("license"), str):
            errors.append(f"{name}/SKILL.md: frontmatter license is missing or not a string")
            continue
        old_entry = old_entries.get(name, {})
        integration = old_entry.get("integration")
        if integration not in ("verbatim", "wrapper", "merged", "from-scratch"):
            errors.append(
                f"{name}: manifest has no valid 'integration' field — "
                f"set 'verbatim', 'wrapper', 'merged', or 'from-scratch'"
            )
            continue
        entries[name] = {
            "name": name,
            "description": fields["description"].strip(),
            "license": fields["license"],
            "stages": stages[name],
            "source": old_entry.get("source", "from-scratch"),
            "integration": integration,
            "upstream_commit": old_entry.get("upstream_commit"),
            "status": old_entry.get("status", "built"),
        }
        if old_entry.get("supported_frameworks") is not None:
            entries[name]["supported_frameworks"] = old_entry["supported_frameworks"]
    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 1
    manifest = {
        "version": 2,
        "generated_by": (
            "Generated by scripts/generate_manifest.py from SKILL.md "
            "frontmatter (description, license) and skills/stages.json "
            "(stages). integration, source, upstream_commit, and status "
            "are curated here — edit them in this file, then re-run "
            "the generator."
        ),
        "skills": entries,
    }
    MANIFEST_PATH.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"wrote {MANIFEST_PATH} ({len(entries)} skills)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
