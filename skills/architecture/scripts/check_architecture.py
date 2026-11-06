#!/usr/bin/env python3
"""Check a project's architecture rules that are mechanically checkable.

This is a limited check of relative imports in JavaScript/TypeScript
(plus dependency licences). It is not a full module resolver: it does
not follow re-exports through barrel files, it does not evaluate
conditional or computed imports, and it only resolves the tsconfig
`paths` aliases it is told about (see --tsconfig). For a project that
needs a complete graph, use a real resolver (dependency-cruiser, madge)
instead of this script.

Checks:
  1. Layer rule: no file under src/ imports from outside src/ — that
     includes the tests/ directory and any other path outside src/.
     (A package import from node_modules is fine.)
  2. No circular import among the files under src/.
  3. Every import that is a relative path must resolve to a file; an
     unresolved import is reported, not silently ignored.
  4. Every direct dependency in package.json has a licence recorded in
     node_modules/<dep>/package.json, and that licence is in the
     allowed set (or in the allowlist file). SPDX expressions are
     understood: for OR, one allowed licence is enough; for AND, all
     must be allowed. The legacy `licenses[]` array is also read.

Usage:
    python3 check_architecture.py --root <project> [--allow-licences MIT,Apache-2.0,...]
    [--licence-allowlist <file>] [--src-dir src] [--test-dir tests] [--tsconfig <file>]

Exit 0 when clean, 1 when any violation is found (including when
nothing could be checked — a scan that covered no files is INCOMPLETE,
never clean). Stdlib only. Requires Python 3.9+.
"""

import argparse
import json
import os
import re
import sys
from collections import defaultdict

DEFAULT_ALLOWED = {"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC"}
TS_EXTENSIONS = (".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs")

# import ... from "X"  |  import "X"  |  require("X")  |  export ... from "X"
# |  import("X")  — but not "import type" / "export type", which are
# erased at runtime and are not a runtime dependency.
IMPORT_RE = re.compile(
    r"""(?:import\s+(?!type\b)(?:[^'"]+\s+from\s+)?|export\s+(?!type\b)(?:[^'"]+\s+from\s+)?|require\s*\(\s*|import\s*\(\s*)['"]([^'"]+)['"]"""
)


def _strip_comments(text: str) -> str:
    """Remove // and /* */ comments, without touching string literals.
    A comment is not code, and an import written in a comment is not an
    import. The scan keeps the line structure (a comment becomes a
    space) so the regex still sees the real imports."""
    out = []
    i, n = 0, len(text)
    quote = None  # the string quote we are inside (' " or `), or None
    while i < n:
        c = text[i]
        if quote is not None:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if c == quote:
                quote = None
            i += 1
            continue
        if c in ("'", '"', "`"):
            quote = c
            out.append(c)
            i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            # Line comment: skip to the end of the line.
            while i < n and text[i] != "\n":
                i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            # Block comment: skip to */.
            end = text.find("*/", i + 2)
            if end < 0:
                break
            i = end + 2
            out.append(" ")
            continue
        out.append(c)
        i += 1
    return "".join(out)


def collect_ts_files(root, src_dir):
    out = []
    base = os.path.join(root, src_dir)
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in ("node_modules",)]
        for name in filenames:
            if name.endswith(TS_EXTENSIONS):
                out.append(os.path.join(dirpath, name))
    return sorted(out)


def _load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_tsconfig_paths(root, tsconfig_path):
    """tsconfig compilerOptions.paths, as {prefix: [replacements]}.
    Only the common form is supported (a single * per pattern). Returns
    {} when there is no tsconfig or no paths."""
    path = tsconfig_path or os.path.join(root, "tsconfig.json")
    if not os.path.isfile(path):
        return {}
    try:
        cfg = _load_json(path)
    except (OSError, ValueError):
        return {}
    paths = cfg.get("compilerOptions", {}).get("paths", {})
    if not isinstance(paths, dict):
        return {}
    out = {}
    for pattern, targets in paths.items():
        if isinstance(targets, list):
            out[pattern] = [t for t in targets if isinstance(t, str)]
    return out


