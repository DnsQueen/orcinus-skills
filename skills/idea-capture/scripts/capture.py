#!/usr/bin/env python3
"""The idea-capture store: one Markdown file per raw idea, append-only.

Every idea is a file in <store>/ named YYYYMMDD-HHMMSS-slug.md:

    ---
    id: 20261106-003000-weekly-budget-warning
    created: 2026-11-06T00:30:00+03:30
    source: Niloufar
    status: raw
    ---

    # Raw idea (verbatim)

    <the idea, exactly as spoken, never edited>

    ## History

    - 2026-11-06T00:30:00+03:30: captured (status raw)

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
- A status change writes to a temporary file in the same directory and
  atomically replaces the idea file, so an interruption cannot leave a
  half-written file or lose History.
- The raw text is stored exactly as given (only the emptiness check
  strips whitespace). The source, the note and the reason must not
  contain a newline — a newline in the source would inject a new
  frontmatter field, and a newline in a note or reason would break the
  single-line History entry.
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
transition, missing reason, invalid id, malformed file). Prints the
idea id on capture, and human-readable lines otherwise.

Requires Python 3.9+ (builtin generics, Path.is_relative_to).
"""
import argparse
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
    words = re.findall(r"[A-Za-z0-9\u0600-\u06FF]+", text.lower())
    slug = "-".join(words[:5])[:40].strip("-")
    return slug or "idea"


def validate_id(idea_id: str) -> None:
    """Reject any id that is not the generated shape. Raises ValueError."""
    if not ID_RE.match(idea_id):
        raise ValueError(
            f"invalid idea id {idea_id!r}: expected YYYYMMDD-HHMMSS-slug"
        )


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
    Returns "" when the markers are absent (a malformed file)."""
    text = text.replace("\r\n", "\n")
    start = text.find(RAW_MARKER)
    if start < 0:
        return ""
    start += len(RAW_MARKER)
    end = text.find(HISTORY_MARKER, start)
    if end < 0:
        return text[start:]
    return text[start:end]


def _atomic_write(path: Path, text: str) -> None:
    """Write via a temporary file in the same directory, then atomically
    replace the target. An interruption leaves the old file intact."""
    fd, tmp_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
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
    base = f"{stamp}-{slugify(args.text)}"
    # Store the idea exactly as given — only the emptiness check strips.
    n = 1
    while True:
        idea_id = base if n == 1 else f"{base}-{n}"
        path = idea_path(store, idea_id)
        body = (
            f"---\n"
            f"id: {idea_id}\n"
            f"created: {created}\n"
            f"source: {args.source}\n"
            f"status: raw\n"
            f"---\n\n"
            f"# Raw idea (verbatim)\n\n"
            f"{args.text}\n\n"
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
    silently skipped)."""
    if not store.is_dir():
        return [], []
    ideas: list[tuple[str, dict, Path]] = []
    malformed: list[str] = []
    for path in sorted(store.glob("*.md")):
        try:
            fields = read_frontmatter(path)
        except (ValueError, OSError) as e:
            malformed.append(f"{path.name}: {e}")
            continue
        ideas.append((fields.get("id", path.stem), fields, path))
    return ideas, malformed


def _report_malformed(malformed: list[str]) -> None:
    for m in malformed:
        print(f"warning: skipping malformed idea file ({m})", file=sys.stderr)


def cmd_list(args) -> int:
    store = Path(args.store)
    ideas, malformed = _all_ideas(store)
    _report_malformed(malformed)
    for idea_id, fields, path in ideas:
        if args.status and fields.get("status") != args.status:
            continue
        first_line = ""
        text = path.read_text(encoding="utf-8")
        raw = raw_text_of(text)
        if raw.strip():
            first_line = raw.strip().splitlines()[0]
        print(f"{idea_id} [{fields.get('status', '?')}] {fields.get('created', '?')} — {first_line}")
    return 0


def cmd_search(args) -> int:
    store = Path(args.store)
    query = args.query.lower()
    ideas, malformed = _all_ideas(store)
    _report_malformed(malformed)
    found = False
    for idea_id, _fields, path in ideas:
        # Search the raw idea text only — not the frontmatter or History.
        if query in raw_text_of(path.read_text(encoding="utf-8")).lower():
            print(idea_id)
            found = True
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


def _set_status(store: Path, idea_id: str, new_status: str, note: str) -> int:
    try:
        path = idea_path(store, idea_id)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    if not path.is_file():
        print(f"error: no idea with id {idea_id}", file=sys.stderr)
        return 1
    try:
        fields = read_frontmatter(path)
    except (ValueError, OSError) as e:
        print(f"error: cannot read {path.name}: {e}", file=sys.stderr)
        return 1
    current = fields.get("status", "raw")
    if new_status not in ALLOWED.get(current, ()):
        print(
            f"error: cannot move {idea_id} from {current} to {new_status}",
            file=sys.stderr,
        )
        return 1
    text = path.read_text(encoding="utf-8")
    text = re.sub(
        r"^status: .*$",
        f"status: {new_status}",
        text,
        count=1,
        flags=re.MULTILINE,
    )
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


def main() -> int:
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
