"""Tests for scripts/state.py + scripts/state_schema.json — the
.orcinus/state.json schema and transition tool (round 6, 2-R2).

The state file was spec-only (docs/project-state.md + a digest
helper); nothing validated it or enforced a transition. The schema
is the declarative contract, this module enforces it plus the
transition rules. This is a local check, not the v1.1 tamper-proof
enforcement layer — anyone with write access can still edit the
file (project-state.md Rule 4).

Run: python3 -m pytest scripts/test_state.py -q
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import state as st  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
DIGEST = "sha256:" + "a" * 64
DIGEST2 = "sha256:" + "b" * 64
REV = "b2809bd64f5679ce56eb79a239109978f0c9f06a"


def _building():
    return {
        "format_version": 2,
        "project": "weekly-budget",
        "stage": "BUILDING",
        "revision": REV,
        "content_digest": DIGEST,
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


def _at_stage(stage):
    """A valid state in `stage` (VERIFIED needs an evidence bundle,
    RELEASE_READY needs an approval bound to the digest)."""
    data = _building()
    data["stage"] = stage
    if stage in ("VERIFIED", "AWAITING_APPROVAL", "RELEASE_READY"):
        data["evidence_bundle"] = "docs/verification/x.json"
    if stage == "RELEASE_READY":
        data["approval"] = {
            "approved_by": "x",
            "revision": REV,
            "content_digest": DIGEST,
            "artifact": "a.tgz",
            "at": "2026-11-07T00:00:00+00:00",
        }
    return data


def test_allowed_transitions():
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
        data = _at_stage(frm)
        if to == "VERIFIED":
            data = st.transition(data, to, REV, DIGEST, evidence_bundle="docs/verification/x.json")
        elif to == "RELEASE_READY":
            data["approval"] = {
                "approved_by": "x",
                "revision": REV,
                "content_digest": DIGEST,
                "artifact": "a.tgz",
                "at": "2026-11-07T00:00:00+00:00",
            }
            data = st.transition(data, to, REV, DIGEST)
        else:
            data = st.transition(data, to, REV, DIGEST)
        assert data["stage"] == to
    for frm, to in (
        ("BUILDING", "VERIFIED"),
        ("VERIFYING", "AWAITING_APPROVAL"),
        ("VERIFIED", "VERIFYING"),
        ("RELEASE_READY", "VERIFYING"),
        ("RELEASE_READY", "BUILDING"),
    ):
        data = _at_stage(frm)
        with pytest.raises(ValueError, match="not an allowed transition"):
            st.transition(data, to, REV, DIGEST)


def test_digest_change_forces_building():
    """Rule 2: a content change resets the stage. A transition to
    any other stage with a new digest is refused."""
    data = _building()
    data["stage"] = "VERIFYING"
    with pytest.raises(ValueError, match="BUILDING"):
        st.transition(data, "VERIFIED", REV, DIGEST2, evidence_bundle="docs/verification/x.json")
    data = st.transition(data, "BUILDING", REV, DIGEST2, note="content changed")
    assert data["stage"] == "BUILDING" and data["content_digest"] == DIGEST2


def test_verified_needs_evidence_and_release_needs_approval():
    data = _building()
    data["stage"] = "VERIFYING"
    with pytest.raises(ValueError, match="evidence_bundle"):
        st.transition(data, "VERIFIED", REV, DIGEST)
    data = _building()
    data["stage"] = "AWAITING_APPROVAL"
    with pytest.raises(ValueError, match="approval"):
        st.transition(data, "RELEASE_READY", REV, DIGEST)


def test_transition_appends_history_without_rewriting_it():
    data = _building()
    data = st.transition(data, "VERIFYING", REV, DIGEST, note="verifier running")
    assert len(data["history"]) == 1
    assert data["history"][0]["stage"] == "VERIFYING"
    assert data["history"][0]["note"] == "verifier running"
    first = dict(data["history"][0])
    data = st.transition(data, "BLOCKED", REV, DIGEST)
    assert data["history"][0] == first  # append-only: never rewritten
    assert data["history"][1]["stage"] == "BLOCKED"


def test_cli_validate_and_transition(tmp_path, capsys):
    path = tmp_path / "state.json"
    path.write_text(json.dumps(_building()), encoding="utf-8")
    assert st.main(["validate", str(path)]) == 0
    assert (
        st.main(
            [
                "transition",
                str(path),
                "--to",
                "VERIFYING",
                "--revision",
                REV,
                "--digest",
                DIGEST,
                "--note",
                "verifier running",
            ]
        )
        == 0
    )
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["stage"] == "VERIFYING" and len(data["history"]) == 1
    path.write_text(json.dumps({**_building(), "stage": "DONE"}), encoding="utf-8")
    assert st.main(["validate", str(path)]) == 1
    assert "stage" in capsys.readouterr().out