def _candidates_for(target):
    """The files a relative import target could be, in order."""
    candidates = [target]
    for ext in TS_EXTENSIONS:
        candidates.append(target + ext)
    candidates.append(os.path.join(target, "index.ts"))
    candidates.append(os.path.join(target, "index.tsx"))
    candidates.append(os.path.join(target, "index.js"))
    candidates.append(os.path.join(target, "index.jsx"))
    # TypeScript with NodeNext resolution maps a ".js" import to a ".ts"
    # source file, so "./b.js" resolves to "./b.ts". Without that mapping
    # the import graph breaks and cycles are missed.
    for js_ext, ts_ext in ((".js", ".ts"), (".jsx", ".tsx"),
                           (".mjs", ".mts"), (".cjs", ".cts")):
        if target.endswith(js_ext):
            candidates.append(target[: -len(js_ext)] + ts_ext)
    return candidates


def resolve_import(from_file, spec, root, src_dir, tsconfig_paths=None):
    """Resolve an import to a file inside the project, or None.

    Returns None for a package import (not a local file) and for a
    local import that does not resolve to an existing file (the caller
    reports it as unresolved). A tsconfig `paths` alias (e.g. @/x) is
    resolved against the tsconfig mapping when one is available.
    """
    tsconfig_paths = tsconfig_paths or {}
    if spec.startswith("."):
        base = os.path.dirname(from_file)
        target = os.path.normpath(os.path.join(base, spec))
        for cand in _candidates_for(target):
            if os.path.isfile(cand):
                return cand
        return None  # unresolved local import
    # A tsconfig paths alias, e.g. @/utils -> src/utils.
    for pattern, replacements in tsconfig_paths.items():
        if "*" in pattern:
            prefix, suffix = pattern.split("*", 1)
            if spec.startswith(prefix) and spec.endswith(suffix):
                middle = spec[len(prefix): len(spec) - len(suffix) if suffix else None]
                for repl in replacements:
                    base = repl.replace("*", middle)
                    target = os.path.normpath(os.path.join(root, base))
                    for cand in _candidates_for(target):
                        if os.path.isfile(cand):
                            return cand
                return None  # alias matched but did not resolve
        elif spec == pattern and replacements:
            target = os.path.normpath(os.path.join(root, replacements[0]))
            for cand in _candidates_for(target):
                if os.path.isfile(cand):
                    return cand
            return None
    return None  # a package import, not a local file


def _licence_allowed(lic, allowed, allowlist_name):
    """Whether a licence string is allowed. Handles a plain licence,
    an SPDX expression (OR: one allowed licence is enough; AND: all
    must be allowed), and the legacy licenses[] array (a list of
    {"type": ...} dicts, treated as OR)."""
    if lic is None:
        return False
    if isinstance(lic, list):
        types = [e.get("type") for e in lic if isinstance(e, dict)]
        return any(t in allowed or allowlist_name == t for t in types if t)
    if isinstance(lic, dict):
        lic = lic.get("type")
        if lic is None:
            return False
    # An SPDX expression: split into licence tokens and operators.
    tokens = re.findall(r"[A-Za-z0-9.+-]+", lic)
    if not tokens:
        return False
    licences = [t for t in tokens if t not in ("AND", "OR", "WITH")]
    if not licences:
        return False
    if "AND" in tokens:
        return all(t in allowed for t in licences)
    # OR, or a single licence: one allowed licence is enough.
    return any(t in allowed for t in licences)


def find_cycles(graph):
    """Circular imports, found with an iterative DFS (no recursion, so
    a deep import chain cannot hit Python's recursion limit). Returns a
    list of cycles, each a list of nodes ending where it started."""
    WHITE, GREY, BLACK = 0, 1, 2
    colour = defaultdict(int)
    cycles = []
    for start in sorted(graph):
        if colour[start] != WHITE:
            continue
        colour[start] = GREY
        path = [start]
        # Stack entries: (node, sorted neighbour list, next index).
        stack = [(start, sorted(graph.get(start, ())), 0)]
        while stack:
            node, neighbours, idx = stack[-1]
            if idx >= len(neighbours):
                stack.pop()
                colour[node] = BLACK
                path.pop()
                continue
            nxt = neighbours[idx]
            stack[-1] = (node, neighbours, idx + 1)
            if colour[nxt] == GREY:
                cycle = path[path.index(nxt):] + [nxt]
                cycles.append(cycle)
            elif colour[nxt] == WHITE:
                colour[nxt] = GREY
                path.append(nxt)
                stack.append((nxt, sorted(graph.get(nxt, ())), 0))
    return cycles


