#!/usr/bin/env python3
# ORCINUS change notice (Apache-2.0 §4(b)): ORCINUS changed this file from upstream anthropics/skills@ca45fc4 — packaging is allowlist-based with a printed plan, symlinks are never followed, common secret files are rejected unless explicitly allowed, files are copied from an open descriptor (O_NOFOLLOW), and the archive is written to a temp path, checked against the plan (names + SHA256), and renamed atomically, with a human confirmation prompt before writing; the `scripts.quick_validate` import falls back to a sibling import so the documented script invocation works without PYTHONPATH; archive names are built from the path's parts with forward slashes on every platform (str(Path) on Windows gives backslashes, which the ZIP namelist never matched, so packaging failed); stdout is set to replace unencodable characters so the emoji output cannot crash a Windows cp1252 console; and the confirmation prompt is only shown when stdin and stdout are both terminals, because on Windows sys.stdin.isatty() is True for the NUL device, so a run with stdin redirected from NUL prompted and then aborted on the immediate EOF although no human was there to answer. The rest is verbatim; see ATTRIBUTION.md.
"""
Skill Packager - Creates a distributable .skill file of a skill folder

Usage:
    python -m scripts.package_skill <path/to/skill-folder> [output-directory]
    python3 scripts/package_skill.py <path/to/skill-folder> [output-directory]

    Run the -m form from the skill-creator directory; the script form
    works from anywhere. The packager prints the file list (the
    packaging manifest) first and, on an interactive terminal, asks
    for confirmation before writing anything.

    python -m scripts.package_skill skills/public/my-skill ./dist
    python -m scripts.package_skill skills/public/my-skill --allow-secret .env

Example:
    python -m scripts.package_skill skills/public/my-skill
    python -m scripts.package_skill skills/public/my-skill ./dist
"""

import argparse
import fnmatch
import hashlib
import os
import shutil
import sys
import tempfile
import time
import zipfile
from pathlib import Path

# `python3 scripts/package_skill.py` puts the scripts/ directory on
# sys.path, so `scripts.quick_validate` is not importable there; the
# -m form does the opposite. Try the package import first, fall back
# to the sibling import — both spellings of the documented
# invocation must work without PYTHONPATH.
try:
    from scripts.quick_validate import validate_skill
except ImportError:  # run as a script: scripts/ is on sys.path
    from quick_validate import validate_skill

# Patterns to exclude when packaging skills.
EXCLUDE_DIRS = {"__pycache__", "node_modules"}
EXCLUDE_GLOBS = {"*.pyc"}
EXCLUDE_FILES = {".DS_Store"}
# Directories excluded only at the skill root (not when nested deeper).
ROOT_EXCLUDE_DIRS = {"evals"}

# A skill is docs, scripts, and data. Only these file types are
# packaged; anything else is left out and reported. The set covers
# every file type currently in any skill of this repo.
ALLOWED_SUFFIXES = {
    ".md", ".py", ".txt", ".json", ".yaml", ".yml",
    ".js", ".mjs", ".ts", ".tsx", ".sh", ".html", ".css",
    ".xml", ".sql",
}
# Files with no suffix that are still allowed (licences, notices).
ALLOWED_NAMES = {"LICENSE", "NOTICE"}

# Common secret files, rejected unless explicitly allowed with
# --allow-secret. A secret scan is supplementary and does not prove
# no secret exists — review the printed file list before confirming.
SECRET_SUFFIXES = {".pem", ".key", ".p12", ".pfx"}
SECRET_NAMES = {".env", ".envrc", "id_rsa", "id_ed25519", "id_ecdsa", "id_dsa"}


def _is_secret_file(name):
    """True for a common secret file: the .env family or a private key."""
    if name in SECRET_NAMES or name.startswith(".env."):
        return True
    return any(name.endswith(suffix) for suffix in SECRET_SUFFIXES)


def _archive_name(skill_name, rel_path):
    """Forward-slash archive name for a file in the skill.

    Built from the path's parts so the separator is '/' on every
    platform: str(Path) on Windows gives backslashes, which the ZIP
    namelist (forward slashes) and the forward-slash allowlist
    checks would never match.
    """
    return "/".join((skill_name, *rel_path.parts))


def should_exclude(archive_name: str) -> bool:
    """Check if a path should be excluded from packaging.

    archive_name is the forward-slash name from _archive_name:
    parts[0] is the skill folder name and parts[1] (if present)
    is the first subdir.
    """
    parts = archive_name.split("/")
    if any(part in EXCLUDE_DIRS for part in parts):
        return True
    if len(parts) > 1 and parts[1] in ROOT_EXCLUDE_DIRS:
        return True
    name = parts[-1]
    if name in EXCLUDE_FILES:
        return True
    return any(fnmatch.fnmatch(name, pat) for pat in EXCLUDE_GLOBS)


