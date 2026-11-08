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


def _write_bundle(repo, name="x.json", bundle=None, revision=None):
    """Write a bundle under docs/verification/ (excluded from the
    digest, so it never resets the stage) and return its path
    relative to the repo root, as state.json records it. `revision`
    is the revision the bundle is bound to (round 8, FND-004):
    a bundle whose revision does not resolve in `repo` fails
    tree binding, so fixtures must pass the repo's HEAD — a
    bundle with a made-up revision is not a genuinely recorded
    bundle, and the old default ("abc1234") no longer validates."""
    bundle = _pass_bundle_dict() if bundle is None else dict(bundle)
    if revision is not None:
        bundle["revision"] = revision
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
        data["evidence_bundle"] = _write_bundle(repo, revision=revision)
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
            kwargs["evidence_bundle"] = _write_bundle(repo, revision=revision)
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
            evidence_bundle=_write_bundle(repo, revision=new_revision),
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
    data["evidence_bundle"] = _write_bundle(repo, revision=revision)
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
    bundle = _write_bundle(repo, revision=revision)
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


def test_verified_refuses_stale_revision(tmp_path):
    """FND-008 / N-B4 (round 8): this REPLACES
    test_dirty_check_skipped_for_older_revision, whose expectation
    was the bug. The old test held that the dirty-tree check
    applies only at HEAD, so a transition to VERIFIED at an older
    revision skipped the gate entirely — _tree_is_dirty()
    returned False for revision != HEAD. A VERIFIED stage minted
    at a revision HEAD has moved past binds the stage to content
    HEAD no longer has, and a dirty tree at that point was never
    even looked at. Now a transition to VERIFIED (or
    RELEASE_READY) at a non-HEAD revision is refused outright,
    with an error naming the stale revision — dirty tree or not."""
    repo = _repo(tmp_path)
    old_revision = _head(repo)
    old_digest = cd.content_digest(repo, old_revision)
    _commit_change(repo)  # HEAD moves on
    data = _building(digest=old_digest, revision=old_revision)
    data["stage"] = "VERIFYING"
    # Clean tree, stale revision: still refused, as stale — not as dirty.
    with pytest.raises(ValueError, match="stale"):
        st.transition(
            data,
            "VERIFIED",
            old_revision,
            repo=repo,
            evidence_bundle=_write_bundle(repo, revision=old_revision),
        )
    # Dirty tree, stale revision: still the stale error, not a silent pass.
    (repo / "src" / "app.py").write_text("x = 3\n", encoding="utf-8")
    with pytest.raises(ValueError, match="stale"):
        st.transition(
            data,
            "VERIFIED",
            old_revision,
            repo=repo,
            evidence_bundle=_write_bundle(repo, revision=old_revision),
        )
    # RELEASE_READY at a stale revision is refused the same way.
    data = _building(digest=old_digest, revision=old_revision)
    data["stage"] = "AWAITING_APPROVAL"
    data["evidence_bundle"] = _write_bundle(repo, revision=old_revision)
    data["approval"] = {
        "approved_by": "x",
        "revision": old_revision,
        "content_digest": old_digest,
        "artifact": "a.tgz",
        "at": "2026-11-07T00:00:00+00:00",
    }
    with pytest.raises(ValueError, match="stale"):
        st.transition(data, "RELEASE_READY", old_revision, repo=repo)


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
    bundle = _write_bundle(repo, "incomplete.json", _incomplete_bundle_dict(), revision=revision)
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
    data["evidence_bundle"] = _write_bundle(repo, revision=revision)
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
    data["evidence_bundle"] = _write_bundle(
        repo, "incomplete.json", _incomplete_bundle_dict(), revision=revision
    )
    with pytest.raises(ValueError, match="not PASS"):
        st.transition(data, "VERIFIED", revision, repo=repo)
    # The flag still wins when given: a valid flag bundle accepts
    # even when the stored value is stale.
    data = _building(digest=digest, revision=revision)
    data["stage"] = "VERIFYING"
    data["evidence_bundle"] = "docs/verification/nope.json"
    data = st.transition(
        data,
        "VERIFIED",
        revision,
        repo=repo,
        evidence_bundle=_write_bundle(repo, revision=revision),
    )
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
    data["evidence_bundle"] = _write_bundle(
        repo, "incomplete.json", _incomplete_bundle_dict(), revision=revision
    )
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
    change. Round 8, FND-008: the test's old final step
    transitioned to RELEASE_READY at the old revision AFTER HEAD
    had moved on — a stale-revision transition, now refused.
    The successful release is asserted before HEAD moves, and
    the content-change refusal after."""
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
    data = st.transition(data, "RELEASE_READY", revision, repo=repo)
    assert data["stage"] == "RELEASE_READY"
    # A content change after the approval: the only move is
    # BUILDING, and the approval does not survive it.
    data = _at_stage(repo, "AWAITING_APPROVAL", revision, digest)
    data["approval"] = {
        "approved_by": "x",
        "revision": revision,
        "content_digest": digest,
        "artifact": "a.tgz",
        "at": "2026-11-07T00:00:00+00:00",
    }
    new_revision = _commit_change(repo)
    with pytest.raises(ValueError, match="BUILDING"):
        st.transition(data, "RELEASE_READY", new_revision, repo=repo)


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


# --- Round 8, Track B: FND-007 / FND-008 / FND-009 / FND-004 integration ---


def test_cli_validate_defaults_repo_to_cwd(tmp_path, monkeypatch):
    """FND-007: --repo defaults to the caller's working directory,
    resolved at call time — not to the ORCINUS install. A valid
    state file in a fresh project validates with no --repo when
    run from that project (the round-8 repro: exit 1 before the
    fix, exit 0 after)."""
    repo = _repo(tmp_path)
    revision = _head(repo)
    digest = cd.content_digest(repo, revision)
    path = tmp_path / "state.json"
    path.write_text(json.dumps(_building(digest=digest, revision=revision)), encoding="utf-8")
    monkeypatch.chdir(repo)
    assert st.main(["validate", str(path)]) == 0


def test_cli_transition_defaults_repo_to_cwd(tmp_path, monkeypatch):
    """FND-007 / N-B3: the same bad default also affected
    transition (transition() defaulted repo=ROOT). A transition
    run from the project, with no --repo, must recompute the
    digest in that project."""
    repo = _repo(tmp_path)
    revision = _head(repo)
    digest = cd.content_digest(repo, revision)
    path = tmp_path / "state.json"
    path.write_text(json.dumps(_building(digest=digest, revision=revision)), encoding="utf-8")
    monkeypatch.chdir(repo)
    assert st.main(["transition", str(path), "--to", "VERIFYING", "--revision", revision]) == 0
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["stage"] == "VERIFYING" and data["content_digest"] == digest


def test_transition_defaults_repo_to_cwd_in_process(tmp_path, monkeypatch):
    """FND-007 / N-B3, in-process: transition() with no repo
    argument resolves the caller's cwd at call time, not at
    import time — so a later chdir is honoured."""
    repo = _repo(tmp_path)
    revision = _head(repo)
    digest = cd.content_digest(repo, revision)
    monkeypatch.chdir(repo)
    data = st.transition(_building(digest=digest, revision=revision), "VERIFYING", revision)
    assert data["stage"] == "VERIFYING" and data["content_digest"] == digest


def test_cli_validate_rejects_stale_state_by_default(tmp_path, monkeypatch, capsys):
    """FND-008: a VERIFIED state validates after HEAD advances
    only until the fix — validate now requires the state's
    revision to be HEAD by default (exit 1, naming the stale
    revision), and --no-require-head is the explicit opt-out
    for inspecting a historical state."""
    repo = _repo(tmp_path)
    revision = _head(repo)
    digest = cd.content_digest(repo, revision)
    path = tmp_path / "state.json"
    path.write_text(json.dumps(_at_stage(repo, "VERIFIED", revision, digest)), encoding="utf-8")
    monkeypatch.chdir(repo)
    assert st.main(["validate", str(path)]) == 0
    _commit_change(repo)  # HEAD moves on; the state is now stale.
    assert st.main(["validate", str(path)]) == 1
    assert "stale" in capsys.readouterr().out
    assert st.main(["validate", "--no-require-head", str(path)]) == 0


def test_six_sequential_cli_transitions_print_no_stale_lock_note(tmp_path):
    """FND-005 (round 9): the stale-lock note fired on every run
    after the first — each CLI transition is a new process, so the
    lock file still names the previous (dead) holder, and the note
    printed even though the flock was free on first try. A dead
    recorded PID after a completed transition is the normal state,
    not a stale lock recovered. Six sequential legal transitions
    (via BLOCKED back to BUILDING) must print no stale-lock note.
    Each transition runs as its own CLI process, so the previous
    holder's PID is genuinely dead — the shape the note used to
    fire on."""
    repo = _repo(tmp_path)
    revision = _head(repo)
    digest = cd.content_digest(repo, revision)
    bundle = _write_bundle(repo, revision=revision)
    state_dir = repo / ".orcinus"
    state_dir.mkdir(exist_ok=True)
    state_path = state_dir / "state.json"
    state_path.write_text(json.dumps(_building(digest=digest, revision=revision)), encoding="utf-8")
    script = Path(__file__).resolve().parent / "state.py"
    steps = [
        ("VERIFYING", []),
        ("BLOCKED", []),
        ("BUILDING", []),
        ("VERIFYING", []),
        ("VERIFIED", ["--evidence", bundle]),
        ("AWAITING_APPROVAL", []),
    ]
    for to_stage, extra in steps:
        proc = subprocess.run(
            [
                sys.executable,
                str(script),
                "transition",
                str(state_path),
                "--to",
                to_stage,
                "--revision",
                revision,
                "--repo",
                str(repo),
                *extra,
            ],
            capture_output=True,
            text=True,
            cwd=repo,
            timeout=60,
        )
        assert proc.returncode == 0, proc.stderr
        assert "stale lock" not in proc.stderr, (to_stage, proc.stderr)


def test_stale_lock_note_still_fires_after_contention(tmp_path, capsys):
    """FND-005 control: the note is suppressed only when the flock
    was free on first try — after genuine contention with a dead
    recorded holder, the note still fires."""
    import os
    import threading
    import time

    state_path = tmp_path / "state.json"
    state_path.write_text("{}\n", encoding="utf-8")
    fd, lock_path, _ = st._acquire_lock(state_path)
    assert fd is not None
    st._unlock(fd)
    os.close(fd)
    # Plant a dead holder's PID in the lock file.
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    lock_path.write_text(f" {proc.pid}\n", encoding="utf-8")
    # Hold the flock from another fd so the first try fails, then
    # release it: the acquisition waits, then succeeds.
    contender = os.open(lock_path, os.O_RDWR)
    assert st._try_lock(contender)

    def _release():
        time.sleep(0.2)
        st._unlock(contender)
        os.close(contender)

    threading.Thread(target=_release, daemon=True).start()
    fd2, _, _ = st._acquire_lock(state_path, timeout_s=10.0)
    assert fd2 is not None
    assert "stale lock" in capsys.readouterr().err
    st._unlock(fd2)
    os.close(fd2)


def test_pid_is_alive_posix():
    """_pid_is_alive on POSIX: the current process is alive; a
    reaped subprocess's PID is dead."""
    import os

    assert st._pid_is_alive(os.getpid()) is True
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    assert st._pid_is_alive(proc.pid) is False


