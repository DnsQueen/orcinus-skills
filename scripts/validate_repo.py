#!/usr/bin/env python3
"""Validate the ORCINUS repo: the checks CI runs on every change.

Stdlib only. Exit 0 when clean, 1 when any check fails. Run:
    python3 scripts/validate_repo.py

Checks:
  1. Every skills/*/SKILL.md has valid frontmatter: name matches the
     folder, description is non-empty, license is present and known,
     and the file is under 500 lines. Only the router is a user entry
     point: every sub-skill carries user-invocable: false (a real
     boolean), the router must not, and no skill may set
     disable-model-invocation: true (the router invokes sub-skills
     itself).
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
  9. No SKILL.md references a file outside its own skill folder:
     a reference that only resolves in a full-repo install dangles
     in a skill-only install. ${CLAUDE_PLUGIN_ROOT} paths to the same
     skill, paths in the user's project, skill names, and the
     publishing instructions are allowed; anything else that looks
     like a path must resolve to a file inside the skill folder.
 10. Plugin components are registered where Claude Code discovers
     them: agents/ and commands/ at the plugin root (discovered by
     folder, not listed in plugin.json), with no stale copies left
     inside the skill folders. Each agent file must carry frontmatter
     with name == its filename and a non-empty description — without
     those it is not discovered either.
 11. The version in .claude-plugin/plugin.json equals the latest
     ## [x.y.z] heading in CHANGELOG.md — a version bump and its
     changelog entry travel together.
 12. The Hermes bundle hermes/orcinus.yaml exists, parses, lists
     only skills that exist in skills/, and lists the router only:
     Hermes silently skips a bundle skill that is not installed, so
     a stale name would fail silently at runtime, and a bundle loads
     everything it lists at once, so listing sub-skills would dump
     the whole collection into one message.
 13. The Supported versions table in SECURITY.md must say Yes for the
     major.minor of the version in .claude-plugin/plugin.json.
 14. The router's bundled resources are current: the state spec in
     skills/orcinus/references/project-state.md is a byte-identical
     copy of docs/project-state.md, and the status table in
     skills/orcinus/references/skill-status.md is exactly what
     scripts/generate_router_resources.py produces from docs/MAP.md —
     so a standalone install, which has no docs/, still has the
     status table and the state spec.
 15. Stage containment: each fine router stage's primary skill
     contains that stage in its stages.json range, and every coarse
     stages.json range starts and ends on a router stage boundary —
     so the manifest and the router agree about when a skill applies.
 16. Every modified Apache-2.0 file carries its ORCINUS change
     notice in the file itself (Apache-2.0 §4(b)).
 17. No sub-skill description tells the user to type /<skill>:
     sub-skills are user-invocable: false, so the instruction is a
     dead end.
 18. The skill table in README.md is exactly what
     scripts/generate_readme_table.py produces from
     skills/manifest.json — a hand-edited table drifts from the
     inventory silently.

A check that cannot run (missing file it needs) is reported as a
failure, never silently skipped — except where the check itself says
otherwise. Dates in this repo are Asia/Tehran local time unless a
file says UTC.
"""

import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KNOWN_LICENSES = {
    "MIT",
    "Apache-2.0",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "ISC",
    "CC-BY-4.0",
    "CC-BY-SA-4.0",
    "Unlicense",
}
MAX_SKILL_LINES = 500
# Agent Skills spec (agentskills.io/specification): name is 1-64
# characters, lowercase letters, digits, hyphens, no leading,
# trailing, or double hyphen, and must match the folder; description
# is 1-1024 characters; compatibility is at most 500 characters;
# metadata is a map from string keys to string values. The six spec
# fields are name, description, license, compatibility, metadata,
# allowed-tools. Claude Code adds extension fields (user-invocable,
# disable-model-invocation, when_to_use, argument-hint) that other
# hosts ignore; anything else in frontmatter is rejected.
NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
ALLOWED_FRONTMATTER = {
    "name",
    "description",
    "license",
    "compatibility",
    "metadata",
    "allowed-tools",
    "user-invocable",
    "disable-model-invocation",
    "when_to_use",
    "argument-hint",
}


def _license_is_known(expr):
    """A license field is one known license, or an SPDX expression
    joining known licenses with AND/OR. The independent-review skill
    is 'MIT AND Apache-2.0': its own text is MIT, the agents it
    bundles are Apache-2.0."""
    if not isinstance(expr, str) or not expr.strip():
        return False
    parts = re.split(r"\s+(?:AND|OR)\s+", expr.strip())
    return all(p in KNOWN_LICENSES for p in parts)


failures = []
warnings = []


def fail(msg):
    failures.append(msg)


def warn(msg):
    warnings.append(msg)


def _strip_comment(line):
    """Remove a YAML comment (# ...) from a plain-scalar line. A #
    starts a comment only when preceded by whitespace; inside quotes
    it is literal (callers handle quoted scalars before this)."""
    for i, ch in enumerate(line):
        if ch == "#" and (i == 0 or line[i - 1] in " \t"):
            return line[:i].rstrip()
    return line


def _value_before_comment(value):
    """Return the value part of a `key: value` line, dropping a
    trailing comment. For quoted and flow values the comment starts
    after the closing quote/bracket; for plain values it starts at a
    '#' preceded by whitespace. Anything else after the closing
    quote/bracket is an error, not silently ignored."""
    value = value.strip()
    if not value:
        return value
    if value[0] in "\"'":
        quote = value[0]
        i = 1
        while i < len(value):
            ch = value[i]
            if quote == "'" and ch == "'":
                if i + 1 < len(value) and value[i + 1] == "'":
                    i += 2
                    continue
                return value[: i + 1]
            if quote == '"' and ch == "\\":
                i += 2
                continue
            if quote == '"' and ch == '"':
                return value[: i + 1]
            i += 1
        raise ValueError(f"unterminated quoted scalar: {value!r}")
    if value[0] in "[{":
        open_ch, close_ch = value[0], "]" if value[0] == "[" else "}"
        depth, quote, i = 0, None, 0
        while i < len(value):
            ch = value[i]
            if quote is not None:
                if ch == quote:
                    quote = None
                i += 1
                continue
            if ch in "\"'":
                quote = ch
            elif ch == open_ch:
                depth += 1
            elif ch == close_ch:
                depth -= 1
                if depth == 0:
                    rest = value[i + 1 :].strip()
                    if rest and not rest.startswith("#"):
                        raise ValueError(f"unexpected text after value: {value!r}")
                    return value[: i + 1]
            i += 1
        raise ValueError(f"unterminated flow collection: {value!r}")
    return _strip_comment(value).strip()


