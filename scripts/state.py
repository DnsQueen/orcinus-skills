#!/usr/bin/env python3
"""Validate and transition `.orcinus/state.json` (round 6, 2-R2).

The state file was spec-only (docs/project-state.md + the digest
helper scripts/content_digest.py): nothing validated it, and nothing
enforced which stage could follow which. The schema lives in
scripts/state_schema.json; this module enforces it plus the
transition rules from docs/project-state.md.

This is a local check, not the v1.1 tamper-proof enforcement layer:
any agent (or human) with write access can still edit the file
(project-state.md Rule 4). What this adds is a machine that refuses
an invalid file or an impossible transition instead of silently
recording it.

Usage:
    python3 scripts/state.py validate <state.json>
    python3 scripts/state.py transition <state.json> --to STAGE
        --revision <sha> --digest sha256:<hex>
        [--evidence <bundle path>] [--note <text>]

Stdlib only.
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "scripts" / "state_schema.json"

STAGES = ("BUILDING", "VERIFYING", "BLOCKED", "VERIFIED", "AWAITING_APPROVAL", "RELEASE_READY")

# Allowed transitions (docs/project-state.md): forward along the
# lifecycle, back to BUILDING on rework. RELEASE_READY is terminal.
# A content-digest change is not in this table: it forces BUILDING
# from any stage (Rule 2), handled in transition().
ALLOWED_TRANSITIONS = {
    "BUILDING": {"VERIFYING"},
    "VERIFYING": {"BLOCKED", "VERIFIED"},
    "BLOCKED": {"BUILDING"},
    "VERIFIED": {"AWAITING_APPROVAL", "BUILDING"},
    "AWAITING_APPROVAL": {"RELEASE_READY", "BUILDING"},
    "RELEASE_READY": set(),
}

_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_REQUIRED = (
    "format_version",
    "project",
    "stage",
    "revision",
    "content_digest",
    "evidence_bundle",
    "approval",
    "history",
)


def load_state(path):
    """Load a state file, or raise ValueError with a controlled
    message (never a traceback for a malformed file)."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as e:
        raise ValueError(f"cannot read state file: {e}") from e
    except json.JSONDecodeError as e:
        raise ValueError(f"state file is not valid JSON: {e}") from e
    if not isinstance(data, dict):
        raise ValueError("state file is not a JSON object")
    return data


def validate_state(data):
    """Problems with a state dict, [] when valid. Mirrors
    scripts/state_schema.json (hand-rolled, stdlib only — the repo
    has no jsonschema dependency)."""
    problems = []
    if not isinstance(data, dict):
        return ["state is not an object"]
    for field in _REQUIRED:
        if field not in data:
            problems.append(f"missing required field: {field}")
    if data.get("format_version") != 2:
        problems.append("format_version must be 2")
    project = data.get("project")
    if project is not None and (not isinstance(project, str) or not project.strip()):
        problems.append("project must be a non-empty string")
    stage = data.get("stage")
    if stage is not None and stage not in STAGES:
        problems.append(f"stage is {stage!r}, expected one of {', '.join(STAGES)}")
    revision = data.get("revision")
    if revision is not None and (not isinstance(revision, str) or not _SHA_RE.match(revision)):
        problems.append("revision must be a commit SHA (7-40 hex chars)")
    digest = data.get("content_digest")
    if digest is not None and (not isinstance(digest, str) or not _DIGEST_RE.match(digest)):
        problems.append("content_digest must be 'sha256:<64 hex chars>'")
    if stage == "VERIFIED" and not data.get("evidence_bundle"):
        problems.append(
            "VERIFIED requires evidence_bundle (a state without one is corrupt, not verified)"
        )
    approval = data.get("approval")
    if approval is not None:
        if not isinstance(approval, dict):
            problems.append("approval must be an object or null")
        elif stage == "RELEASE_READY":
            if approval.get("content_digest") != digest:
                problems.append("approval content_digest does not match the state's content_digest")
    if stage == "RELEASE_READY" and not approval:
        problems.append("RELEASE_READY requires approval")
    history = data.get("history")
    if history is not None:
        if not isinstance(history, list):
            problems.append("history must be an array")
        else:
            for i, entry in enumerate(history):
                if not isinstance(entry, dict):
                    problems.append(f"history[{i}] is not an object")
                    continue
                if entry.get("stage") not in STAGES:
                    problems.append(f"history[{i}].stage is not a stage")
                if not isinstance(entry.get("revision"), str) or not _SHA_RE.match(
                    entry.get("revision") or ""
                ):
                    problems.append(f"history[{i}].revision must be a commit SHA")
                if not isinstance(entry.get("content_digest"), str) or not _DIGEST_RE.match(
                    entry.get("content_digest") or ""
                ):
                    problems.append(f"history[{i}].content_digest must be a sha256 digest")
    return problems


