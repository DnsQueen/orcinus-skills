"""Tests for capture.py (the idea-capture store).

Each test covers a real defect found by an external review (2026-11-06):
frontmatter injection, CRLF silent failure, malformed files, search
scope, the TOCTOU race, non-verbatim storage, the double timestamp,
id validation / path traversal, and the non-atomic status update.

Second review round (2026-11-06): the Persian-only crash (slugify
kept Persian letters but ID_RE rejected them), the lost update in
_set_status (no lock), the symlink gap in list/search, the
"## History" delimiter collision in the raw text, and the weak
verbatim test (it accepted a 20-character prefix). Each has a
regression test below.
Run: python3 -m pytest skills/idea-capture/scripts/test_capture.py -q
"""

import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "capture.py"

sys.path.insert(0, str(Path(__file__).resolve().parent))
import capture as cap  # noqa: E402  (the module under test)


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
    """The raw text is stored exactly as given, not stripped — and the
    check is exact equality, not a 20-character prefix."""
    store = tmp_path / "ideas"
    text = "  an idea with leading and trailing space  \nand a second line\n"
    rc, out, err = capture(store, text)
    assert rc == 0, err
    idea_id = out.strip()
    content = (store / f"{idea_id}.md").read_text(encoding="utf-8")
    # Exact round-trip: raw_text_of returns the input, nothing more.
    assert cap.raw_text_of(content) == text
    assert "  an idea with leading" in cap.raw_text_of(content)


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
    rc, out, err = run(
        store, "promote", "--store", str(store), idea_id, "calibrated", "--note", "a\nb"
    )
    assert rc == 1
    assert "single line" in err
    rc, out, err = run(store, "drop", "--store", str(store), idea_id, "--reason", "a\nb")
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
    good files still list — but the run is partial (exit 2), not a
    success: a machine caller must not treat an incomplete list as
    complete. (Third review round: this test used to assert rc 0.)"""
    store = tmp_path / "ideas"
    rc, out, err = capture(store, "a good idea")
    assert rc == 0, err
    good_id = out.strip()
    (store / "broken.md").write_text("no frontmatter here\n", encoding="utf-8")
    rc, out, err = run(store, "list", "--store", str(store))
    assert rc == 2, err
    assert good_id in out
    assert "broken.md" in err
    assert "warning" in err
    assert "partial" in err


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
    each other — the second gets a -2 suffix (exclusive create). The
    pair is retried until both land in the same second: two captures
    straddling a second boundary get distinct timestamps instead, and
    that is correct behaviour, not a failure — the old test asserted
    the -2 suffix unconditionally and failed about a third of the
    time on the boundary."""
    for attempt in range(10):
        store = tmp_path / f"ideas-{attempt}"
        rc1, out1, _ = capture(store, "same idea twice")
        rc2, out2, _ = capture(store, "same idea twice")
        assert rc1 == 0 and rc2 == 0
        id1, id2 = out1.strip(), out2.strip()
        assert id1 != id2
        assert len(list(store.glob("*.md"))) == 2
        if id1[:15] == id2[:15]:  # same YYYYMMDD-HHMMSS stamp
            assert id2.endswith("-2")
            return
    raise AssertionError("two captures never landed in the same second after 10 attempts")


def test_id_stamp_and_created_agree(tmp_path):
    """The id's timestamp and the created field come from one now()."""
    store = tmp_path / "ideas"
    rc, out, err = capture(store, "timestamp idea")
    assert rc == 0, err
    idea_id = out.strip()
    content = (store / f"{idea_id}.md").read_text(encoding="utf-8")
    created = [line for line in content.splitlines() if line.startswith("created: ")][0]
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
    rc, out, err = run(
        store, "promote", "--store", str(store), "20261106-120000-broken", "calibrated"
    )
    assert rc == 1
    assert "Traceback" not in err
    assert "error" in err