def _parse_plain_scalar(text):
    """Resolve a plain scalar the way PyYAML does for the cases this
    repo uses: booleans, null, integers, floats, else the string."""
    lowered = text.lower()
    if lowered in ("true", "yes", "on"):
        return True
    if lowered in ("false", "no", "off"):
        return False
    if lowered in ("null", "~", ""):
        return None
    if re.fullmatch(r"[-+]?[0-9]+", text):
        try:
            return int(text)
        except ValueError:
            pass
    if re.fullmatch(r"[-+]?(\.[0-9]+|[0-9]+\.[0-9]*)([eE][-+]?[0-9]+)?", text):
        try:
            return float(text)
        except ValueError:
            pass
    return text


def _parse_inline_scalar(text):
    """Parse one inline scalar: quoted ('...', "..." with escapes),
    flow collection ([a, b], {k: v}), or a plain scalar."""
    text = text.strip()
    if not text:
        return None
    if text[0] == "'":
        if len(text) < 2 or not text.endswith("'"):
            raise ValueError(f"unterminated single-quoted scalar: {text!r}")
        return text[1:-1].replace("''", "'")
    if text[0] == '"':
        if len(text) < 2 or not text.endswith('"'):
            raise ValueError(f"unterminated double-quoted scalar: {text!r}")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            raise ValueError(f"bad double-quoted scalar: {text!r}")
    if text[0] == "[":
        if not text.endswith("]"):
            raise ValueError(f"unterminated flow sequence: {text!r}")
        inner = text[1:-1].strip()
        if not inner:
            return []
        return [_parse_inline_scalar(item) for item in _split_flow(inner)]
    if text[0] == "{":
        if not text.endswith("}"):
            raise ValueError(f"unterminated flow mapping: {text!r}")
        inner = text[1:-1].strip()
        if not inner:
            return {}
        out = {}
        for item in _split_flow(inner):
            if ":" not in item:
                raise ValueError(f"flow mapping item has no colon: {item!r}")
            key, value = item.split(":", 1)
            out[_parse_inline_scalar(key)] = _parse_inline_scalar(value)
        return out
    return _parse_plain_scalar(_strip_comment(text).strip())


def _split_flow(text):
    """Split a flow collection's inner text on top-level commas."""
    parts, depth, current, quote = [], 0, "", None
    for ch in text:
        if quote is not None:
            current += ch
            if ch == quote:
                quote = None
            continue
        if ch in "'\"":
            quote, current = ch, current + ch
        elif ch in "[{":
            depth, current = depth + 1, current + ch
        elif ch in "]}":
            depth, current = depth - 1, current + ch
        elif ch == "," and depth == 0:
            parts.append(current.strip())
            current = ""
        else:
            current += ch
    if current.strip():
        parts.append(current.strip())
    return parts


def _block_scalar_lines(lines, start, parent_indent):
    """Collect the raw lines of a block scalar starting at `start`.
    Returns (content_lines, next_index). The content indent is the
    indent of the first non-empty line; less-indented lines end it."""
    content = []
    indent = None
    i = start
    while i < len(lines):
        raw = lines[i]
        if not raw.strip():
            content.append("")
            i += 1
            continue
        cur = len(raw) - len(raw.lstrip(" "))
        if cur <= parent_indent:
            break
        if indent is None:
            indent = cur
        content.append(raw[indent:] if len(raw) >= indent else "")
        i += 1
    # Trailing blank lines are part of the scalar (chomping decides
    # how many survive); the caller applies chomping.
    return content, i


def _apply_chomping(text, chomp):
    """YAML chomping: '-' strips all trailing newlines, '+' keeps
    them, the default (clip) keeps exactly one when there is text."""
    if chomp == "-":
        return text.rstrip("\n")
    if chomp == "+":
        return text
    return text.rstrip("\n") + "\n" if text else ""


def _parse_block(lines, start, indent):
    """Parse a YAML block starting at line `start` with the given
    indent. Returns (value, next_index)."""
    # Skip blank/comment-only lines to find the first content line.
    i = start
    while i < len(lines):
        stripped = lines[i].strip()
        if stripped and not stripped.startswith("#"):
            break
        i += 1
    if i >= len(lines):
        return None, i
    first = lines[i]
    cur_indent = len(first) - len(first.lstrip(" "))
    if cur_indent < indent:
        return None, start
    if first.lstrip().startswith("- ") or first.strip() == "-":
        items = []
        while i < len(lines):
            raw = lines[i]
            stripped = raw.strip()
            if not stripped or stripped.startswith("#"):
                i += 1
                continue
            cur = len(raw) - len(raw.lstrip(" "))
            if cur != indent or not raw.lstrip().startswith("-"):
                break
            after = raw.lstrip()[1:]
            if after.startswith(" "):
                after = after[1:]
            if not after.strip():
                value, i = _parse_block(lines, i + 1, indent + 1)
                items.append(value)
            elif ":" in after and not after.strip().startswith(('"', "'")):
                # "- key: value" — an inline mapping start.
                sub = [raw[:cur] + " " * 2 + after]
                j = i + 1
                while j < len(lines):
                    nxt = lines[j]
                    if not nxt.strip() or nxt.strip().startswith("#"):
                        j += 1
                        continue
                    if len(nxt) - len(nxt.lstrip(" ")) <= indent:
                        break
                    sub.append(nxt)
                    j += 1
                value, _ = _parse_block(sub, 0, cur + 2)
                items.append(value)
                i = j
            else:
                items.append(_parse_inline_scalar(after))
                i += 1
        return items, i
    # Mapping: lines of "key: value" at this indent.
    mapping = {}
    while i < len(lines):
        raw = lines[i]
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            i += 1
            continue
        cur = len(raw) - len(raw.lstrip(" "))
        if cur != indent:
            break
        if ":" not in stripped:
            raise ValueError(f"frontmatter line has no colon: {raw!r}")
        key, rest = stripped.split(":", 1)
        key = key.strip()
        rest = _value_before_comment(rest.strip())
        if not key:
            raise ValueError(f"frontmatter line has an empty key: {raw!r}")
        if rest in (">", "|", ">-", ">+", "|-", "|+"):
            folded = rest.startswith(">")
            chomp = rest[1:] if len(rest) > 1 else ""
            content, i = _block_scalar_lines(lines, i + 1, indent)
            if folded:
                # Folding: adjacent non-empty lines join with a space;
                # each blank line is a paragraph break (one newline).
                text = ""
                for line in content:
                    if line == "":
                        text += "\n"
                    else:
                        text += (" " if text and not text.endswith("\n") else "") + line
            else:
                text = "\n".join(content)
            mapping[key] = _apply_chomping(text, chomp)
            continue
        if rest == "":
            # Nested block on the following lines, or an empty value.
            j = i + 1
            while j < len(lines):
                nxt = lines[j].strip()
                if nxt and not nxt.startswith("#"):
                    break
                j += 1
            if j < len(lines):
                nxt_indent = len(lines[j]) - len(lines[j].lstrip(" "))
                if nxt_indent > indent:
                    value, i = _parse_block(lines, j, nxt_indent)
                    mapping[key] = value
                    continue
            mapping[key] = None
            i += 1
            continue
        # Plain scalar, possibly continued on more-indented lines.
        value = rest
        j = i + 1
        parts = [value]
        while j < len(lines):
            nxt = lines[j]
            if not nxt.strip() or nxt.strip().startswith("#"):
                break
            nxt_indent = len(nxt) - len(nxt.lstrip(" "))
            if nxt_indent <= indent:
                break
            parts.append(nxt.strip())
            j += 1
        if len(parts) > 1:
            value = " ".join(parts)
            i = j
        else:
            i += 1
        mapping[key] = _parse_inline_scalar(value)
    return mapping, i


