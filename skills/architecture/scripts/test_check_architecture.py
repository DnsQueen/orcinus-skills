"""Tests for check_architecture.py.

Each test covers a real defect found by external reviews (2026-11-06),
most importantly the relative-root false pass: with --root . the
checker used to report OK on a fixture that had a layer violation and
a cycle. Run:
    python3 -m pytest skills/architecture/scripts/test_check_architecture.py -q
"""

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "check_architecture.py"


def run(root, *extra):
    cmd = [sys.executable, str(SCRIPT), "--root", str(root), *extra]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    return result.returncode, result.stdout, result.stderr


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def pkg(root, deps=None):
    write(
        root / "package.json",
        json.dumps({"name": "fixture", "version": "1.0.0", "dependencies": deps or {}}),
    )


def test_relative_root_finds_the_same_violations_as_absolute(tmp_path):
    """The P1 regression test: --root . must find exactly what an
    absolute --root finds. The old code reported OK with a relative root."""
    root = tmp_path / "proj"
    write(root / "src" / "a.ts", 'import { b } from "./b.js";\nexport const a = b + 1;\n')
    write(root / "src" / "b.ts", 'import { a } from "./a.js";\nexport const b = a + 1;\n')
    write(root / "src" / "c.ts", 'import { h } from "../tests/helper.js";\nexport const c = h;\n')
    write(root / "tests" / "helper.ts", "export const h = 1;\n")
    pkg(root)
    rc_abs, out_abs, _ = run(root)
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", "."],
        capture_output=True,
        text=True,
        cwd=root,
        timeout=60,
    )
    rc_rel, out_rel = result.returncode, result.stdout
    assert rc_abs == 1, out_abs
    assert rc_rel == 1, out_rel
    assert "circular import" in out_abs and "circular import" in out_rel
    assert "layer violation" in out_abs and "layer violation" in out_rel
    assert "tests/" in out_rel


def test_clean_project_passes(tmp_path):
    root = tmp_path / "proj"
    write(root / "src" / "a.ts", 'import { b } from "./b.js";\nexport const a = b;\n')
    write(root / "src" / "b.ts", "export const b = 1;\n")
    pkg(root)
    rc, out, _ = run(root)
    assert rc == 0, out
    assert out.startswith("OK:")


def test_layer_violation_outside_src_not_just_tests(tmp_path):
    """The docstring promises 'any path outside src/', not only tests/."""
    root = tmp_path / "proj"
    write(root / "src" / "a.ts", 'import { u } from "../shared/util.js";\nexport const a = u;\n')
    write(root / "shared" / "util.ts", "export const u = 1;\n")
    pkg(root)
    rc, out, _ = run(root)
    assert rc == 1, out
    assert "outside src/" in out


def test_tsx_and_jsx_are_checked(tmp_path):
    root = tmp_path / "proj"
    write(root / "src" / "a.tsx", 'import { b } from "./b.jsx";\nexport const a = b;\n')
    write(root / "src" / "b.jsx", 'import { a } from "./a.tsx";\nexport const b = a;\n')
    pkg(root)
    rc, out, _ = run(root)
    assert rc == 1, out
    assert "circular import" in out


def test_unresolved_import_is_reported(tmp_path):
    root = tmp_path / "proj"
    write(root / "src" / "a.ts", 'import { m } from "./missing.js";\nexport const a = m;\n')
    pkg(root)
    rc, out, _ = run(root)
    assert rc == 1, out
    assert "unresolved import" in out and "./missing.js" in out


def test_dynamic_import_is_followed(tmp_path):
    root = tmp_path / "proj"
    write(root / "src" / "a.ts", 'export async function load() { return import("./b.js"); }\n')
    write(root / "src" / "b.ts", 'import { a } from "./a.js";\nexport const b = a;\n')
    pkg(root)
    rc, out, _ = run(root)
    assert rc == 1, out
    assert "circular import" in out


def test_import_type_and_comments_are_not_runtime_imports(tmp_path):
    """import type is erased at runtime, and an import in a comment is
    not an import. Neither may produce a layer violation."""
    root = tmp_path / "proj"
    write(
        root / "src" / "a.ts",
        'import type { H } from "../tests/helper.js";\n'
        '// import { h } from "../tests/helper.js";\n'
        '/* import { h } from "../tests/helper.js"; */\n'
        "export const a = 1;\n",
    )
    write(root / "tests" / "helper.ts", "export type H = number;\n")
    pkg(root)
    rc, out, _ = run(root)
    assert rc == 0, out


def test_tsconfig_paths_alias_is_resolved(tmp_path):
    root = tmp_path / "proj"
    write(root / "tsconfig.json", json.dumps({"compilerOptions": {"paths": {"@/*": ["src/*"]}}}))
    write(root / "src" / "a.ts", 'import { b } from "@/b";\nexport const a = b;\n')
    write(root / "src" / "b.ts", 'import { a } from "./a.js";\nexport const b = a;\n')
    pkg(root)
    rc, out, _ = run(root)
    assert rc == 1, out
    assert "circular import" in out