def transition(data, to_stage, revision, content_digest, evidence_bundle=None, note=""):
    """Move a state dict to `to_stage`, returning a new dict (the
    input is not mutated). Raises ValueError on an invalid current
    state, a transition the table does not allow, a content-digest
    change to any stage but BUILDING, VERIFIED without an evidence
    bundle, or RELEASE_READY without an approval bound to the same
    digest. The history is append-only: the old entries are kept
    verbatim and one entry is added."""
    problems = validate_state(data)
    if problems:
        raise ValueError(f"invalid state: {'; '.join(problems)}")
    if to_stage not in STAGES:
        raise ValueError(f"unknown stage: {to_stage!r}")
    current = data["stage"]
    digest_changed = content_digest != data["content_digest"]
    if digest_changed and to_stage != "BUILDING":
        raise ValueError(
            "content digest changed: the stage must go back to BUILDING first "
            "(a content change resets the stage)"
        )
    if to_stage not in ALLOWED_TRANSITIONS[current] and not (
        digest_changed and to_stage == "BUILDING"
    ):
        raise ValueError(
            f"not an allowed transition: {current} -> {to_stage} "
            f"(allowed: {', '.join(sorted(ALLOWED_TRANSITIONS[current])) or 'none'})"
        )
    if to_stage == "VERIFIED" and not (evidence_bundle or data.get("evidence_bundle")):
        raise ValueError("VERIFIED requires evidence_bundle")
    if to_stage == "RELEASE_READY":
        approval = data.get("approval")
        if not approval or approval.get("content_digest") != content_digest:
            raise ValueError("RELEASE_READY requires approval bound to this content_digest")
    new = dict(data)
    new["stage"] = to_stage
    new["revision"] = revision
    new["content_digest"] = content_digest
    if evidence_bundle is not None:
        new["evidence_bundle"] = evidence_bundle
    entry = {
        "stage": to_stage,
        "revision": revision,
        "content_digest": content_digest,
        "at": datetime.now(timezone.utc).isoformat(),
        "note": note,
    }
    new["history"] = [*data["history"], entry]
    return new


def main(argv):
    parser = argparse.ArgumentParser(description="Validate and transition .orcinus/state.json.")
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate", help="check a state file against the schema")
    validate.add_argument("path")
    move = sub.add_parser("transition", help="move a state file to a new stage")
    move.add_argument("path")
    move.add_argument("--to", required=True, choices=list(STAGES))
    move.add_argument("--revision", required=True)
    move.add_argument("--digest", required=True)
    move.add_argument("--evidence")
    move.add_argument("--note", default="")
    args = parser.parse_args(argv)
    try:
        data = load_state(args.path)
    except ValueError as e:
        print(f"invalid: {e}")
        return 1
    if args.command == "validate":
        problems = validate_state(data)
        if problems:
            for problem in problems:
                print(f"invalid: {problem}")
            return 1
        print("OK: state is valid")
        return 0
    try:
        new = transition(data, args.to, args.revision, args.digest, args.evidence, args.note)
    except ValueError as e:
        print(f"refused: {e}")
        return 1
    Path(args.path).write_text(json.dumps(new, indent=2) + "\n", encoding="utf-8")
    print(f"OK: stage is now {args.to}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