def parse_frontmatter(path):
    """Parse the YAML frontmatter of a SKILL.md with a small YAML
    subset parser (stdlib only): mappings, block sequences, flow
    collections, quoted scalars, plain scalars (bool/null/number),
    block scalars (> folded, | literal, with -/+ chomping), and
    comments. Anything outside the subset is an error, never a
    silent misread. Returns (fields, error). The test suite checks
    this parser against PyYAML on every SKILL.md in the repo."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return None, "missing frontmatter (must start with ---)"
    end = text.find("\n---\n", 4)
    if end < 0:
        return None, "frontmatter is not closed with ---"
    try:
        fields, _ = _parse_block(text[4:end].splitlines(), 0, 0)
    except ValueError as e:
        return None, str(e)
    if fields is None:
        return {}, None
    if not isinstance(fields, dict):
        return None, "frontmatter is not a mapping"
    return fields, None


def parse_yaml_file(path):
    """Parse a plain YAML file (no --- delimiters) with the same
    subset parser as frontmatter. Returns (data, error)."""
    text = path.read_text(encoding="utf-8")
    try:
        data, _ = _parse_block(text.splitlines(), 0, 0)
    except ValueError as e:
        return None, str(e)
    if data is None:
        return {}, None
    if not isinstance(data, dict):
        return None, "file is not a mapping"
    return data, None


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
            fail(
                f"{skill_dir.name}/SKILL.md: {len(lines)} lines, "
                f"over the {MAX_SKILL_LINES}-line cap"
            )
        fields, err = parse_frontmatter(skill)
        if err:
            fail(f"{skill_dir.name}/SKILL.md: {err}")
            continue
        for key in sorted(fields):
            if key not in ALLOWED_FRONTMATTER:
                fail(
                    f"{skill_dir.name}/SKILL.md: frontmatter field "
                    f"{key!r} is not a spec field or a Claude Code "
                    f"extension field"
                )
        name = fields.get("name")
        if not isinstance(name, str) or not NAME_RE.match(name) or len(name) > 64:
            fail(
                f"{skill_dir.name}/SKILL.md: frontmatter name {name!r} "
                f"must be 1-64 lowercase letters, digits, and hyphens, "
                f"with no leading, trailing, or double hyphen"
            )
        elif name != skill_dir.name:
            fail(
                f"{skill_dir.name}/SKILL.md: frontmatter name is "
                f"{name!r}, expected {skill_dir.name!r}"
            )
        desc = fields.get("description")
        if not isinstance(desc, str) or not 1 <= len(desc) <= 1024:
            fail(
                f"{skill_dir.name}/SKILL.md: frontmatter description "
                f"must be a string of 1-1024 characters"
            )
        lic = fields.get("license")
        if not lic:
            fail(f"{skill_dir.name}/SKILL.md: frontmatter license is missing")
        elif not _license_is_known(lic):
            fail(f"{skill_dir.name}/SKILL.md: unknown license {lic!r}")
        compat = fields.get("compatibility")
        if compat is not None and (not isinstance(compat, str) or len(compat) > 500):
            fail(
                f"{skill_dir.name}/SKILL.md: compatibility must be a "
                f"string of at most 500 characters"
            )
        metadata = fields.get("metadata")
        if metadata is not None and (
            not isinstance(metadata, dict)
            or not all(isinstance(k, str) and isinstance(v, str) for k, v in metadata.items())
        ):
            fail(
                f"{skill_dir.name}/SKILL.md: metadata must be a map "
                f"from string keys to string values (Agent Skills spec)"
            )
        for flag in ("user-invocable", "disable-model-invocation"):
            if flag in fields and not isinstance(fields[flag], bool):
                fail(f"{skill_dir.name}/SKILL.md: {flag} must be a boolean")
        # One install, one entry point: the user invokes only the
        # router. Every sub-skill hides from the / menu
        # (user-invocable: false — a real boolean, not the string
        # "false"), and no skill may block model invocation: the
        # router invokes sub-skills itself.
        if skill_dir.name == "orcinus":
            if fields.get("user-invocable") is False:
                fail(
                    "orcinus/SKILL.md: the router must stay "
                    "user-invocable — it is the one entry point"
                )
        elif fields.get("user-invocable") is not False:
            fail(
                f"{skill_dir.name}/SKILL.md: user-invocable must be "
                f"false — only the router is a user entry point"
            )
        if fields.get("disable-model-invocation") is True:
            fail(
                f"{skill_dir.name}/SKILL.md: disable-model-invocation "
                f"must not be true — the router invokes sub-skills "
                f"itself"
            )


def license_from_file(path):
    """Best-effort license identifier from a LICENSE.txt."""
    text = path.read_text(encoding="utf-8", errors="ignore")
    if "Apache License" in text and "Version 2.0" in text:
        return "Apache-2.0"
    if text.startswith("MIT License"):
        return "MIT"
    if (
        "BSD 3-Clause" in text
        or "Redistribution and use in source and binary forms" in text
        and "Neither the name" in text
    ):
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
            fail(
                f"{skill_dir.name}: LICENSE.txt exists but ATTRIBUTION.md "
                f"is missing — explain the upstream source"
            )
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
        copied = bool(
            re.search(r"byte-identical|bundled|copied verbatim|is verbatim|are verbatim", lower)
        )
        if copied and not lic.is_file():
            fail(
                f"{skill_dir.name}: ATTRIBUTION.md says upstream content "
                f"was copied or bundled, but LICENSE.txt is missing"
            )
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
                fail(
                    f"{skill_dir.name}: ATTRIBUTION.md says license "
                    f"{attr_lic!r} but the frontmatter says {front!r}"
                )
        file_lic = license_from_file(lic) if lic.is_file() else None
        if file_lic and file_lic != front:
            # The frontmatter license is the skill's own text; the
            # LICENSE.txt is the bundled files' license. They may
            # differ legitimately (e.g. independent-review: MIT text,
            # Apache-2.0 bundled agents) — but then ATTRIBUTION.md
            # must say so explicitly.
            if (
                "bundled" not in attr_text.lower()
                and "own-words" not in attr_text.lower()
                and "own words" not in attr_text.lower()
            ):
                fail(
                    f"{skill_dir.name}: LICENSE.txt is {file_lic} but the "
                    f"frontmatter says {front!r}, and ATTRIBUTION.md does "
                    f"not explain the split"
                )


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
                fail(
                    f"THIRD_PARTY_NOTICES.md does not list "
                    f"{skill_dir.name} (it has an ATTRIBUTION.md)"
                )
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
            fail(
                f"THIRD_PARTY_NOTICES.md says {name} is {row.group(1)} "
                f"but its ATTRIBUTION.md says {attr_lic!r}"
            )


def check_glossary_copy():
    root_glossary = ROOT / "GLOSSARY.md"
    bundled = ROOT / "skills" / "orcinus" / "references" / "GLOSSARY.md"
    if not root_glossary.is_file():
        fail("GLOSSARY.md is missing at the repo root")
        return
    if not bundled.is_file():
        fail(
            "skills/orcinus/references/GLOSSARY.md is missing — the "
            "router's glossary must travel with the skill"
        )
        return
    if root_glossary.read_bytes() != bundled.read_bytes():
        fail(
            "skills/orcinus/references/GLOSSARY.md differs from the "
            "canonical GLOSSARY.md — copy the root file over it"
        )


def _load_router_generator():
    """Load scripts/generate_router_resources.py as a module, or None
    when the script is missing (the caller reports that as a failure)."""
    return _load_script_module("generate_router_resources")


def _load_readme_table_generator():
    """Load scripts/generate_readme_table.py as a module, or None
    when the script is missing (the caller reports that as a failure)."""
    return _load_script_module("generate_readme_table")


def _load_script_module(name):
    """Load a scripts/<name>.py file as a module, or None."""
    path = ROOT / "scripts" / f"{name}.py"
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_router_resources():
    """The router's bundled resources are current: the state spec is a
    byte-identical copy of docs/project-state.md, and the status table
    is exactly what the generator produces from docs/MAP.md. In a
    standalone install docs/ does not exist, so a stale or missing
    copy misclassifies skills or loses the state spec."""
    map_file = ROOT / "docs" / "MAP.md"
    state_file = ROOT / "docs" / "project-state.md"
    bundled_state = ROOT / "skills" / "orcinus" / "references" / "project-state.md"
    bundled_status = ROOT / "skills" / "orcinus" / "references" / "skill-status.md"
    if not map_file.is_file():
        fail("docs/MAP.md is missing")
        return
    if not state_file.is_file():
        fail("docs/project-state.md is missing")
        return
    generator = _load_router_generator()
    if generator is None:
        fail(
            "scripts/generate_router_resources.py is missing — the "
            "router's bundled resources cannot be checked"
        )
        return
    if not bundled_state.is_file():
        fail(
            "skills/orcinus/references/project-state.md is missing — "
            "the router's state spec must travel with the skill"
        )
    elif bundled_state.read_bytes() != state_file.read_bytes():
        fail(
            "skills/orcinus/references/project-state.md differs from "
            "docs/project-state.md — re-run "
            "scripts/generate_router_resources.py"
        )
    if not bundled_status.is_file():
        fail(
            "skills/orcinus/references/skill-status.md is missing — "
            "the router's status table must travel with the skill"
        )
    else:
        expected = generator.generate_skill_status(map_file.read_text(encoding="utf-8"))
        if bundled_status.read_text(encoding="utf-8") != expected:
            fail(
                "skills/orcinus/references/skill-status.md is stale — "
                "re-run scripts/generate_router_resources.py after "
                "changing docs/MAP.md"
            )


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
            fail(
                f"stage range mismatch: router {router_name} is "
                f"{r[0]}–{r[1]} but MAP {map_name} is {m[0]}–{m[1]}"
            )
        elif relation == "inside" and not (m[0] <= r[0] and r[1] <= m[1]):
            fail(
                f"stage range mismatch: router {router_name} is "
                f"{r[0]}–{r[1]}, which is not inside MAP {map_name} "
                f"{m[0]}–{m[1]}"
            )
    # The linear stages must not overlap: a stage detected from
    # evidence must name one stage, not two.
    linear = ["Idea", "Architecture", "Scaffold", "Build", "Verify", "Finalize"]
    prev = None
    for name in linear:
        r = router_ranges.get(name)
        if r is None:
            continue
        if prev is not None and r[0] <= prev[1]:
            fail(
                f"linear stage ranges overlap: {name} starts at "
                f"{r[0]} but the previous stage ends at {prev[1]}"
            )
        prev = r


# The fine stage of the router each primary skill serves: the skill's
# coarse stages.json range must contain that fine range. Cross-cutting
# skills (skill-creator, accessibility) are staged by their audit band,
# not by a linear stage, so they are covered by the boundary rule below
# instead of this mapping.
STAGE_PRIMARY_SKILLS = {
    "Idea": ["idea-capture", "idea-calibrate"],
    "Architecture": ["architecture"],
    "Scaffold": ["scaffold"],
    "Build": ["build"],
    "Verify": ["orcinus-verify"],
    "Security": ["security-review"],
    "Debugging": ["diagnosing-bugs", "refactor", "incomplete-refactor"],
    "Finalize": ["finalize"],
}


def _parse_range(text):
    """Parse a 'low-high' range string into (low, high), or None."""
    m = re.fullmatch(r"(\d+)-(\d+)", text.strip())
    if m is None:
        return None
    return (int(m.group(1)), int(m.group(2)))


def check_stage_containment():
    """Every coarse stages.json range is built from the router's fine
    ranges: each fine stage's primary skill contains that stage, and
    every coarse range starts and ends on a fine-range boundary. A
    coarse range that no longer contains its fine stage (or starts
    mid-stage) means the router and the manifest disagree about when
    a skill applies."""
    router = ROOT / "skills" / "orcinus" / "SKILL.md"
    stages_file = ROOT / "skills" / "stages.json"
    if not router.is_file():
        fail("router SKILL.md is missing")
        return
    if not stages_file.is_file():
        fail("skills/stages.json is missing")
        return
    router_ranges = _stage_ranges(router.read_text(encoding="utf-8"))
    try:
        stages = json.loads(stages_file.read_text(encoding="utf-8"))["stages"]
    except (json.JSONDecodeError, KeyError) as e:
        fail(f"skills/stages.json is not readable: {e}")
        return
    # Primary containment: the fine range must sit inside the skill's
    # coarse range.
    for stage, skills in STAGE_PRIMARY_SKILLS.items():
        fine = router_ranges.get(stage)
        if fine is None:
            fail(f"router does not define a range for {stage}")
            continue
        for skill in skills:
            coarse = stages.get(skill)
            if coarse is None:
                fail(f"skills/stages.json has no range for {skill}")
                continue
            ranges = [_parse_range(r) for r in coarse]
            if any(r is None for r in ranges):
                fail(f"skills/stages.json range for {skill} is not 'low-high': {coarse}")
                continue
            if not any(lo <= fine[0] and fine[1] <= hi for lo, hi in ranges):
                fail(
                    f"stage range mismatch: router {stage} is "
                    f"{fine[0]}–{fine[1]} but {skill} is staged {coarse}"
                )
    # Boundary alignment: a coarse range must start and end on a
    # fine-range boundary, so it is a union of fine ranges, never a
    # range that starts or ends mid-stage.
    lows = {r[0] for r in router_ranges.values()}
    highs = {r[1] for r in router_ranges.values()}
    for skill in sorted(stages):
        for text in stages[skill]:
            parsed = _parse_range(text)
            if parsed is None:
                fail(f"skills/stages.json range for {skill} is not 'low-high': {text!r}")
                continue
            if parsed[0] not in lows or parsed[1] not in highs:
                fail(
                    f"skills/stages.json range for {skill} is {text}, "
                    f"which does not start and end on a router stage boundary"
                )


# Files modified from an Apache-2.0 upstream, which must carry their
# change notice in the file itself (Apache-2.0 §4(b)). The list is the
# recorded set: a new modification must be added here with its notice.
# The notice is an HTML comment (Markdown) or a # comment (Python),
# placed right after the frontmatter (or at the top of the script):
# it is invisible in rendering, so the rendered body stays verbatim,
# and it does not touch the frontmatter, which the frontmatter spec
# check would reject as an unknown field.
MODIFIED_APACHE_FILES = [
    "skills/mcp-builder/SKILL.md",
    "skills/skill-creator/SKILL.md",
    "skills/webapp-testing/SKILL.md",
    "skills/webapp-testing/scripts/with_server.py",
    "agents/analyzer.md",
    "agents/comparator.md",
    "agents/grader.md",
]


def check_apache_change_notices():
    """Every modified Apache-2.0 file carries its ORCINUS change
    notice in the file itself."""
    for rel in MODIFIED_APACHE_FILES:
        path = ROOT / rel
        if not path.is_file():
            fail(f"{rel} is missing")
            continue
        if "ORCINUS change notice" not in path.read_text(encoding="utf-8"):
            fail(
                f"{rel} is a modified Apache-2.0 file without its "
                f"ORCINUS change notice (Apache-2.0 §4(b))"
            )


SLASH_COMMAND_RE = re.compile(r"(?<![A-Za-z0-9])/[a-z][a-z0-9-]*")


def check_no_slash_invocation():
    """A sub-skill's description must not tell the user to type
    /<skill>: sub-skills are user-invocable: false, so no slash
    command can invoke them, and the instruction is a dead end."""
    skills_dir = ROOT / "skills"
    if not skills_dir.is_dir():
        fail("skills/ directory is missing")
        return
    for skill_dir in sorted(skills_dir.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill = skill_dir / "SKILL.md"
        if not skill.is_file():
            continue
        fields, err = parse_frontmatter(skill)
        if err:
            continue  # the frontmatter check reports it
        if fields.get("user-invocable") is not False:
            continue  # the router may name slash commands; sub-skills may not
        desc = fields.get("description")
        if not isinstance(desc, str):
            continue
        m = SLASH_COMMAND_RE.search(desc)
        if m:
            fail(
                f"{skill_dir.name}/SKILL.md: description tells the user to "
                f"type {m.group(0)!r}, but sub-skills are not user-invocable"
            )


def check_readme_skill_table():
    """The skill table in README.md is exactly what the generator
    produces from skills/manifest.json — a hand-edited table drifts
    from the inventory silently."""
    readme = ROOT / "README.md"
    manifest_file = ROOT / "skills" / "manifest.json"
    if not readme.is_file():
        fail("README.md is missing")
        return
    if not manifest_file.is_file():
        fail("skills/manifest.json is missing")
        return
    generator = _load_readme_table_generator()
    if generator is None:
        fail(
            "scripts/generate_readme_table.py is missing — the README skill table cannot be checked"
        )
        return
    try:
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        current = generator.table_section(readme.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError) as e:
        fail(f"README skill table cannot be read: {e}")
        return
    if current != generator.build_skill_table(manifest):
        fail("README skill table is stale — run scripts/generate_readme_table.py")


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
                fail(
                    f"plugin.json lists skills path {skill_path!r}, which does not exist"
                    + (" (it escapes the repo)" if target is None else "")
                )
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
                    fail(
                        f"marketplace.json plugin {entry.get('name')!r} has "
                        f"source {source!r}, which does not exist"
                        + (" (it escapes the repo)" if target is None else "")
                    )
        description = data.get("description")
        if not isinstance(description, str) or not description.strip():
            fail(
                "marketplace.json is missing a non-empty description — "
                "`claude plugin validate --strict` warns without one"
            )
    # `claude plugin validate --strict` fails without a plugin icon
    # (ICON_MISSING). The CLI is the real check; this guard keeps the
    # repo green even on a machine without the CLI.
    if not (plugin_dir / "icon.png").is_file():
        fail(
            ".claude-plugin/icon.png is missing — `claude plugin "
            "validate --strict` fails without it (ICON_MISSING)"
        )


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
        m = re.search(r"Router \+ (\d+) focused sub-skills", data.get("description", ""))
        if m is None:
            fail(
                "plugin.json description does not state the sub-skill "
                "count as 'Router + N focused sub-skills'"
            )
        elif int(m.group(1)) != count - 1:
            fail(
                f"plugin.json says 'Router + {m.group(1)} focused "
                f"sub-skills' but there are {count} skill folders "
                f"(router + {count - 1})"
            )
    readme = ROOT / "README.md"
    if readme.is_file():
        text = readme.read_text(encoding="utf-8")
        m = re.search(r"all (\d+) skills", text)
        if m is None:
            fail("README.md does not state the skill count as 'all N skills'")
        elif int(m.group(1)) != count:
            fail(f"README.md says 'all {m.group(1)} skills' but there are {count} skill folders")


def check_manifest():
    """skills/manifest.json is the single source of truth for the skill
    inventory: name, licence, stages, source, integration, and status
    per skill. It must agree with the actual skill folders and with
    each skill's frontmatter, so a skill added, removed, or
    re-licensed without updating the manifest fails the build.
    `integration` says how the skill's content relates to its
    upstream: verbatim (copied from upstream; frontmatter adapted
    only, plus fixes recorded in ATTRIBUTION.md), wrapper (own-words
    method around a bundled as-is upstream component), merged
    (own-words combination of two or more upstreams), or from-scratch
    (no upstream). A non-from-scratch integration needs a full
    github.com source URL and a 40-hex upstream commit; a
    from-scratch skill has neither — a tool it drives is recorded in
    ATTRIBUTION.md, not as a source."""
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
        fail(f"skills/manifest.json lists {name}, but there is no skills/{name} folder")
    valid_stages = {"0-9", "10-19", "20-39", "40-59", "50-79", "80-100", "0-100"}
    stages_path = ROOT / "skills" / "stages.json"
    if not stages_path.is_file():
        fail("skills/stages.json is missing")
        return
    try:
        stages_data = json.loads(stages_path.read_text(encoding="utf-8"))
        registry = stages_data.get("stages")
    except json.JSONDecodeError as e:
        fail(f"skills/stages.json is not valid JSON: {e}")
        return
    if not isinstance(registry, dict):
        fail("skills/stages.json has no 'stages' object")
        return
    for name in sorted(dirs - set(registry)):
        fail(f"skill folder skills/{name} is not in skills/stages.json")
    for name in sorted(set(registry) - dirs):
        fail(f"skills/stages.json lists {name}, but there is no skills/{name} folder")
    url_re = re.compile(r"^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/?$")
    sha_re = re.compile(r"^[0-9a-f]{40}$")
    for name in sorted(set(entries) & dirs):
        entry = entries[name]
        if not isinstance(entry, dict):
            fail(f"skills/manifest.json entry for {name} is not an object")
            continue
        if entry.get("name") != name:
            fail(
                f"skills/manifest.json entry for {name} has name "
                f"{entry.get('name')!r}, expected {name!r}"
            )
        fm, _err = parse_frontmatter(ROOT / "skills" / name / "SKILL.md")
        fm_desc = fm.get("description") if fm else None
        if isinstance(fm_desc, str):
            fm_desc = fm_desc.strip()
        if entry.get("description") != fm_desc:
            fail(
                f"skills/manifest.json says {name} has description "
                f"{str(entry.get('description'))[:60]!r}, but its "
                f"SKILL.md frontmatter says "
                f"{str(fm_desc)[:60]!r} — run "
                f"scripts/generate_manifest.py"
            )
        lic = fm.get("license") if fm else None
        if entry.get("license") != lic:
            fail(
                f"skills/manifest.json says {name} is licensed "
                f"{entry.get('license')!r}, but its SKILL.md frontmatter "
                f"says {lic!r}"
            )
        stages = entry.get("stages")
        if not isinstance(stages, list) or not stages:
            fail(f"skills/manifest.json entry for {name} has no stages")
        else:
            for s in stages:
                if s not in valid_stages:
                    fail(f"skills/manifest.json entry for {name} has unknown stage {s!r}")
            if registry.get(name) is not None and stages != registry[name]:
                fail(
                    f"skills/manifest.json says {name} serves stages "
                    f"{stages}, but skills/stages.json says "
                    f"{registry[name]}"
                )
        if entry.get("status") not in ("built", "external-optional", "todo"):
            fail(
                f"skills/manifest.json entry for {name} has unknown status {entry.get('status')!r}"
            )
        integration = entry.get("integration")
        if integration not in ("verbatim", "wrapper", "merged", "from-scratch"):
            fail(
                f"skills/manifest.json entry for {name} has unknown "
                f"integration {integration!r}: expected 'verbatim', "
                f"'wrapper', 'merged', or 'from-scratch'"
            )
        source = entry.get("source")
        if not source:
            fail(f"skills/manifest.json entry for {name} has no source")
        elif source != "from-scratch" and not url_re.match(source):
            fail(
                f"skills/manifest.json entry for {name} has source "
                f"{source!r}: expected 'from-scratch' or a github.com "
                f"repo URL (no trailing comma)"
            )
        commit = entry.get("upstream_commit")
        frameworks = entry.get("supported_frameworks")
        if frameworks is not None and (
            not isinstance(frameworks, list)
            or not frameworks
            or not all(isinstance(f, str) and f for f in frameworks)
        ):
            fail(
                f"skills/manifest.json entry for {name} has "
                f"supported_frameworks {frameworks!r}: expected a "
                f"non-empty list of framework names"
            )
        if integration == "from-scratch":
            if source != "from-scratch":
                fail(
                    f"skills/manifest.json entry for {name} is "
                    f"from-scratch but source is {source!r} — a "
                    f"from-scratch skill has no upstream repo; record "
                    f"a tool origin in ATTRIBUTION.md, not here"
                )
            if commit is not None:
                fail(
                    f"skills/manifest.json entry for {name} has source "
                    f"'from-scratch' but upstream_commit {commit!r} — "
                    f"the commit belongs to a bundled component, "
                    f"record it in ATTRIBUTION.md, not here"
                )
        else:
            if source == "from-scratch":
                fail(
                    f"skills/manifest.json entry for {name} has "
                    f"integration {integration!r} but source is "
                    f"'from-scratch' — the upstream repo is required"
                )
            if commit is None:
                fail(
                    f"skills/manifest.json entry for {name} has "
                    f"integration {integration!r} but upstream_commit "
                    f"is null — the commit pins the vendored content"
                )
            elif not sha_re.match(commit):
                fail(
                    f"skills/manifest.json entry for {name} has "
                    f"upstream_commit {commit!r}, expected a 40-hex SHA"
                )


def check_json_files():
    """Every JSON file the repo owns must parse. A broken manifest or
    evidence schema is a silent gate failure: the validator would
    crash (or skip) instead of checking."""
    for rel in (
        "skills/manifest.json",
        "skills/orcinus-verify/references/evidence.schema.json",
        ".claude-plugin/plugin.json",
        ".claude-plugin/marketplace.json",
    ):
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
        for ref in sorted(
            set(re.findall(r"(?:skills|docs|evals|examples)/[A-Za-z0-9_./-]+", text))
        ):
            ref = ref.rstrip(").,")
            if not (ROOT / ref).exists():
                fail(f"{doc} references {ref}, which does not exist")


# Paths a SKILL.md may name that live in the USER's project, not the
# repo — they resolve where the skill runs, not where it is installed.
USER_PROJECT_PATHS = (
    "docs/adr/",
    "docs/constitution.md",
    "docs/contract.md",
    "docs/api/openapi.yaml",
    "docs/openapi.yaml",
    "openapi.yaml",
    "ideas/",
    "tasks/",
    "evals/evals.json",
    "GLOSSARY.md",
    "src/",
    "tests/",
    "dist/",
    "node_modules/",
    "mutants/",
    ".claude/",
)
# The first segment of a relative path that means "a file this skill
# owns" (its own subdirectories). A relative file path under any other
# first segment (pages/, modules/, shared/, app/, ...) is the user's
# file — an example of the tree the skill prescribes — not a file this
# skill must contain, so the check does not judge it.
SKILL_OWNED_DIRS = (
    "references",
    "reference",
    "scripts",
    "examples",
    "templates",
    "assets",
    "agents",
    "commands",
    "rules",
    "evals",
)
FILE_EXTENSIONS = (
    ".md",
    ".json",
    ".py",
    ".sh",
    ".mjs",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".yaml",
    ".yml",
    ".txt",
    ".html",
)
# A SKILL.md may name another skill's file only in the publishing
# instructions that tell the reader where to put the folder in a
# public repo ("path like skills/<this-skill>/SKILL.md"). Every other
# skills/<name>/SKILL.md reference is a file in another skill.
PUBLISHING_INSTRUCTION_SKILLS = {
    "frontend-architecture",
    "frontend-data-contracts",
    "frontend-optimistic-mutations",
}


def _skill_reference_targets(text):
    """File-path-like targets named in a SKILL.md: markdown link
    targets and backticked paths."""
    targets = re.findall(r"\[[^\]]*\]\(([^)\s]+)\)", text)
    targets += re.findall(r"`([^`\n]+)`", text)
    return targets


def _looks_like_file_path(target):
    """Whether a backticked string or link target is a file path at
    all, as opposed to a command, an API route, a package name, or
    prose with a slash in it. The check only judges file paths; the
    rest is not its business, and flagging it would drown the real
    findings in false positives (GET /api/tasks, `npx ...`,
    @modelcontextprotocol/sdk, modules/{feature}/, ...)."""
    if not target or any(c.isspace() for c in target):
        return False
    if any(c in target for c in "<>{}*?$'\":"):
        return False
    if target.startswith(("~", "/", "http", "mailto:")) or "://" in target:
        return False
    return True


def check_skill_references():
    """No SKILL.md may reference a file outside its own skill folder.
    A reference that only resolves in a full-repo install dangles in
    a skill-only (npx) install, where only the skill folders are
    present. Allowed: ${CLAUDE_PLUGIN_ROOT}/skills/<same-skill>/...
    (and ${CLAUDE_SKILL_DIR}/..., which is the skill folder itself),
    paths in the user's project, another skill named by its repo
    directory (skills/<name> — the router resolves skills by name),
    and the publishing instructions. A relative file path under one
    of the skill's own subdirectories must resolve to a file inside
    the skill folder; anything else is the user's file, not this
    check's business."""
    for skill_dir in sorted((ROOT / "skills").iterdir()):
        if not skill_dir.is_dir():
            continue
        name = skill_dir.name
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.is_file():
            continue
        text = skill_md.read_text(encoding="utf-8")
        for target in _skill_reference_targets(text):
            # A #fragment names a section in the file, not another file.
            target = target.split("#", 1)[0]
            if not target:
                continue
            # Plugin-root paths are judged by prefix first: they
            # contain $ and {} which the file-path filter below would
            # reject as non-paths.
            if target.startswith("${CLAUDE_PLUGIN_ROOT}/skills/"):
                rest = target[len("${CLAUDE_PLUGIN_ROOT}/skills/") :]
                if rest == name or rest.startswith(name + "/"):
                    continue
                fail(f"{name}/SKILL.md references {target!r}, which is outside this skill")
                continue
            if target.startswith("${CLAUDE_SKILL_DIR}/"):
                continue
            if not _looks_like_file_path(target):
                continue
            if target.startswith("../"):
                fail(f"{name}/SKILL.md references {target!r}, which escapes the skill folder")
                continue
            if target.startswith("skills/"):
                parts = target.rstrip("/").split("/")
                if parts == ["skills"]:
                    continue  # the generic `skills/` directory in prose
                if len(parts) == 2:
                    continue  # a skill name, resolved by the router
                if (
                    name in PUBLISHING_INSTRUCTION_SKILLS
                    and len(parts) == 3
                    and parts[1] == name
                    and parts[2] == "SKILL.md"
                ):
                    continue  # publishing instruction for this skill
                fail(f"{name}/SKILL.md references {target!r}, which is a file in another skill")
                continue
            if target.startswith("evals/"):
                # Only evals/evals.json is a user-project path; any
                # other evals/ path is a repo path that dangles in a
                # skill-only install — unless the skill itself owns
                # that file (a skill-local evals/ folder).
                if target == "evals/evals.json":
                    continue
                try:
                    resolved = (skill_dir / target).resolve()
                except OSError:
                    resolved = None
                if (
                    resolved is not None
                    and resolved.is_relative_to(skill_dir)
                    and resolved.is_file()
                ):
                    continue
                fail(
                    f"{name}/SKILL.md references {target!r}, which is "
                    f"a repo path outside this skill"
                )
                continue
            if any(target == p or target.startswith(p) for p in USER_PROJECT_PATHS):
                continue
            # A relative file path under one of the skill's own
            # subdirectories must exist inside the skill folder. A
            # bare filename, a bare directory, and a path under any
            # other first segment are the user's files, not this
            # check's business.
            stripped = target[2:] if target.startswith("./") else target
            first = stripped.split("/", 1)[0]
            if "/" in stripped and first in SKILL_OWNED_DIRS and stripped.endswith(FILE_EXTENSIONS):
                try:
                    resolved = (skill_dir / stripped).resolve()
                except OSError:
                    resolved = None
                if (
                    resolved is None
                    or not resolved.is_relative_to(skill_dir)
                    or not resolved.is_file()
                ):
                    fail(
                        f"{name}/SKILL.md references {target!r}, which "
                        f"does not exist inside this skill"
                    )