def test_traversal_id_is_rejected(tmp_path):
    """An id that escapes the store is rejected, not followed."""
    store = tmp_path / "ideas"
    store.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("secret\n", encoding="utf-8")
    for bad_id in (
        "../../outside",
        "../outside",
        "/tmp/outside",
        "20261106-120000-x/../../outside",
    ):
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


# --- Second review round: regression tests (2026-11-06) ---


def test_persian_only_idea_round_trips(tmp_path):
    """A Persian-only idea must capture, show, search and promote —
    the slug is ASCII ("idea") while the raw text stays Persian.
    This is the bug that crashed with a ValueError traceback."""
    store = tmp_path / "ideas"
    text = "یک ایده تازه"
    rc, out, err = capture(store, text)
    assert rc == 0, err
    assert "Traceback" not in err
    idea_id = out.strip()
    assert idea_id.endswith("-idea"), idea_id
    rc, out, err = run(store, "show", "--store", str(store), idea_id)
    assert rc == 0, err
    assert text in out
    rc, out, err = run(store, "search", "--store", str(store), "ایده")
    assert rc == 0, err
    assert idea_id in out
    rc, out, err = run(store, "promote", "--store", str(store), idea_id, "calibrated")
    assert rc == 0, err


def test_persian_and_english_mixed(tmp_path):
    """Mixed text uses the Latin words for the slug; the raw text is
    still the full mixed input."""
    store = tmp_path / "ideas"
    text = "سامانه مدیریت هزینه weekly budget"
    rc, out, err = capture(store, text)
    assert rc == 0, err
    idea_id = out.strip()
    assert "weekly-budget" in idea_id
    content = (store / f"{idea_id}.md").read_text(encoding="utf-8")
    assert cap.raw_text_of(content) == text


def test_persian_half_space_and_emoji_and_punctuation(tmp_path):
    """Half-space (ZWNJ), emoji-only and punctuation-only ideas all
    capture without a traceback."""
    store = tmp_path / "ideas"
    # U+200C ZERO WIDTH NON-JOINER between می and خواهم.
    rc, out, err = capture(store, "می‌خواهم یک اپ بسازم")
    assert rc == 0, err
    assert "Traceback" not in err
    first = out.strip()
    assert (
        cap.raw_text_of((store / f"{first}.md").read_text(encoding="utf-8"))
        == "می‌خواهم یک اپ بسازم"
    )
    rc, out, err = capture(store, "🚀💡🎉")
    assert rc == 0, err
    # Slug "idea" (no ASCII words); a -2 suffix is fine when another
    # "idea" slug was captured in the same second.
    assert "-idea" in out.strip()
    rc, out, err = capture(store, "!!! ??? ...")
    assert rc == 0, err
    assert "-idea" in out.strip()


def test_raw_text_containing_history_marker_is_not_truncated(tmp_path):
    """An idea that itself contains a line reading '## History' must
    round-trip in full — raw_length makes the section unambiguous."""
    store = tmp_path / "ideas"
    text = "my idea\n## History\n- not the real history\nmore text after it"
    rc, out, err = capture(store, text)
    assert rc == 0, err
    idea_id = out.strip()
    content = (store / f"{idea_id}.md").read_text(encoding="utf-8")
    assert cap.raw_text_of(content) == text
    rc, out, err = run(store, "search", "--store", str(store), "more text after it")
    assert rc == 0, err
    assert idea_id in out


def test_crlf_input_is_stored_as_lf_and_round_trips(tmp_path):
    """CRLF input is normalised to LF on capture, so raw_length stays
    exact and the round-trip is verbatim."""
    store = tmp_path / "ideas"
    text = "first line\r\nsecond line\r\n"
    rc, out, err = capture(store, text)
    assert rc == 0, err
    idea_id = out.strip()
    content = (store / f"{idea_id}.md").read_text(encoding="utf-8")
    assert cap.raw_text_of(content) == "first line\nsecond line\n"
    assert "\r" not in content


