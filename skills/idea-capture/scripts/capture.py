#!/usr/bin/env python3
"""The idea-capture store: one Markdown file per raw idea, append-only.

Every idea is a file in <store>/ named YYYYMMDD-HHMMSS-slug.md:

    ---
    id: 20261106-003000-weekly-budget-warning
    created: 2026-11-06T00:30:00+03:30
    source: Niloufar
    status: raw
    raw_length: 24
    ---

    # Raw idea (verbatim)

    <the idea, exactly as spoken, never edited>

    ## History

    - 2026-11-06T00:30:00+03:30: captured (status raw)

The slug in the id is ASCII only (a-z, 0-9, hyphen). The raw text may
be in any language — Persian, Arabic, emoji — but the slug is only an
identifier, so it is built from the ASCII words of the text (or "idea"
when there are none). This keeps filenames portable across filesystems
(no NFC/NFD normalisation surprises on macOS/Windows) while the raw
text itself is preserved verbatim.

`raw_length` is the length, in characters, of the raw idea text as
stored (line endings normalised to LF on capture). It makes the raw
section unambiguous: an idea that itself contains a line reading
"## History" must not be mistaken for the History section. When the
field is present, the raw text is read by exact length; when it is
absent (files written before this field existed), the reader falls
back to the marker search.

Statuses: raw -> calibrated -> scoped, or any -> dropped. A dropped idea
is never deleted; dropping only changes the status and records the
reason. The raw text is never edited after capture.

Safety rules (these are the point of this tool — an idea must never be
lost silently, and a file must never be written to a path the caller
did not intend):

- Idea ids are strictly validated: only the generated shape
  YYYYMMDD-HHMMSS-slug (with an optional -N suffix) is accepted, and
  the resolved path must stay inside the store. An id containing a
  separator, "..", or any other character is rejected.
- A capture creates the file exclusively (open with mode "x"), so two
  concurrent captures cannot overwrite each other.
- A status change takes a lock file (created with O_EXCL) for the
  whole read-modify-write, then writes to a temporary file in the same
  directory and atomically replaces the idea file. The lock prevents a
  lost update when two processes change the same idea at once; the
  atomic replace prevents a half-written file.
- Listing and searching resolve every file and require it to stay
  inside the store, so a symlink planted in the store cannot make the
  tool read a file outside it. A file whose frontmatter id does not
  match its filename is reported as malformed.
- The raw text is stored exactly as given (only the emptiness check
  strips whitespace, and CRLF line endings are normalised to LF so the
  stored length is unambiguous). The source, the note and the reason
  must not contain a newline — a newline in the source would inject a
  new frontmatter field, and a newline in a note or reason would break
  the single-line History entry.
- A file that cannot be parsed is reported to stderr, never silently
  skipped. Line endings are normalized (CRLF is accepted).
- Search matches only the raw idea text, not the frontmatter or the
  History (so searching for "raw" or "dropped" does not return
  everything).

Usage:
    capture.py capture --store <dir> --text <text> [--source <who>]
    capture.py list --store <dir> [--status <status>]
    capture.py search --store <dir> <query>
    capture.py show --store <dir> <id>
    capture.py promote --store <dir> <id> calibrated|scoped [--note <note>]
    capture.py drop --store <dir> <id> --reason <reason>

Exit 0 on success, 1 on error (empty text, unknown id, illegal
transition, missing reason, invalid id, malformed file, a status
change on a file with no status recorded). Exit 2 when a list or a
search skipped malformed files: the result is partial, and a machine
caller must not treat it as complete. Prints the
idea id on capture, and human-readable lines otherwise.

Requires Python 3.11+ (builtin generics, Path.is_relative_to).
"""

import argparse
import io
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

