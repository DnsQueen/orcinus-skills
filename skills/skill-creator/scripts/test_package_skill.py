"""Tests for skills/skill-creator/scripts/package_skill.py.

Round 6 (2026-11-07), 3-R3-04: the packager archived .env files and
followed symlinks into the ZIP, so a secret file and an outside
file's contents were distributed with the skill. Packaging is now
allowlist-based with a printed plan, symlinks are never followed,
secret files are rejected unless explicitly allowed, and the archive
is written to a temp path, checked against the plan, and renamed
atomically. The script's own documented invocation also failed as
written (ModuleNotFoundError: No module named 'scripts').

Run: python3 -m pytest skills/skill-creator/scripts/test_package_skill.py -q
"""

import os
import subprocess
import sys
import zipfile
from pathlib import Path, PureWindowsPath

sys.path.insert(0, str(Path(__file__).resolve().parent))
import package_skill as ps  # noqa: E402

SCRIPTS_DIR = Path(__file__).resolve().parent
SKILL_CREATOR_DIR = SCRIPTS_DIR.parent


def _valid_skill(tmp_path, name="demo-skill"):
    """A minimal skill that passes quick_validate."""
    skill = tmp_path / name
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\n"
        f"name: {name}\n"
        "description: A demo skill for packaging tests.\n"
        "license: MIT\n"
        "---\n\n"
        "# Demo skill\n",
        encoding="utf-8",
    )
    return skill


def _zip_names(path):
    with zipfile.ZipFile(path) as zf:
        return zf.namelist()


def _zip_contents(path):
    with zipfile.ZipFile(path) as zf:
        return {name: zf.read(name) for name in zf.namelist()}


def test_archive_names_use_forward_slashes_for_windows_paths():
    """Plan/archive keys must use forward slashes on every platform:
    on Windows str(Path) gives backslashes, which the ZIP namelist
    (forward slashes) and the forward-slash allowlist checks never
    match — so packaging failed with 'archive contents do not match
    the packaging plan'. PureWindowsPath reproduces that on Linux."""
    rel = PureWindowsPath("sub") / ".env"
    assert ps._archive_name("demo-skill", rel) == "demo-skill/sub/.env"


