"""Tests for scripts/generate_manifest.py (round 6, 2-S4).

The generator used to ignore its arguments entirely: `--check`
REWROTE the file it was supposed to only verify, and a typo'd flag
passed silently. argparse now owns the CLI: --check diffs and never
writes, unknown flags exit 2.

The tests build a tiny fake repo (two skills) and monkeypatch the
module globals MANIFEST_PATH / STAGES_PATH / ROOT at the fake repo,
so the real manifest is never touched.

Run: python3 -m pytest scripts/test_generate_manifest.py -q
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import generate_manifest  # noqa: E402

SKILL_A = """---
name: alpha
description: Alpha skill.
license: MIT
---

# Alpha
"""

SKILL_B = """---
name: beta
description: Beta skill.
license: Apache-2.0
---

# Beta
"""


def _fake_repo(tmp_path):
    """A repo with two skills, a stages registry, and a manifest
    whose curated fields are already filled in."""
    repo = tmp_path / "repo"
    skills = repo / "skills"
    (skills / "alpha").mkdir(parents=True)
    (skills / "beta").mkdir(parents=True)
    (skills / "alpha" / "SKILL.md").write_text(SKILL_A, encoding="utf-8")
    (skills / "beta" / "SKILL.md").write_text(SKILL_B, encoding="utf-8")
    stages = {"stages": {"alpha": [10], "beta": [20]}}
    (repo / "skills" / "stages.json").write_text(json.dumps(stages), encoding="utf-8")
    manifest = {
        "version": 2,
        "generated_by": "test",
        "skills": {
            "alpha": {
                "name": "alpha",
                "description": "Alpha skill.",
                "license": "MIT",
                "stages": [10],
                "source": "from-scratch",
                "integration": "from-scratch",
                "upstream_commit": None,
                "status": "built",
            },
            "beta": {
                "name": "beta",
                "description": "Beta skill.",
                "license": "Apache-2.0",
                "stages": [20],
                "source": "from-scratch",
                "integration": "from-scratch",
                "upstream_commit": None,
                "status": "built",
            },
        },
    }
    manifest_path = repo / "skills" / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return repo, manifest_path


def _point_at(monkeypatch, repo, manifest_path):
    monkeypatch.setattr(generate_manifest, "ROOT", repo)
    monkeypatch.setattr(generate_manifest, "MANIFEST_PATH", manifest_path)
    monkeypatch.setattr(generate_manifest, "STAGES_PATH", repo / "skills" / "stages.json")


def test_check_exits_1_and_does_not_write_when_stale(tmp_path, monkeypatch):
    """2-S4, the reported bug: --check on a stale manifest must exit
    1 and leave the file byte-identical — it used to rewrite it."""
    repo, manifest_path = _fake_repo(tmp_path)
    _point_at(monkeypatch, repo, manifest_path)
    # Make the manifest stale: the frontmatter says "Alpha skill."
    # but the manifest says something else.
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    data["skills"]["alpha"]["description"] = "Stale description."
    manifest_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    before = manifest_path.read_bytes()
    assert generate_manifest.main(["--check"]) == 1
    assert manifest_path.read_bytes() == before, "--check rewrote the manifest"


def test_check_exits_0_when_up_to_date(tmp_path, monkeypatch):
    """Control: a manifest that already matches its sources passes
    --check with exit 0. The up-to-date manifest is produced by a
    plain run first, so the generated_by boilerplate matches what
    --check compares against."""
    repo, manifest_path = _fake_repo(tmp_path)
    _point_at(monkeypatch, repo, manifest_path)
    assert generate_manifest.main([]) == 0
    assert generate_manifest.main(["--check"]) == 0


def test_unknown_arg_exits_2(tmp_path, monkeypatch):
    """2-S4: a typo'd flag must not pass silently — argparse exits 2
    on unknown arguments."""
    repo, manifest_path = _fake_repo(tmp_path)
    _point_at(monkeypatch, repo, manifest_path)
    with __import__("pytest").raises(SystemExit) as exc:
        generate_manifest.main(["--chek"])
    assert exc.value.code == 2


def test_default_run_still_writes(tmp_path, monkeypatch):
    """Regression: the plain run (no --check) still regenerates the
    manifest — the --check fix must not change normal behaviour."""
    repo, manifest_path = _fake_repo(tmp_path)
    _point_at(monkeypatch, repo, manifest_path)
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    data["skills"]["alpha"]["description"] = "Stale description."
    manifest_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    assert generate_manifest.main([]) == 0
    after = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert after["skills"]["alpha"]["description"] == "Alpha skill."