def _dep_with_licence(root, name, licence_field):
    """A fake installed dependency with a given licence field."""
    dep_dir = root / "node_modules" / name
    dep_dir.mkdir(parents=True, exist_ok=True)
    data = {"name": name, "version": "1.0.0"}
    data.update(licence_field)
    (dep_dir / "package.json").write_text(json.dumps(data), encoding="utf-8")


def test_spdx_expressions(tmp_path):
    root = tmp_path / "proj"
    write(root / "src" / "a.ts", "export const a = 1;\n")
    pkg(root, deps={"or-dep": "1.0.0", "and-dep": "1.0.0", "gpl-dep": "1.0.0"})
    _dep_with_licence(root, "or-dep", {"license": "(MIT OR Apache-2.0)"})
    _dep_with_licence(root, "and-dep", {"license": "(GPL-3.0 AND MIT)"})
    _dep_with_licence(root, "gpl-dep", {"license": "GPL-3.0"})
    rc, out, _ = run(root)
    assert rc == 1, out
    # OR with an allowed member passes; AND with a disallowed member fails.
    assert "and-dep" in out and "gpl-dep" in out
    assert "or-dep" not in out


def test_spdx_or_with_one_allowed_passes(tmp_path):
    root = tmp_path / "proj"
    write(root / "src" / "a.ts", "export const a = 1;\n")
    pkg(root, deps={"or-dep": "1.0.0"})
    _dep_with_licence(root, "or-dep", {"license": "(GPL-3.0 OR MIT)"})
    rc, out, _ = run(root)
    assert rc == 0, out


def test_legacy_licenses_array_is_read(tmp_path):
    root = tmp_path / "proj"
    write(root / "src" / "a.ts", "export const a = 1;\n")
    pkg(root, deps={"legacy-dep": "1.0.0"})
    _dep_with_licence(
        root, "legacy-dep", {"licenses": [{"type": "MIT", "url": "https://example.com"}]}
    )
    rc, out, _ = run(root)
    assert rc == 0, out


def test_no_source_files_is_incomplete_not_clean(tmp_path):
    """A scan that checked nothing must not report OK."""
    root = tmp_path / "proj"
    pkg(root)
    rc, out, _ = run(root)
    assert rc == 2, out
    assert "INCOMPLETE" in out or "nothing was checked" in out


def test_empty_dir_is_incomplete_exit_2(tmp_path):
    """Round 7 (F-13): an empty directory — no source files and no
    package.json — checked nothing, so it exits 2 (INCOMPLETE), not
    1. Exit 1 is for a real violation; exit 2 means nothing was
    checked (the same rule as monitoring's verify.sh)."""
    root = tmp_path / "proj"
    root.mkdir()
    rc, out, _ = run(root)
    assert rc == 2, out
    assert "INCOMPLETE" in out
    assert "nothing was checked" in out
    assert "package.json not found" in out


def test_python_project_is_incomplete_exit_2_names_the_stack(tmp_path):
    """Round 7 (F-08/F-13): a Python project has no TypeScript source
    and no package.json, so nothing was checked — exit 2, and the
    reason names the stack it detected instead of only saying what
    is missing. The checker is npm/TypeScript-only; it does not
    pretend to check a Python project."""
    root = tmp_path / "proj"
    write(root / "pyproject.toml", '[project]\nname = "fixture"\n')
    write(root / "src" / "main.py", "print('hello')\n")
    rc, out, _ = run(root)
    assert rc == 2, out
    assert "INCOMPLETE" in out
    assert "Python" in out


def test_go_project_is_incomplete_exit_2_names_the_stack(tmp_path):
    """Round 7 (F-08/F-13): same as the Python case, for a Go
    project (go.mod, .go files under src/)."""
    root = tmp_path / "proj"
    write(root / "go.mod", "module fixture\n\ngo 1.22\n")
    write(root / "src" / "main.go", "package main\n")
    rc, out, _ = run(root)
    assert rc == 2, out
    assert "INCOMPLETE" in out
    assert "Go" in out


def test_real_licence_violation_stays_exit_1(tmp_path):
    """Round 7 (F-13): exit 2 is only for nothing-checked. A real
    violation — here a GPL dependency in an otherwise valid npm
    project — still exits 1."""
    root = tmp_path / "proj"
    write(root / "src" / "a.ts", "export const a = 1;\n")
    pkg(root, deps={"gpl-dep": "1.0.0"})
    _dep_with_licence(root, "gpl-dep", {"license": "GPL-3.0"})
    rc, out, _ = run(root)
    assert rc == 1, out
    assert "gpl-dep" in out


