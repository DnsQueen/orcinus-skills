#!/usr/bin/env python3
"""Check that vendored (upstream-copied) files have not drifted.

Reads scripts/drift-manifest.json — a map of repo-relative path to the
SHA256 the file had when it was last recorded — and verifies each file
still matches. A mismatch means someone edited a vendored file without
recording the change in that skill's ATTRIBUTION.md, or the file was
deleted. A match does not prove the file is still identical to upstream
(it proves it is identical to the last recorded ORCINUS copy); to check
against upstream, re-run the diff against the upstream commit named in
the ATTRIBUTION.

Usage:
    python3 scripts/check_drift.py            # check the manifest
    python3 scripts/check_drift.py --update   # regenerate the manifest
                                                # from the current files
                                                # (only after a recorded
                                                # change, and only with
                                                # the ATTRIBUTION updated)

Exit code: 0 when every listed file matches, 1 otherwise.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "scripts" / "drift-manifest.json"

# Skills whose files are vendored from upstream (copied verbatim or
# bundled as-is). ORCINUS-original from-scratch skills are not listed:
# their files change freely and are not vendored.
VENDORED_SKILLS = [
    "accessibility",
    "api-and-interface-design",
    "ask-questions-if-underspecified",
    "codebase-knowledge-builder",
    "database-designer",
    "diagnosing-bugs",
    "frontend-architecture",
    "frontend-data-contracts",
    "frontend-optimistic-mutations",
    "i18n",
    "independent-review",
    "issue-triage",
    "mcp-builder",
    "monitoring",
    "monitoring-observability",
    "performance-optimization",
    "refactor",
    "skill-creator",
    "waza",
    "webapp-testing",
]

# Vendored files that live at the plugin root, not inside a skill:
# Claude Code discovers agents/commands by folder at the plugin
# root, so the pr-review-toolkit agents/command and the
# skill-creator agents moved there (round 3, track 8). Their
# upstream provenance is recorded in the owning skill's
# ATTRIBUTION.md; the skill-creator agents additionally carry
# ORCINUS-added frontmatter (name + description), recorded there.
# build_manifest() glob-scans agents/ and commands/ instead of
# listing them: a hardcoded list made a new file under either
# directory invisible. A new file is reported unrecorded until it
# is either recorded in the manifest (vendored) or listed in
# ORCINUS_ROOT_FILES (ORCINUS-authored).
ORCINUS_ROOT_FILES: set[str] = set()

# Test files inside a vendored skill that are ORCINUS-authored, not
# vendored. An explicit allowlist, not a name heuristic: a file
# named test_*.py that is NOT listed here is treated as vendored,
# so a new upstream test file (or a misplaced ORCINUS file) cannot
# slip past the check unrecorded. Verified against upstream at the
# pinned commits named in each skill's ATTRIBUTION.md (2026-11-06):
# - database-designer (alirezarezvani/claude-skills @ 8f08254):
#   upstream has no test files at all.
# - webapp-testing (anthropics/skills @ ca45fc4): upstream has no
#   test files at all.
ORCINUS_TEST_FILES = {
    "skills/accessibility/scripts/test_check_accessibility.py",
    "skills/database-designer/test_migration_generator.py",
    "skills/database-designer/test_migration_integration.py",
    "skills/database-designer/test_postgres_migration.py",
    "skills/mcp-builder/scripts/test_mcp_builder.py",
    "skills/skill-creator/scripts/test_package_skill.py",
    "skills/skill-creator/scripts/test_quick_validate.py",
    "skills/skill-creator/scripts/test_run_eval.py",
    "skills/webapp-testing/scripts/test_with_server.py",
}

# Files inside a vendored skill that are ORCINUS-authored, not vendored.
EXCLUDED_NAMES = {"ATTRIBUTION.md", "LICENSE.txt"}
EXCLUDED_SUFFIXES = (".pyc",)
EXCLUDED_DIRS = {"__pycache__"}


def _manifest_key(rel: Path) -> str:
    """Manifest keys are always forward-slash (posix) paths. The
    manifest is recorded on Linux, and str() of a relative path
    uses the OS separator — backslashes on Windows — so a Windows
    build produced keys that never matched the manifest and every
    vendored file was reported 'unrecorded' (CI 0.9.4, windows job:
    130 unrecorded)."""
    return rel.as_posix()


def _is_vendored(path: Path) -> bool:
    rel = path.relative_to(ROOT)
    parts = rel.parts
    if len(parts) < 2 or parts[0] != "skills":
        return False
    if parts[1] not in VENDORED_SKILLS:
        return False
    if parts[-1] in EXCLUDED_NAMES:
        return False
    if path.suffix in EXCLUDED_SUFFIXES:
        return False
    if any(part in EXCLUDED_DIRS for part in parts):
        return False
    # ORCINUS-authored test files inside a vendored skill (explicit
    # allowlist — a test_*.py that is not listed is vendored).
    if rel.as_posix() in ORCINUS_TEST_FILES:
        return False
    return True


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_manifest() -> dict:
    manifest = {}
    for skill in VENDORED_SKILLS:
        skill_dir = ROOT / "skills" / skill
        if not skill_dir.is_dir():
            continue
        for path in sorted(skill_dir.rglob("*")):
            if path.is_file() and _is_vendored(path):
                manifest[_manifest_key(path.relative_to(ROOT))] = _sha256(path)
    for root_dir in ("agents", "commands"):
        dir_path = ROOT / root_dir
        if not dir_path.is_dir():
            continue
        for path in sorted(dir_path.rglob("*")):
            if not path.is_file():
                continue
            rel = _manifest_key(path.relative_to(ROOT))
            if rel in ORCINUS_ROOT_FILES:
                continue
            manifest[rel] = _sha256(path)
    return manifest


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--update", action="store_true", help="regenerate the manifest from the current files"
    )
    args = parser.parse_args(argv)
    if args.update:
        manifest = build_manifest()
        if not manifest:
            # Empty-scan guard (0.12.4): the collection is known to
            # hold vendored files, so a scan that finds none is a
            # broken instrument — writing it out would destroy the
            # recorded checksums. Adapted from
            # rebelytics/one-skill-to-rule-them-all (CC-BY-4.0,
            # pattern only): a scan over content known to exist that
            # returns nothing must fail loudly.
            print(
                "FAIL: SCAN BROKEN — the vendored-file scan found "
                "nothing, but the collection is known to hold vendored "
                "files; refusing to overwrite the manifest with an "
                "empty one",
                file=sys.stderr,
            )
            return 1
        MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {MANIFEST} ({len(manifest)} files)")
        return 0
    if not MANIFEST.exists():
        print(f"FAIL: manifest not found: {MANIFEST}", file=sys.stderr)
        print("Run: python3 scripts/check_drift.py --update", file=sys.stderr)
        return 1
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if not manifest:
        # Empty-scan guard (0.12.4): the manifest is known to record
        # the vendored files, so an empty manifest is a broken
        # instrument, not an empty collection — without it the check
        # below passes on zero entries. Adapted from
        # rebelytics/one-skill-to-rule-them-all (CC-BY-4.0, pattern
        # only): a scan over content known to exist that returns
        # nothing must fail loudly.
        print(
            "FAIL: SCAN BROKEN — the drift manifest is empty, but the "
            "collection is known to hold vendored files",
            file=sys.stderr,
        )
        return 1
    problems = []
    for rel, expected in sorted(manifest.items()):
        path = ROOT / rel
        if not path.exists():
            problems.append(f"missing: {rel}")
        elif _sha256(path) != expected:
            problems.append(
                f"drifted: {rel} (changed since the manifest was recorded — update the skill's ATTRIBUTION.md and regenerate the manifest)"
            )
    # A vendored file that is not in the manifest is also a problem:
    # it was added without being recorded.
    for rel in sorted(build_manifest()):
        if rel not in manifest:
            problems.append(
                f"unrecorded: {rel} (a vendored file with no recorded checksum — add it to the manifest)"
            )
    if problems:
        print(f"FAIL: {len(problems)} problem(s)")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print(f"OK: {len(manifest)} vendored files match the recorded checksums")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
