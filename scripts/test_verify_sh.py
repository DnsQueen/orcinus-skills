"""Tests for skills/monitoring/scripts/verify.sh.

The script is a bash gate, so the tests run it as a subprocess
against throwaway config dirs — the same style as
test_check_refactor.py. Round 6 (2-S3 / 3-F2-04 / 3-F2-05).

Run: python3 -m pytest scripts/test_verify_sh.py -q
"""

import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "skills" / "monitoring" / "scripts" / "verify.sh"


def _run(target):
    proc = subprocess.run(
        ["bash", str(SCRIPT), str(target)], capture_output=True, text=True, timeout=30
    )
    return proc.returncode, proc.stdout + proc.stderr


def _write(tmp_path, name, content):
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


GOOD = """\
alerts:
  - name: HighErrorRate
    expr: error_rate > 0.05
    windows: [5m, 1h]
    burn_rate: 14.4
    runbook: https://example.com/runbooks/high-error-rate
health:
  livez: /livez
  readyz: /readyz
monitors:
  - target: /api/checkout
"""

# Every load-bearing keyword appears ONLY in comments; the real
# content is a bare cpu threshold. Before the fix the gate passed
# this vacuously on the comments (3-F2-04); the eval
# (evals/monitoring-01.md) had to remove the comments to make the
# bad config fail honestly.
COMMENT_ONLY_BAD = """\
# liveness and readiness are split: /livez and /readyz
# burn_rate multi-window alert with runbook reference
# critical journey target, not the homepage
alerts:
  - name: HighCpu
    expr: cpu > 90
monitors:
  - target: /
"""


def test_missing_path_is_incomplete_not_skip(tmp_path):
    """2-S3 / 3-F2-05: a nonexistent path used to print SKIP and exit
    0 — indistinguishable from a clean config. A path that does not
    exist means nothing was checked: INCOMPLETE, exit 2."""
    rc, out = _run(tmp_path / "does-not-exist")
    assert rc == 2, out
    assert "INCOMPLETE" in out or "not found" in out.lower()


def test_comment_keywords_do_not_pass(tmp_path):
    """3-F2-04: keywords in comments must not satisfy any check —
    the config above has no real liveness/readiness split, no
    burn-rate alert, no runbook, and only a cpu threshold."""
    _write(tmp_path, "alerts.yml", COMMENT_ONLY_BAD)
    rc, out = _run(tmp_path)
    assert rc == 1, out
    assert "only cause-based" in out
    assert "no runbook" in out
    # With the comments stripped the config has NO health spec at
    # all, so check 2 honestly skips instead of failing on a split
    # that was never specified — what matters is that no comment
    # keyword passes it: there is no PASS for liveness/readiness.
    assert "no health-endpoint spec present" in out
    assert "PASS: health spec separates" not in out


def test_comment_opsgenie_does_not_fail(tmp_path):
    """3-F2-04, banlist side: an Opsgenie mention in a comment only
    (e.g. a do-not note or a historical mention) must not fail the
    gate — the stripped haystack has no opsgenie at all."""
    _write(
        tmp_path,
        "alerts.yml",
        "# opsgenie alerting was configured in the old console\n" + GOOD,
    )
    rc, out = _run(tmp_path)
    assert rc == 0, out


def test_good_config_still_passes_with_comments(tmp_path):
    """Control: stripping full-line comments must not break a good
    config that also carries comments."""
    _write(tmp_path, "alerts.yml", "# deployment notes\n" + GOOD)
    rc, out = _run(tmp_path)
    assert rc == 0, out


def test_summary_reports_counts(tmp_path):
    """The summary reports how much was actually gated — candidate
    files and alert blocks — so a pass over one file cannot be
    mistaken for a pass over the whole config."""
    _write(tmp_path, "alerts.yml", GOOD)
    rc, out = _run(tmp_path)
    assert rc == 0, out
    assert "1 candidate" in out
    assert "alert" in out.lower()


def test_empty_dir_still_passes(tmp_path):
    """Documented policy, unchanged: an existing path with no
    monitoring candidates exits 0 — a clean target is never a
    failure. (The reviewer's --allow-empty suggestion for this case
    was skipped: there is nothing to allow, the exit already says
    nothing was gated.)"""
    rc, out = _run(tmp_path)
    assert rc == 0, out
    assert "nothing to gate" in out