def test_deep_chain_does_not_hit_the_recursion_limit(tmp_path):
    """A 1100-deep import chain must not raise RecursionError (the old
    recursive DFS hit Python's limit of 1000)."""
    root = tmp_path / "proj"
    n = 1100
    for i in range(n):
        nxt = f"./f{i + 1}.js" if i + 1 < n else "./f0.js"
        write(root / "src" / f"f{i}.ts", f'import {{ x }} from "{nxt}";\nexport const x{i} = x;\n')
    pkg(root)
    rc, out, err = run(root)
    assert "RecursionError" not in err
    assert rc == 1, out
    assert "circular import" in out


# --- Second review round: regression tests (2026-11-06) ---


def test_jsonc_tsconfig_with_comments_is_parsed(tmp_path):
    """A tsconfig with // comments and a trailing comma must still
    load its paths aliases — it used to fail silently and drop them."""
    root = tmp_path / "proj"
    write(
        root / "tsconfig.json",
        '{\n  // the base config\n  "compilerOptions": {\n'
        '    "paths": { "@/*": ["src/*"], },\n  },\n}\n',
    )
    write(root / "src" / "a.ts", 'import { b } from "@/b";\nexport const a = b;\n')
    write(root / "src" / "b.ts", 'import { a } from "./a.js";\nexport const b = a;\n')
    pkg(root)
    rc, out, _ = run(root)
    assert rc == 1, out
    assert "circular import" in out


def test_unparseable_tsconfig_is_incomplete_not_clean(tmp_path):
    """A tsconfig that exists but cannot be parsed must not silently
    shrink the import graph — the run is INCOMPLETE. Round 7 (F-13):
    the import graph is unknown, so nothing trustworthy was checked
    — exit 2, the same as the nothing-checked case, not 1."""
    root = tmp_path / "proj"
    write(root / "tsconfig.json", '{"compilerOptions": {"paths": {"@/*": ["src/*"]')
    write(root / "src" / "a.ts", 'import { b } from "@/b";\nexport const a = b;\n')
    write(root / "src" / "b.ts", "export const b = 1;\n")
    pkg(root)
    rc, out, _ = run(root)
    assert rc == 2, out
    assert "INCOMPLETE" in out
    assert "tsconfig" in out


def test_baseurl_is_honoured(tmp_path):
    """paths resolve relative to baseUrl, not relative to the root:
    with baseUrl "src", @/b must find src/lib/b, not lib/b."""
    root = tmp_path / "proj"
    write(
        root / "tsconfig.json",
        json.dumps({"compilerOptions": {"baseUrl": "src", "paths": {"@/*": ["lib/*"]}}}),
    )
    write(root / "src" / "lib" / "b.ts", "export const b = 1;\n")
    write(root / "src" / "a.ts", 'import { b } from "@/b";\nexport const a = b;\n')
    pkg(root)
    rc, out, _ = run(root)
    assert rc == 0, out


def test_tsconfig_extends_is_followed(tmp_path):
    """A tsconfig that extends a base config inherits its paths."""
    root = tmp_path / "proj"
    write(
        root / "tsconfig.base.json", json.dumps({"compilerOptions": {"paths": {"@/*": ["src/*"]}}})
    )
    write(
        root / "tsconfig.json",
        json.dumps({"extends": "./tsconfig.base.json", "compilerOptions": {}}),
    )
    write(root / "src" / "a.ts", 'import { b } from "@/b";\nexport const a = b;\n')
    write(root / "src" / "b.ts", 'import { a } from "./a.js";\nexport const b = a;\n')
    pkg(root)
    rc, out, _ = run(root)
    assert rc == 1, out
    assert "circular import" in out


def test_star_pattern_does_not_flag_package_imports(tmp_path):
    """A catch-all "*" pattern must not turn every package import
    (react, ...) into a false "unresolved import"."""
    root = tmp_path / "proj"
    write(root / "tsconfig.json", json.dumps({"compilerOptions": {"paths": {"*": ["src/*"]}}}))
    write(
        root / "src" / "a.ts",
        'import { r } from "react";\nimport { b } from "./b.js";\nexport const a = b;\n',
    )
    write(root / "src" / "b.ts", "export const b = 1;\n")
    pkg(root, deps={"react": "18.0.0"})
    _dep_with_licence(root, "react", {"license": "MIT"})
    rc, out, _ = run(root)
    assert rc == 0, out
    assert "unresolved import" not in out


