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
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import state as st  # noqa: E402
import content_digest as cd  # noqa: E402
import verify_attestation as va  # noqa: E402

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


def _stub_verified_attestation(repo, revision):
    """The attestation stub for tests whose subject is not the
    gate itself: the live check is replaced by a verified result,
    explicitly — never by making the check optional. Tests that
    exercise the gate itself use their own stub (not-verified /
    unavailable) or a proof file instead."""
    return va.AttestationResult("verified", "stubbed attestation")


def _proof_dict(repo, revision, digest, **overrides):
    """A targeted-rerun proof dict as the gate's own rerun
    returns it (method, revision, content_digest, tests, junit
    totals, exit_code) — the shape _check_rerun_proof checks."""
    proof = {
        "method": "targeted-rerun",
        "revision": revision,
        "content_digest": digest,
        "tests": ["tests/test_x.py::test_y"],
        "junit": {"total": 2, "passed": 2},
        "exit_code": 0,
    }
    proof.update(overrides)
    return proof


def _stub_rerun_runner(proof):
    """A rerun runner stub for tests whose subject is not the
    runner itself: it returns `proof` without running anything,
    explicitly — the gate still re-checks the proof's fields."""

    def _run(repo, revision, bundle_path):
        return dict(proof)

    return _run


def _failing_rerun_runner(repo, revision, bundle_path):
    raise ValueError("targeted rerun refused: rerun_check.py exited 1: fail_first test failed")