def main():
    ap = argparse.ArgumentParser(description="Check architecture rules.")
    ap.add_argument("--root", required=True)
    ap.add_argument("--src-dir", default="src")
    ap.add_argument("--test-dir", default="tests")
    ap.add_argument("--allow-licences", default=",".join(sorted(DEFAULT_ALLOWED)))
    ap.add_argument("--licence-allowlist", default=None,
                    help="JSON file mapping dependency name -> licence, for licences outside the allowed set that were decided in an ADR.")
    ap.add_argument("--tsconfig", default=None,
                    help="Path to tsconfig.json (default: <root>/tsconfig.json), for resolving paths aliases.")
    args = ap.parse_args()

    # Absolutise and normalise the root FIRST. Every path derived from
    # it (src_base, test_base, collected files, resolved targets) must
    # be in the same form, or the commonpath comparisons silently fail
    # — with --root . the checker used to report OK on a project that
    # had a layer violation and a cycle.
    root = os.path.abspath(os.path.normpath(args.root))
    allowed = {x.strip() for x in args.allow_licences.split(",") if x.strip()}
    allowlist = {}
    if args.licence_allowlist:
        try:
            allowlist = _load_json(args.licence_allowlist)
        except (OSError, ValueError) as e:
            print(f"error: cannot read licence allowlist: {e}", file=sys.stderr)
            return 1
    tsconfig_paths = load_tsconfig_paths(root, args.tsconfig)

    violations = []
    src_base = os.path.join(root, args.src_dir)
    test_base = os.path.join(root, args.test_dir)

    # --- 1. layer rule + build the import graph ---
    graph = defaultdict(set)
    files = collect_ts_files(root, args.src_dir)
    if not files:
        violations.append(
            f"no source files found under {args.src_dir}/ — nothing was "
            f"checked (INCOMPLETE, not clean)")
    for path in files:
        try:
            with open(path, encoding="utf-8", errors="ignore") as f:
                text = f.read()
        except OSError as e:
            violations.append(f"{path}: cannot read ({e})")
            continue
        rel = os.path.relpath(path, root)
        for spec in IMPORT_RE.findall(_strip_comments(text)):
            target = resolve_import(path, spec, root, args.src_dir, tsconfig_paths)
            if target is None:
                if spec.startswith(".") or any(
                    spec.startswith(p.split("*")[0]) for p in tsconfig_paths
                ):
                    violations.append(f"{rel}: unresolved import {spec}")
                continue
            target_rel = os.path.relpath(target, root)
            if os.path.commonpath([target, test_base]) == test_base:
                violations.append(
                    f"{rel}: layer violation — imports from tests/ ({spec})")
            elif os.path.commonpath([target, src_base]) != src_base:
                violations.append(
                    f"{rel}: layer violation — imports from outside "
                    f"{args.src_dir}/ ({spec} -> {target_rel})")
            else:
                graph[rel].add(target_rel)

    # --- 2. circular imports among src/ files ---
    for cycle in find_cycles(graph):
        violations.append("circular import: " + " -> ".join(cycle))

    # --- 3. dependency licences ---
    dep_licences = {}
    pkg_path = os.path.join(root, "package.json")
    if not os.path.isfile(pkg_path):
        violations.append("package.json not found")
    else:
        try:
            pkg = _load_json(pkg_path)
        except (OSError, ValueError) as e:
            violations.append(f"package.json: cannot read ({e})")
            pkg = None
        if pkg is not None:
            deps = {}
            deps.update(pkg.get("dependencies", {}))
            deps.update(pkg.get("devDependencies", {}))
            for name in sorted(deps):
                dep_pkg = os.path.join(root, "node_modules", name, "package.json")
                if not os.path.isfile(dep_pkg):
                    violations.append(f"dependency {name}: not installed, licence unknown")
                    continue
                try:
                    dep = _load_json(dep_pkg)
                except (OSError, ValueError) as e:
                    violations.append(f"dependency {name}: cannot read package.json ({e})")
                    continue
                lic = dep.get("license")
                if lic is None:
                    lic = dep.get("licenses")
                if lic is None:
                    violations.append(f"dependency {name}: no licence recorded")
                    continue
                dep_licences[name] = lic if isinstance(lic, str) else str(lic)
                if _licence_allowed(lic, allowed, None):
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