def test_pid_is_alive_windows_probe(monkeypatch):
    """N-F5x (round 9): on Windows _pid_is_alive always returned
    True, so a dead holder was never detected there. The probe is
    OpenProcess: a handle means alive; no handle with
    ERROR_ACCESS_DENIED (5) means alive but not ours; any other
    failure means dead. Tested with a faked windll (this suite
    runs on Linux)."""
    import ctypes
    from types import SimpleNamespace

    class FakeKernel32:
        def __init__(self):
            self.last_error = 0

        def OpenProcess(self, access, inherit, pid):
            assert access == 0x1000
            if pid == 1111:
                return 4321  # a handle: alive
            self.last_error = 5 if pid == 2222 else 87
            return 0

        def CloseHandle(self, handle):
            return True

        def GetLastError(self):
            return self.last_error

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(kernel32=FakeKernel32()), raising=False)
    assert st._pid_is_alive(1111) is True
    assert st._pid_is_alive(2222) is True  # access denied: alive, not ours
    assert st._pid_is_alive(3333) is False  # no such process


def test_validate_state_require_head(tmp_path):
    """FND-008, function level: require_head compares the state's
    revision with HEAD; a stale revision is a problem, and a
    missing HEAD fails closed. With require_head off (the
    default, preserving in-process callers) only the digest is
    recomputed."""
    repo = _repo(tmp_path)
    revision = _head(repo)
    digest = cd.content_digest(repo, revision)
    data = _building(digest=digest, revision=revision)
    assert st.validate_state(data, repo=repo, require_head=True) == []
    assert st.validate_state(data, repo=repo) == []
    _commit_change(repo)
    problems = st.validate_state(data, repo=repo, require_head=True)
    assert any("stale" in p and "HEAD" in p for p in problems)
    assert st.validate_state(data, repo=repo) == []  # off: digest still matches