# Agents and commands shipped by this plugin, by the name Claude
# Code registers them under. The six reviewers and the review-pr
# command come from pr-review-toolkit (Apache-2.0); the three
# skill-creator agents come from anthropics/skills (Apache-2.0).
# Both sets used to live inside their skill folders, where Claude
# Code does not discover them.
EXPECTED_AGENTS = [
    "analyzer",
    "code-reviewer",
    "code-simplifier",
    "comment-analyzer",
    "comparator",
    "grader",
    "pr-test-analyzer",
    "silent-failure-hunter",
    "type-design-analyzer",
]
EXPECTED_COMMANDS = ["review-pr"]


def check_plugin_components():
    """Agents and commands live at the plugin root, where Claude Code
    discovers them by folder — not listed in plugin.json, and not
    nested under a skill. A file left in a skill folder is stale: it
    is never registered, and editing it edits the wrong copy. Each
    agent file must carry frontmatter with name == its filename and
    a non-empty description, which is what Claude Code uses to route
    an invocation to it; a command needs a non-empty description to
    show in the / menu."""
    for name in EXPECTED_AGENTS:
        path = ROOT / "agents" / f"{name}.md"
        if not path.is_file():
            fail(f"missing plugin agent: agents/{name}.md")
            continue
        fields, error = parse_frontmatter(path)
        if error is not None:
            fail(f"agents/{name}.md: unparsable frontmatter: {error}")
            continue
        if fields.get("name") != name:
            fail(f"agents/{name}.md: frontmatter name {fields.get('name')!r} != filename {name!r}")
        description = fields.get("description")
        if not isinstance(description, str) or not description.strip():
            fail(f"agents/{name}.md: missing non-empty description")
    for name in EXPECTED_COMMANDS:
        path = ROOT / "commands" / f"{name}.md"
        if not path.is_file():
            fail(f"missing plugin command: commands/{name}.md")
            continue
        fields, error = parse_frontmatter(path)
        if error is not None:
            fail(f"commands/{name}.md: unparsable frontmatter: {error}")
            continue
        description = fields.get("description")
        if not isinstance(description, str) or not description.strip():
            fail(f"commands/{name}.md: missing non-empty description")
    for skill_dir in sorted((ROOT / "skills").iterdir()):
        if not skill_dir.is_dir():
            continue
        for sub in ("agents", "commands"):
            if (skill_dir / sub).exists():
                fail(
                    f"stale plugin component copy: "
                    f"skills/{skill_dir.name}/{sub} — agents and "
                    f"commands live at the plugin root, not in a skill"
                )


