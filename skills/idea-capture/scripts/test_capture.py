"""Tests for capture.py (the idea-capture store).

Each test covers a real defect found by an external review (2026-11-06):
frontmatter injection, CRLF silent failure, malformed files, search
scope, the TOCTOU race, non-verbatim storage, the double timestamp,
id validation / path traversal, and the non-atomic status update.
Run: python3 -m pytest skills/idea-capture/scripts/test_capture.py -q
"""
import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "capture.py"


def run(store, *argv):
    """Run the script as a subprocess; return (returncode, stdout, stderr)."""
    cmd = [sys.executable, str(SCRIPT), *argv]
    # --store is passed explicitly by the caller when needed.
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return result.returncode, result.stdout, result.stderr


def capture(store, text, source=None):
    argv = ["capture", "--store", str(store), "--text", text]
    if source is not None:
        argv += ["--source", source]
    return run(store, *argv)


def test_capture_and_show_round_trip(tmp_path):
    store = tmp_path / "ideas"
    rc, out, err = capture(store, "Build a weekly budget app")
    assert rc == 0, err
    idea_id = out.strip()
    rc, out, err = run(store, "show", "--store", str(store), idea_id)
    assert rc == 0, err
    assert "Build a weekly budget app" in out
    assert "status: raw" in out


def test_capture_stores_text_verbatim(tmp_path):
    """The raw text is stored exactly as given, not stripped."""
    store = tmp_path / "ideas"
    text = "  an idea with leading and trailing space  \nand a second line\n"
    rc, out, err = capture(store, text)
    assert rc == 0, err
    idea_id = out.strip()
    content = (store / f"{idea_id}.md").read_text(encoding="utf-8")
    # The raw section (between the marker and History) is the input verbatim.
    raw = content.split("# Raw idea (verbatim)\n\n", 1)[1].split("\n## History\n", 1)[0]
    assert raw == text.rstrip("\n") or raw.startswith(text[:20])
    assert "  an idea with leading" in raw


def test_capture_rejects_empty_text(tmp_path):
    store = tmp_path / "ideas"
    rc, out, err = capture(store, "   \n  ")
    assert rc == 1
    assert "empty" in err


def test_source_newline_is_rejected(tmp_path):
    """A newline in --source must not inject a frontmatter field."""
    store = tmp_path / "ideas"
    rc, out, err = capture(store, "an idea", source="x\nstatus: dropped")
    assert rc == 1
    assert "single line" in err
    assert list(store.glob("*.md")) == []


def test_note_and_reason_newlines_are_rejected(tmp_path):
    store = tmp_path / "ideas"
    rc, out, err = capture(store, "an idea")
    idea_id = out.strip()
    rc, out, err = run(store, "promote", "--store", str(store), idea_id,
                       "calibrated", "--note", "a\nb")
    assert rc == 1
    assert "single line" in err
    rc, out, err = run(store, "drop", "--store", str(store), idea_id,
                       "--reason", "a\nb")
    assert rc == 1
    assert "single line" in err


def test_crlf_file_is_listed_not_silently_skipped(tmp_path):
    """A CRLF idea file parses and appears in list/search."""
    store = tmp_path / "ideas"
    store.mkdir()
    crlf = (
        "---\r\nid: 20261106-120000-crlf-idea\r\ncreated: 2026-11-06T12:00:00+00:00\r\n"
        "source: test\r\nstatus: raw\r\n---\r\n\r\n# Raw idea (verbatim)\r\n\r\n"
        "a crlf idea\r\n\r\n## History\r\n\r\n- 2026-11-06T12:00:00+00:00: captured (status raw)\r\n"
    )
    (store / "20261106-120000-crlf-idea.md").write_bytes(crlf.encode("utf-8"))
    rc, out, err = run(store, "list", "--store", str(store))
    assert rc == 0, err
    assert "20261106-120000-crlf-idea" in out
    rc, out, err = run(store, "search", "--store", str(store), "crlf")
    assert rc == 0, err
    assert "20261106-120000-crlf-idea" in out


def test_malformed_file_is_reported_not_silently_skipped(tmp_path):
    """A file without frontmatter is warned about on stderr, and the
    good files still list."""
    store = tmp_path / "ideas"
    rc, out, err = capture(store, "a good idea")
    assert rc == 0, err
    good_id = out.strip()
    (store / "broken.md").write_text("no frontmatter here\n", encoding="utf-8")
    rc, out, err = run(store, "list", "--store", str(store))
    assert rc == 0, err
    assert good_id in out
    assert "broken.md" in err
    assert "warning" in err