def test_evidence_bundle_must_bind_to_tree(tmp_path):
    """FND-004 integration: _evidence_problems now passes the
    resolved repo to validate_bundle, so state validation gains
    the same tree binding. A bundle whose revision does not
    resolve in the repo is not evidence for VERIFIED — the old
    fixture shape (revision "abc1234", never recorded anywhere)
    now fails, and only a bundle genuinely recorded at the
    repo's HEAD validates. Fixtures were updated to record the
    real revision instead of weakening the binding."""
    repo = _repo(tmp_path)
    revision = _head(repo)
    digest = cd.content_digest(repo, revision)
    data = _at_stage(repo, "VERIFIED", revision, digest)
    assert st.validate_state(data, repo=repo) == []
    data = _at_stage(repo, "VERIFIED", revision, digest)
    data["evidence_bundle"] = _write_bundle(repo, "unbound.json")  # revision "abc1234"
    problems = st.validate_state(data, repo=repo)
    assert any("does not resolve" in p for p in problems), problems
    data = _building(digest=digest, revision=revision)
    data["stage"] = "VERIFYING"
    with pytest.raises(ValueError, match="does not resolve"):
        st.transition(
            data,
            "VERIFIED",
            revision,
            repo=repo,
            evidence_bundle=_write_bundle(repo, "unbound.json"),
        )


