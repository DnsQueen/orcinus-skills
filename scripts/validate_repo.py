#!/usr/bin/env python3
"""Validate the ORCINUS repo: the checks CI runs on every change.

Stdlib only. Exit 0 when clean, 1 when any check fails. Run:
    python3 scripts/validate_repo.py

Checks:
  1. Every skills/*/SKILL.md has valid frontmatter: name matches the
     folder, description is non-empty, license is present and known,
     and the file is under 500 lines.
  2. ATTRIBUTION.md and LICENSE.txt come in pairs: a skill folder with
     one must have the other.
  3. The frontmatter license agrees with ATTRIBUTION.md and with
     LICENSE.txt (when they exist).
  4. THIRD_PARTY_NOTICES.md lists every skill that bundles upstream
     content, with a license that agrees with the frontmatter. The
     table's first column is parsed exactly — a substring match would
     let a missing row hide behind a longer name (monitoring inside
     monitoring-observability).
  5. The glossary bundled in skills/orcinus/references/ is identical
     to the canonical GLOSSARY.md at the repo root.
  6. The stage ranges in the router agree with docs/MAP.md, including
     Idea and Finalize, and the router's linear stages do not overlap.
  7. .claude-plugin/plugin.json and marketplace.json are valid JSON
     with the required fields, and the plugin's skills/ exists. The
     skill counts stated in plugin.json ("Router + N focused
     sub-skills") and README.md ("all N skills") must match the
     actual number of skill folders.
  8. Relative paths mentioned in README.md, SCOPE.md and docs/MAP.md
     (skills/..., docs/..., evals/..., examples/...) exist.

A check that cannot run (missing file it needs) is reported as a
failure, never silently skipped — except where the check itself says
otherwise. Dates in this repo are Asia/Tehran local time unless a
file says UTC.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KNOWN_LICENSES = {
    "MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC",
    "CC-BY-4.0", "CC-BY-SA-4.0", "Unlicense",
}
MAX_SKILL_LINES = 500

failures = []
warnings = []


def fail(msg):
    failures.append(msg)


def warn(msg):
    warnings.append(msg)


def parse_frontmatter(path):
    """Parse the YAML frontmatter of a SKILL.md (simple key: value,
    with indented continuation lines). Returns (fields, error)."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return None, "missing frontmatter (must start with ---)"
    end = text.find("\n---\n", 4)
    if end < 0:
        return None, "frontmatter is not closed with ---"
    fields = {}
    current_key = None
    for line in text[4:end].splitlines():
        if not line.strip():
            continue
        if line[0] in " \t" and current_key is not None:
            fields[current_key] += " " + line.strip()
            continue
        if ":" not in line:
            return None, f"frontmatter line has no colon: {line!r}"
        key, value = line.split(":", 1)
        current_key = key.strip()
        value = value.strip()
        # Strip surrounding quotes (YAML allows name: "foo").
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        fields[current_key] = value
    return fields, None


