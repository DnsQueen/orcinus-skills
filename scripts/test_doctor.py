"""Tests for doctor.py (the environment diagnostic).

The doctor must distinguish three states honestly: ready, incomplete
(missing, skippable), and incompatible (present but wrong). A missing
tool reported as ready would let a verification claim PASS on a gate
that never ran; a missing tool reported as incompatible would send
the user fixing the wrong thing.

Run: python3 -m pytest scripts/test_doctor.py -q
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import doctor  # noqa: E402


def test_version_tuple():
    assert doctor._version_tuple("pytest 8.4.2") == (8, 4, 2)
    assert doctor._version_tuple("ruff 0.17.4") == (0, 17, 4)
    assert doctor._version_tuple("8.4.2") == (8, 4, 2)
    assert doctor._version_tuple("no version here") is None
    assert doctor._version_tuple("") is None


def test_python_check_ready():
    result = doctor.check_python()
    assert result["status"] == "ready"
    assert "Python" in result["detail"]


def test_repo_files_check_ready():
    result = doctor.check_repo_files()
    assert result["status"] == "ready"


def test_git_check_ready():
    result = doctor.check_git()
    assert result["status"] == "ready"
    assert "git version" in result["detail"]


def test_check_shape():
    for check in (doctor.check_python(), doctor.check_git(),
                  doctor.check_repo_files()):
        assert set(check) == {"name", "status", "detail", "fix"}
        assert check["status"] in ("ready", "incomplete", "incompatible")
