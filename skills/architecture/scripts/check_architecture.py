#!/usr/bin/env python3
"""Check a project's architecture rules that are mechanically checkable.

This is a limited check of relative imports in JavaScript/TypeScript
(plus dependency licences). It is not a full module resolver: it does
not follow re-exports through barrel files, it does not evaluate
conditional or computed imports, and it only resolves the tsconfig
`paths` aliases it is told about (see --tsconfig). A string literal
containing the text of an import statement is counted as an import —
the scanner is a regex over comment-stripped text, not a parser — so
a file that quotes an import in a string can report a false
"unresolved import". A serious gate needs a real parser (an AST).
For a project that needs a complete graph, use a real resolver
(dependency-cruiser, madge) instead of this script.

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
     parsed properly (parentheses and operator precedence: AND binds
     tighter than OR, so (MIT OR GPL-3.0) AND Apache-2.0 needs Apache
     plus one of MIT/GPL). The legacy `licenses[]` array is also read.

The tsconfig `paths` aliases are resolved the way TypeScript does:
the longest matching prefix wins, every replacement of that pattern
is tried, and a pattern that matches but does not resolve falls
through to the next pattern (and then to a package import) instead
of reporting a false "unresolved import". `baseUrl` is honoured
(paths resolve relative to it) and `extends` is followed — and a
relative path resolves against the file that declared it, so a
baseUrl or paths inherited from a base config resolve against the
base config's directory, not the child's. A tsconfig
that exists but cannot be parsed (JSONC comments and trailing commas
are accepted) is an INCOMPLETE result, never a silent empty mapping —
a config that failed to load must not shrink the import graph
without anyone noticing.

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


# Words after which a "/" starts a regex literal, not a division.
_REGEX_KEYWORDS = {
    "return",
    "typeof",
    "case",
    "delete",
    "void",
    "in",
    "of",
    "new",
    "throw",
    "else",
    "do",
    "yield",
    "await",
}


def _strip_comments(text: str) -> str:
    """Remove // and /* */ comments, without touching string literals
    or regex literals. A comment is not code, and an import written in
    a comment is not an import. A regex literal may contain a quote
    (/'/), so it must be skipped as a literal too — otherwise the
    scanner would think the quote opened a string and swallow the rest
    of the file. The scan keeps the line structure (a comment becomes a
    space) so the regex still sees the real imports.

    Whether "/" starts a regex or a division is decided by context:
    after an operator, an opening bracket, a comma, a semicolon, or a
    keyword like return, an expression is expected, so "/" starts a
    regex; after an identifier, a number, a string, or a closing
    bracket, it is a division."""
    out = []
    i, n = 0, len(text)
    quote = None  # the string quote we are inside (' " or `), or None
    prev_word = ""  # the identifier/keyword just before this position
    prev_sig = ""  # the last significant (non-space) character
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
                prev_sig = c
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
        if c == "/" and _starts_regex(prev_sig, prev_word):
            # Regex literal: skip to the closing /, honouring escapes
            # and character classes (which may contain a /).
            out.append(c)
            i += 1
            in_class = False
            while i < n:
                d = text[i]
                out.append(d)
                if d == "\\" and i + 1 < n:
                    out.append(text[i + 1])
                    i += 2
                    continue
                if d == "[":
                    in_class = True
                elif d == "]":
                    in_class = False
                elif d == "/" and not in_class:
                    i += 1
                    break
                elif d == "\n":
                    break  # unterminated; do not swallow the file
                i += 1
            prev_sig = "/"
            prev_word = ""
            continue
        if c.isalnum() or c in "_$":
            prev_word += c
        elif not c.isspace():
            prev_word = ""
            prev_sig = c
        out.append(c)
        i += 1
    return "".join(out)


def _starts_regex(prev_sig: str, prev_word: str) -> bool:
    """Whether a "/" at this point starts a regex literal."""
    if prev_word in _REGEX_KEYWORDS:
        return True
    # Start of file, or after an operator / opener / separator, an
    # expression is expected. After an identifier, a number, a string,
    # or a closing bracket, "/" is a division.
    if prev_sig == "":
        return True
    return prev_sig in "(,=:[!&|?{};"


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


class TsconfigError(Exception):
    """A tsconfig that exists but cannot be used (unparseable, or its
    extends target cannot be found)."""


def _strip_jsonc(text: str) -> str:
    """Remove // and /* */ comments and trailing commas, so a tsconfig
    written as JSONC (the common form) parses as JSON. String-aware:
    a // inside a string is not a comment."""
    out = []
    i, n = 0, len(text)
    quote = None
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
        if c in ("'", '"'):
            quote = c
            out.append(c)
            i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            end = text.find("*/", i + 2)
            if end < 0:
                break
            i = end + 2
            continue
        out.append(c)
        i += 1
    # Trailing commas before } or ] are valid in JSONC, not in JSON.
    return re.sub(r",(\s*[}\]])", r"\1", "".join(out))


def _load_tsconfig_file(path):
    """Parse one tsconfig file (JSONC accepted). Raises TsconfigError."""
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        raise TsconfigError(f"cannot read {path}: {e}")
    try:
        cfg = json.loads(_strip_jsonc(text))
    except ValueError as e:
        raise TsconfigError(f"cannot parse {path}: {e}")
    if not isinstance(cfg, dict):
        raise TsconfigError(f"{path}: expected a JSON object")
    return cfg


def load_tsconfig_paths(root, tsconfig_path):
    """tsconfig compilerOptions.paths, as {"paths": {...}, "base_dir": ...}.

    `paths` replacements are relative to base_dir: the tsconfig's
    baseUrl when set, otherwise the directory containing the tsconfig
    that declared the paths. `extends` is followed (a relative target
    resolves against the extending file's directory; a bare name is
    looked up under node_modules). Relative paths resolve against the
    file that DECLARED them, the way TypeScript does: a baseUrl
    inherited from a base config resolves against the base config's
    directory, not the child's — and paths with no baseUrl anywhere
    resolve against the directory of the config that declared them.
    Returns ({"paths": {}, "base_dir": root}) when there is no
    tsconfig file. Raises TsconfigError when a tsconfig exists but
    cannot be used — the caller must report INCOMPLETE, never
    silently use an empty mapping."""
    path = tsconfig_path or os.path.join(root, "tsconfig.json")
    if not os.path.isfile(path):
        return {"paths": {}, "base_dir": root}
    # Walk the extends chain, child first, remembering which file each
    # config came from. A relative extends target resolves against the
    # extending file's directory.
    chain = []  # [(abspath, cfg)] — child first, root-most base last
    cfg = _load_tsconfig_file(path)
    seen = {os.path.abspath(path)}
    chain.append((os.path.abspath(path), cfg))
    while isinstance(cfg.get("extends"), str):
        parent = cfg["extends"]
        if parent.startswith("."):
            base_path = os.path.normpath(
                os.path.join(os.path.dirname(os.path.abspath(path)), parent)
            )
            if not base_path.endswith(".json"):
                base_path += ".json"
        else:
            base_path = os.path.join(root, "node_modules", parent)
            if not base_path.endswith(".json"):
                base_path += ".json"
        if os.path.abspath(base_path) in seen:
            raise TsconfigError(f"tsconfig extends cycle at {base_path}")
        seen.add(os.path.abspath(base_path))
        if not os.path.isfile(base_path):
            raise TsconfigError(f"tsconfig {path} extends {parent!r}, which was not found")
        cfg = _load_tsconfig_file(base_path)
        chain.append((os.path.abspath(base_path), cfg))
        path = base_path
    # Merge base-first so the child wins, tracking which file defined
    # each compilerOptions key — the winner's file is what relative
    # paths resolve against.
    opts = {}
    origins = {}
    for cfg_path, cfg in reversed(chain):
        cfg_opts = cfg.get("compilerOptions") or {}
        if not isinstance(cfg_opts, dict):
            raise TsconfigError(f"{cfg_path}: compilerOptions is not an object")
        for key, value in cfg_opts.items():
            opts[key] = value
            origins[key] = cfg_path
    paths = opts.get("paths", {})
    if not isinstance(paths, dict):
        raise TsconfigError(
            f"{origins.get('paths', chain[0][0])}: compilerOptions.paths is not an object"
        )
    base_url = opts.get("baseUrl")
    if base_url is not None and not isinstance(base_url, str):
        raise TsconfigError(f"{origins['baseUrl']}: compilerOptions.baseUrl is not a string")
    if base_url is not None:
        # baseUrl resolves relative to the file that declared it.
        base_dir = os.path.normpath(os.path.join(os.path.dirname(origins["baseUrl"]), base_url))
    elif paths:
        # No baseUrl: paths resolve relative to the file that declared
        # them.
        base_dir = os.path.dirname(origins["paths"])
    else:
        base_dir = os.path.dirname(chain[0][0])
    out = {}
    for pattern, targets in paths.items():
        if isinstance(targets, list):
            out[pattern] = [t for t in targets if isinstance(t, str)]
    return {"paths": out, "base_dir": base_dir}


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
    for js_ext, ts_ext in ((".js", ".ts"), (".jsx", ".tsx"), (".mjs", ".mts"), (".cjs", ".cts")):
        if target.endswith(js_ext):
            candidates.append(target[: -len(js_ext)] + ts_ext)
    return candidates


def resolve_import(from_file, spec, root, src_dir, tsconfig=None):
    """Resolve an import to a file inside the project, or None.

    Returns None for a package import (not a local file) and for a
    local import that does not resolve to an existing file (the caller
    reports it as unresolved). A tsconfig `paths` alias is resolved
    the way TypeScript does: the pattern with the longest matching
    prefix wins, every replacement of that pattern is tried, and a
    pattern that matches but does not resolve falls through to the
    next matching pattern — it never reports a false "unresolved
    import" for a package that merely matches a catch-all pattern.
    `tsconfig` is the {"paths": ..., "base_dir": ...} mapping from
    load_tsconfig_paths (or None).
    """
    tsconfig = tsconfig or {"paths": {}, "base_dir": root}
    tsconfig_paths = tsconfig.get("paths", {})
    base_dir = tsconfig.get("base_dir", root)
    if spec.startswith("."):
        base = os.path.dirname(from_file)
        target = os.path.normpath(os.path.join(base, spec))
        for cand in _candidates_for(target):
            if os.path.isfile(cand):
                return cand
        return None  # unresolved local import
    # A tsconfig paths alias. Collect every matching pattern, longest
    # prefix first (TypeScript's rule), and try them all.
    matches = []
    for pattern, replacements in tsconfig_paths.items():
        if "*" in pattern:
            prefix, suffix = pattern.split("*", 1)
            if spec.startswith(prefix) and spec.endswith(suffix):
                middle = spec[len(prefix) : len(spec) - len(suffix) if suffix else None]
                matches.append((len(prefix), pattern, replacements, middle))
        elif spec == pattern:
            matches.append((len(pattern), pattern, replacements, None))
    matches.sort(key=lambda m: -m[0])
    for _plen, _pattern, replacements, middle in matches:
        for repl in replacements:
            base = repl.replace("*", middle) if middle is not None else repl
            target = os.path.normpath(os.path.join(base_dir, base))
            for cand in _candidates_for(target):
                if os.path.isfile(cand):
                    return cand
    return None  # a package import, or an alias that did not resolve


def _spdx_tokens(expr):
    """Tokens of an SPDX expression: licence ids, AND, OR, WITH, and
    parentheses. A trailing "+" on a licence id ("GPL-2.0+") means "or
    later" and is kept with the id."""
    return re.findall(r"\(|\)|[A-Za-z0-9.+-]+", expr)


def _spdx_parse(tokens):
    """Parse SPDX tokens into a tree: ("lic", id) | ("and", l, r) |
    ("or", l, r). AND binds tighter than OR; parentheses group.
    A WITH exception attaches to its licence and does not change
    whether the licence is allowed. Raises ValueError on bad input."""
    pos = [0]

    def peek():
        return tokens[pos[0]] if pos[0] < len(tokens) else None

    def take():
        tok = tokens[pos[0]]
        pos[0] += 1
        return tok

    def parse_or():
        node = parse_and()
        while peek() == "OR":
            take()
            node = ("or", node, parse_and())
        return node

    def parse_and():
        node = parse_primary()
        while peek() == "AND":
            take()
            node = ("and", node, parse_primary())
        return node

    def parse_primary():
        tok = peek()
        if tok == "(":
            take()
            node = parse_or()
            if peek() != ")":
                raise ValueError("missing closing parenthesis")
            take()
            return node
        if tok is None or tok in ("AND", "OR", "WITH", ")"):
            raise ValueError(f"unexpected token {tok!r}")
        take()
        if peek() == "WITH":
            take()  # the exception name; it does not affect allowability
            if peek() is None:
                raise ValueError("WITH without an exception name")
            take()
        return ("lic", tok)

    tree = parse_or()
    if pos[0] != len(tokens):
        raise ValueError(f"unexpected trailing token {tokens[pos[0]]!r}")
    return tree


def _spdx_eval(tree, allowed):
    """Whether an SPDX tree is satisfied by the allowed set."""
    kind = tree[0]
    if kind == "lic":
        lic = tree[1]
        # "GPL-2.0+" also satisfies "GPL-2.0" (the "+" is "or later").
        return lic in allowed or lic.rstrip("+") in allowed
    if kind == "and":
        return _spdx_eval(tree[1], allowed) and _spdx_eval(tree[2], allowed)
    return _spdx_eval(tree[1], allowed) or _spdx_eval(tree[2], allowed)


def _licence_allowed(lic, allowed, allowlist_name):
    """Whether a licence string is allowed. Handles a plain licence,
    a full SPDX expression (parentheses and precedence: AND binds
    tighter than OR), and the legacy licenses[] array (a list of
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
    try:
        tree = _spdx_parse(_spdx_tokens(lic))
    except ValueError:
        return False
    return _spdx_eval(tree, allowed)


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
                cycle = path[path.index(nxt) :] + [nxt]
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
    ap.add_argument(
        "--licence-allowlist",
        default=None,
        help="JSON file mapping dependency name -> licence, for licences outside the allowed set that were decided in an ADR.",
    )
    ap.add_argument(
        "--tsconfig",
        default=None,
        help="Path to tsconfig.json (default: <root>/tsconfig.json), for resolving paths aliases.",
    )
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
    tsconfig = {"paths": {}, "base_dir": root}
    try:
        tsconfig = load_tsconfig_paths(root, args.tsconfig)
    except TsconfigError as e:
        # A tsconfig that exists but cannot be used must not silently
        # shrink the import graph: the run is INCOMPLETE, not clean.
        print(f"FAIL: 1 violation(s)\n  - tsconfig: {e} (INCOMPLETE, not clean)")
        return 1

    violations = []
    src_base = os.path.join(root, args.src_dir)
    test_base = os.path.join(root, args.test_dir)

    # --- 1. layer rule + build the import graph ---
    graph = defaultdict(set)
    files = collect_ts_files(root, args.src_dir)
    if not files:
        violations.append(
            f"no source files found under {args.src_dir}/ — nothing was "
            f"checked (INCOMPLETE, not clean)"
        )
    for path in files:
        try:
            with open(path, encoding="utf-8", errors="ignore") as f:
                text = f.read()
        except OSError as e:
            violations.append(f"{path}: cannot read ({e})")
            continue
        rel = os.path.relpath(path, root)
        for spec in IMPORT_RE.findall(_strip_comments(text)):
            target = resolve_import(path, spec, root, args.src_dir, tsconfig)
            if target is None:
                # A relative import that does not resolve is a
                # violation. So is an alias import (a spec matching a
                # paths pattern with a non-empty prefix, e.g. @/x)
                # that does not resolve — the author meant it to be
                # local. A bare "*" pattern has an empty prefix and
                # matches every package name, so it must not turn a
                # package import into a false "unresolved import".
                if spec.startswith(".") or any(
                    spec.startswith(p.split("*")[0]) for p in tsconfig["paths"] if p.split("*")[0]
                ):
                    violations.append(f"{rel}: unresolved import {spec}")
                continue
            target_rel = os.path.relpath(target, root)
            if os.path.commonpath([target, test_base]) == test_base:
                violations.append(f"{rel}: layer violation — imports from tests/ ({spec})")
            elif os.path.commonpath([target, src_base]) != src_base:
                violations.append(
                    f"{rel}: layer violation — imports from outside "
                    f"{args.src_dir}/ ({spec} -> {target_rel})"
                )
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
                        f"({', '.join(sorted(allowed))}) and has no recorded decision"
                    )

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