def test_symlink_in_list_and_search_is_reported_not_read(tmp_path):
    """A symlink inside the store pointing outside must not be read
    by list/search — it is reported as malformed instead."""
    store = tmp_path / "ideas"
    store.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text(
        "---\nid: 20261106-120000-outside\ncreated: 2026-11-06T12:00:00+00:00\n"
        "source: test\nstatus: raw\n---\n\n# Raw idea (verbatim)\n\nsecret outside\n\n"
        "## History\n\n- 2026-11-06T12:00:00+00:00: captured (status raw)\n",
        encoding="utf-8",
    )
    link = store / "20261106-120000-outside.md"
    try:
        os.symlink(outside, link)
    except OSError:
        return  # Symlinks not supported here; skip.
    rc, out, err = run(store, "list", "--store", str(store))
    assert rc == 2, err  # partial: a file was skipped (third review round)
    assert "secret outside" not in out
    assert "escapes the store" in err
    rc, out, err = run(store, "search", "--store", str(store), "secret")
    assert rc == 2  # partial, not "not found" (third review round)
    assert "20261106-120000-outside" not in out


def test_frontmatter_id_must_match_filename(tmp_path):
    """A file whose frontmatter id differs from its filename is
    malformed and reported, not silently listed under the wrong id."""
    store = tmp_path / "ideas"
    store.mkdir()
    (store / "20261106-120000-aaa.md").write_text(
        "---\nid: 20261106-120000-bbb\ncreated: 2026-11-06T12:00:00+00:00\n"
        "source: test\nstatus: raw\n---\n\n# Raw idea (verbatim)\n\nmismatched\n\n"
        "## History\n\n- 2026-11-06T12:00:00+00:00: captured (status raw)\n",
        encoding="utf-8",
    )
    rc, out, err = run(store, "list", "--store", str(store))
    assert rc == 2, err  # partial: a file was skipped (third review round)
    assert "20261106-120000-aaa" not in out
    assert "does not match the filename" in err


def test_concurrent_promotes_do_not_lose_history(tmp_path):
    """Two status changes at once must not lose a History entry: the
    lock serialises the read-modify-write, so the second process reads
    the updated status. The two transitions may conflict (a dropped
    idea cannot be promoted), so the assertion is consistency, not
    that both succeed: the number of History entries must equal the
    number of successful operations. Without the lock, both could
    read "raw", both succeed, and the second write would silently
    drop the first one's entry."""
    import threading

    store = tmp_path / "ideas"
    rc, out, err = capture(store, "concurrent idea")
    assert rc == 0, err
    idea_id = out.strip()
    results = []

    def promote():
        r = run(store, "promote", "--store", str(store), idea_id, "calibrated")
        results.append(r[0])

    def drop():
        r = run(store, "drop", "--store", str(store), idea_id, "--reason", "second")
        results.append(r[0])

    t1 = threading.Thread(target=promote)
    t2 = threading.Thread(target=drop)
    t1.start()
    t2.start()
    t1.join(timeout=30)
    t2.join(timeout=30)
    assert len(results) == 2
    content = (store / f"{idea_id}.md").read_text(encoding="utf-8")
    # Every successful transition left its History entry behind (the
    # capture entry has no "->"; each transition adds exactly one).
    assert content.count("->") == results.count(0), content
    # The final status matches the last successful transition.
    if results.count(0) == 2:
        assert "status: dropped" in content
    # No lock file left behind.
    assert list(store.glob(".*.lock")) == []


# --- Third review round: regression tests (2026-11-06) ---


def test_list_with_malformed_file_is_partial_not_success(tmp_path):
    """list with a malformed file exits 2 (partial), not 0: a machine
    caller must not treat an incomplete list as success. The good
    ideas still list, and stderr says partial."""
    store = tmp_path / "ideas"
    rc, out, err = capture(store, "a good idea")
    assert rc == 0, err
    good_id = out.strip()
    (store / "broken.md").write_text("no frontmatter here\n", encoding="utf-8")
    rc, out, err = run(store, "list", "--store", str(store))
    assert rc == 2, err
    assert good_id in out
    assert "broken.md" in err
    assert "partial" in err