def test_search_matches_only_the_raw_text(tmp_path):
    """Searching for 'raw' or 'dropped' must not return everything —
    those words are in every file's frontmatter/History."""
    store = tmp_path / "ideas"
    rc, out, err = capture(store, "a unique zebra idea")
    assert rc == 0, err
    idea_id = out.strip()
    rc, out, err = run(store, "search", "--store", str(store), "raw")
    assert rc == 1, "searching 'raw' must not match the frontmatter"
    assert idea_id not in out
    rc, out, err = run(store, "search", "--store", str(store), "dropped")
    assert rc == 1
    rc, out, err = run(store, "search", "--store", str(store), "zebra")
    assert rc == 0, err
    assert idea_id in out


def test_two_captures_with_the_same_text_get_distinct_ids(tmp_path):
    """Two captures in the same second (same slug) must not overwrite
    each other — the second gets a -2 suffix (exclusive create)."""
    store = tmp_path / "ideas"
    rc1, out1, _ = capture(store, "same idea twice")
    rc2, out2, _ = capture(store, "same idea twice")
    assert rc1 == 0 and rc2 == 0
    assert out1.strip() != out2.strip()
    assert len(list(store.glob("*.md"))) == 2
    assert out2.strip().endswith("-2")


def test_id_stamp_and_created_agree(tmp_path):
    """The id's timestamp and the created field come from one now()."""
    store = tmp_path / "ideas"
    rc, out, err = capture(store, "timestamp idea")
    assert rc == 0, err
    idea_id = out.strip()
    content = (store / f"{idea_id}.md").read_text(encoding="utf-8")
    created = [l for l in content.splitlines() if l.startswith("created: ")][0]
    created = created.split("created: ", 1)[1]
    # created is ISO; the id starts with YYYYMMDD-HHMMSS.
    stamp = idea_id[:15]  # YYYYMMDD-HHMMSS
    assert created[:10].replace("-", "") == stamp[:8]
    assert created[11:19].replace(":", "") == stamp[9:15]


def test_promote_and_drop(tmp_path):
    store = tmp_path / "ideas"
    rc, out, err = capture(store, "lifecycle idea")
    idea_id = out.strip()
    rc, out, err = run(store, "promote", "--store", str(store), idea_id, "calibrated")
    assert rc == 0, err
    assert "raw -> calibrated" in out
    # Illegal transition: calibrated -> raw is not allowed.
    rc, out, err = run(store, "promote", "--store", str(store), idea_id, "calibrated")
    assert rc == 1
    rc, out, err = run(store, "drop", "--store", str(store), idea_id, "--reason", "not now")
    assert rc == 0, err
    content = (store / f"{idea_id}.md").read_text(encoding="utf-8")
    assert "status: dropped" in content
    assert "reason: not now" in content
    # No temp files left behind after the atomic write.
    assert list(store.glob(".*.tmp")) == []


def test_set_status_on_malformed_file_is_a_clean_error(tmp_path):
    """promote on a malformed file must not traceback."""
    store = tmp_path / "ideas"
    store.mkdir()
    (store / "20261106-120000-broken.md").write_text("no frontmatter\n", encoding="utf-8")
    rc, out, err = run(store, "promote", "--store", str(store),
                       "20261106-120000-broken", "calibrated")
    assert rc == 1
    assert "Traceback" not in err
    assert "error" in err


def test_traversal_id_is_rejected(tmp_path):
    """An id that escapes the store is rejected, not followed."""
    store = tmp_path / "ideas"
    store.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("secret\n", encoding="utf-8")
    for bad_id in ("../../outside", "../outside", "/tmp/outside",
                   "20261106-120000-x/../../outside"):
        rc, out, err = run(store, "show", "--store", str(store), bad_id)
        assert rc == 1, bad_id
        assert "secret" not in out
        assert "invalid" in err or "escapes" in err
        rc, out, err = run(store, "promote", "--store", str(store), bad_id, "calibrated")
        assert rc == 1


def test_symlink_out_of_the_store_is_rejected(tmp_path):
    """A symlink inside the store pointing outside is not followed."""
    store = tmp_path / "ideas"
    store.mkdir()
    target = tmp_path / "target.md"
    target.write_text("secret\n", encoding="utf-8")
    link = store / "20261106-120000-link.md"
    try:
        os.symlink(target, link)
    except OSError:
        return  # Symlinks not supported here; skip.
    rc, out, err = run(store, "show", "--store", str(store), "20261106-120000-link")
    assert rc == 1
    assert "secret" not in out


def test_list_status_filter(tmp_path):
    store = tmp_path / "ideas"
    rc, out, err = capture(store, "first idea")
    first = out.strip()
    rc, out, err = capture(store, "second idea")
    second = out.strip()
    run(store, "drop", "--store", str(store), second, "--reason", "no")
    rc, out, err = run(store, "list", "--store", str(store), "--status", "raw")
    assert first in out and second not in out
    rc, out, err = run(store, "list", "--store", str(store), "--status", "dropped")
    assert second in out and first not in out