def _rerun_record(revision, tests=("tests/test_x.py::test_y",)):
    """A valid rerun record as a RERUN_CONFIRMED state stores it:
    the proof the gate's rerun produced, plus when it ran."""
    return {
        "method": "targeted-rerun",
        "revision": revision,
        "at": "2026-11-10T00:00:00+00:00",
        "tests": list(tests),
        "junit": {"total": 2, "passed": 2},
        "exit_code": 0,
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


def _rerun_bundle(repo, revision, fail_first="tests/test_x.py::test_y"):
    """A PASS bundle the in-gate rerun can run: the docs-only
    fixture plus a fail-first entry naming the test to rerun.
    The change itself is docs-only (files_changed stays
    README.md — a docs-only bundle listing a code file is
    rejected); the fail-first method is "not-applicable" with a
    note saying exactly that, because there is no behaviour to
    prove fail-first for — the test is only the rerun target.
    The test file itself need not exist for the stub-runner
    tests, which never run it."""
    bundle = _pass_bundle_dict()
    if fail_first is not None:
        bundle["fail_first"] = {
            "test": fail_first,
            "failed_before": False,
            "passed_after": True,
            "method": "not-applicable",
            "note": "Docs-only change: no behaviour to prove fail-first for; "
            "the test named here is the target the gate's rerun re-runs.",
        }
    return _write_bundle(repo, "rerun.json", bundle, revision=revision)


def _building(digest=DIGEST, revision=REV):
    return {
        "format_version": 3,
        "project": "weekly-budget",
        "stage": "BUILDING",
        "revision": revision,
        "content_digest": digest,
        "evidence_bundle": None,
        "approval": None,
        "history": [],
        "verification_origin": None,
        "rerun": None,
    }


def test_schema_file_matches_module():
    """The schema file is the contract: seven stages, format_version 3,
    digest pattern, required fields — and the module enforces the
    same stages."""
    schema = json.loads((REPO / "scripts" / "state_schema.json").read_text(encoding="utf-8"))
    assert schema["properties"]["stage"]["enum"] == list(st.STAGES)
    assert schema["properties"]["format_version"]["const"] == 3
    assert set(schema["required"]) == {
        "format_version",
        "project",
        "stage",
        "revision",
        "content_digest",
        "evidence_bundle",
        "approval",
        "history",
        "verification_origin",
        "rerun",
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
    bound to the computed digest; VERIFIED records a CI
    attestation origin, RERUN_CONFIRMED a local-rerun origin
    with its rerun record)."""
    data = _building(digest=digest, revision=revision)
    data["stage"] = stage
    if stage in ("VERIFIED", "AWAITING_APPROVAL", "RELEASE_READY"):
        data["evidence_bundle"] = _write_bundle(repo, revision=revision)
        data["verification_origin"] = "CI_ATTESTED"
    if stage == "RERUN_CONFIRMED":
        data["evidence_bundle"] = _write_bundle(repo, revision=revision)
        data["verification_origin"] = "LOCAL_RERUN"
        data["rerun"] = _rerun_record(revision)
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
        ("VERIFYING", "RERUN_CONFIRMED"),
        ("BLOCKED", "BUILDING"),
        ("VERIFIED", "AWAITING_APPROVAL"),
        ("RERUN_CONFIRMED", "AWAITING_APPROVAL"),
        ("AWAITING_APPROVAL", "RELEASE_READY"),
    ):
        repo = _repo(tmp_path / f"repo-{frm}-{to}")
        revision = _head(repo)
        digest = cd.content_digest(repo, revision)
        data = _at_stage(repo, frm, revision, digest)
        kwargs = {"repo": repo, "attestation_checker": _stub_verified_attestation}
        if to == "VERIFIED":
            kwargs["evidence_bundle"] = _write_bundle(repo, revision=revision)
        elif to == "RERUN_CONFIRMED":
            kwargs["evidence_bundle"] = _write_bundle(repo, revision=revision)
            kwargs["rerun_runner"] = _stub_rerun_runner(_proof_dict(repo, revision, digest))
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
        ("BUILDING", "RERUN_CONFIRMED"),
        ("VERIFYING", "AWAITING_APPROVAL"),
        ("VERIFIED", "VERIFYING"),
        ("VERIFIED", "RERUN_CONFIRMED"),
        ("RERUN_CONFIRMED", "VERIFIED"),
        ("RERUN_CONFIRMED", "RELEASE_READY"),
        ("AWAITING_APPROVAL", "VERIFIED"),
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
    data = st.transition(
        data,
        "VERIFIED",
        revision,
        repo=repo,
        evidence_bundle=bundle,
        attestation_checker=_stub_verified_attestation,
    )
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
    # _at_stage (not a hand-built stage) so the origin rule is
    # satisfied and the stale check is what refuses it.
    data = _at_stage(repo, "AWAITING_APPROVAL", old_revision, old_digest)
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
    data = st.transition(
        data, "VERIFIED", revision, repo=repo, attestation_checker=_stub_verified_attestation
    )
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
        attestation_checker=_stub_verified_attestation,
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
    state_dir = repo / ".orcinus"
    state_dir.mkdir(exist_ok=True)
    state_path = state_dir / "state.json"
    state_path.write_text(json.dumps(_building(digest=digest, revision=revision)), encoding="utf-8")
    script = Path(__file__).resolve().parent / "state.py"
    # Six sequential legal transitions (via BLOCKED back to
    # BUILDING). No VERIFIED or RERUN_CONFIRMED step: those need
    # a live attestation or a real rerun, and the real-runner
    # tests cover those paths; this test's subject is the lock
    # note, not the gates.
    steps = [
        ("VERIFYING", []),
        ("BLOCKED", []),
        ("BUILDING", []),
        ("VERIFYING", []),
        ("BLOCKED", []),
        ("BUILDING", []),
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
            timeout=120,
        )
        assert proc.returncode == 0, proc.stderr
        assert "stale lock" not in proc.stderr, (to_stage, proc.stderr)


# Hold the lock from another process (the production shape: a
# second orcinus run), cross-platform: a same-process fd does not
# conflict on Windows, where msvcrt locking is per-process, so a
# same-process contender would let the first try succeed there
# and the stale-lock note would never fire. The holder prints
# "locked" once it holds the lock, then sleeps and exits (the OS
# releases the lock on exit).
_HOLD_LOCK_SCRIPT = (
    "import os, sys, time\n"
    "fd = os.open(sys.argv[1], os.O_RDWR)\n"
    "try:\n"
    "    import fcntl; fcntl.flock(fd, fcntl.LOCK_EX)\n"
    "except ImportError:\n"
    "    import msvcrt; os.lseek(fd, 0, 0); msvcrt.locking(fd, msvcrt.LK_LOCK, 1)\n"
    "print('locked', flush=True)\n"
    "time.sleep(float(sys.argv[2]))\n"
)


def test_stale_lock_note_still_fires_after_contention(tmp_path, capsys):
    """FND-005 control: the note is suppressed only when the flock
    was free on first try — after genuine contention with a dead
    recorded holder, the note still fires."""
    import gc
    import os

    state_path = tmp_path / "state.json"
    state_path.write_text("{}\n", encoding="utf-8")
    fd, lock_path, _ = st._acquire_lock(state_path)
    assert fd is not None
    st._unlock(fd)
    os.close(fd)
    # Plant a dead holder's PID in the lock file. The child must
    # be released first (del + gc closes its handle): a Popen kept
    # alive in this test would keep the Windows handle open and
    # the PID would read alive there. The guard proves the PID
    # reads dead on every platform before the test proceeds.
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    dead_pid = proc.pid
    proc.wait()
    del proc
    gc.collect()
    assert not st._pid_is_alive(dead_pid)
    lock_path.write_text(f" {dead_pid}\n", encoding="utf-8")
    # Hold the lock from another process so the first try fails,
    # then release it: the acquisition waits, then succeeds.
    holder = subprocess.Popen(
        [sys.executable, "-c", _HOLD_LOCK_SCRIPT, str(lock_path), "1"],
        stdout=subprocess.PIPE,
        text=True,
    )
    assert holder.stdout.readline().strip() == "locked"
    fd2 = None
    try:
        fd2, _, _ = st._acquire_lock(state_path, timeout_s=10.0)
        assert fd2 is not None
        assert "stale lock" in capsys.readouterr().err
    finally:
        if fd2 is not None:
            st._unlock(fd2)
            os.close(fd2)
        holder.wait(timeout=10)


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="os.kill(pid, 0) semantics are POSIX-only: on Windows a "
    "reaped child still has a live kernel object while its Popen "
    "handle is open, so the PID reads alive (see "
    "test_pid_is_alive_windows_probe)",
)
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


# --- 0.11.0: the VERIFIED gate additionally requires a CI attestation ---
# The attestation is checked LIVE at transition time, never as a
# recorded claim in the bundle. The default checker is the real
# verify_attestation check, in production and in tests alike;
# tests inject a stub explicitly, never by making the check
# optional. (0.12.0 removed the --attestation-proof file fallback:
# a hand-written proof minted VERIFIED through the gate itself.)


def _not_verified_attestation(repo, revision):
    return va.AttestationResult("not_verified", "no attestations found")


def _unavailable_attestation(repo, revision):
    return va.AttestationResult("unavailable", "gh is not authenticated (run: gh auth login)")


def _verified_state_data(repo, revision, digest):
    data = _building(digest=digest, revision=revision)
    data["stage"] = "VERIFYING"
    return data


def test_verified_refused_without_attestation(tmp_path):
    """A valid PASS bundle with no CI attestation for the revision
    is not VERIFIED: the live check says not-verified, and the
    transition is refused naming the attestation."""
    repo = _repo(tmp_path)
    revision = _head(repo)
    digest = cd.content_digest(repo, revision)
    data = _verified_state_data(repo, revision, digest)
    with pytest.raises(ValueError, match="attestation"):
        st.transition(
            data,
            "VERIFIED",
            revision,
            repo=repo,
            evidence_bundle=_write_bundle(repo, revision=revision),
            attestation_checker=_not_verified_attestation,
        )


def test_verified_allowed_with_stubbed_attestation(tmp_path):
    """The same transition with a verified attestation succeeds:
    the stub stands in for the live check, explicitly."""
    repo = _repo(tmp_path)
    revision = _head(repo)
    digest = cd.content_digest(repo, revision)
    data = _verified_state_data(repo, revision, digest)
    data = st.transition(
        data,
        "VERIFIED",
        revision,
        repo=repo,
        evidence_bundle=_write_bundle(repo, revision=revision),
        attestation_checker=_stub_verified_attestation,
    )
    assert data["stage"] == "VERIFIED"


def test_verified_refused_when_attestation_unavailable_names_only_the_live_check(tmp_path):
    """No gh / no network / no auth is not a pass and not a
    'not verified': the transition is refused, naming the live
    check as the only way forward — since 0.12.0 there is no
    proof-file fallback to name."""
    repo = _repo(tmp_path)
    revision = _head(repo)
    digest = cd.content_digest(repo, revision)
    data = _verified_state_data(repo, revision, digest)
    with pytest.raises(ValueError, match="attestation") as exc:
        st.transition(
            data,
            "VERIFIED",
            revision,
            repo=repo,
            evidence_bundle=_write_bundle(repo, revision=revision),
            attestation_checker=_unavailable_attestation,
        )
    assert "attestation-proof" not in str(exc.value)
    assert "gh" in str(exc.value)


def test_verified_default_checker_is_the_live_check(tmp_path, monkeypatch):
    """The default in production and in tests is the same: with
    no checker injected, transition() calls the real
    verify_attestation check — proved by recording the call,
    not by reaching the network."""
    repo = _repo(tmp_path)
    revision = _head(repo)
    digest = cd.content_digest(repo, revision)
    calls = []

    def _recording(repo_arg, revision_arg):
        calls.append((repo_arg, revision_arg))
        return va.AttestationResult("verified", "recorded live check")

    monkeypatch.setattr(st._verify_attestation, "verify_attestation", _recording)
    data = _verified_state_data(repo, revision, digest)
    data = st.transition(
        data,
        "VERIFIED",
        revision,
        repo=repo,
        evidence_bundle=_write_bundle(repo, revision=revision),
    )
    assert data["stage"] == "VERIFIED"
    assert calls == [(repo, revision)]


def test_cli_verified_refused_without_attestation(tmp_path):
    """The CLI, with no live attestation for this throwaway repo,
    refuses VERIFIED (exit 1) naming the attestation — the refusal
    holds whether the live check fails as not-verified or as
    unavailable."""
    repo = _repo(tmp_path)
    revision = _head(repo)
    digest = cd.content_digest(repo, revision)
    path = tmp_path / "state.json"
    path.write_text(json.dumps(_verified_state_data(repo, revision, digest)), encoding="utf-8")
    bundle = _write_bundle(repo, revision=revision)
    proc = subprocess.run(
        [
            sys.executable,
            str(REPO / "scripts" / "state.py"),
            "transition",
            str(path),
            "--to",
            "VERIFIED",
            "--revision",
            revision,
            "--repo",
            str(repo),
            "--evidence",
            bundle,
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 1
    assert "attestation" in proc.stdout + proc.stderr


# --- 0.12.0: the proof file is gone; RERUN_CONFIRMED replaces it ---
# A hand-written proof JSON with correct values used to mint
# VERIFIED through the gate itself (friend review of 0.11.1,
# claim 5, verified by execution). The gate now runs the rerun
# itself, from the revision-pinned rerun_check.py, and a local
# rerun mints RERUN_CONFIRMED — never VERIFIED. The state records
# its verification origin, and format 3 is required: a format-2
# state must be migrated, and a pre-0.12 VERIFIED is demoted,
# because its origin cannot be known afterwards.


def test_local_rerun_can_never_become_verified():
    """The privilege-escalation test: walk every (stage, origin)
    pair reachable from (RERUN_CONFIRMED, LOCAL_RERUN) through
    the allowed-transition table, applying the origin rules the
    gate enforces (BUILDING discards the record, VERIFIED mints
    CI_ATTESTED, RERUN_CONFIRMED mints LOCAL_RERUN, anything else
    keeps it). No reachable pair has stage VERIFIED with an origin
    other than CI_ATTESTED — the only way back to VERIFIED is
    through BUILDING, which discards the local-rerun record, and
    a fresh live attestation."""
    start = ("RERUN_CONFIRMED", "LOCAL_RERUN")
    seen = {start}
    queue = [start]
    while queue:
        stage, origin = queue.pop()
        for nxt in st.ALLOWED_TRANSITIONS[stage]:
            if nxt == "BUILDING":
                new_origin = None
            elif nxt == "VERIFIED":
                new_origin = "CI_ATTESTED"
            elif nxt == "RERUN_CONFIRMED":
                new_origin = "LOCAL_RERUN"
            else:
                new_origin = origin
            pair = (nxt, new_origin)
            if pair not in seen:
                seen.add(pair)
                queue.append(pair)
    assert not any(s == "VERIFIED" and o != "CI_ATTESTED" for s, o in seen)
    assert ("VERIFIED", "CI_ATTESTED") in seen  # reachable only by re-verifying via CI


def test_origin_rules_in_validate(tmp_path):
    """One case per stage group: the origin must match the stage,
    and a human approval never supplies one."""
    repo = _repo(tmp_path)
    revision = _head(repo)
    digest = cd.content_digest(repo, revision)
    # VERIFIED with a local-rerun origin is corrupt, not verified.
    data = _at_stage(repo, "VERIFIED", revision, digest)
    data["verification_origin"] = "LOCAL_RERUN"
    data["rerun"] = _rerun_record(revision)
    assert any("CI_ATTESTED" in p for p in st.validate_state(data, repo=repo))
    # RERUN_CONFIRMED with a CI origin, or without a rerun record, is corrupt.
    data = _at_stage(repo, "RERUN_CONFIRMED", revision, digest)
    data["verification_origin"] = "CI_ATTESTED"
    data["rerun"] = None
    problems = st.validate_state(data, repo=repo)
    assert any("LOCAL_RERUN" in p for p in problems)
    assert any("rerun record" in p for p in problems)
    # AWAITING_APPROVAL with no origin: an approval is a decision, not a verification.
    data = _at_stage(repo, "AWAITING_APPROVAL", revision, digest)
    data["verification_origin"] = None
    assert any("verification_origin" in p for p in st.validate_state(data, repo=repo))
    # BUILDING carrying a verification record is corrupt.
    data = _building(digest=digest, revision=revision)
    data["verification_origin"] = "CI_ATTESTED"
    assert any("verification_origin" in p for p in st.validate_state(data))
    # A rerun record for another revision is not a rerun of this content.
    data = _at_stage(repo, "RERUN_CONFIRMED", revision, digest)
    data["rerun"] = _rerun_record("c" * 40)
    assert any("rerun.revision" in p for p in st.validate_state(data, repo=repo))


def test_rerun_confirmed_with_stubbed_runner(tmp_path):
    """The stub stands in for the runner explicitly — the gate
    still re-checks the proof's fields, and records what the
    rerun did (revision, tests, junit, exit code, time) plus the
    origin, in the state and in the history entry."""
    repo = _repo(tmp_path)
    revision = _head(repo)
    digest = cd.content_digest(repo, revision)
    bundle = _write_bundle(repo, revision=revision)
    data = _building(digest=digest, revision=revision)
    data["stage"] = "VERIFYING"
    data = st.transition(
        data,
        "RERUN_CONFIRMED",
        revision,
        repo=repo,
        evidence_bundle=bundle,
        rerun_runner=_stub_rerun_runner(_proof_dict(repo, revision, digest)),
    )
    assert data["stage"] == "RERUN_CONFIRMED"
    assert data["verification_origin"] == "LOCAL_RERUN"
    assert data["rerun"]["tests"] == ["tests/test_x.py::test_y"]
    assert data["rerun"]["junit"] == {"total": 2, "passed": 2}
    assert data["rerun"]["revision"] == revision
    assert data["rerun"]["exit_code"] == 0
    assert data["rerun"]["at"]
    assert data["history"][-1]["origin"] == "LOCAL_RERUN"
    assert st.validate_state(data, repo=repo) == []


def test_rerun_confirmed_refused_when_runner_fails(tmp_path):
    """A rerun that cannot run, or whose claim does not hold, is
    a refusal — never a pass."""
    repo = _repo(tmp_path)
    revision = _head(repo)
    digest = cd.content_digest(repo, revision)
    data = _building(digest=digest, revision=revision)
    data["stage"] = "VERIFYING"
    with pytest.raises(ValueError, match="rerun"):
        st.transition(
            data,
            "RERUN_CONFIRMED",
            revision,
            repo=repo,
            evidence_bundle=_write_bundle(repo, revision=revision),
            rerun_runner=_failing_rerun_runner,
        )


def test_rerun_confirmed_refused_when_runner_returns_bad_proof(tmp_path):
    """Defence in depth: even the gate's own runner output is
    re-checked field by field — a proof for another tree's digest
    is refused, as is one that does not list the fail-first test."""
    repo = _repo(tmp_path)
    revision = _head(repo)
    digest = cd.content_digest(repo, revision)
    data = _building(digest=digest, revision=revision)
    data["stage"] = "VERIFYING"
    bad = _proof_dict(repo, revision, digest, content_digest="sha256:" + "f" * 64)
    with pytest.raises(ValueError, match="content_digest"):
        st.transition(
            data,
            "RERUN_CONFIRMED",
            revision,
            repo=repo,
            evidence_bundle=_write_bundle(repo, revision=revision),
            rerun_runner=_stub_rerun_runner(bad),
        )
    bundle = _rerun_bundle(repo, revision)  # fail-first tests/test_x.py::test_y
    proof = _proof_dict(repo, revision, digest, tests=["tests/test_other.py::test_z"])
    with pytest.raises(ValueError, match="fail-first"):
        st.transition(
            data,
            "RERUN_CONFIRMED",
            revision,
            repo=repo,
            evidence_bundle=bundle,
            rerun_runner=_stub_rerun_runner(proof),
        )


def test_building_resets_verification_record(tmp_path):
    """Rework discards the verification record: it described the
    old content, not the tree the state now points at."""
    repo = _repo(tmp_path)
    revision = _head(repo)
    digest = cd.content_digest(repo, revision)
    data = _at_stage(repo, "VERIFIED", revision, digest)
    data = st.transition(data, "BUILDING", revision, repo=repo)
    assert data["verification_origin"] is None and data["rerun"] is None
    assert data["history"][-1]["origin"] is None
    data = _at_stage(repo, "RERUN_CONFIRMED", revision, digest)
    data = st.transition(data, "BUILDING", revision, repo=repo)
    assert data["verification_origin"] is None and data["rerun"] is None


def test_local_rerun_origin_survives_approval_but_never_becomes_verified(tmp_path):
    """RERUN_CONFIRMED -> AWAITING_APPROVAL -> RELEASE_READY
    keeps the LOCAL_RERUN origin: the human approval decides the
    release, it does not upgrade the technical trust, and the
    stage never becomes VERIFIED along the way."""
    repo = _repo(tmp_path)
    revision = _head(repo)
    digest = cd.content_digest(repo, revision)
    data = _at_stage(repo, "RERUN_CONFIRMED", revision, digest)
    data = st.transition(data, "AWAITING_APPROVAL", revision, repo=repo)
    assert data["verification_origin"] == "LOCAL_RERUN"
    data["approval"] = {
        "approved_by": "x",
        "revision": revision,
        "content_digest": digest,
        "artifact": "a.tgz",
        "at": "2026-11-07T00:00:00+00:00",
    }
    data = st.transition(data, "RELEASE_READY", revision, repo=repo)
    assert data["stage"] == "RELEASE_READY"
    assert data["verification_origin"] == "LOCAL_RERUN"
    assert data["rerun"] is not None


def test_cli_attestation_proof_flag_is_gone(tmp_path, capsys):
    """0.12.0: --attestation-proof no longer exists. A caller that
    passes it gets an argparse usage error (exit 2) — the friend's
    hand-written proof has no flag left to feed it through."""
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
                "--attestation-proof",
                "proof.json",
            ]
        )
    assert exc.value.code == 2
    assert "unrecognized arguments: --attestation-proof" in capsys.readouterr().err


def _v2_building(digest=DIGEST, revision=REV, stage="BUILDING"):
    """A format-2 state dict: no verification_origin, no rerun."""
    return {
        "format_version": 2,
        "project": "weekly-budget",
        "stage": stage,
        "revision": revision,
        "content_digest": digest,
        "evidence_bundle": None,
        "approval": None,
        "history": [],
    }


def test_migrate_v2_verified_demoted():
    """A pre-0.12 VERIFIED has unknown provenance — the file never
    recorded whether it came from a CI attestation or a proof file
    — so the migration demotes it to VERIFYING instead of
    grandfathering it as CI-attested. The input is not mutated."""
    data = _v2_building(stage="VERIFIED")
    data["evidence_bundle"] = "docs/verification/x.json"
    new = st.migrate_state(data)
    assert new["format_version"] == 3
    assert new["stage"] == "VERIFYING"
    assert new["verification_origin"] is None and new["rerun"] is None
    assert new["history"][-1]["stage"] == "VERIFYING"
    assert "unknown verification provenance" in new["history"][-1]["note"]
    assert data["stage"] == "VERIFIED" and data["format_version"] == 2


def test_migrate_v2_awaiting_and_release_demoted_and_approval_preserved():
    """AWAITING_APPROVAL and RELEASE_READY derive from VERIFIED,
    so they are demoted the same way — but the approval itself is
    a separate fact from technical verification, and it survives
    the migration (it still binds the same digest when the content
    is verified again)."""
    approval = {
        "approved_by": "x",
        "revision": REV,
        "content_digest": DIGEST,
        "artifact": "a.tgz",
        "at": "2026-11-07T00:00:00+00:00",
    }
    for stage in ("AWAITING_APPROVAL", "RELEASE_READY"):
        data = _v2_building(stage=stage)
        data["approval"] = dict(approval)
        new = st.migrate_state(data)
        assert new["stage"] == "VERIFYING", stage
        assert new["approval"] == approval, stage


def test_migrate_v2_building_kept_and_idempotent():
    """Stages that imply no verification keep their stage; the
    migration only adds the null fields. Migrating twice changes
    nothing the second time."""
    data = _v2_building(stage="BUILDING")
    new = st.migrate_state(data)
    assert new["stage"] == "BUILDING"
    assert new["format_version"] == 3
    assert new["verification_origin"] is None and new["rerun"] is None
    assert st.migrate_state(new) == new
    with pytest.raises(ValueError, match="only format 2"):
        st.migrate_state({**_v2_building(), "format_version": 1})


def test_migrate_malformed_history_refused():
    """Migration refuses a malformed history with a ValueError —
    it must never crash with a traceback on a file load_state
    only checked for JSON shape (history null, or an entry that
    is not an object)."""
    for bad in (None, "x", [{"stage": "BUILDING"}, "not-an-object"]):
        data = _v2_building()
        data["history"] = bad
        with pytest.raises(ValueError, match="history must be a list of objects"):
            st.migrate_state(data)


def test_v2_refused_until_migrated(tmp_path):
    """A format-2 state is refused by validate and by transition
    until it is migrated — there is no silent grandfathering."""
    repo = _repo(tmp_path)
    revision = _head(repo)
    digest = cd.content_digest(repo, revision)
    data = _v2_building(digest=digest, revision=revision)
    assert any("migrate" in p for p in st.validate_state(data, repo=repo))
    with pytest.raises(ValueError, match="invalid state"):
        st.transition(data, "VERIFYING", revision, repo=repo)


def test_cli_migrate(tmp_path, capsys):
    """The CLI migrate: a v2 VERIFIED file becomes a v3 VERIFYING
    file (demoted, with the note), and migrating again is a
    no-op."""
    repo = _repo(tmp_path)
    revision = _head(repo)
    digest = cd.content_digest(repo, revision)
    data = _v2_building(digest=digest, revision=revision, stage="VERIFIED")
    data["evidence_bundle"] = _write_bundle(repo, revision=revision)
    path = tmp_path / "state.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert st.main(["migrate", str(path), "--repo", str(repo)]) == 0
    assert "re-verification required" in capsys.readouterr().out
    new = json.loads(path.read_text(encoding="utf-8"))
    assert new["format_version"] == 3 and new["stage"] == "VERIFYING"
    assert new["verification_origin"] is None and new["rerun"] is None
    assert st.validate_state(new, repo=repo) == []
    assert st.main(["migrate", str(path), "--repo", str(repo)]) == 0
    assert "already format 3" in capsys.readouterr().out


def test_attest_job_needs_all_gates_and_push_only():
    """0.12.0: the attest job must wait for every essential gate
    and run only on push to main — a fork PR cannot write
    attestations, and an attestation must mean the whole CI was
    green, not just the test matrix."""
    yaml = pytest.importorskip("yaml")
    workflow = yaml.safe_load(
        (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    )
    triggers = workflow.get("on", workflow.get(True))  # PyYAML reads `on:` as True
    assert set(triggers["push"]["branches"]) == {"main"}
    assert "pull_request" in triggers
    attest = workflow["jobs"]["attest"]
    assert set(attest["needs"]) == {
        "test",
        "waza",
        "demo",
        "waza-fixtures",
        "shellcheck",
        "clean-install",
        "version-bump",
        "plugin-validate",
        "postgres-migration",
    }
    assert attest["if"] == "github.event_name == 'push'"


def _gate_probe_repo(tmp_path, test_source, dirname="probe-repo"):
    """A standalone scratch repo with the real rerun machinery and
    one probe test committed: the gate's real runner needs a repo
    whose revision contains rerun_check.py (the revision-pinned
    copy it runs) plus the two files it loads at the same relative
    paths — scripts/content_digest.py beside it and
    skills/orcinus-verify/scripts/validate_evidence.py under the
    repo root — all three stdlib-only, so a scratch repo can host
    exactly them. Returns (repo, revision). Standalone on purpose:
    the earlier shape worktree'd the real repo at HEAD, which fails
    in a clean copy (no .git there) and coupled the test to the
    enclosing checkout. pytest removes tmp_path afterwards, so
    there is no worktree to clean up. Commits use -c
    user.email/name so no repo config is changed."""
    repo = tmp_path / dirname
    repo.mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@orcinus.local")
    _git(repo, "config", "user.name", "ORCINUS Test")
    (repo / "scripts").mkdir()
    for name in ("rerun_check.py", "content_digest.py"):
        shutil.copy2(REPO / "scripts" / name, repo / "scripts" / name)
    validator_dir = repo / "skills" / "orcinus-verify" / "scripts"
    validator_dir.mkdir(parents=True)
    shutil.copy2(
        REPO / "skills" / "orcinus-verify" / "scripts" / "validate_evidence.py",
        validator_dir / "validate_evidence.py",
    )
    (repo / "tests").mkdir()
    (repo / "tests" / "test_gate_probe.py").write_text(test_source, encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "probe repo: rerun_check.py and one probe test")
    return repo, _head(repo)


def _probe_bundle(tmp_path, revision, fail_first="tests/test_gate_probe.py::test_probe"):
    """A PASS bundle for the probe worktree, written outside the
    worktree (absolute path) so the worktree stays clean."""
    bundle = _pass_bundle_dict()
    if fail_first is not None:
        bundle["fail_first"] = {
            "test": fail_first,
            "failed_before": False,
            "passed_after": True,
            "method": "not-applicable",
            "note": "Docs-only change: no behaviour to prove fail-first for; "
            "the test named here is the target the gate's rerun re-runs.",
        }
    bundle["revision"] = revision
    path = tmp_path / "probe-bundle.json"
    path.write_text(json.dumps(bundle), encoding="utf-8")
    return str(path)


def test_rerun_confirmed_real_runner_honest(tmp_path):
    """The real in-gate rerun, end to end: the gate runs the
    revision-pinned rerun_check.py in a temporary worktree, the
    probe test passes there, and the transition mints
    RERUN_CONFIRMED with the recorded rerun."""
    wt, revision = _gate_probe_repo(tmp_path, "def test_probe():\n    assert 1 + 1 == 2\n")
    digest = cd.content_digest(wt, revision)
    data = _building(digest=digest, revision=revision)
    data["stage"] = "VERIFYING"
    data = st.transition(
        data,
        "RERUN_CONFIRMED",
        revision,
        repo=wt,
        evidence_bundle=_probe_bundle(tmp_path, revision),
    )
    assert data["stage"] == "RERUN_CONFIRMED"
    assert data["verification_origin"] == "LOCAL_RERUN"
    assert data["rerun"]["tests"] == ["tests/test_gate_probe.py::test_probe"]
    assert data["rerun"]["junit"] == {"total": 1, "passed": 1}
    assert data["rerun"]["revision"] == revision
    assert data["history"][-1]["origin"] == "LOCAL_RERUN"
    assert st.validate_state(data, repo=wt) == []


def test_rerun_confirmed_real_runner_liar_and_no_fail_first(tmp_path):
    """The real runner refuses a bundle whose fail-first test
    fails at the revision, and a bundle that names no test to
    rerun — the two negative cases from the friend's table."""
    wt, revision = _gate_probe_repo(tmp_path, "def test_probe():\n    assert 1 == 2\n")
    digest = cd.content_digest(wt, revision)
    data = _building(digest=digest, revision=revision)
    data["stage"] = "VERIFYING"
    with pytest.raises(ValueError, match="rerun"):
        st.transition(
            data,
            "RERUN_CONFIRMED",
            revision,
            repo=wt,
            evidence_bundle=_probe_bundle(tmp_path, revision),
        )
    wt, revision = _gate_probe_repo(
        tmp_path, "def test_probe():\n    assert 1 + 1 == 2\n", dirname="probe-repo-2"
    )
    digest = cd.content_digest(wt, revision)
    data = _building(digest=digest, revision=revision)
    data["stage"] = "VERIFYING"
    with pytest.raises(ValueError, match="fail_first"):
        st.transition(
            data,
            "RERUN_CONFIRMED",
            revision,
            repo=wt,
            evidence_bundle=_probe_bundle(tmp_path, revision, fail_first=None),
        )
