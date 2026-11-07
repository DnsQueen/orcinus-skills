# Release checklist

Every release follows these steps, in order. The checklist exists
because 0.9.2 was never tagged (round 6, 2-P1-7): the version was
bumped and the changelog written, but no tag was created, so there
was no release object to point at and no way to check out "0.9.2"
later. History is not rewritten — 0.9.2 stays untagged — but every
release from 0.9.3 on is tagged.

## Before the tag

1. **Version bump.** The version in `.claude-plugin/plugin.json`
   must be greater than the base version AND greater than the
   latest release tag (a downgrade or a bump to an
   already-released version fails CI — see
   `scripts/check_version_bump.py`).
2. **Changelog.** A `CHANGELOG.md` entry for the new version, in
   the same push as the bump. A version bump without a changelog
   entry fails CI.
3. **CI green.** All jobs pass on the exact commit to be tagged:
   test (ubuntu + Windows + macOS), waza, demo (Node 22 and 24),
   waza-fixtures, shellcheck, clean-install, version-bump,
   plugin-validate, postgres-migration, and CodeQL. **Tag only a
   CI-green commit** — never tag a commit whose CI has not run or
   has not passed.
4. **Drift clean.** `python3 scripts/check_drift.py` passes — no
   vendored file changed without its drift-manifest entry.

## Tag and release

5. **Tag.** `git tag vX.Y.Z <commit>` — annotated tags are not
   required; the tag name is `v` + the version in
   `.claude-plugin/plugin.json`, nothing else.
6. **Push the tag.** `git push origin vX.Y.Z`.
7. **GitHub release.** Create the release from the tag in the
   GitHub web UI, with the changelog entry as the release notes.
   The release is not "published" until this step exists — a tag
   alone is not a release.

## After the release

8. **Verify.** The tag points at the CI-green commit (`git rev-list
   -n 1 vX.Y.Z`), and the release appears under Releases with the
   right notes.
9. **Next version.** Work continues on main; the next bump starts
   at step 1. Never reuse a released version number, and never
   move a release tag.
