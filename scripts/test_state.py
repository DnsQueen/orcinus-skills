"""Tests for scripts/state.py + scripts/state_schema.json — the
.orcinus/state.json schema and transition tool (round 6, 2-R2;
round 7, F-07: the digest is recomputed, never caller-supplied).

The state file was spec-only (docs/project-state.md + a digest
helper); nothing validated it or enforced a transition. The schema
is the declarative contract, this module enforces it plus the
transition rules. This is a local check, not the v1.1 tamper-proof
enforcement layer — anyone with write access can still edit the
file (project-state.md Rule 4) — but the next `validate` now
DETECTS a hand-edited digest, because the digest is recomputed
from the revision's tree and compared with the stored value.

Run: python3 -m pytest scripts/test_state.py -q
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import state as st  # noqa: E402
import content_digest as cd  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
DIGEST = "sha256:" + "a" * 64
DIGEST2 = "sha256:" + "b" * 64
REV = "b2809bd64f5679ce56eb79a239109978f0c9f06a"


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def _repo(tmp_path):
    """A real git repo with one committed file: transitions compute
    their digest from this, never from a caller-supplied string."""
    repo = tmp_path / "proj"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@orcinus.local")
    _git(repo, "config", "user.name", "ORCINUS Test")
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("x = 1\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "code")
    return repo


def _head(repo):
    proc = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip()


def _commit_change(repo, filename="src/app.py", content="x = 2\n", message="change code"):
    (repo / filename).write_text(content, encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", message)
    return _head(repo)


def _pass_bundle_dict():
    """A minimal valid PASS bundle (docs-only, every gate waived,
    no checks): the same shape the evidence validator accepts
    (verified against validate_evidence.py before these tests were
    written). A docs-only PASS needs no recorded checks, so the
    fixture needs no record_check.py machinery."""
    return {
        "schema_version": 6,
        "revision": "abc1234",
        "working_tree_state": "clean",
        "requirement": "Fix a typo in the README.",
        "acceptance_criteria": ["The typo is fixed."],
        "files_changed": ["README.md"],
        "checks": [],
        "findings": [],
        "unresolved_risks": [],
        "unverified_items": [],
        "verdict": "PASS",
        "reviewer_identity": "reviewer",
        "implementer_identity": "implementer",
        "verification_plan": {
            "change_type": "docs-only",
            "required_gates": [],
            "not_applicable_gates": [
                {"gate": "build", "reason": "Docs have no build step."},
                {"gate": "lint", "reason": "Docs have no lint step."},
                {"gate": "typecheck", "reason": "Docs have no typechecker."},
                {"gate": "test", "reason": "Docs change needs no tests."},
            ],
        },
    }


def _write_bundle(repo, name="x.json", bundle=None):
    """Write a bundle under docs/verification/ (excluded from the
    digest, so it never resets the stage) and return its path
    relative to the repo root, as state.json records it."""
    bundle = _pass_bundle_dict() if bundle is None else bundle
    directory = repo / "docs" / "verification"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(json.dumps(bundle), encoding="utf-8")
    return f"docs/verification/{name}"


def _building(digest=DIGEST, revision=REV):
    return {
        "format_version": 2,
        "project": "weekly-budget",
        "stage": "BUILDING",
        "revision": revision,
        "content_digest": digest,
        "evidence_bundle": None,
        "approval": None,
        "history": [],
    }


def test_schema_file_matches_module():
    """The schema file is the contract: six stages, format_version 2,
    digest pattern, required fields — and the module enforces the
    same stages."""
    schema = json.loads((REPO / "scripts" / "state_schema.json").read_text(encoding="utf-8"))
    assert schema["properties"]["stage"]["enum"] == list(st.STAGES)
    assert schema["properties"]["format_version"]["const"] == 2
    assert set(schema["required"]) == {
        "format_version",
        "project",
        "stage",
        "revision",
        "content_digest",
        "evidence_bundle",
        "approval",
        "history",
    }
    assert st.validate_state(_building()) == []


def test_validate_rejects_bad_states():
    bad = _building()
    bad["stage"] = "DONE"
    assert any("stage" in p for p in st.validate_state(bad))
    bad = _building()
    bad["content_digest"] = "not-a-digest"
    assert any("content_digest" in p for p in st.validate_state(bad))
    bad = _building()
    del bad["project"]
    assert any("project" in p for p in st.validate_state(bad))
    bad = _building()
    bad["stage"] = "VERIFIED"  # VERIFIED with no evidence bundle is corrupt.
    assert any("evidence_bundle" in p for p in st.validate_state(bad))
    bad = _building()
    bad["stage"] = "RELEASE_READY"
    bad["approval"] = {
        "approved_by": "x",
        "revision": REV,
        "content_digest": DIGEST2,
        "artifact": "a.tgz",
        "at": "2026-11-07T00:00:00+00:00",
    }
    assert any("approval" in p for p in st.validate_state(bad))


def _at_stage(repo, stage, revision, digest):
    """A valid state in `stage` for a real repo (VERIFIED needs a
    real evidence bundle file, RELEASE_READY needs an approval
    bound to the computed digest)."""
    data = _building(digest=digest, revision=revision)
    data["stage"] = stage
    if stage in ("VERIFIED", "AWAITING_APPROVAL", "RELEASE_READY"):
        data["evidence_bundle"] = _write_bundle(repo)
    if stage == "RELEASE_READY":
        data["approval"] = {
            "approved_by": "x",
            "revision": revision,
            "content_digest": digest,
            "artifact": "a.tgz",
            "at": "2026-11-07T00:00:00+00:00",
        }
    return data


def test_validate_recomputes_digest(tmp_path):
    """F-07: validate with a repo recomputes the stored digest
    from the state's revision — a hand-edited digest is a problem,
    not a value to trust. Without a repo only the structural
    checks run."""
    repo = _repo(tmp_path)
    revision = _head(repo)
    digest = cd.content_digest(repo, revision)
    assert st.validate_state(_building(digest=digest, revision=revision), repo=repo) == []
    tampered = _building(digest=digest, revision=revision)
    tampered["content_digest"] = "sha256:" + "f" * 64
    assert any("content_digest" in p for p in st.validate_state(tampered, repo=repo))
    missing = _building(digest=digest, revision=revision)
    missing["revision"] = "a" * 40  # well-formed, not in this repo
    assert any("content_digest" in p for p in st.validate_state(missing, repo=repo))
    assert st.validate_state(tampered) == []  # no repo: structural only


def test_allowed_transitions(tmp_path):
    """The allowed-transition table: forward along the lifecycle,
    back to BUILDING on rework — never sideways or backwards."""
    for frm, to in (
        ("BUILDING", "VERIFYING"),
        ("VERIFYING", "BLOCKED"),
        ("VERIFYING", "VERIFIED"),
        ("BLOCKED", "BUILDING"),
        ("VERIFIED", "AWAITING_APPROVAL"),
        ("AWAITING_APPROVAL", "RELEASE_READY"),
    ):
        repo = _repo(tmp_path / f"repo-{frm}-{to}")
        revision = _head(repo)
        digest = cd.content_digest(repo, revision)
        data = _at_stage(repo, frm, revision, digest)
        kwargs = {"repo": repo}
        if to == "VERIFIED":
            kwargs["evidence_bundle"] = _write_bundle(repo)
        elif to == "RELEASE_READY":
            data["approval"] = {
                "approved_by": "x",
                "revision": revision,
                "content_digest": digest,
                "artifact": "a.tgz",
                "at": "2026-11-07T00:00:00+00:00",
            }
        data = st.transition(data, to, revision, **kwargs)
        assert data["stage"] == to
    for frm, to in (
        ("BUILDING", "VERIFIED"),
        ("VERIFYING", "AWAITING_APPROVAL"),
        ("VERIFIED", "VERIFYING"),
        ("RELEASE_READY", "VERIFYING"),
        ("RELEASE_READY", "BUILDING"),
    ):
        repo = _repo(tmp_path / f"repo-bad-{frm}-{to}")
        revision = _head(repo)
        digest = cd.content_digest(repo, revision)
        data = _at_stage(repo, frm, revision, digest)
        with pytest.raises(ValueError, match="not an allowed transition"):
            st.transition(data, to, revision, repo=repo)


def test_digest_change_forces_building(tmp_path):
    """Rule 2: a content change resets the stage. A transition to
    any other stage with a new digest is refused."""
    repo = _repo(tmp_path)
    revision = _head(repo)
    digest = cd.content_digest(repo, revision)
    data = _building(digest=digest, revision=revision)
    data["stage"] = "VERIFYING"
    new_revision = _commit_change(repo)
    new_digest = cd.content_digest(repo, new_revision)
    assert new_digest != digest
    with pytest.raises(ValueError, match="BUILDING"):
        st.transition(
            data,
            "VERIFIED",
            new_revision,
            repo=repo,
            evidence_bundle=_write_bundle(repo),
        )
    data = st.transition(data, "BUILDING", new_revision, repo=repo, note="content changed")
    assert data["stage"] == "BUILDING" and data["content_digest"] == new_digest


def test_digest_change_from_verified_forces_building(tmp_path):
    """Golden-digest test (F-07): a VERIFIED state is bound to its
    digest — after a content change the only move is BUILDING, and
    the stored digest becomes the new recomputed one."""
    repo = _repo(tmp_path)
    revision = _head(repo)
    digest = cd.content_digest(repo, revision)
    data = _at_stage(repo, "VERIFIED", revision, digest)
    new_revision = _commit_change(repo)
    new_digest = cd.content_digest(repo, new_revision)
    assert new_digest != digest
    with pytest.raises(ValueError, match="BUILDING"):
        st.transition(data, "AWAITING_APPROVAL", new_revision, repo=repo)
    data = st.transition(data, "BUILDING", new_revision, repo=repo)
    assert data["stage"] == "BUILDING"
    assert data["content_digest"] == new_digest
    assert data["revision"] == new_revision


def test_transition_stores_recomputed_digest(tmp_path):
    """F-07: the digest comes from the repo, never from the caller.
    The stored digest after a transition is the recomputed digest
    for the new revision, whatever the state held before."""
    repo = _repo(tmp_path)
    revision = _head(repo)
    digest = cd.content_digest(repo, revision)
    data = _building(digest=digest, revision=revision)
    data = st.transition(data, "VERIFYING", revision, repo=repo)
    assert data["content_digest"] == digest
    assert data["revision"] == revision
    new_revision = _commit_change(repo)
    new_digest = cd.content_digest(repo, new_revision)
    data = st.transition(data, "BUILDING", new_revision, repo=repo)
    assert data["content_digest"] == new_digest
    assert data["content_digest"] != digest


def test_tampered_digest_refuses_transition(tmp_path):
    """F-07: a hand-edited digest is detected, not stored. The old
    repro (sha256: + "f" x 64 accepted verbatim) is now refused:
    the stored digest does not match the recomputed digest for the
    state's revision, so the state is invalid before any
    transition is considered."""
    repo = _repo(tmp_path)
    revision = _head(repo)
    digest = cd.content_digest(repo, revision)
    data = _building(digest=digest, revision=revision)
    data["content_digest"] = "sha256:" + "f" * 64  # well-formed, wrong
    with pytest.raises(ValueError, match="invalid state"):
        st.transition(data, "VERIFYING", revision, repo=repo)


def test_cli_digest_flag_is_gone(tmp_path, capsys):
    """F-07: --digest no longer exists. A caller that passes it
    gets an argparse usage error (exit 2), not a stored digest."""
    repo = _repo(tmp_path)
    revision = _head(repo)
    digest = cd.content_digest(repo, revision)
    path = tmp_path / "state.json"
    path.write_text(json.dumps(_building(digest=digest, revision=revision)), encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        st.main(
            [
                "transition",
                str(path),
                "--to",
                "VERIFYING",
                "--revision",
                revision,
                "--digest",
                digest,
            ]
        )
    assert exc.value.code == 2
    assert "unrecognized arguments: --digest" in capsys.readouterr().err


def test_expect_digest(tmp_path):
    """--expect-digest asserts against the recomputed digest: it
    is never the stored value, only a check on it."""
    repo = _repo(tmp_path)
    revision = _head(repo)
    digest = cd.content_digest(repo, revision)
    data = _building(digest=digest, revision=revision)
    data = st.transition(data, "VERIFYING", revision, repo=repo, expect_digest=digest)
    assert data["stage"] == "VERIFYING"
    with pytest.raises(ValueError, match="expect-digest"):
        st.transition(data, "BLOCKED", revision, repo=repo, expect_digest="sha256:" + "f" * 64)


def test_verified_needs_evidence_and_release_needs_approval(tmp_path):
    repo = _repo(tmp_path)
    revision = _head(repo)
    digest = cd.content_digest(repo, revision)
    data = _building(digest=digest, revision=revision)
    data["stage"] = "VERIFYING"
    with pytest.raises(ValueError, match="evidence_bundle"):
        st.transition(data, "VERIFIED", revision, repo=repo)
    data = _building(digest=digest, revision=revision)
    data["stage"] = "AWAITING_APPROVAL"
    data["evidence_bundle"] = _write_bundle(repo)
    with pytest.raises(ValueError, match="approval"):
        st.transition(data, "RELEASE_READY", revision, repo=repo)


def test_transition_appends_history_without_rewriting_it(tmp_path):
    repo = _repo(tmp_path)
    revision = _head(repo)
    digest = cd.content_digest(repo, revision)
    data = _building(digest=digest, revision=revision)
    data = st.transition(data, "VERIFYING", revision, repo=repo, note="verifier running")
    assert len(data["history"]) == 1
    assert data["history"][0]["stage"] == "VERIFYING"
    assert data["history"][0]["note"] == "verifier running"
    first = dict(data["history"][0])
    data = st.transition(data, "BLOCKED", revision, repo=repo)
    assert data["history"][0] == first  # append-only: never rewritten
    assert data["history"][1]["stage"] == "BLOCKED"


def test_verified_refused_on_dirty_tree(tmp_path):
    """F-07: the digest covers committed content only — VERIFIED
    on a dirty tree would bind the stage to content that was
    never committed. Untracked files where recording verification
    writes (.orcinus/, docs/verification/) and ignored files are
    not dirt."""
    repo = _repo(tmp_path)
    (repo / ".gitignore").write_text("*.log\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "ignore logs")
    revision = _head(repo)
    digest = cd.content_digest(repo, revision)
    bundle = _write_bundle(repo)
    data = _building(digest=digest, revision=revision)
    data["stage"] = "VERIFYING"
    (repo / "src" / "app.py").write_text("x = 2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="dirty"):
        st.transition(data, "VERIFIED", revision, repo=repo, evidence_bundle=bundle)
    (repo / "src" / "app.py").write_text("x = 1\n", encoding="utf-8")
    (repo / "src" / "new.py").write_text("y = 1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="dirty"):
        st.transition(data, "VERIFIED", revision, repo=repo, evidence_bundle=bundle)
    (repo / "src" / "new.py").unlink()
    (repo / ".orcinus").mkdir(exist_ok=True)
    (repo / ".orcinus" / "state.json").write_text("{}\n", encoding="utf-8")
    (repo / "docs" / "verification" / "other.json").write_text("{}\n", encoding="utf-8")
    (repo / "x.log").write_text("log\n", encoding="utf-8")
    data = st.transition(data, "VERIFIED", revision, repo=repo, evidence_bundle=bundle)
    assert data["stage"] == "VERIFIED"


def test_release_ready_refused_on_dirty_tree(tmp_path):
    repo = _repo(tmp_path)
    revision = _head(repo)
    digest = cd.content_digest(repo, revision)
    data = _at_stage(repo, "AWAITING_APPROVAL", revision, digest)
    data["approval"] = {
        "approved_by": "x",
        "revision": revision,
        "content_digest": digest,
        "artifact": "a.tgz",
        "at": "2026-11-07T00:00:00+00:00",
    }
    (repo / "src" / "app.py").write_text("x = 2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="dirty"):
        st.transition(data, "RELEASE_READY", revision, repo=repo)
    (repo / "src" / "app.py").write_text("x = 1\n", encoding="utf-8")
    data = st.transition(data, "RELEASE_READY", revision, repo=repo)
    assert data["stage"] == "RELEASE_READY"


def test_dirty_check_skipped_for_older_revision(tmp_path):
    """The dirty-tree check applies only when the revision IS
    HEAD: for an older revision the working tree is irrelevant —
    the digest describes that revision's tree, not the work in
    progress."""
    repo = _repo(tmp_path)
    old_revision = _head(repo)
    old_digest = cd.content_digest(repo, old_revision)
    _commit_change(repo)  # HEAD moves on
    (repo / "src" / "app.py").write_text("x = 3\n", encoding="utf-8")  # dirty, uncommitted
    data = _building(digest=old_digest, revision=old_revision)
    data["stage"] = "VERIFYING"
    data = st.transition(
        data, "VERIFIED", old_revision, repo=repo, evidence_bundle=_write_bundle(repo)
    )
    assert data["stage"] == "VERIFIED"


def _incomplete_bundle_dict():
    """A valid INCOMPLETE bundle (no plan, with a stop_reason):
    the validator accepts it, but it is not evidence for VERIFIED
    — only a PASS bundle is."""
    bundle = _pass_bundle_dict()
    bundle["verdict"] = "INCOMPLETE"
    bundle.pop("verification_plan")
    bundle["stop_reason"] = "Verification stopped: the test runner was unavailable."
    return bundle


def test_verified_refuses_missing_bundle_file(tmp_path):
    """F-07: the old repro (VERIFIED with ./bundle.json
    nonexistent, exit 0) is now refused — the bundle path must
    name an existing file."""
    repo = _repo(tmp_path)
    revision = _head(repo)
    digest = cd.content_digest(repo, revision)
    data = _building(digest=digest, revision=revision)
    data["stage"] = "VERIFYING"
    with pytest.raises(ValueError, match="does not exist"):
        st.transition(
            data, "VERIFIED", revision, repo=repo, evidence_bundle="docs/verification/nope.json"
        )


def test_verified_refuses_incomplete_bundle(tmp_path):
    """A bundle whose verdict is INCOMPLETE is a valid bundle —
    and not evidence for VERIFIED. Only a PASS bundle satisfies
    the gate."""
    repo = _repo(tmp_path)
    revision = _head(repo)
    digest = cd.content_digest(repo, revision)
    bundle = _write_bundle(repo, "incomplete.json", _incomplete_bundle_dict())
    data = _building(digest=digest, revision=revision)
    data["stage"] = "VERIFYING"
    with pytest.raises(ValueError, match="not PASS"):
        st.transition(data, "VERIFIED", revision, repo=repo, evidence_bundle=bundle)


def test_whitespace_only_evidence_rejected(tmp_path):
    """N2: a whitespace-only evidence value passes a truthiness
    test and names no file — it is rejected, whether passed with
    the flag or stored in the state."""
    repo = _repo(tmp_path)
    revision = _head(repo)
    digest = cd.content_digest(repo, revision)
    data = _building(digest=digest, revision=revision)
    data["stage"] = "VERIFYING"
    with pytest.raises(ValueError, match="evidence_bundle"):
        st.transition(data, "VERIFIED", revision, repo=repo, evidence_bundle=" ")
    data = _building(digest=digest, revision=revision)
    data["stage"] = "VERIFYING"
    data["evidence_bundle"] = "   "
    with pytest.raises(ValueError, match="evidence_bundle"):
        st.transition(data, "VERIFIED", revision, repo=repo)


def test_stored_evidence_bundle_rule(tmp_path):
    """N2, the stored-bundle rule: a stored evidence_bundle may
    satisfy the VERIFIED gate with no --evidence flag — but only
    if it names an existing file that validates with verdict PASS.
    A stale stored path (missing file, non-PASS bundle) refuses
    the transition; it never silently satisfies the gate. The flag
    is required only when the stored value is absent or blank."""
    repo = _repo(tmp_path)
    revision = _head(repo)
    digest = cd.content_digest(repo, revision)
    # (a) Stored valid PASS bundle, no flag: accepted.
    data = _building(digest=digest, revision=revision)
    data["stage"] = "VERIFYING"
    data["evidence_bundle"] = _write_bundle(repo)
    data = st.transition(data, "VERIFIED", revision, repo=repo)
    assert data["stage"] == "VERIFIED"
    # (b) Stored path names no file: refused.
    data = _building(digest=digest, revision=revision)
    data["stage"] = "VERIFYING"
    data["evidence_bundle"] = "docs/verification/nope.json"
    with pytest.raises(ValueError, match="does not exist"):
        st.transition(data, "VERIFIED", revision, repo=repo)
    # (c) Stored bundle is INCOMPLETE, not PASS: refused.
    data = _building(digest=digest, revision=revision)
    data["stage"] = "VERIFYING"
    data["evidence_bundle"] = _write_bundle(repo, "incomplete.json", _incomplete_bundle_dict())
    with pytest.raises(ValueError, match="not PASS"):
        st.transition(data, "VERIFIED", revision, repo=repo)
    # The flag still wins when given: a valid flag bundle accepts
    # even when the stored value is stale.
    data = _building(digest=digest, revision=revision)
    data["stage"] = "VERIFYING"
    data["evidence_bundle"] = "docs/verification/nope.json"
    data = st.transition(data, "VERIFIED", revision, repo=repo, evidence_bundle=_write_bundle(repo))
    assert data["stage"] == "VERIFIED"
    assert data["evidence_bundle"] == "docs/verification/x.json"


def test_validate_flags_evidence_problems(tmp_path):
    """N2: `validate` shares the fix — evidence referenced by the
    state must exist, and a VERIFIED state must point at a bundle
    that validates with verdict PASS."""
    repo = _repo(tmp_path)
    revision = _head(repo)
    digest = cd.content_digest(repo, revision)
    data = _at_stage(repo, "VERIFIED", revision, digest)
    assert st.validate_state(data, repo=repo) == []
    data = _at_stage(repo, "VERIFIED", revision, digest)
    data["evidence_bundle"] = "docs/verification/nope.json"
    assert any("does not exist" in p for p in st.validate_state(data, repo=repo))
    data = _at_stage(repo, "VERIFIED", revision, digest)
    data["evidence_bundle"] = _write_bundle(repo, "incomplete.json", _incomplete_bundle_dict())
    assert any("not PASS" in p for p in st.validate_state(data, repo=repo))
    data = _building(digest=digest, revision=revision)
    data["stage"] = "VERIFYING"
    data["evidence_bundle"] = "docs/verification/nope.json"
    assert any("does not exist" in p for p in st.validate_state(data, repo=repo))
    data = _building(digest=digest, revision=revision)
    data["evidence_bundle"] = "   "
    assert any("blank" in p for p in st.validate_state(data, repo=repo))


def test_release_ready_uses_computed_digest(tmp_path):
    """F-07: RELEASE_READY keeps the approval check, now against
    the COMPUTED digest — an approval bound to any other digest
    does not release, and an approval does not survive a content
    change."""
    repo = _repo(tmp_path)
    revision = _head(repo)
    digest = cd.content_digest(repo, revision)
    data = _at_stage(repo, "AWAITING_APPROVAL", revision, digest)
    data["approval"] = {
        "approved_by": "x",
        "revision": revision,
        "content_digest": "sha256:" + "c" * 64,  # well-formed, not this tree
        "artifact": "a.tgz",
        "at": "2026-11-07T00:00:00+00:00",
    }
    with pytest.raises(ValueError, match="approval"):
        st.transition(data, "RELEASE_READY", revision, repo=repo)
    data["approval"]["content_digest"] = digest
    new_revision = _commit_change(repo)
    with pytest.raises(ValueError, match="BUILDING"):
        st.transition(data, "RELEASE_READY", new_revision, repo=repo)
    data = st.transition(data, "RELEASE_READY", revision, repo=repo)
    assert data["stage"] == "RELEASE_READY"


def test_cli_validate_and_transition(tmp_path, capsys):
    repo = _repo(tmp_path)
    revision = _head(repo)
    digest = cd.content_digest(repo, revision)
    path = tmp_path / "state.json"
    path.write_text(json.dumps(_building(digest=digest, revision=revision)), encoding="utf-8")
    assert st.main(["validate", "--repo", str(repo), str(path)]) == 0
    assert (
        st.main(
            [
                "transition",
                str(path),
                "--to",
                "VERIFYING",
                "--revision",
                revision,
                "--repo",
                str(repo),
                "--note",
                "verifier running",
            ]
        )
        == 0
    )
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["stage"] == "VERIFYING" and len(data["history"]) == 1
    assert data["content_digest"] == digest
    path.write_text(json.dumps({**_building(), "stage": "DONE"}), encoding="utf-8")
    assert st.main(["validate", "--repo", str(repo), str(path)]) == 1
    assert "stage" in capsys.readouterr().out