VERSION_HEADING_RE = re.compile(r"^## \[(\d+\.\d+\.\d+)\]", re.MULTILINE)


def check_version_matches_changelog():
    """The version in .claude-plugin/plugin.json must equal the
    latest ## [x.y.z] heading in CHANGELOG.md. The version is the
    release's identity: a bump without a changelog entry (or a
    changelog entry without a bump) means the release never happened,
    or happened twice."""
    changelog = ROOT / "CHANGELOG.md"
    if not changelog.is_file():
        fail("CHANGELOG.md is missing")
        return
    match = VERSION_HEADING_RE.search(changelog.read_text(encoding="utf-8"))
    if match is None:
        fail("CHANGELOG.md has no ## [x.y.z] release heading")
        return
    changelog_version = match.group(1)
    plugin = ROOT / ".claude-plugin" / "plugin.json"
    if not plugin.is_file():
        fail(".claude-plugin/plugin.json is missing")
        return
    try:
        version = json.loads(plugin.read_text(encoding="utf-8")).get("version")
    except json.JSONDecodeError as e:
        fail(f".claude-plugin/plugin.json is not valid JSON: {e}")
        return
    if version != changelog_version:
        fail(
            f"plugin.json version {version!r} != CHANGELOG.md latest release {changelog_version!r}"
        )


