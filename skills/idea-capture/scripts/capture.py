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

Usage:
    capture.py capture --store <dir> --text <text> [--source <who>]
    capture.py list --store <dir> [--status <status>]
    capture.py search --store <dir> <query>
    capture.py show --store <dir> <id>
    capture.py promote --store <dir> <id> calibrated|scoped [--note <note>]
    capture.py drop --store <dir> <id> --reason <reason>

Exit 0 on success, 1 on error (empty text, unknown id, illegal
transition, missing reason). Prints the idea id on capture, and
human-readable lines otherwise.
"""
import argparse
import re
import sys
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


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def slugify(text: str) -> str:
    words = re.findall(r"[A-Za-z0-9\u0600-\u06FF]+", text.lower())
    slug = "-".join(words[:5])[:40].strip("-")
    return slug or "idea"


def idea_path(store: Path, idea_id: str) -> Path:
    return store / f"{idea_id}.md"


def read_frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError(f"{path.name}: missing frontmatter")
    end = text.index("\n---\n", 4)
    fields = {}
    for line in text[4:end].splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            fields[key.strip()] = value.strip()
    return fields


def cmd_capture(args) -> int:
    text = args.text.strip()
    if not text:
        print("error: cannot capture an empty idea", file=sys.stderr)
        return 1
    store = Path(args.store)
    store.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    base = f"{stamp}-{slugify(text)}"
    idea_id = base
    n = 2
    while idea_path(store, idea_id).exists():
        idea_id = f"{base}-{n}"
        n += 1
    created = now_iso()
    body = (
        f"---\n"
        f"id: {idea_id}\n"
        f"created: {created}\n"
        f"source: {args.source}\n"
        f"status: raw\n"
        f"---\n\n"
        f"# Raw idea (verbatim)\n\n"
        f"{text}\n\n"
        f"## History\n\n"
        f"- {created}: captured (status raw)\n"
    )
    idea_path(store, idea_id).write_text(body, encoding="utf-8")
    print(idea_id)
    return 0


def _all_ideas(store: Path) -> list[tuple[str, dict, Path]]:
    if not store.is_dir():
        return []
    ideas = []
    for path in sorted(store.glob("*.md")):
        try:
            fields = read_frontmatter(path)
        except ValueError:
            continue
        ideas.append((fields.get("id", path.stem), fields, path))
    return ideas


def cmd_list(args) -> int:
    store = Path(args.store)
    for idea_id, fields, path in _all_ideas(store):
        if args.status and fields.get("status") != args.status:
            continue
        first_line = ""
        text = path.read_text(encoding="utf-8")
        marker = "# Raw idea (verbatim)\n\n"
        if marker in text:
            first_line = text.split(marker, 1)[1].strip().splitlines()[0]
        print(f"{idea_id} [{fields.get('status', '?')}] {fields.get('created', '?')} — {first_line}")
    return 0


def cmd_search(args) -> int:
    store = Path(args.store)
    query = args.query.lower()
    found = False
    for idea_id, _fields, path in _all_ideas(store):
        if query in path.read_text(encoding="utf-8").lower():
            print(idea_id)
            found = True
    return 0 if found else 1


def cmd_show(args) -> int:
    path = idea_path(Path(args.store), args.id)
    if not path.is_file():
        print(f"error: no idea with id {args.id}", file=sys.stderr)
        return 1
    sys.stdout.write(path.read_text(encoding="utf-8"))
    return 0


def _set_status(store: Path, idea_id: str, new_status: str, note: str) -> int:
    path = idea_path(store, idea_id)
    if not path.is_file():
        print(f"error: no idea with id {idea_id}", file=sys.stderr)
        return 1
    fields = read_frontmatter(path)
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
    path.write_text(text, encoding="utf-8")
    print(f"{idea_id}: {current} -> {new_status}")
    return 0


def cmd_promote(args) -> int:
    return _set_status(Path(args.store), args.id, args.new_status, args.note or "")


def cmd_drop(args) -> int:
    if not args.reason.strip():
        print("error: dropping an idea needs a reason", file=sys.stderr)
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
