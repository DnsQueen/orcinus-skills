"""Tests for scripts/verify_attestation.py — the live CI-attestation
check for the VERIFIED gate (0.11.0).

`gh attestation verify` is never run for real here: the tests
monkeypatch subprocess.run with a fake gh, so the three outcomes
(verified / not-verified / unavailable) are deterministic with no
network and no GitHub credentials. The fake delegates every
non-gh call to the real subprocess.run, so the content digest is
still computed from a real git repo.

Run: python3 -m pytest scripts/test_verify_attestation.py -q
"""

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import content_digest as cd  # noqa: E402
import verify_attestation as va  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def _repo(tmp_path, origin=None):
    """A real git repo with one committed file."""
    repo = tmp_path / "proj"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@orcinus.local")
    _git(repo, "config", "user.name", "ORCINUS Test")
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("x = 1\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "code")
    if origin is not None:
        _git(repo, "remote", "add", "origin", origin)
    return repo


def _head(repo):
    proc = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip()


def _verified_json(file_sha256):
    """What `gh attestation verify --format json` prints on
    success: one entry whose statement subject carries the digest
    of the attested file."""
    return json.dumps(
        [
            {
                "attestation": {"bundle": {}},
                "verificationResult": {
                    "statement": {
                        "subject": [
                            {"name": "content-digest.txt", "digest": {"sha256": file_sha256}}
                        ],
                        "predicateType": "https://slsa.dev/provenance/v1",
                    }
                },
            }
        ]
    )


class _FakeRun:
    """A fake subprocess.run: answers gh calls from a script, runs
    everything else for real. Records the gh argv it saw."""

    def __init__(self, gh):
        self.gh = gh
        self.gh_argv = None
        self.subject_bytes = None
        # Captured at construction (before monkeypatching), so the
        # delegation below runs the real subprocess.run, not this fake.
        self._real_run = subprocess.run

    def __call__(self, argv, **kwargs):
        if argv and argv[0] == "gh":
            self.gh_argv = list(argv)
            # The subject file gh is asked to verify: record its
            # bytes, so the test can prove the digest was recomputed
            # (and written byte-identically to what CI attests).
            subject = argv[3] if len(argv) > 3 else None
            if subject is not None:
                self.subject_bytes = Path(subject).read_bytes()
            return self.gh(argv)
        return self._real_run(argv, **kwargs)


def _gh_result(returncode=0, stdout="", stderr=""):
    def _run(argv):
        return subprocess.CompletedProcess(argv, returncode, stdout, stderr)

    return _run


def test_verified_when_gh_confirms(tmp_path, monkeypatch):
    """The happy path: gh exits 0 with JSON whose subject digest
    is the attested file's sha256."""
    repo = _repo(tmp_path)
    revision = _head(repo)
    digest = cd.content_digest(repo, revision)
    import hashlib

    file_sha256 = hashlib.sha256(f"{digest}\n".encode()).hexdigest()
    fake = _FakeRun(_gh_result(stdout=_verified_json(file_sha256)))
    monkeypatch.setattr(subprocess, "run", fake)
    result = va.verify_attestation(repo, revision)
    assert result.status == "verified"
    assert result.reason == ""
    # The subject file gh verified holds exactly the recomputed
    # digest, byte-identical to what CI writes (digest + newline).
    assert fake.subject_bytes == f"{digest}\n".encode()
    # The gh call pins the identity: repo, signer workflow, and
    # the source revision — never a bare --owner.
    assert fake.gh_argv[4:6] == ["--repo", "DnsQueen/orcinus-skills"]
    assert "--signer-workflow" in fake.gh_argv
    idx = fake.gh_argv.index("--signer-workflow")
    assert fake.gh_argv[idx + 1] == "DnsQueen/orcinus-skills/.github/workflows/ci.yml"
    idx = fake.gh_argv.index("--source-digest")
    assert fake.gh_argv[idx + 1] == revision
    assert "--format" in fake.gh_argv and fake.gh_argv[fake.gh_argv.index("--format") + 1] == "json"


def test_not_verified_when_no_attestation_found(tmp_path, monkeypatch):
    """gh exits 1 with 'no attestations found': the revision was
    never attested in CI — not verified, not unavailable."""
    repo = _repo(tmp_path)
    revision = _head(repo)
    fake = _FakeRun(
        _gh_result(
            returncode=1,
            stderr="Error: no attestations found for subject sha256:deadbeef\n",
        )
    )
    monkeypatch.setattr(subprocess, "run", fake)
    result = va.verify_attestation(repo, revision)
    assert result.status == "not_verified"
    assert "no attestations found" in result.reason


def test_not_verified_on_http_404(tmp_path, monkeypatch):
    """The attestations API 404s for a subject with no
    attestations: same outcome as the explicit message."""
    repo = _repo(tmp_path)
    fake = _FakeRun(
        _gh_result(returncode=1, stderr="HTTP 404: Not Found (https://api.github.com/)")
    )
    monkeypatch.setattr(subprocess, "run", fake)
    result = va.verify_attestation(repo, _head(repo))
    assert result.status == "not_verified"


def test_unavailable_when_gh_not_authenticated(tmp_path, monkeypatch):
    """gh exits 4 asking for `gh auth login`: the check could not
    run — unavailable, never a silent pass or a 'not verified'."""
    repo = _repo(tmp_path)
    fake = _FakeRun(
        _gh_result(
            returncode=4,
            stderr="To get started with GitHub CLI, please run:  gh auth login\n",
        )
    )
    monkeypatch.setattr(subprocess, "run", fake)
    result = va.verify_attestation(repo, _head(repo))
    assert result.status == "unavailable"
    assert "gh auth login" in result.reason


def test_unavailable_when_gh_missing(tmp_path, monkeypatch):
    """No gh binary at all: unavailable with the exact cause."""

    real_run = subprocess.run

    def _missing(argv, **kwargs):
        if argv and argv[0] == "gh":
            raise FileNotFoundError(2, "No such file or directory", "gh")
        return real_run(argv, **kwargs)

    repo = _repo(tmp_path)
    monkeypatch.setattr(subprocess, "run", _missing)
    result = va.verify_attestation(repo, _head(repo))
    assert result.status == "unavailable"
    assert "gh" in result.reason


def test_unavailable_on_rate_limit(tmp_path, monkeypatch):
    """A GitHub API rate limit is a failure to check, not proof
    of absence."""
    repo = _repo(tmp_path)
    fake = _FakeRun(
        _gh_result(returncode=1, stderr="HTTP 403: API rate limit exceeded for user ID 1\n")
    )
    monkeypatch.setattr(subprocess, "run", fake)
    result = va.verify_attestation(repo, _head(repo))
    assert result.status == "unavailable"


def test_unknown_gh_failure_is_unavailable_not_not_verified(tmp_path, monkeypatch):
    """Fail closed: a gh failure the classifier does not recognise
    is 'unavailable' with the exact stderr, never 'not verified'
    — absence of an attestation must be proven, not assumed."""
    repo = _repo(tmp_path)
    fake = _FakeRun(_gh_result(returncode=1, stderr="Error: something entirely new went wrong\n"))
    monkeypatch.setattr(subprocess, "run", fake)
    result = va.verify_attestation(repo, _head(repo))
    assert result.status == "unavailable"
    assert "something entirely new" in result.reason


def test_exit_zero_with_empty_json_is_not_verified(tmp_path, monkeypatch):
    """CVE-2025-25204: gh < 2.67.0 returned exit 0 when no
    attestations were present. An empty JSON array on exit 0 is
    not a verification — the subject digest must be present in
    the output."""
    repo = _repo(tmp_path)
    fake = _FakeRun(_gh_result(returncode=0, stdout="[]"))
    monkeypatch.setattr(subprocess, "run", fake)
    result = va.verify_attestation(repo, _head(repo))
    assert result.status == "not_verified"


def test_exit_zero_with_wrong_subject_digest_is_not_verified(tmp_path, monkeypatch):
    """Exit 0 is not enough on its own: the JSON subject digest
    must be the attested file's digest, or the output is not
    proof of this subject."""
    repo = _repo(tmp_path)
    fake = _FakeRun(_gh_result(stdout=_verified_json("0" * 64)))
    monkeypatch.setattr(subprocess, "run", fake)
    result = va.verify_attestation(repo, _head(repo))
    assert result.status == "not_verified"


def test_exit_zero_with_malformed_json_is_unavailable(tmp_path, monkeypatch):
    """gh exited 0 but its JSON cannot be parsed: the check cannot
    be established — unavailable, not verified."""
    repo = _repo(tmp_path)
    fake = _FakeRun(_gh_result(returncode=0, stdout="not json at all"))
    monkeypatch.setattr(subprocess, "run", fake)
    result = va.verify_attestation(repo, _head(repo))
    assert result.status == "unavailable"


def test_unresolvable_revision_is_unavailable(tmp_path, monkeypatch):
    """A revision that does not resolve in the repo is a failure
    to check, with the cause named."""
    repo = _repo(tmp_path)
    result = va.verify_attestation(repo, "f" * 40)
    assert result.status == "unavailable"
    assert "does not resolve" in result.reason


def test_attest_repo_derives_from_origin(tmp_path, monkeypatch):
    """A fork's attestation proves a run in THAT repo's CI, not
    upstream's: --repo/--signer-workflow derive from the repo's
    origin, defaulting to upstream only with no GitHub origin."""
    repo = _repo(tmp_path, origin="git@github.com:SomeOrg/some-fork.git")
    revision = _head(repo)
    digest = cd.content_digest(repo, revision)
    import hashlib

    file_sha256 = hashlib.sha256(f"{digest}\n".encode()).hexdigest()
    fake = _FakeRun(_gh_result(stdout=_verified_json(file_sha256)))
    monkeypatch.setattr(subprocess, "run", fake)
    result = va.verify_attestation(repo, revision)
    assert result.status == "verified"
    assert fake.gh_argv[4:6] == ["--repo", "SomeOrg/some-fork"]
    idx = fake.gh_argv.index("--signer-workflow")
    assert fake.gh_argv[idx + 1] == "SomeOrg/some-fork/.github/workflows/ci.yml"


def test_attest_repo_explicit_override_wins(tmp_path, monkeypatch):
    """--attest-repo overrides the origin derivation."""
    repo = _repo(tmp_path, origin="git@github.com:SomeOrg/some-fork.git")
    revision = _head(repo)
    digest = cd.content_digest(repo, revision)
    import hashlib

    file_sha256 = hashlib.sha256(f"{digest}\n".encode()).hexdigest()
    fake = _FakeRun(_gh_result(stdout=_verified_json(file_sha256)))
    monkeypatch.setattr(subprocess, "run", fake)
    result = va.verify_attestation(repo, revision, attest_repo="OtherOrg/other")
    assert result.status == "verified"
    assert fake.gh_argv[4:6] == ["--repo", "OtherOrg/other"]


def test_bundle_mode_passes_bundle_to_gh(tmp_path, monkeypatch):
    """Offline verification: --bundle is passed to gh (the
    attestations come from disk, not the API) and identity is
    still enforced."""
    repo = _repo(tmp_path)
    revision = _head(repo)
    digest = cd.content_digest(repo, revision)
    import hashlib

    file_sha256 = hashlib.sha256(f"{digest}\n".encode()).hexdigest()
    bundle = tmp_path / "bundle.jsonl"
    bundle.write_text("{}\n", encoding="utf-8")
    fake = _FakeRun(_gh_result(stdout=_verified_json(file_sha256)))
    monkeypatch.setattr(subprocess, "run", fake)
    result = va.verify_attestation(repo, revision, bundle=bundle)
    assert result.status == "verified"
    assert "--bundle" in fake.gh_argv
    assert fake.gh_argv[fake.gh_argv.index("--bundle") + 1] == str(bundle)


def test_cli_exit_codes(tmp_path, monkeypatch, capsys):
    """The CLI: 0 verified, 1 not verified, 2 unavailable — and
    the verified line names the repo, workflow, source digest,
    and subject digest."""
    repo = _repo(tmp_path)
    revision = _head(repo)
    digest = cd.content_digest(repo, revision)
    import hashlib

    file_sha256 = hashlib.sha256(f"{digest}\n".encode()).hexdigest()
    fake = _FakeRun(_gh_result(stdout=_verified_json(file_sha256)))
    monkeypatch.setattr(subprocess, "run", fake)
    assert va.main(["verify_attestation.py", "--repo", str(repo), "--revision", revision]) == 0
    out = capsys.readouterr().out
    assert "DnsQueen/orcinus-skills" in out
    assert ".github/workflows/ci.yml" in out
    assert revision in out
    assert digest in out
    fake.gh = _gh_result(returncode=1, stderr="Error: no attestations found\n")
    assert va.main(["verify_attestation.py", "--repo", str(repo), "--revision", revision]) == 1
    assert "not verified" in capsys.readouterr().out
    fake.gh = _gh_result(returncode=4, stderr="please run: gh auth login\n")
    assert va.main(["verify_attestation.py", "--repo", str(repo), "--revision", revision]) == 2
    assert "unavailable" in capsys.readouterr().out