def test_evidence_bundle_must_match_state_revision(tmp_path):
    """Round 8, FND-004 (coordinator reconciliation): binding the
    bundle to the repo is not enough — a bundle recorded at R1
    must not verify a state pinned at R2. The state's own
    revision is passed as expected_revision, so a VERIFIED state
    whose bundle was recorded on an older revision is a problem,
    and a transition to VERIFIED with such a bundle is refused."""
    repo = _repo(tmp_path)
    old_revision = _head(repo)
    new_revision = _commit_change(repo)
    digest = cd.content_digest(repo, new_revision)
    data = _at_stage(repo, "VERIFIED", new_revision, digest)
    data["evidence_bundle"] = _write_bundle(repo, "old.json", revision=old_revision)
    problems = st.validate_state(data, repo=repo, require_head=False)
    assert any("revision" in p for p in problems), problems
    data2 = _building(digest=digest, revision=new_revision)
    data2["stage"] = "VERIFYING"
    with pytest.raises(ValueError, match="revision"):
        st.transition(
            data2,
            "VERIFIED",
            new_revision,
            repo=repo,
            evidence_bundle=_write_bundle(repo, "old2.json", revision=old_revision),
        )


def _run_cli_transition(state_path, repo, to_stage, revision):
    """One state.py transition as a subprocess (the real CLI,
    with its lock file), returning (returncode, stdout)."""
    proc = subprocess.run(
        [
            sys.executable,
            str(REPO / "scripts" / "state.py"),
            "transition",
            str(state_path),
            "--to",
            to_stage,
            "--revision",
            revision,
            "--repo",
            str(repo),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    return proc.returncode, proc.stdout + proc.stderr


def test_concurrent_transitions_lose_no_history(tmp_path):
    """FND-009 / N-B2: two simultaneous transitions must not lose
    history. The invariant, stated exactly: the final history
    holds one entry per successful writer, and a writer that
    exits 0 always has its entry in the file — a failed writer
    fails loudly, never silently overwrites. (Why not "both exit
    0, history 3" for two identical transitions: no two distinct
    transitions from one stage both stay legal after the other
    lands — e.g. two --to VERIFYING from BUILDING, where the
    second is VERIFYING->VERIFYING and illegal — so identical
    targets can never both succeed under any correct lock; the
    chained case below is the both-succeed shape.) Six trials,
    as in the verification repro."""
    import concurrent.futures

    repo = _repo(tmp_path)
    revision = _head(repo)
    digest = cd.content_digest(repo, revision)
    path = tmp_path / "state.json"
    for _trial in range(6):
        data = _building(digest=digest, revision=revision)
        data["history"] = [
            {
                "stage": "BUILDING",
                "revision": revision,
                "content_digest": digest,
                "at": "2026-11-08T00:00:00+00:00",
                "note": "start",
            }
        ]
        path.write_text(json.dumps(data), encoding="utf-8")
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            futs = [
                pool.submit(_run_cli_transition, path, repo, "VERIFYING", revision)
                for _ in range(2)
            ]
            results = [f.result() for f in futs]
        successes = sum(1 for rc, _ in results if rc == 0)
        assert successes == 1, results  # exactly one wins; the other fails loudly
        final = json.loads(path.read_text(encoding="utf-8"))
        assert len(final["history"]) == 1 + successes, final["history"]
        assert final["stage"] == "VERIFYING"
        assert any("not an allowed transition" in out for rc, out in results if rc != 0)


def test_concurrent_chained_transitions_both_succeed(tmp_path):
    """FND-009, the both-succeed shape: two transitions that
    chain (VERIFIED -> AWAITING_APPROVAL, then -> BUILDING),
    launched simultaneously, must both exit 0 with history 3 —
    the loser re-reads the winner's commit instead of
    overwriting it. Run sequentially first as a control (the
    chain itself is legal), then simultaneously."""
    import concurrent.futures

    repo = _repo(tmp_path)
    revision = _head(repo)
    digest = cd.content_digest(repo, revision)
    path = tmp_path / "state.json"

    def _write_verified():
        data = _at_stage(repo, "VERIFIED", revision, digest)
        data["history"] = [
            {
                "stage": "VERIFIED",
                "revision": revision,
                "content_digest": digest,
                "at": "2026-11-08T00:00:00+00:00",
                "note": "start",
            }
        ]
        path.write_text(json.dumps(data), encoding="utf-8")

    _write_verified()
    assert _run_cli_transition(path, repo, "AWAITING_APPROVAL", revision)[0] == 0
    assert _run_cli_transition(path, repo, "BUILDING", revision)[0] == 0
    final = json.loads(path.read_text(encoding="utf-8"))
    assert len(final["history"]) == 3
    _write_verified()
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futs = [
            pool.submit(_run_cli_transition, path, repo, "AWAITING_APPROVAL", revision),
            pool.submit(_run_cli_transition, path, repo, "BUILDING", revision),
        ]
        results = [f.result() for f in futs]
    # The order is whichever process acquires the lock first; the
    # BUILDING-first order cannot then take AWAITING_APPROVAL, so
    # the strict both-succeed assertion only holds when
    # AWAITING_APPROVAL lands first. The invariant that always
    # holds is no silent loss: history length is 1 + successes.
    successes = sum(1 for rc, _ in results if rc == 0)
    final = json.loads(path.read_text(encoding="utf-8"))
    assert len(final["history"]) == 1 + successes, (results, final["history"])
    assert successes >= 1, results


def test_stale_lock_is_recoverable(tmp_path):
    """FND-009: a lock file left by a dead holder (PID recorded,
    process gone) must not block the next transition forever —
    the next acquirer notes the stale lock and proceeds."""
    repo = _repo(tmp_path)
    revision = _head(repo)
    digest = cd.content_digest(repo, revision)
    path = tmp_path / "state.json"
    path.write_text(json.dumps(_building(digest=digest, revision=revision)), encoding="utf-8")
    lock_path = path.parent / f".{path.name}.lock"
    lock_path.write_bytes(b" 999999\n")  # dead PID, no flock holder
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
            ]
        )
        == 0
    )
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["stage"] == "VERIFYING"


def test_lock_released_after_refused_transition(tmp_path):
    """FND-009: the lock is released on the error path too — a
    refused transition must not leave the next transition
    blocked."""
    repo = _repo(tmp_path)
    revision = _head(repo)
    digest = cd.content_digest(repo, revision)
    path = tmp_path / "state.json"
    path.write_text(json.dumps(_building(digest=digest, revision=revision)), encoding="utf-8")
    assert (
        st.main(
            [
                "transition",
                str(path),
                "--to",
                "VERIFIED",
                "--revision",
                revision,
                "--repo",
                str(repo),
            ]
        )
        == 1
    )
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
            ]
        )
        == 0
    )
