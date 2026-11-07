#!/usr/bin/env python3
"""ORCINUS accessibility gate — audit with the ultra11y engine, but
never report a check that did not run as passed.

The vendored engine (skills/accessibility/scripts/ultra11y.mjs)
silently skips an input it cannot find: it warns on stderr, audits
zero files, reports conformancePct 100, and exits 0. This wrapper
is the gate: it pre-checks every explicit input exists and is
readable, fails a glob that matches nothing, runs the engine, and
fails when the engine audited zero files — even when the engine
itself exits 0. The engine is not edited: it is bundled verbatim
from upstream (see skills/accessibility/ATTRIBUTION.md).

Upstream follow-up (open): report the silent skip to
maxgfr/ultra11y — the wrapper is the ORCINUS-side fix, not an
upstream fix.

Usage:
    python3 skills/accessibility/scripts/check_accessibility.py <page-or-glob>... [--fail-on major] [--out <dir>] [--allow-empty-glob]

Exit 0: the engine ran on at least one file and found no finding at
or above --fail-on. Exit 1: the engine found such a finding.
Exit 2: INCOMPLETE — an input is missing or unreadable, a glob
matched nothing (unless --allow-empty-glob), no file was audited,
fewer files were audited than requested, the engine could not run,
or its JSON could not be read. A missing input is never a PASS.
"""

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ENGINE = Path(__file__).resolve().parent / "ultra11y.mjs"
_GLOB_CHARS = set("*?[")


def _has_glob_magic(text):
    return any(ch in _GLOB_CHARS for ch in text)


def _expand_inputs(inputs, allow_empty_glob):
    """Resolve the inputs to (expanded_inputs, expected_files).

    Raises ValueError when an input is missing or unreadable, or a
    glob matches nothing (unless allowed). Directories are passed
    through — the engine expands them itself, so they add no
    expected file count. Duplicate inputs are collapsed: the engine
    must audit at least the distinct files requested.
    """
    expanded = []
    seen = set()
    expected_files = 0
    for raw in inputs:
        if _has_glob_magic(raw):
            matches = sorted(glob.glob(raw, recursive=True))
            if not matches and not allow_empty_glob:
                raise ValueError(f"glob matched nothing: {raw}")
            for match in matches:
                if match in seen:
                    continue
                seen.add(match)
                expanded.append(match)
                if Path(match).is_file():
                    expected_files += 1
            continue
        path = Path(raw)
        if not path.exists():
            raise ValueError(f"input not found: {raw}")
        if not os.access(path, os.R_OK):
            raise ValueError(f"input not readable: {raw}")
        if raw in seen:
            continue
        seen.add(raw)
        expanded.append(raw)
        if path.is_file():
            expected_files += 1
    if not expanded:
        raise ValueError("no inputs to audit")
    return expanded, expected_files


def _run_engine(argv):
    return subprocess.run(argv, capture_output=True, text=True, timeout=300)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Audit pages with the ultra11y engine, refusing "
        "to report a check that did not run as passed."
    )
    parser.add_argument("inputs", nargs="+", help="Page, directory, or glob to audit")
    parser.add_argument(
        "--fail-on",
        default="major",
        help="Severity the gate fails on: blocking, major, or minor (default: major)",
    )
    parser.add_argument("--out", default=None, help="Directory for the engine's report files")
    parser.add_argument(
        "--allow-empty-glob",
        action="store_true",
        help="Allow a glob that matches nothing (it still cannot PASS: "
        "zero audited files is INCOMPLETE)",
    )
    args = parser.parse_args(argv)

    if not ENGINE.is_file():
        print(f"error: ultra11y engine not found: {ENGINE}", file=sys.stderr)
        return 2
    node = shutil.which("node")
    if node is None:
        print("error: node is not installed", file=sys.stderr)
        return 2
    try:
        expanded, expected_files = _expand_inputs(args.inputs, args.allow_empty_glob)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    cmd = [node, str(ENGINE), "audit", *expanded, "--fail-on", args.fail_on, "--json"]
    if args.out:
        cmd += ["--out", args.out]
    try:
        proc = _run_engine(cmd)
    except OSError as e:
        print(f"error: could not run the engine: {e}", file=sys.stderr)
        return 2
    try:
        report = json.loads(proc.stdout)
        files = report["scope"]["files"]
    except (ValueError, KeyError, TypeError):
        print("error: the engine did not return a readable JSON report", file=sys.stderr)
        if proc.stderr.strip():
            print(proc.stderr.strip()[:2000], file=sys.stderr)
        return 2
    if files == 0:
        print("error: the engine audited 0 files — INCOMPLETE, never a PASS", file=sys.stderr)
        if proc.stderr.strip():
            print(proc.stderr.strip()[:2000], file=sys.stderr)
        return 2
    if files < expected_files:
        print(
            f"error: the engine audited {files} file(s) but {expected_files} "
            "were requested — INCOMPLETE",
            file=sys.stderr,
        )
        return 2
    sys.stdout.write(proc.stdout)
    if not proc.stdout.endswith("\n"):
        sys.stdout.write("\n")
    if proc.returncode == 0:
        return 0
    if proc.returncode == 1:
        return 1
    print(f"error: the engine exited {proc.returncode}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
