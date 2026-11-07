"""Tests for the secret-scan pattern in skills/security-review/SKILL.md.

The pattern is the thin scan the skill tells the reviewer to run
(grep -i -E); the test extracts it from the SKILL.md itself, so the
documented command and the tested pattern cannot drift apart, and
runs it with the real grep. A test that only re-reads the prose
would pass while the scan still missed secrets.

Run: python3 -m pytest skills/security-review/test_secret_scan.py -q
"""

import re
import shutil
import subprocess
from pathlib import Path

SKILL_MD = Path(__file__).resolve().parent / "SKILL.md"


def extract_grep_pattern():
    """The ERE inside `grep -r -n -i -E "..."` in step 2 of the
    SKILL.md. The pattern is written shell-double-quoted, so an
    escaped quote (\\") inside it is a literal quote for grep."""
    for line in SKILL_MD.read_text(encoding="utf-8").splitlines():
        marker = 'grep -r -n -i -E "'
        at = line.find(marker)
        if at < 0:
            continue
        start = at + len(marker)
        i = start
        while i < len(line):
            if line[i] == '"' and line[i - 1] != "\\":
                return line[start:i].replace('\\"', '"')
            i += 1
        raise AssertionError("unterminated grep pattern in SKILL.md")
    raise AssertionError("no grep -i -E pattern found in SKILL.md")


def _matches(pattern, line):
    result = subprocess.run(
        ["grep", "-q", "-i", "-E", pattern],
        input=line,
        text=True,
        capture_output=True,
        timeout=10,
    )
    return result.returncode == 0


# Lines the scan must catch (2-S2: unquoted assignments, npm_ /
# rk_live_ / Bearer tokens, and the controls that already worked).
MUST_MATCH = [
    "API_KEY=abcdefgh12345678",  # unquoted assignment (was missed)
    "token: abcdefgh12345678",  # unquoted, colon form (was missed)
    'password = "hunter2hunter2"',  # quoted control
    "api_key = 'abcdefgh12345678'",  # quoted control
    "npm_abcdefghijklmnopqrstuvwxyz1234567890",  # npm token (was missed)
    "rk_live_abcdefghij1234567890",  # rk_live_ token (was missed)
    "Authorization: Bearer abcdefghij1234567890XYZ",  # Bearer (was missed)
    # Built by concatenation: a literal 20-char sk- token would trip
    # the repo's own no-secret-shape guard (test_readme_table.py).
    "sk-" + "abcdefghij1234567890",  # real sk- token still matches
    "sk_live_abcdefghij1234567890",  # real sk_live_ token still matches
    "sk_test_abcdefghij1234567890",  # prose lists sk_test_; regex lacked it
]

# Lines the scan must NOT catch.
MUST_NOT_MATCH = [
    "disk-usage-monitor",  # 2-S2: "di**sk-**usage-monitor" matched via sk-
    "disk_live_abcdefghij",  # same word-boundary gap for sk_live_
    'password = "short"',  # quoted value under 8 chars
    "token: abc",  # unquoted value under 8 chars
    'token = ""',  # empty value
    "no secrets here",
]


def test_secret_scan_pattern():
    if shutil.which("grep") is None:
        import pytest

        pytest.skip("grep is not installed")
    pattern = extract_grep_pattern()
    assert "BEGIN" in pattern and "sk-" in pattern, "extracted the wrong text"
    for line in MUST_MATCH:
        assert _matches(pattern, line), f"scan must match: {line!r}"
    for line in MUST_NOT_MATCH:
        assert not _matches(pattern, line), f"scan must not match: {line!r}"


def test_gitleaks_absence_forces_regex_only_report():
    """2-S2: when gitleaks is absent the secrets check is reported
    as regex-only — the thin scan ran, gitleaks did not — never as
    a full secrets check that passed."""
    text = SKILL_MD.read_text(encoding="utf-8")
    assert "regex-only" in text
    assert re.search(r"gitleaks is not installed.*regex-only|regex-only.*gitleaks", text, re.S), (
        "the gitleaks-absent sentence must require a regex-only report"
    )