def test_longest_prefix_pattern_wins(tmp_path):
    """When two patterns match, TypeScript picks the longest prefix —
    the checker must resolve the same file, not the first pattern's."""
    root = tmp_path / "proj"
    write(
        root / "tsconfig.json",
        json.dumps({"compilerOptions": {"paths": {"@/*": ["wrong/*"], "@/deep/*": ["src/*"]}}}),
    )
    write(root / "src" / "b.ts", 'import { a } from "./a.js";\nexport const b = a;\n')
    write(root / "src" / "a.ts", 'import { b } from "@/deep/b";\nexport const a = b;\n')
    pkg(root)
    rc, out, _ = run(root)
    assert rc == 1, out
    assert "circular import" in out


def test_regex_literal_with_quote_does_not_swallow_imports(tmp_path):
    """A regex literal containing a quote (/'/) must not make the
    comment stripper think a string opened and swallow the rest of
    the file — the import after it must still be seen."""
    root = tmp_path / "proj"
    write(
        root / "src" / "a.ts",
        'const re = /\'/;\nimport { h } from "../tests/helper.js";\nexport const a = h;\n',
    )
    write(root / "tests" / "helper.ts", "export const h = 1;\n")
    pkg(root)
    rc, out, _ = run(root)
    assert rc == 1, out
    assert "layer violation" in out


def test_spdx_parentheses_and_precedence(tmp_path):
    """(MIT OR GPL-3.0) AND Apache-2.0 passes: MIT satisfies the OR
    branch and Apache-2.0 satisfies the AND. The old code required
    every licence in the expression to be allowed, so it rejected it."""
    root = tmp_path / "proj"
    write(root / "src" / "a.ts", "export const a = 1;\n")
    pkg(root, deps={"ok-dep": "1.0.0", "bad-dep": "1.0.0"})
    _dep_with_licence(root, "ok-dep", {"license": "(MIT OR GPL-3.0) AND Apache-2.0"})
    _dep_with_licence(root, "bad-dep", {"license": "(MIT AND GPL-3.0)"})
    rc, out, _ = run(root)
    assert rc == 1, out
    assert "bad-dep" in out
    assert "ok-dep" not in out


# --- Third review round: regression tests (2026-11-06) ---


def test_inherited_baseurl_resolves_against_the_base_config(tmp_path):
    """A baseUrl inherited from a base config resolves against the
    BASE config's directory (the file that declared it), not the
    child's: the old code resolved it against the child's directory,
    so @/b pointed at config/src/lib/b and the import was reported
    unresolved."""
    root = tmp_path / "proj"
    write(
        root / "tsconfig.base.json",
        json.dumps({"compilerOptions": {"baseUrl": "src", "paths": {"@/*": ["lib/*"]}}}),
    )
    write(
        root / "config" / "tsconfig.json",
        json.dumps({"extends": "../tsconfig.base.json", "compilerOptions": {}}),
    )
    write(root / "src" / "lib" / "b.ts", "export const b = 1;\n")
    write(root / "src" / "a.ts", 'import { b } from "@/b";\nexport const a = b;\n')
    pkg(root)
    rc, out, _ = run(root, "--tsconfig", str(root / "config" / "tsconfig.json"))
    assert rc == 0, out
    assert "unresolved import" not in out


def test_inherited_paths_without_baseurl_resolve_against_the_base_config(tmp_path):
    """Paths inherited from a base config, with no baseUrl anywhere,
    resolve against the BASE config's directory (the file that
    declared them) — not the child's directory."""
    root = tmp_path / "proj"
    write(
        root / "tsconfig.base.json",
        json.dumps({"compilerOptions": {"paths": {"@/*": ["src/lib/*"]}}}),
    )
    write(
        root / "config" / "tsconfig.json",
        json.dumps({"extends": "../tsconfig.base.json", "compilerOptions": {}}),
    )
    write(root / "src" / "lib" / "b.ts", "export const b = 1;\n")
    write(root / "src" / "a.ts", 'import { b } from "@/b";\nexport const a = b;\n')
    pkg(root)
    rc, out, _ = run(root, "--tsconfig", str(root / "config" / "tsconfig.json"))
    assert rc == 0, out
    assert "unresolved import" not in out


def test_child_baseurl_wins_over_inherited_paths(tmp_path):
    """When the child declares its own baseUrl, the inherited paths
    resolve against the CHILD's baseUrl — the child's declaration
    wins over the base's (which declares none here)."""
    root = tmp_path / "proj"
    write(
        root / "tsconfig.base.json", json.dumps({"compilerOptions": {"paths": {"@/*": ["lib/*"]}}})
    )
    write(
        root / "tsconfig.json",
        json.dumps({"extends": "./tsconfig.base.json", "compilerOptions": {"baseUrl": "src"}}),
    )
    write(root / "src" / "lib" / "b.ts", "export const b = 1;\n")
    write(root / "src" / "a.ts", 'import { b } from "@/b";\nexport const a = b;\n')
    pkg(root)
    rc, out, _ = run(root)
    assert rc == 0, out
    assert "unresolved import" not in out
