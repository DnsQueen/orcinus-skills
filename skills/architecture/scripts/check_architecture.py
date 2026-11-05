#!/usr/bin/env python3
"""Check a project's architecture rules that are mechanically checkable.

Checks:
  1. Layer rule: no file under src/ imports from the tests/ directory
     (or from any path outside src/, other than a package in node_modules).
  2. No circular import among the files under src/.
  3. Every direct dependency in package.json has a licence recorded in
     node_modules/<dep>/package.json, and that licence is in the allowed
     set (or in the allowlist file).

Usage:
    python3 check_architecture.py --root <project> [--allow-licences MIT,Apache-2.0,...]
    [--licence-allowlist <file>] [--src-dir src] [--test-dir tests]

Exit 0 when clean, 1 when any violation is found. Stdlib only.
"""

import argparse
import json
import os
import re
import sys
from collections import defaultdict

DEFAULT_ALLOWED = {"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC"}

# import ... from "X"  |  import "X"  |  require("X")  |  export ... from "X"
IMPORT_RE = re.compile(
    r"""(?:import\s+(?:[^'"]+\s+from\s+)?|export\s+(?:[^'"]+\s+from\s+)?|require\s*\(\s*)['"]([^'"]+)['"]"""
)


def collect_ts_files(root, src_dir):
    out = []
    base = os.path.join(root, src_dir)
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in ("node_modules",)]
        for name in filenames:
            if name.endswith((".ts", ".mts", ".cts", ".js", ".mjs", ".cjs")):
                out.append(os.path.join(dirpath, name))
    return sorted(out)


def resolve_import(from_file, spec, root, src_dir):
    """Resolve a relative import to a path inside the project, or None.

    TypeScript with NodeNext resolution maps a ".js" import to a ".ts"
    source file, so "./b.js" resolves to "./b.ts". Without that mapping
    the import graph breaks and cycles are missed.
    """
    if not spec.startswith("."):
        return None  # a package import, not a local file
    base = os.path.dirname(from_file)
    target = os.path.normpath(os.path.join(base, spec))
    candidates = [target, target + ".ts", target + ".js",
                  os.path.join(target, "index.ts"), os.path.join(target, "index.js")]
    if target.endswith(".js"):
        candidates.append(target[:-3] + ".ts")
    if target.endswith(".mjs"):
        candidates.append(target[:-4] + ".mts")
    if target.endswith(".cjs"):
        candidates.append(target[:-4] + ".cts")
    for cand in candidates:
        if os.path.isfile(cand):
            return cand
    return target  # unresolved, but still a local path: report it as-is


def main():
    ap = argparse.ArgumentParser(description="Check architecture rules.")
    ap.add_argument("--root", required=True)
    ap.add_argument("--src-dir", default="src")
    ap.add_argument("--test-dir", default="tests")
    ap.add_argument("--allow-licences", default=",".join(sorted(DEFAULT_ALLOWED)))
    ap.add_argument("--licence-allowlist", default=None,
                    help="JSON file mapping dependency name -> licence, for licences outside the allowed set that were decided in an ADR.")
    args = ap.parse_args()

    root = args.root
    allowed = {x.strip() for x in args.allow_licences.split(",") if x.strip()}
    allowlist = {}
    if args.licence_allowlist:
        allowlist = json.load(open(args.licence_allowlist))

    violations = []
    src_base = os.path.join(root, args.src_dir)
    test_base = os.path.join(root, args.test_dir)

    # --- 1. layer rule + build the import graph ---
    graph = defaultdict(set)
    for path in collect_ts_files(root, args.src_dir):
        try:
            text = open(path, encoding="utf-8", errors="ignore").read()
        except OSError as e:
            violations.append(f"{path}: cannot read ({e})")
            continue
        for spec in IMPORT_RE.findall(text):
            target = resolve_import(path, spec, root, args.src_dir)
            if target is None:
                continue
            rel = os.path.relpath(path, root)
            target_rel = os.path.relpath(target, root)
            if os.path.commonpath([target, test_base]) == test_base:
                violations.append(
                    f"{rel}: layer violation — imports from tests/ ({spec})")
            if os.path.commonpath([target, src_base]) == src_base:
                graph[rel].add(target_rel)

    # --- 2. circular imports among src/ files ---
    WHITE, GREY, BLACK = 0, 1, 2
    colour = defaultdict(int)
    stack = []

    def visit(node):
        colour[node] = GREY
        stack.append(node)
        for nxt in sorted(graph.get(node, ())):
            if colour[nxt] == GREY:
                cycle = stack[stack.index(nxt):] + [nxt]
                violations.append(
                    "circular import: " + " -> ".join(cycle))
            elif colour[nxt] == WHITE:
                visit(nxt)
        stack.pop()
        colour[node] = BLACK

    for node in sorted(graph):
        if colour[node] == WHITE:
            visit(node)

    # --- 3. dependency licences ---
    pkg_path = os.path.join(root, "package.json")
    if not os.path.isfile(pkg_path):
        violations.append("package.json not found")
    else:
        pkg = json.load(open(pkg_path))
        deps = {}
        deps.update(pkg.get("dependencies", {}))
        deps.update(pkg.get("devDependencies", {}))
        dep_licences = {}
        for name in sorted(deps):
            dep_pkg = os.path.join(root, "node_modules", name, "package.json")
            if not os.path.isfile(dep_pkg):
                violations.append(f"dependency {name}: not installed, licence unknown")
                continue
            lic = json.load(open(dep_pkg)).get("license")
            if isinstance(lic, dict):
                lic = lic.get("type")
            dep_licences[name] = lic
            if lic is None:
                violations.append(f"dependency {name}: no licence recorded")
            elif lic in allowed:
                pass
            elif allowlist.get(name) == lic:
                pass
            else:
                violations.append(
                    f"dependency {name}: licence {lic} is not in the allowed set "
                    f"({', '.join(sorted(allowed))}) and has no recorded decision")

    if violations:
        print(f"FAIL: {len(violations)} violation(s)")
        for v in violations:
            print(f"  - {v}")
        return 1
    print("OK: no layer violations, no circular imports, all dependency licences allowed")
    for name in sorted(dep_licences):
        print(f"  licence: {name}: {dep_licences[name]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