def test_cli_does_not_crash_on_non_utf8_stdout(tmp_path):
    """The CLI prints emoji; on a Windows console (cp1252) the first
    one raised UnicodeEncodeError and killed the run before any
    packaging happened. PYTHONIOENCODING=cp1252 reproduces that
    console on Linux."""
    skill = _valid_skill(tmp_path)
    out = tmp_path / "out"
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env["PYTHONIOENCODING"] = "cp1252"
    proc = subprocess.run(
        [sys.executable, "scripts/package_skill.py", str(skill), str(out)],
        cwd=str(SKILL_CREATOR_DIR),
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert (out / "demo-skill.skill").is_file()


def test_env_file_is_never_packaged_by_default(tmp_path):
    skill = _valid_skill(tmp_path)
    (skill / ".env").write_text("FAKE_API_KEY=abcdefgh12345678\n", encoding="utf-8")
    out = tmp_path / "out"
    result = ps.package_skill(skill, out)
    assert result is not None
    assert "demo-skill/.env" not in _zip_names(result)


def test_private_key_is_never_packaged_by_default(tmp_path):
    skill = _valid_skill(tmp_path)
    (skill / "id_rsa").write_text("FAKE PRIVATE KEY\n", encoding="utf-8")
    (skill / "cert.pem").write_text("FAKE CERT\n", encoding="utf-8")
    out = tmp_path / "out"
    result = ps.package_skill(skill, out)
    assert result is not None
    names = _zip_names(result)
    assert "demo-skill/id_rsa" not in names
    assert "demo-skill/cert.pem" not in names


def test_external_symlink_target_is_never_packaged(tmp_path):
    """A symlink to a file outside the skill must not smuggle the
    target's contents into the archive under the link's name."""
    outside = tmp_path / "outside.txt"
    outside.write_text("OUTSIDE-CONTENT-FAKE\n", encoding="utf-8")
    skill = _valid_skill(tmp_path)
    os.symlink(outside, skill / "data.txt")
    out = tmp_path / "out"
    result = ps.package_skill(skill, out)
    assert result is not None
    contents = _zip_contents(result)
    assert "demo-skill/data.txt" not in contents
    assert all(b"OUTSIDE-CONTENT-FAKE" not in data for data in contents.values())


def test_broken_symlink_is_never_packaged(tmp_path):
    skill = _valid_skill(tmp_path)
    os.symlink(tmp_path / "no-such-target.txt", skill / "broken.txt")
    out = tmp_path / "out"
    result = ps.package_skill(skill, out)
    assert result is not None, "a broken symlink must not fail the run"
    assert "demo-skill/broken.txt" not in _zip_names(result)


def test_symlinked_directory_does_not_smuggle_outside_files(tmp_path):
    outside_dir = tmp_path / "outside-dir"
    outside_dir.mkdir()
    (outside_dir / "secret.txt").write_text("OUTSIDE-CONTENT-FAKE\n", encoding="utf-8")
    skill = _valid_skill(tmp_path)
    os.symlink(outside_dir, skill / "linked")
    out = tmp_path / "out"
    result = ps.package_skill(skill, out)
    assert result is not None
    contents = _zip_contents(result)
    assert not any("linked" in name for name in contents)
    assert all(b"OUTSIDE-CONTENT-FAKE" not in data for data in contents.values())


def test_ordinary_files_are_packaged_with_content(tmp_path):
    skill = _valid_skill(tmp_path)
    (skill / "notes.md").write_text("# Notes\n", encoding="utf-8")
    (skill / "helper.py").write_text("X = 1\n", encoding="utf-8")
    out = tmp_path / "out"
    result = ps.package_skill(skill, out)
    assert result is not None
    contents = _zip_contents(result)
    assert contents["demo-skill/SKILL.md"].startswith(b"---\n")
    assert contents["demo-skill/notes.md"] == b"# Notes\n"
    assert contents["demo-skill/helper.py"] == b"X = 1\n"


def test_allow_secret_includes_only_the_named_file(tmp_path):
    """Explicit confirmation (--allow-secret / allow_secrets) admits
    exactly the file named, nothing else secret."""
    skill = _valid_skill(tmp_path)
    (skill / ".env").write_text("FAKE_API_KEY=abcdefgh12345678\n", encoding="utf-8")
    (skill / "id_rsa").write_text("FAKE PRIVATE KEY\n", encoding="utf-8")
    out = tmp_path / "out"
    result = ps.package_skill(skill, out, allow_secrets=[".env"])
    assert result is not None
    names = _zip_names(result)
    assert "demo-skill/.env" in names
    assert "demo-skill/id_rsa" not in names


def test_plan_reports_skipped_files_with_reasons(tmp_path):
    skill = _valid_skill(tmp_path)
    (skill / ".env").write_text("FAKE=1\n", encoding="utf-8")
    (skill / "blob.bin").write_text("binary?\n", encoding="utf-8")
    os.symlink(tmp_path / "outside.txt", skill / "link.txt")
    included, skipped = ps.collect_files(skill)
    skipped_by_name = {str(name): reason for name, reason in skipped}
    assert "demo-skill/.env" in skipped_by_name
    assert "secret" in skipped_by_name["demo-skill/.env"]
    assert "demo-skill/blob.bin" in skipped_by_name
    assert "allowlist" in skipped_by_name["demo-skill/blob.bin"]
    assert "demo-skill/link.txt" in skipped_by_name
    assert "symlink" in skipped_by_name["demo-skill/link.txt"]
    assert any(str(name).endswith("SKILL.md") for name, _ in included)


def test_archive_is_checked_against_the_plan(tmp_path):
    """The written archive's namelist equals the planned file list —
    nothing added, dropped, or renamed mid-write."""
    skill = _valid_skill(tmp_path)
    (skill / "notes.md").write_text("# Notes\n", encoding="utf-8")
    out = tmp_path / "out"
    included, _ = ps.collect_files(skill)
    result = ps.package_skill(skill, out)
    assert result is not None
    assert set(_zip_names(result)) == {str(arcname) for _, arcname in included}


def test_failed_write_leaves_no_partial_archive(tmp_path, monkeypatch):
    """A failure mid-write leaves no .skill file and no temp file
    behind (temp path + atomic rename)."""
    skill = _valid_skill(tmp_path)
    (skill / "a.md").write_text("a\n", encoding="utf-8")
    (skill / "b.md").write_text("b\n", encoding="utf-8")

    def _boom(zipf, file_path, arcname):
        raise OSError("simulated write failure")

    monkeypatch.setattr(ps, "_archive_file", _boom)
    out = tmp_path / "out"
    result = ps.package_skill(skill, out)
    assert result is None
    assert list(out.iterdir()) == []


def test_confirmation_declined_writes_nothing(tmp_path, monkeypatch):
    skill = _valid_skill(tmp_path)
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")
    out = tmp_path / "out"
    result = ps.package_skill(skill, out, confirm=True)
    assert result is None
    assert not out.exists() or list(out.iterdir()) == []


def test_confirmation_accepted_writes_archive(tmp_path, monkeypatch):
    skill = _valid_skill(tmp_path)
    monkeypatch.setattr("builtins.input", lambda prompt="": "y")
    out = tmp_path / "out"
    result = ps.package_skill(skill, out, confirm=True)
    assert result is not None
    assert "demo-skill/SKILL.md" in _zip_names(result)


def _run_packager_cli(args, cwd):
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    return subprocess.run(
        [sys.executable, *args],
        cwd=str(cwd),
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_documented_script_invocation_works_without_pythonpath(tmp_path):
    """3-R3-04 incidental: `python3 scripts/package_skill.py ...`
    from the skill-creator directory died with ModuleNotFoundError:
    No module named 'scripts'."""
    skill = _valid_skill(tmp_path)
    out = tmp_path / "out"
    proc = _run_packager_cli(
        ["scripts/package_skill.py", str(skill), str(out)], SKILL_CREATOR_DIR
    )
    assert proc.returncode == 0, proc.stderr
    assert "ModuleNotFoundError" not in proc.stderr
    assert (out / "demo-skill.skill").is_file()


def test_module_invocation_works(tmp_path):
    """The SKILL.md form, `python -m scripts.package_skill ...`,
    from the skill-creator directory."""
    skill = _valid_skill(tmp_path)
    out = tmp_path / "out"
    proc = _run_packager_cli(
        ["-m", "scripts.package_skill", str(skill), str(out)], SKILL_CREATOR_DIR
    )
    assert proc.returncode == 0, proc.stderr
    assert (out / "demo-skill.skill").is_file()