def collect_files(skill_path, allow_secrets=()):
    """The packaging plan: (included, skipped).

    included is a list of (file_path, arcname); skipped is a list of
    (arcname, reason). arcname is the forward-slash archive name
    from _archive_name, so it matches the ZIP namelist and the
    forward-slash allowlist checks on every platform. Symlinks are
    never followed — a symlink, a file reached through a symlinked
    directory, and anything that resolves outside the skill is
    skipped. Secret files are skipped unless their path relative
    to the skill is in allow_secrets.
    """
    skill_path = Path(skill_path).resolve()
    allowed_secrets = {Path(s).as_posix() for s in allow_secrets}
    included, skipped = [], []
    for file_path in sorted(skill_path.rglob("*")):
        if not file_path.is_file() and not file_path.is_symlink():
            continue
        rel = file_path.relative_to(skill_path)
        arcname = _archive_name(skill_path.name, rel)
        if file_path.is_symlink():
            skipped.append((arcname, "symlink — never followed"))
            continue
        try:
            resolved = file_path.resolve()
        except OSError:
            skipped.append((arcname, "cannot resolve"))
            continue
        if not resolved.is_relative_to(skill_path):
            skipped.append((arcname, "resolves outside the skill"))
            continue
        if should_exclude(arcname):
            skipped.append((arcname, "excluded (build artifact or evals)"))
            continue
        if _is_secret_file(file_path.name):
            if rel.as_posix() not in allowed_secrets:
                skipped.append((arcname, "secret file — pass --allow-secret to include"))
                continue
            # Explicitly allowed: the named file is included
            # regardless of the allowlist below.
            included.append((file_path, arcname))
            continue
        if file_path.suffix not in ALLOWED_SUFFIXES and file_path.name not in ALLOWED_NAMES:
            skipped.append((arcname, "not on the packaging allowlist"))
            continue
        included.append((file_path, arcname))
    return included, skipped


def print_plan(included, skipped):
    """The packaging manifest, printed before anything is written,
    so a human can review what goes in and what stays out."""
    print(f"  Plan: {len(included)} file(s) to package, {len(skipped)} skipped")
    for file_path, arcname in included:
        print(f"  Added: {arcname} ({file_path.stat().st_size} bytes)")
    for arcname, reason in skipped:
        print(f"  Skipped: {arcname} ({reason})")


