"""Tests for scripts/check_accessibility.py (the ORCINUS
accessibility gate wrapper).

Round 6 (2026-11-07), 3-R3-03: the vendored ultra11y engine silently
skips an input it cannot find — it warns on stderr, audits zero
files, reports conformancePct 100, and exits 0. The engine itself
is bundled verbatim and is NOT edited; this wrapper is the gate:
it pre-checks every input, fails a glob that matches nothing, and
fails when the engine audited zero files — even when the engine
exits 0.

Run: python3 -m pytest skills/accessibility/scripts/test_check_accessibility.py -q
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_accessibility as caa  # noqa: E402

GOOD_HTML = (
    '<!DOCTYPE html><html lang="en"><head><title>t</title></head>'
    "<body><main><h1>Hi</h1><p>Text</p></main></body></html>\n"
)
# An image without an alternative: a blocking finding for the engine.
BAD_HTML = (
    '<!DOCTYPE html><html lang="en"><head><title>t</title></head>'
    '<body><main><h1>Hi</h1><img src="x.png"></main></body></html>\n'
)


def _page(tmp_path, name, content):
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


def test_missing_input_is_incomplete(tmp_path):
    """3-R3-03: a missing file alone must be INCOMPLETE (exit 2),
    not the engine's exit 0 with files: 0 and 100% conformance."""
    missing = tmp_path / "no-such-file.html"
    assert caa.main([str(missing)]) == 2


def test_mixed_valid_and_missing_is_incomplete(tmp_path):
    """3-R3-03: a healthy page plus a missing path must not PASS —
    the coverage is incomplete."""
    good = _page(tmp_path, "good.html", GOOD_HTML)
    missing = tmp_path / "no-such-file.html"
    assert caa.main([str(good), str(missing)]) == 2


def test_glob_with_no_match_is_incomplete(tmp_path):
    """3-R3-03: a glob that matches nothing is INCOMPLETE, not a
    zero-file PASS."""
    assert caa.main([str(tmp_path / "no-such-*.html")]) == 2


def test_glob_with_no_match_allowed_still_cannot_pass(tmp_path):
    """--allow-empty-glob makes the policy explicit, but zero audited
    files still cannot PASS."""
    assert caa.main([str(tmp_path / "no-such-*.html"), "--allow-empty-glob"]) == 2


def test_healthy_page_passes(tmp_path, capsys):
    good = _page(tmp_path, "good.html", GOOD_HTML)
    assert caa.main([str(good)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["scope"]["files"] == 1


def test_page_with_major_finding_fails(tmp_path):
    bad = _page(tmp_path, "bad.html", BAD_HTML)
    assert caa.main([str(bad)]) == 1


def test_engine_reporting_zero_files_is_incomplete(tmp_path, monkeypatch):
    """3-R3-03, post-check half: even if the engine itself exits 0
    with files: 0 (the silent-skip shape), the gate fails. The
    engine run is stubbed here so the check is tested directly,
    not only through the pre-check."""
    good = _page(tmp_path, "good.html", GOOD_HTML)

    class _Proc:
        returncode = 0
        stdout = json.dumps({"scope": {"inputs": [str(good)], "files": 0}})
        stderr = "ultra11y: input not found: good.html\n"

    monkeypatch.setattr(caa, "_run_engine", lambda argv: _Proc())
    assert caa.main([str(good)]) == 2


def test_engine_fewer_files_than_requested_is_incomplete(tmp_path, monkeypatch):
    """A run that audits fewer files than the requested inputs is
    INCOMPLETE, even when the audited files are clean."""
    good = _page(tmp_path, "good.html", GOOD_HTML)
    other = _page(tmp_path, "other.html", GOOD_HTML)

    class _Proc:
        returncode = 0
        stdout = json.dumps({"scope": {"inputs": [str(good)], "files": 1}})
        stderr = ""

    monkeypatch.setattr(caa, "_run_engine", lambda argv: _Proc())
    assert caa.main([str(good), str(other)]) == 2


def test_skill_points_at_the_wrapper():
    """The accessibility SKILL.md must route the audit through the
    wrapper, not straight at the engine."""
    repo_root = Path(__file__).resolve().parents[3]
    text = (repo_root / "skills" / "accessibility" / "SKILL.md").read_text(encoding="utf-8")
    assert "check_accessibility.py" in text