def check_security_versions():
    """The Supported versions table in SECURITY.md must say Yes for
    the major.minor of the version in .claude-plugin/plugin.json.
    SECURITY.md said 1.0.x while the plugin was 0.9.0: a user reading
    it would conclude the released version is unsupported, and nothing
    checked the table at all."""
    security = ROOT / "SECURITY.md"
    if not security.is_file():
        fail("SECURITY.md is missing")
        return
    yes_row = None
    for line in security.read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 2 and cells[1] == "Yes":
            yes_row = cells[0]
            break
    if yes_row is None:
        fail("SECURITY.md has no Supported versions row marked Yes")
        return
    match = re.fullmatch(r"(\d+)\.(\d+)\.x", yes_row)
    if match is None:
        fail(f"SECURITY.md Yes row {yes_row!r} is not a '<major>.<minor>.x' range")
        return
    plugin = ROOT / ".claude-plugin" / "plugin.json"
    if not plugin.is_file():
        fail(".claude-plugin/plugin.json is missing")
        return
    try:
        version = json.loads(plugin.read_text(encoding="utf-8")).get("version")
    except json.JSONDecodeError as e:
        fail(f".claude-plugin/plugin.json is not valid JSON: {e}")
        return
    major_minor = ".".join(str(version).split(".")[:2]) if version else None
    if major_minor != f"{match.group(1)}.{match.group(2)}":
        fail(f"SECURITY.md says {yes_row} is supported but plugin.json version is {version!r}")