def _archive_file(zipf, file_path, arcname):
    """Copy one file into the archive from an open descriptor and
    return the SHA256 of the bytes written. Opening with O_NOFOLLOW
    means a path swapped for a symlink after the plan was made
    cannot be followed; mtime and mode come from fstat on the
    descriptor, so they describe the file actually read."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(file_path, flags)
    src = None
    try:
        st = os.fstat(fd)
        src = os.fdopen(fd, "rb")
        mtime = time.localtime(st.st_mtime)[:6]
        if mtime[0] < 1980:  # ZIP cannot represent earlier timestamps
            mtime = (1980, 1, 1, 0, 0, 0)
        zinfo = zipfile.ZipInfo(str(arcname), date_time=mtime)
        zinfo.external_attr = (st.st_mode & 0xFFFF) << 16
        digest = hashlib.sha256()
        with src, zipf.open(zinfo, "w") as dest:
            while True:
                chunk = src.read(1024 * 64)
                if not chunk:
                    break
                digest.update(chunk)
                dest.write(chunk)
        return digest.hexdigest()
    finally:
        if src is None:
            os.close(fd)


def package_skill(skill_path, output_dir=None, allow_secrets=(), confirm=False):
    """
    Package a skill folder into a .skill file.

    Args:
        skill_path: Path to the skill folder
        output_dir: Optional output directory for the .skill file (defaults to current directory)
        allow_secrets: Relative paths of secret files to include anyway
            (explicit confirmation; anything else secret stays out)
        confirm: Ask for confirmation on stdin before writing
            (the CLI sets this for interactive runs)

    Returns:
        Path to the created .skill file, or None if error
    """
    skill_path = Path(skill_path).resolve()

    # Validate skill folder exists
    if not skill_path.exists():
        print(f"❌ Error: Skill folder not found: {skill_path}")
        return None

    if not skill_path.is_dir():
        print(f"❌ Error: Path is not a directory: {skill_path}")
        return None

    # Validate SKILL.md exists
    skill_md = skill_path / "SKILL.md"
    if not skill_md.exists():
        print(f"❌ Error: SKILL.md not found in {skill_path}")
        return None

    # Run validation before packaging
    print("🔍 Validating skill...")
    valid, message = validate_skill(skill_path)
    if not valid:
        print(f"❌ Validation failed: {message}")
        print("   Please fix the validation errors before packaging.")
        return None
    print(f"✅ {message}\n")

    included, skipped = collect_files(skill_path, allow_secrets)
    print_plan(included, skipped)

    if confirm:
        try:
            answer = input("Package these files? [y/N] ").strip().lower()
        except EOFError:
            answer = ""
        if answer not in ("y", "yes"):
            print("Aborted — nothing was written.")
            return None

    # Determine output location
    skill_name = skill_path.name
    if output_dir:
        output_path = Path(output_dir).resolve()
        output_path.mkdir(parents=True, exist_ok=True)
    else:
        output_path = Path.cwd()

    skill_filename = output_path / f"{skill_name}.skill"

    # Create the .skill file on a temp path and rename atomically,
    # so a failed run never leaves a partial archive behind.
    fd, tmp_name = tempfile.mkstemp(prefix=f".{skill_name}.", suffix=".tmp", dir=output_path)
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        # A distributable file, not a private temp file.
        tmp_path.chmod(0o644)
        digests = {}
        with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            for file_path, arcname in included:
                digests[str(arcname)] = _archive_file(zipf, file_path, arcname)
        # Check the archive against the plan before release: a file
        # added, dropped, renamed, or changed mid-write fails the run.
        with zipfile.ZipFile(tmp_path) as zipf:
            names = zipf.namelist()
            if set(names) != set(digests):
                print("❌ Error: archive contents do not match the packaging plan")
                return None
            for name in names:
                if hashlib.sha256(zipf.read(name)).hexdigest() != digests[name]:
                    print(f"❌ Error: archived contents of {name} changed during packaging")
                    return None
        os.replace(tmp_path, skill_filename)
    except Exception as e:
        print(f"❌ Error creating .skill file: {e}")
        return None
    finally:
        if tmp_path.exists():
            tmp_path.unlink()

    print(f"\n✅ Successfully packaged skill to: {skill_filename}")
    return skill_filename


def _is_interactive():
    """True only when the run is genuinely interactive: stdin AND
    stdout are both terminals. stdin alone is not enough — on Windows
    sys.stdin.isatty() is True for the NUL device, so a run with
    stdin redirected from NUL (subprocess DEVNULL) was treated as
    interactive, prompted, and then aborted on the immediate EOF,
    although no human was there to answer. Requiring stdout too means
    the prompt is only shown when the user can see it (and answer it).
    """
    return sys.stdin.isatty() and sys.stdout.isatty()


def main(argv=None):
    # The CLI prints emoji (📦 ✅ ❌); on a Windows console the
    # stdout encoding is cp1252, where those raise UnicodeEncodeError
    # and kill the run before any packaging happens. Keep the locale
    # encoding but never fail on an unprintable character — it prints
    # as '?' instead. Harmless where stdout is already UTF-8.
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass

    parser = argparse.ArgumentParser(
        description="Package a skill folder into a .skill file. "
        "Only allowlisted files are included; symlinks are never "
        "followed and common secret files are left out unless named "
        "with --allow-secret. The file list is printed first, and "
        "an interactive run asks for confirmation before writing."
    )
    parser.add_argument("skill_folder", help="Path to the skill folder")
    parser.add_argument(
        "output_dir",
        nargs="?",
        default=None,
        help="Output directory (defaults to the current directory)",
    )
    parser.add_argument(
        "--allow-secret",
        action="append",
        default=[],
        metavar="PATH",
        help="Include a secret file by its path relative to the skill "
        "folder (explicit confirmation; repeatable)",
    )
    parser.add_argument(
        "--yes", "-y", action="store_true", help="Skip the confirmation prompt"
    )
    args = parser.parse_args(argv)

    print(f"📦 Packaging skill: {args.skill_folder}")
    if args.output_dir:
        print(f"   Output directory: {args.output_dir}")
    print()

    result = package_skill(
        args.skill_folder,
        args.output_dir,
        allow_secrets=args.allow_secret,
        confirm=_is_interactive() and not args.yes,
    )

    sys.exit(0 if result else 1)


if __name__ == "__main__":
    main()