def check_skill_frontmatter():
    skills_dir = ROOT / "skills"
    if not skills_dir.is_dir():
        fail("skills/ directory is missing")
        return
    for skill_dir in sorted(skills_dir.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill = skill_dir / "SKILL.md"
        if not skill.is_file():
            fail(f"{skill_dir.name}: SKILL.md is missing")
            continue
        lines = skill.read_text(encoding="utf-8").splitlines()
        if len(lines) >= MAX_SKILL_LINES:
            fail(f"{skill_dir.name}/SKILL.md: {len(lines)} lines, "
                 f"over the {MAX_SKILL_LINES}-line cap")
        fields, err = parse_frontmatter(skill)
        if err:
            fail(f"{skill_dir.name}/SKILL.md: {err}")
            continue
        if fields.get("name") != skill_dir.name:
            fail(f"{skill_dir.name}/SKILL.md: frontmatter name is "
                 f"{fields.get('name')!r}, expected {skill_dir.name!r}")
        if not fields.get("description"):
            fail(f"{skill_dir.name}/SKILL.md: frontmatter description is missing")
        lic = fields.get("license")
        if not lic:
            fail(f"{skill_dir.name}/SKILL.md: frontmatter license is missing")
        elif lic not in KNOWN_LICENSES:
            fail(f"{skill_dir.name}/SKILL.md: unknown license {lic!r}")


def license_from_file(path):
    """Best-effort license identifier from a LICENSE.txt."""
    text = path.read_text(encoding="utf-8", errors="ignore")
    if "Apache License" in text and "Version 2.0" in text:
        return "Apache-2.0"
    if text.startswith("MIT License"):
        return "MIT"
    if "BSD 3-Clause" in text or "Redistribution and use in source and binary forms" in text and "Neither the name" in text:
        return "BSD-3-Clause"
    if "BSD 2-Clause" in text:
        return "BSD-2-Clause"
    if "ISC License" in text or text.startswith("ISC"):
        return "ISC"
    return None


def check_attribution_pairs():
    for skill_dir in sorted((ROOT / "skills").iterdir()):
        if not skill_dir.is_dir():
            continue
        attr = skill_dir / "ATTRIBUTION.md"
        lic = skill_dir / "LICENSE.txt"
        # A LICENSE.txt without an ATTRIBUTION.md is unexplained upstream
        # content; an ATTRIBUTION.md without a LICENSE.txt is fine when
        # nothing was copied verbatim (own-words merge), but not when the
        # content was copied or bundled as-is.
        if lic.is_file() and not attr.is_file():
            fail(f"{skill_dir.name}: LICENSE.txt exists but ATTRIBUTION.md "
                 f"is missing — explain the upstream source")
            continue
        if not attr.is_file():
            continue
        attr_text = attr.read_text(encoding="utf-8")
        lower = attr_text.lower()
        # Upstream files are in this folder when the ATTRIBUTION says so
        # positively: "byte-identical", "bundled", or "copied verbatim".
        # A negative mention ("neither SKILL.md verbatim", "no code was
        # copied") does not count, and an own-words method that merely
        # uses a tool as-is does not put the tool's files in the folder.
        copied = bool(re.search(
            r"byte-identical|bundled|copied verbatim|is verbatim|are verbatim",
            lower))
        if copied and not lic.is_file():
            fail(f"{skill_dir.name}: ATTRIBUTION.md says upstream content "
                 f"was copied or bundled, but LICENSE.txt is missing")
            continue
        # Frontmatter license must agree with ATTRIBUTION.md and LICENSE.txt.
        fields, err = parse_frontmatter(skill_dir / "SKILL.md")
        if err:
            continue
        front = fields.get("license")
        # The licence line is written as "Licence: MIT" or
        # "Licence: Apache License 2.0" — normalize both forms.
        m = re.search(r"\*\*Licen[cs]e:\*\*\s*([^\n—]+)", attr_text)
        attr_lic = None
        if m:
            raw = m.group(1).strip()
            if raw.startswith("Apache License 2.0") or raw.startswith("Apache-2.0"):
                attr_lic = "Apache-2.0"
            elif raw.startswith("MIT"):
                attr_lic = "MIT"
            elif raw.startswith("BSD-3-Clause"):
                attr_lic = "BSD-3-Clause"
            elif raw.startswith("BSD-2-Clause"):
                attr_lic = "BSD-2-Clause"
            elif raw.startswith("ISC"):
                attr_lic = "ISC"
        if attr_lic and attr_lic != front:
            # The frontmatter license is the SKILL.md text's license; the
            # ATTRIBUTION license is the upstream source's. They must agree
            # when the SKILL.md itself is verbatim, but they may differ
            # legitimately for an own-words wrapper around an upstream tool
            # (e.g. breaking-change: MIT text, Apache-2.0 oasdiff CLI;
            # independent-review: MIT text, Apache-2.0 bundled agents).
            # In that case the ATTRIBUTION must say the method is own
            # words — which it does, so the split is documented.
            lower = attr_text.lower()
            if "own words" not in lower and "own-words" not in lower:
                fail(f"{skill_dir.name}: ATTRIBUTION.md says license "
                     f"{attr_lic!r} but the frontmatter says {front!r}")
        file_lic = license_from_file(lic) if lic.is_file() else None
        if file_lic and file_lic != front:
            # The frontmatter license is the skill's own text; the
            # LICENSE.txt is the bundled files' license. They may
            # differ legitimately (e.g. independent-review: MIT text,
            # Apache-2.0 bundled agents) — but then ATTRIBUTION.md
            # must say so explicitly.
            if "bundled" not in attr_text.lower() and "own-words" not in attr_text.lower() and "own words" not in attr_text.lower():
                fail(f"{skill_dir.name}: LICENSE.txt is {file_lic} but the "
                     f"frontmatter says {front!r}, and ATTRIBUTION.md does "
                     f"not explain the split")


def _resolve_inside(relative):
    """Resolve a repo-relative path and require it to stay inside ROOT.
    Returns the resolved Path, or None when it escapes. (str.lstrip
    is not a prefix strip: "../outside".lstrip("./") is "outside", so
    a path escaping the repo would have passed as valid.)"""
    target = (ROOT / relative).resolve()
    return target if target.is_relative_to(ROOT) else None


def _notices_table_names(text):
    """The skill names in the first column of the THIRD_PARTY_NOTICES
    table, as an exact set. A substring check would let a missing row
    hide behind a longer name (monitoring inside
    monitoring-observability), so the table is parsed, not searched."""
    names = set()
    in_table = False
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if not cells:
            continue
        if cells[0].lower() == "skill":
            in_table = True
            continue
        if in_table and set(cells[0]) <= set("-: "):
            continue  # the |---|---| separator row
        if in_table and cells[0]:
            names.add(cells[0])
    return names


def check_third_party_notices():
    manifest = ROOT / "THIRD_PARTY_NOTICES.md"
    if not manifest.is_file():
        fail("THIRD_PARTY_NOTICES.md is missing")
        return
    text = manifest.read_text(encoding="utf-8")
    listed = _notices_table_names(text)
    # Every skill that has an ATTRIBUTION.md must be listed.
    for skill_dir in sorted((ROOT / "skills").iterdir()):
        if not skill_dir.is_dir():
            continue
        if (skill_dir / "ATTRIBUTION.md").is_file():
            if skill_dir.name not in listed:
                fail(f"THIRD_PARTY_NOTICES.md does not list "
                     f"{skill_dir.name} (it has an ATTRIBUTION.md)")
    # Every skill listed must exist and its license must agree with the
    # upstream license recorded in its ATTRIBUTION.md (the manifest
    # records the third-party content's license, which for an own-words
    # wrapper can differ from the skill's own frontmatter license).
    for name in re.findall(r"\|\s*([a-z0-9][a-z0-9-]*)\s*\|", text):
        skill_dir = ROOT / "skills" / name
        if not skill_dir.is_dir():
            fail(f"THIRD_PARTY_NOTICES.md lists {name}, but no such skill exists")
            continue
        attr = skill_dir / "ATTRIBUTION.md"
        if not attr.is_file():
            fail(f"THIRD_PARTY_NOTICES.md lists {name}, but it has no ATTRIBUTION.md")
            continue
        attr_text = attr.read_text(encoding="utf-8")
        m = re.search(r"\*\*Licen[cs]e:\*\*\s*([^\n—]+)", attr_text)
        attr_lic = None
        if m:
            raw = m.group(1).strip()
            if raw.startswith("Apache License 2.0") or raw.startswith("Apache-2.0"):
                attr_lic = "Apache-2.0"
            elif raw.startswith("MIT"):
                attr_lic = "MIT"
            elif raw.startswith("BSD-3-Clause"):
                attr_lic = "BSD-3-Clause"
            elif raw.startswith("BSD-2-Clause"):
                attr_lic = "BSD-2-Clause"
            elif raw.startswith("ISC"):
                attr_lic = "ISC"
        row = re.search(rf"\|\s*{re.escape(name)}\s*\|[^|]*\|\s*([A-Za-z0-9.+-]+)\s*\|", text)
        if row and attr_lic and row.group(1) != attr_lic:
            fail(f"THIRD_PARTY_NOTICES.md says {name} is {row.group(1)} "
                 f"but its ATTRIBUTION.md says {attr_lic!r}")


def check_glossary_copy():
    root_glossary = ROOT / "GLOSSARY.md"
    bundled = ROOT / "skills" / "orcinus" / "references" / "GLOSSARY.md"
    if not root_glossary.is_file():
        fail("GLOSSARY.md is missing at the repo root")
        return
    if not bundled.is_file():
        fail("skills/orcinus/references/GLOSSARY.md is missing — the "
             "router's glossary must travel with the skill")
        return
    if root_glossary.read_bytes() != bundled.read_bytes():
        fail("skills/orcinus/references/GLOSSARY.md differs from the "
             "canonical GLOSSARY.md — copy the root file over it")


def _stage_ranges(text):
    """Extract {stage: (low, high)} from 'Name (low–high)' mentions.
    Stage names may contain a hyphen ("Finalize / Post-publish")."""
    out = {}
    for m in re.finditer(r"([A-Za-z /-]+?)\s*\((\d+)\s*[–-]\s*(\d+)[^)]*\)", text):
        out[m.group(1).strip()] = (int(m.group(2)), int(m.group(3)))
    return out


def check_stage_ranges():
    router = ROOT / "skills" / "orcinus" / "SKILL.md"
    map_file = ROOT / "docs" / "MAP.md"
    if not router.is_file() or not map_file.is_file():
        fail("router SKILL.md or docs/MAP.md is missing")
        return
    router_ranges = _stage_ranges(router.read_text(encoding="utf-8"))
    map_ranges = _stage_ranges(map_file.read_text(encoding="utf-8"))
    # Canonical mapping: router stage name -> (MAP section name, how they
    # must relate). A top-level stage must equal the MAP section; a
    # sub-stage (Scaffold, Build) must lie inside the MAP section.
    # Security and Debugging are cross-cutting: they share the 50–79
    # band by design (they can apply at any linear stage), so they are
    # checked for equality with the MAP but are not part of the
    # non-overlap check below.
    mapping = {
        "Idea": ("Idea", "equal"),
        "Architecture": ("Architecture / Setup", "equal"),
        "Scaffold": ("Coding", "inside"),
        "Build": ("Coding", "inside"),
        "Verify": ("Testing / Verification", "equal"),
        "Security": ("Security / Health", "equal"),
        "Debugging": ("Debugging / Refactor", "equal"),
        "Finalize": ("Finalize / Post-publish", "equal"),
    }
    for router_name, (map_name, relation) in mapping.items():
        r = router_ranges.get(router_name)
        m = map_ranges.get(map_name)
        if r is None:
            fail(f"router does not define a range for {router_name}")
        elif m is None:
            fail(f"docs/MAP.md does not define a range for {map_name}")
        elif relation == "equal" and r != m:
            fail(f"stage range mismatch: router {router_name} is "
                 f"{r[0]}–{r[1]} but MAP {map_name} is {m[0]}–{m[1]}")
        elif relation == "inside" and not (m[0] <= r[0] and r[1] <= m[1]):
            fail(f"stage range mismatch: router {router_name} is "
                 f"{r[0]}–{r[1]}, which is not inside MAP {map_name} "
                 f"{m[0]}–{m[1]}")
    # The linear stages must not overlap: a stage detected from
    # evidence must name one stage, not two.
    linear = ["Idea", "Architecture", "Scaffold", "Build", "Verify", "Finalize"]
    prev = None
    for name in linear:
        r = router_ranges.get(name)
        if r is None:
            continue
        if prev is not None and r[0] <= prev[1]:
            fail(f"linear stage ranges overlap: {name} starts at "
                 f"{r[0]} but the previous stage ends at {prev[1]}")
        prev = r


def check_plugin_manifests():
    plugin_dir = ROOT / ".claude-plugin"
    plugin = plugin_dir / "plugin.json"
    marketplace = plugin_dir / "marketplace.json"
    for path, required in (
        (plugin, ["name", "version", "description", "author"]),
        (marketplace, ["name", "owner", "plugins"]),
    ):
        if not path.is_file():
            fail(f"{path.relative_to(ROOT)} is missing")
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            fail(f"{path.relative_to(ROOT)} is not valid JSON: {e}")
            continue
        for field in required:
            if field not in data:
                fail(f"{path.relative_to(ROOT)} is missing required field {field!r}")
    if plugin.is_file():
        try:
            data = json.loads(plugin.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
        for skill_path in data.get("skills", []):
            target = _resolve_inside(skill_path)
            if target is None or not target.is_dir():
                fail(f"plugin.json lists skills path {skill_path!r}, which does not exist"
                     + (" (it escapes the repo)" if target is None else ""))
    if marketplace.is_file():
        try:
            data = json.loads(marketplace.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
        for entry in data.get("plugins", []):
            source = entry.get("source", "")
            if source.startswith("./"):
                target = _resolve_inside(source)
                if target is None or not target.is_dir():
                    fail(f"marketplace.json plugin {entry.get('name')!r} has "
                         f"source {source!r}, which does not exist"
                         + (" (it escapes the repo)" if target is None else ""))


def check_skill_counts():
    """The skill counts stated in plugin.json and README.md must match
    the actual number of skill folders. A stale number is a real
    inconsistency (plugin.json once said "Router + 34" for 36 folders)."""
    skills = [d for d in sorted((ROOT / "skills").iterdir()) if d.is_dir()]
    count = len(skills)
    plugin = ROOT / ".claude-plugin" / "plugin.json"
    if plugin.is_file():
        try:
            data = json.loads(plugin.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
        m = re.search(r"Router \+ (\d+) focused sub-skills",
                      data.get("description", ""))
        if m is None:
            fail("plugin.json description does not state the sub-skill "
                 "count as 'Router + N focused sub-skills'")
        elif int(m.group(1)) != count - 1:
            fail(f"plugin.json says 'Router + {m.group(1)} focused "
                 f"sub-skills' but there are {count} skill folders "
                 f"(router + {count - 1})")
    readme = ROOT / "README.md"
    if readme.is_file():
        text = readme.read_text(encoding="utf-8")
        m = re.search(r"all (\d+) skills", text)
        if m is None:
            fail("README.md does not state the skill count as 'all N skills'")
        elif int(m.group(1)) != count:
            fail(f"README.md says 'all {m.group(1)} skills' but there "
                 f"are {count} skill folders")


def check_manifest():
    """skills/manifest.json is the single source of truth for the skill
    inventory: name, licence, stages, source, and status per skill.
    It must agree with the actual skill folders and with each skill's
    frontmatter, so a skill added, removed, or re-licensed without
    updating the manifest fails the build."""
    path = ROOT / "skills" / "manifest.json"
    if not path.is_file():
        fail("skills/manifest.json is missing")
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        fail(f"skills/manifest.json is not valid JSON: {e}")
        return
    entries = data.get("skills")
    if not isinstance(entries, dict):
        fail("skills/manifest.json has no 'skills' object")
        return
    dirs = {d.name for d in (ROOT / "skills").iterdir() if d.is_dir()}
    for name in sorted(dirs - set(entries)):
        fail(f"skill folder skills/{name} is not in skills/manifest.json")
    for name in sorted(set(entries) - dirs):
        fail(f"skills/manifest.json lists {name}, but there is no "
             f"skills/{name} folder")
    valid_stages = {"0-9", "10-19", "20-39", "40-59", "50-79",
                    "80-100", "0-100"}
    for name in sorted(set(entries) & dirs):
        entry = entries[name]
        if not isinstance(entry, dict):
            fail(f"skills/manifest.json entry for {name} is not an object")
            continue
        fm, _err = parse_frontmatter(ROOT / "skills" / name / "SKILL.md")
        lic = fm.get("license") if fm else None
        if entry.get("license") != lic:
            fail(f"skills/manifest.json says {name} is licensed "
                 f"{entry.get('license')!r}, but its SKILL.md frontmatter "
                 f"says {lic!r}")
        stages = entry.get("stages")
        if not isinstance(stages, list) or not stages:
            fail(f"skills/manifest.json entry for {name} has no stages")
        else:
            for s in stages:
                if s not in valid_stages:
                    fail(f"skills/manifest.json entry for {name} has "
                         f"unknown stage {s!r}")
        if entry.get("status") not in ("built", "external-optional", "todo"):
            fail(f"skills/manifest.json entry for {name} has unknown "
                 f"status {entry.get('status')!r}")
        if not entry.get("source"):
            fail(f"skills/manifest.json entry for {name} has no source")


def check_json_files():
    """Every JSON file the repo owns must parse. A broken manifest or
    evidence schema is a silent gate failure: the validator would
    crash (or skip) instead of checking."""
    for rel in ("skills/manifest.json", "evals/evidence.schema.json",
                ".claude-plugin/plugin.json",
                ".claude-plugin/marketplace.json"):
        path = ROOT / rel
        if not path.is_file():
            continue
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            fail(f"{rel} is not valid JSON: {e}")


def check_relative_paths():
    for doc in ("README.md", "SCOPE.md", "docs/MAP.md"):
        path = ROOT / doc
        if not path.is_file():
            fail(f"{doc} is missing")
            continue
        text = path.read_text(encoding="utf-8")
        for ref in sorted(set(re.findall(r"(?:skills|docs|evals|examples)/[A-Za-z0-9_./-]+", text))):
            ref = ref.rstrip(").,")
            if not (ROOT / ref).exists():
                fail(f"{doc} references {ref}, which does not exist")


def main():
    check_skill_frontmatter()
    check_attribution_pairs()
    check_third_party_notices()
    check_glossary_copy()
    check_stage_ranges()
    check_plugin_manifests()
    check_skill_counts()
    check_manifest()
    check_json_files()
    check_relative_paths()
    for w in warnings:
        print(f"warning: {w}")
    if failures:
        print(f"FAIL: {len(failures)} problem(s)")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("OK: repo validation passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