STATUSES = ("raw", "calibrated", "scoped", "dropped")
# raw -> calibrated -> scoped; anything -> dropped (with a reason).
ALLOWED = {
    "raw": ("calibrated", "dropped"),
    "calibrated": ("scoped", "dropped"),
    "scoped": ("dropped",),
    "dropped": (),
}
# The only id shape this tool ever generates or accepts.
ID_RE = re.compile(r"^[0-9]{8}-[0-9]{6}-[a-z0-9][a-z0-9-]*$")
RAW_MARKER = "# Raw idea (verbatim)\n\n"
HISTORY_MARKER = "\n## History\n"


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def slugify(text: str) -> str:
    """An ASCII-only slug for the id. The raw text may be any language,
    but the slug is only an identifier: it is built from the ASCII
    words of the text, so a Persian-only idea gets the slug "idea"
    (and a timestamp suffix if two collide in the same second)."""
    words = re.findall(r"[a-z0-9]+", text.lower())
    slug = "-".join(words[:5])[:40].strip("-")
    return slug or "idea"


def validate_id(idea_id: str) -> None:
    """Reject any id that is not the generated shape. Raises ValueError."""
    if not ID_RE.match(idea_id):
        raise ValueError(f"invalid idea id {idea_id!r}: expected YYYYMMDD-HHMMSS-slug")


def idea_path(store: Path, idea_id: str) -> Path:
    """The idea file, confined to the store. Raises ValueError on an
    invalid id or a path that escapes the store (including through a
    symlink)."""
    validate_id(idea_id)
    store_resolved = store.resolve()
    path = (store_resolved / f"{idea_id}.md").resolve()
    if not path.is_relative_to(store_resolved):
        raise ValueError(f"idea id {idea_id!r} escapes the store")
    return path


def read_frontmatter(path: Path) -> dict:
    # Normalize line endings so a CRLF file parses the same as an LF one.
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    if not text.startswith("---\n"):
        raise ValueError(f"{path.name}: missing frontmatter")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise ValueError(f"{path.name}: frontmatter is not closed")
    fields = {}
    for line in text[4:end].splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            fields[key.strip()] = value.strip()
    return fields


def raw_text_of(text: str) -> str:
    """The raw idea text only — between the verbatim marker and History.
    Returns "" when the markers are absent (a malformed file).

    When the frontmatter carries raw_length, exactly that many
    characters after the marker are returned, so an idea that itself
    contains a line reading "## History" is not truncated. Without
    raw_length (files written before that field existed), the text runs
    to the first History marker."""
    text = text.replace("\r\n", "\n")
    start = text.find(RAW_MARKER)
    if start < 0:
        return ""
    start += len(RAW_MARKER)
    length = None
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end >= 0:
            for line in text[4:end].splitlines():
                if ":" in line:
                    key, value = line.split(":", 1)
                    if key.strip() == "raw_length":
                        try:
                            length = int(value.strip())
                        except ValueError:
                            length = None
                        break
    if length is not None and length >= 0:
        return text[start : start + length]
    end = text.find(HISTORY_MARKER, start)
    if end < 0:
        return text[start:]
    return text[start:end]


def _atomic_write(path: Path, text: str) -> None:
    """Write via a temporary file in the same directory, then atomically
    replace the target. An interruption leaves the old file intact."""
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _check_single_line(value: str, field: str) -> bool:
    """A frontmatter value or a History entry must be one line. Returns
    True when the value is clean, False (after printing the error) when
    it contains a newline."""
    if "\r" in value or "\n" in value:
        print(
            f"error: {field} must be a single line (no newline)",
            file=sys.stderr,
        )
        return False
    return True