def test_list_clean_store_exits_zero(tmp_path):
    """The partial exit code must not leak into a clean list."""
    store = tmp_path / "ideas"
    rc, out, err = capture(store, "a good idea")
    assert rc == 0, err
    rc, out, err = run(store, "list", "--store", str(store))
    assert rc == 0, err
    assert "partial" not in err


def test_search_with_malformed_file_is_partial(tmp_path):
    """search with a malformed file exits 2 (partial): the result
    cannot be trusted — a match may live in the skipped file."""
    store = tmp_path / "ideas"
    rc, out, err = capture(store, "a unique zebra idea")
    assert rc == 0, err
    (store / "broken.md").write_text("no frontmatter here\n", encoding="utf-8")
    rc, out, err = run(store, "search", "--store", str(store), "zebra")
    assert rc == 2, err
    assert "partial" in err


def _handwritten_idea(store, idea_id, frontmatter_lines, raw_text):
    """An idea file written by hand (not by capture), so the fixture
    can carry a defect capture() would never produce."""
    store.mkdir(parents=True, exist_ok=True)
    body = (
        "---\n"
        f"id: {idea_id}\n"
        "created: 2026-11-06T12:00:00+00:00\n"
        "source: test\n"
        + "".join(f"{line}\n" for line in frontmatter_lines)
        + "---\n\n# Raw idea (verbatim)\n\n"
        + raw_text
        + "\n\n## History\n\n- 2026-11-06T12:00:00+00:00: captured (status raw)\n"
    )
    path = store / f"{idea_id}.md"
    path.write_text(body, encoding="utf-8")
    return path


def test_set_status_with_missing_status_is_an_error(tmp_path):
    """A file with no status in the frontmatter must fail cleanly —
    the old code silently assumed "raw", changed nothing, yet
    appended a History entry claiming the transition happened and
    returned 0."""
    store = tmp_path / "ideas"
    path = _handwritten_idea(store, "20261106-120000-no-status", [], "an idea with no status field")
    before = path.read_text(encoding="utf-8")
    rc, out, err = run(
        store, "promote", "--store", str(store), "20261106-120000-no-status", "calibrated"
    )
    assert rc == 1, out
    assert "error" in err
    assert "status" in err
    assert path.read_text(encoding="utf-8") == before
    assert "-> calibrated" not in path.read_text(encoding="utf-8")


def test_set_status_does_not_rewrite_a_status_line_in_the_raw_text(tmp_path):
    """The status rewrite ran over the WHOLE file, so when the
    frontmatter had no status line it rewrote a `status: ...` line
    inside the raw idea text instead — corrupting the verbatim text
    while claiming success. The file must be left untouched."""
    store = tmp_path / "ideas"
    path = _handwritten_idea(
        store,
        "20261106-120000-status-in-text",
        [],
        "an idea whose text says\nstatus: raw\non its own line",
    )
    before = path.read_text(encoding="utf-8")
    rc, out, err = run(
        store, "promote", "--store", str(store), "20261106-120000-status-in-text", "calibrated"
    )
    assert rc == 1, out
    assert "error" in err
    assert path.read_text(encoding="utf-8") == before
    assert "status: calibrated" not in path.read_text(encoding="utf-8")


def test_set_status_rewrites_only_the_frontmatter(tmp_path):
    """Guard: with a status line in the frontmatter AND one in the
    raw text, only the frontmatter line changes — the verbatim raw
    text is never edited."""
    store = tmp_path / "ideas"
    path = _handwritten_idea(
        store,
        "20261106-120000-status-both",
        ["status: raw"],
        "an idea whose text says\nstatus: raw\non its own line",
    )
    rc, out, err = run(
        store, "promote", "--store", str(store), "20261106-120000-status-both", "calibrated"
    )
    assert rc == 0, err
    content = path.read_text(encoding="utf-8")
    assert content.startswith(
        "---\nid: 20261106-120000-status-both\n"
        "created: 2026-11-06T12:00:00+00:00\n"
        "source: test\nstatus: calibrated\n---\n"
    )
    assert "an idea whose text says\nstatus: raw\non its own line" in content