def check_hermes_bundle():
    """The Hermes bundle hermes/orcinus.yaml must exist, parse, list
    only skills that exist in skills/, and list the router only.
    Hermes silently skips a bundle skill that is not installed, so a
    stale name fails silently at runtime instead of at validation
    time; and a bundle loads everything it lists at once, so listing
    sub-skills would dump the whole collection into one message —
    the router loads them on demand instead."""
    path = ROOT / "hermes" / "orcinus.yaml"
    if not path.is_file():
        fail("hermes/orcinus.yaml is missing — Hermes users have no bundle entry point")
        return
    data, error = parse_yaml_file(path)
    if error is not None:
        fail(f"hermes/orcinus.yaml: unparsable YAML: {error}")
        return
    name = data.get("name")
    if name is not None and name != "orcinus":
        fail(f"hermes/orcinus.yaml: name {name!r} != filename stem 'orcinus'")
    description = data.get("description")
    if description is not None and (not isinstance(description, str) or not description.strip()):
        fail("hermes/orcinus.yaml: description must be a non-empty string")
    skills = data.get("skills")
    if not isinstance(skills, list) or not skills:
        fail("hermes/orcinus.yaml: skills must be a non-empty list")
        return
    for skill in skills:
        if not isinstance(skill, str) or not skill.strip():
            fail(f"hermes/orcinus.yaml: skills entry {skill!r} is not a skill name")
            continue
        if not (ROOT / "skills" / skill / "SKILL.md").is_file():
            fail(
                f"hermes/orcinus.yaml: skill {skill!r} has no "
                f"skills/{skill}/SKILL.md — Hermes would silently "
                f"skip it"
            )
    if "orcinus" not in skills:
        fail(
            "hermes/orcinus.yaml: the router 'orcinus' must be listed "
            "— the bundle has no entry point without it"
        )
    extra = [s for s in skills if isinstance(s, str) and s.strip() and s != "orcinus"]
    if extra:
        fail(
            f"hermes/orcinus.yaml: lists sub-skills directly "
            f"({', '.join(extra)}) — this bundle is the entry point; "
            f"the router loads sub-skills on demand"
        )


def main():
    check_skill_frontmatter()
    check_attribution_pairs()
    check_third_party_notices()
    check_glossary_copy()
    check_router_resources()
    check_stage_ranges()
    check_stage_containment()
    check_apache_change_notices()
    check_no_slash_invocation()
    check_readme_skill_table()
    check_plugin_manifests()
    check_skill_counts()
    check_manifest()
    check_json_files()
    check_relative_paths()
    check_skill_references()
    check_plugin_components()
    check_version_matches_changelog()
    check_security_versions()
    check_hermes_bundle()
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