def cmd_capture(args) -> int:
    if not args.text.strip():
        print("error: cannot capture an empty idea", file=sys.stderr)
        return 1
    if not _check_single_line(args.source, "--source"):
        return 1
    store = Path(args.store)
    store.mkdir(parents=True, exist_ok=True)
    # One timestamp for both the id and the created field, so they can
    # never disagree across a second boundary.
    now = datetime.now().astimezone()
    stamp = now.strftime("%Y%m%d-%H%M%S")
    created = now.isoformat(timespec="seconds")
    # The slug is ASCII only, so a Persian (or emoji-only) idea gets a
    # valid id; the raw text itself is preserved verbatim. Line endings
    # are normalised to LF so raw_length is unambiguous.
    text = args.text.replace("\r\n", "\n")
    base = f"{stamp}-{slugify(text)}"
    # Store the idea exactly as given — only the emptiness check strips.
    n = 1
    while True:
        idea_id = base if n == 1 else f"{base}-{n}"
        try:
            path = idea_path(store, idea_id)
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        body = (
            f"---\n"
            f"id: {idea_id}\n"
            f"created: {created}\n"
            f"source: {args.source}\n"
            f"status: raw\n"
            f"raw_length: {len(text)}\n"
            f"---\n\n"
            f"# Raw idea (verbatim)\n\n"
            f"{text}\n\n"
            f"## History\n\n"
            f"- {created}: captured (status raw)\n"
        )
        try:
            # Exclusive create: two concurrent captures with the same id
            # cannot overwrite each other; the loser retries with a suffix.
            with path.open("x", encoding="utf-8") as f:
                f.write(body)
            break
        except FileExistsError:
            n += 1
    print(idea_id)
    return 0


def _all_ideas(store: Path) -> tuple[list[tuple[str, dict, Path]], list[str]]:
    """All parseable ideas, plus a list of malformed files (reported, not
    silently skipped). A file is only read when its resolved path stays
    inside the store, so a symlink planted in the store cannot make the
    tool read a file outside it; a file whose frontmatter id does not
    match its filename is malformed."""
    if not store.is_dir():
        return [], []
    store_resolved = store.resolve()
    ideas: list[tuple[str, dict, Path]] = []
    malformed: list[str] = []
    for path in sorted(store.glob("*.md")):
        try:
            resolved = path.resolve()
        except OSError as e:
            malformed.append(f"{path.name}: cannot resolve ({e})")
            continue
        if not resolved.is_relative_to(store_resolved):
            malformed.append(f"{path.name}: escapes the store (symlink)")
            continue
        try:
            fields = read_frontmatter(path)
        except (ValueError, OSError) as e:
            malformed.append(f"{path.name}: {e}")
            continue
        if fields.get("id", path.stem) != path.stem:
            malformed.append(
                f"{path.name}: frontmatter id {fields.get('id')!r} does not match the filename"
            )
            continue
        ideas.append((fields.get("id", path.stem), fields, path))
    return ideas, malformed


def _report_malformed(malformed: list[str]) -> bool:
    """Warn about each malformed file on stderr. Returns True when
    any file was skipped, so the caller can say the result is
    partial — a list or search that skipped files must not exit 0
    (or, for search, 1 for "not found"), or a machine caller treats
    an incomplete result as complete."""
    for m in malformed:
        print(f"warning: skipping malformed idea file ({m})", file=sys.stderr)
    if malformed:
        print(
            f"partial: {len(malformed)} malformed file(s) skipped — the result is incomplete",
            file=sys.stderr,
        )
    return bool(malformed)


def cmd_list(args) -> int:
    store = Path(args.store)
    ideas, malformed = _all_ideas(store)
    partial = _report_malformed(malformed)
    for idea_id, fields, path in ideas:
        if args.status and fields.get("status") != args.status:
            continue
        first_line = ""
        text = path.read_text(encoding="utf-8")
        raw = raw_text_of(text)
        if raw.strip():
            first_line = raw.strip().splitlines()[0]
        print(
            f"{idea_id} [{fields.get('status', '?')}] {fields.get('created', '?')} — {first_line}"
        )
    # Exit 2 when the list is partial: a machine caller must not
    # treat an incomplete list as success.
    return 2 if partial else 0


def cmd_search(args) -> int:
    store = Path(args.store)
    query = args.query.lower()
    ideas, malformed = _all_ideas(store)
    partial = _report_malformed(malformed)
    found = False
    for idea_id, _fields, path in ideas:
        # Search the raw idea text only — not the frontmatter or History.
        if query in raw_text_of(path.read_text(encoding="utf-8")).lower():
            print(idea_id)
            found = True
    # Exit 2 when the search is partial: a match may live in a
    # skipped file, and "not found" cannot be trusted either.
    if partial:
        return 2
    return 0 if found else 1


def cmd_show(args) -> int:
    try:
        path = idea_path(Path(args.store), args.id)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    if not path.is_file():
        print(f"error: no idea with id {args.id}", file=sys.stderr)
        return 1
    sys.stdout.write(path.read_text(encoding="utf-8"))
    return 0


def _read_lock_pid(lock_path):
    """The PID recorded in a lock file, or None when it cannot be read
    (empty file, torn write, non-numeric content, or the file is gone).
    A missing PID means the lock cannot be proven stale, so the caller
    must treat it as held."""
    try:
        text = lock_path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return None
    try:
        pid = int(text)
    except ValueError:
        return None
    return pid if pid > 0 else None


def _pid_is_alive_windows(pid):
    """Windows probe: OpenProcess + GetExitCodeProcess. On Windows
    os.kill(pid, 0) terminates the process instead of probing it,
    so os.kill must never run here. A process that cannot be opened
    because it does not exist (ERROR_INVALID_PARAMETER, 87) is dead;
    any other failure to open it, or to read its exit code, is
    treated as alive (fail-safe — the lock is held, never stolen)."""
    import ctypes

    kernel32 = ctypes.windll.kernel32
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return kernel32.GetLastError() != 87
    try:
        exit_code = ctypes.c_ulong(0)
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return True  # unreadable exit code — fail-safe: alive.
        return exit_code.value == STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def _pid_is_alive(pid):
    """True when the process exists. A PermissionError means the
    process exists but belongs to another user — alive, so the lock
    is held. (A reused PID can make a stale lock look held; the cost
    is a wait and an error, never a stolen lock.) On Windows the
    probe goes through _pid_is_alive_windows: os.kill(pid, 0) would
    terminate the process instead of probing it."""
    if sys.platform == "win32":
        return _pid_is_alive_windows(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def _try_lock(fd) -> bool:
    """Take the OS advisory lock on an open fd, non-blocking: True
    when acquired, False when another process holds it. POSIX uses
    fcntl.flock; Windows uses msvcrt.locking on one byte at offset
    0. Raises RuntimeError when no locking primitive exists on this
    platform — the caller must fail closed, never proceed unlocked."""
    if sys.platform == "win32":
        import msvcrt

        try:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True
    try:
        import fcntl
    except ImportError:
        raise RuntimeError("no advisory file-locking primitive on this platform")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def _unlock(fd) -> None:
    """Release the OS advisory lock on an open fd. Closing the fd
    releases it too; this is belt-and-braces, and it never fails
    the caller."""
    try:
        if sys.platform == "win32":
            import msvcrt

            try:
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
        else:
            import fcntl

            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
    except ImportError:
        pass


def _acquire_lock(path: Path, timeout_s: float = 2.0):
    """An OS advisory lock for one idea, on a DURABLE lock file
    that is never unlinked or renamed. The holder's PID is written
    into the file after acquiring, for the "blocked by pid N"
    message only — it is not the lock. Returns (fd, lock_path,
    holder_pid): fd is None when the lock is still held after the
    timeout, and holder_pid is then the recorded PID when it could
    be read, else None. The caller must release it (unlock + close)
    in a finally block.

    Semantics (round 6, 3-P2-7 — this replaces the O_EXCL +
    unlink-stale design, whose docstring admitted the race): the
    lock is the flock/msvcrt lock on the file, not the file's
    existence, so two processes can never both hold it, and there
    is no recovery step left to race. When the holder dies the OS
    releases the lock — even on SIGKILL, which no userspace cleanup
    can survive — and the file stays behind with the dead holder's
    PID; the next acquirer notes "stale lock ... recovered" and
    overwrites the PID. A lock file with no flock holder is not
    held, whatever PID it records (or fails to record): a planted
    file is not a holder.

    The holder's PID is written starting at offset 1, not 0: byte
    0 is the locked region (msvcrt.locking locks one byte at offset
    0), and on Windows a read of that byte fails while the holder
    holds it — so a contender waiting on the lock could never read
    the PID for the "blocked by pid N" message if it lived at
    offset 0. _read_lock_pid strips, so both layouts parse.

    Crash behaviour: a holder killed mid-change leaves the file
    (with a dead PID) and releases the lock; the next acquirer
    proceeds, so no change is ever blocked forever by a dead
    holder. The file itself is never removed, so nothing can unlink
    another process's lock.

    Portability: flock is POSIX, msvcrt.locking is Windows. The
    Windows path is untestable on this host (no Windows machine in
    this VM) — it is the standard one-byte region lock and fails
    closed (OSError -> held) like the POSIX path. Network
    filesystems: flock/msvcrt semantics depend on the filesystem
    and (for NFS) on lockd; on a filesystem without advisory
    locking, flock may succeed vacuously and two holders could
    interleave — the store is a local directory by design, and a
    network store is unsupported, not silently safe.
    """
    import time

    lock_path = path.parent / f".{path.name}.lock"
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
    except OSError:
        return None, lock_path, None
    deadline = time.monotonic() + timeout_s
    holder_pid = None
    while True:
        if _try_lock(fd):
            break
        pid = _read_lock_pid(lock_path)
        if pid is not None:
            holder_pid = pid
        if time.monotonic() >= deadline:
            try:
                os.close(fd)
            except OSError:
                pass
            return None, lock_path, holder_pid
        time.sleep(0.1)
    # We hold the lock. The recorded PID may name a dead process
    # (the previous holder died; the OS released the lock and the
    # file stayed): note it, then overwrite it with ours.
    old_pid = _read_lock_pid(lock_path)
    if old_pid is not None and not _pid_is_alive(old_pid):
        print(
            f"note: stale lock {lock_path.name} recovered "
            f"(holder process {old_pid} no longer exists)",
            file=sys.stderr,
        )
    try:
        os.ftruncate(fd, 0)
        os.lseek(fd, 0, os.SEEK_SET)
        # Byte 0 is the locked region (see the docstring): the PID
        # starts at offset 1, so a contender can read it without
        # touching the locked byte.
        os.write(fd, f" {os.getpid()}\n".encode("utf-8"))
        try:
            os.fsync(fd)
        except OSError:
            pass
    except OSError:
        _release_lock(fd, lock_path)
        return None, lock_path, None
    return fd, lock_path, None


def _release_lock(fd, lock_path) -> None:
    """Release the advisory lock and close the fd. The lock file is
    NEVER unlinked: it is durable, and unlinking it is what made
    the old stale-lock recovery racy (two processes could unlink
    each other's just-created lock)."""
    _unlock(fd)
    try:
        os.close(fd)
    except OSError:
        pass


def _set_status(store: Path, idea_id: str, new_status: str, note: str) -> int:
    try:
        path = idea_path(store, idea_id)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    if not path.is_file():
        print(f"error: no idea with id {idea_id}", file=sys.stderr)
        return 1
    # Lock the whole read-modify-write: without it, two concurrent
    # status changes read the same version and the second one's write
    # silently drops the first one's History entry (a lost update).
    # The atomic replace alone only prevents a half-written file.
    # A RuntimeError means no locking primitive exists on this
    # platform: fail closed with a clean error, never proceed
    # unlocked (round 6, 3-P2-7).
    try:
        fd, lock_path, holder_pid = _acquire_lock(path)
    except RuntimeError as e:
        print(f"error: cannot lock {idea_id}: {e}", file=sys.stderr)
        return 1
    if fd is None:
        if holder_pid is not None:
            print(
                f"error: {idea_id} is being changed by another process (pid {holder_pid})",
                file=sys.stderr,
            )
        else:
            print(
                f"error: {idea_id} is being changed by another process",
                file=sys.stderr,
            )
        return 1
    try:
        return _set_status_locked(path, idea_id, new_status, note)
    finally:
        _release_lock(fd, lock_path)


def _set_status_locked(path: Path, idea_id: str, new_status: str, note: str) -> int:
    try:
        fields = read_frontmatter(path)
    except (ValueError, OSError) as e:
        print(f"error: cannot read {path.name}: {e}", file=sys.stderr)
        return 1
    # A missing status is an error, not "raw": silently assuming a
    # status invents a transition from a state the file never recorded.
    if "status" not in fields:
        print(
            f"error: {path.name}: no status recorded in the frontmatter",
            file=sys.stderr,
        )
        return 1
    current = fields["status"]
    if new_status not in ALLOWED.get(current, ()):
        print(
            f"error: cannot move {idea_id} from {current} to {new_status}",
            file=sys.stderr,
        )
        return 1
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    # Rewrite the status line ONLY inside the frontmatter. The old
    # code ran re.sub over the whole file, so when the frontmatter had
    # no status line it rewrote a `status: ...` line inside the raw
    # idea text instead — corrupting the verbatim text — and when no
    # status line existed anywhere it changed nothing yet appended a
    # History entry claiming the transition happened.
    if not text.startswith("---\n"):
        print(f"error: {path.name}: missing frontmatter", file=sys.stderr)
        return 1
    end = text.find("\n---\n", 4)
    if end < 0:
        print(f"error: {path.name}: frontmatter is not closed", file=sys.stderr)
        return 1
    frontmatter = text[4:end]
    new_frontmatter, n = re.subn(
        r"^status:.*$", f"status: {new_status}", frontmatter, flags=re.MULTILINE
    )
    if n == 0:
        print(
            f"error: {path.name}: no status line in the frontmatter",
            file=sys.stderr,
        )
        return 1
    text = text[:4] + new_frontmatter + text[end:]
    entry = f"- {now_iso()}: {current} -> {new_status}"
    if note:
        entry += f" ({note})"
    text = text.rstrip("\n") + f"\n{entry}\n"
    _atomic_write(path, text)
    print(f"{idea_id}: {current} -> {new_status}")
    return 0


def cmd_promote(args) -> int:
    if args.note and not _check_single_line(args.note, "--note"):
        return 1
    return _set_status(Path(args.store), args.id, args.new_status, args.note or "")


def cmd_drop(args) -> int:
    if not args.reason.strip():
        print("error: dropping an idea needs a reason", file=sys.stderr)
        return 1
    if not _check_single_line(args.reason, "--reason"):
        return 1
    return _set_status(Path(args.store), args.id, "dropped", f"reason: {args.reason}")


def _ensure_utf8_output() -> None:
    """Stdout and stderr emit UTF-8 even when the console encoding
    is not: on Windows stdout defaults to cp1252, which cannot
    encode Persian text, and show/list print raw idea text (any
    language). Best-effort — a stream that is not a TextIOWrapper
    or cannot be reconfigured keeps its encoding, and a later
    write fails exactly as it would have without this call."""
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            try:
                stream.reconfigure(encoding="utf-8")
            except ValueError:
                pass


def main() -> int:
    _ensure_utf8_output()
    parser = argparse.ArgumentParser(description="The idea-capture store")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("capture", help="capture a raw idea")
    p.add_argument("--store", required=True)
    p.add_argument("--text", required=True)
    p.add_argument("--source", default="user")
    p.set_defaults(func=cmd_capture)

    p = sub.add_parser("list", help="list ideas")
    p.add_argument("--store", required=True)
    p.add_argument("--status", choices=STATUSES)
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("search", help="search ideas by keyword")
    p.add_argument("--store", required=True)
    p.add_argument("query")
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("show", help="show one idea")
    p.add_argument("--store", required=True)
    p.add_argument("id")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("promote", help="move an idea forward")
    p.add_argument("--store", required=True)
    p.add_argument("id")
    p.add_argument("new_status", choices=("calibrated", "scoped"))
    p.add_argument("--note")
    p.set_defaults(func=cmd_promote)

    p = sub.add_parser("drop", help="drop an idea (never deletes it)")
    p.add_argument("--store", required=True)
    p.add_argument("id")
    p.add_argument("--reason", required=True)
    p.set_defaults(func=cmd_drop)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
