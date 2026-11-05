# EVAL — skill-creator-01

How to check whether `skill-creator` works. Follow its own workflow (capture intent → write the draft → test prompts → evaluate → iterate) to author a new skill, and prove the authored skill works. The authored skill lives in a throwaway workspace (`/tmp/skill-lint-test/`); it is not added to this repo. No criterion may be skipped.

## Setup (not part of the score)

- Intent, captured per the creator's workflow: the new skill is **skill-lint** — it validates a `SKILL.md` against the Agent Skills spec. It triggers whenever a skill is written or changed, before committing. Its output is PASS or FAIL with each violation named. Its outputs are objectively verifiable, so test cases apply.
- The authored skill has `SKILL.md` plus `scripts/check_skill.py` (Python, stdlib only), written by following the creator's guidance (imperative form, exact output format, examples).
- Test prompts (the creator's 2–3 realistic cases): (1) "validate the orcinus-verify SKILL.md"; (2) "validate a SKILL.md with no description"; (3) "validate a SKILL.md whose name does not match its folder".

## Case 1 — the authored skill is valid

**Input:** the authored `skill-lint` skill, checked with the creator's own `quick_validate.py` and by reading it.

**Pass criteria:**

1. `quick_validate.py` prints "Skill is valid!" and exits 0.
2. Its `SKILL.md` is under 500 lines, its frontmatter name matches its folder (`skill-lint`), and its description is present (1–1,024 characters).
3. `package_skill.py` packages it (a zip file is produced).
4. Verdict is PASS.

**Fail criteria:**

- `quick_validate.py` reports the skill invalid.
- The name does not match the folder, or the description is missing or out of range.
- The packaging script fails.

## Case 2 — the authored skill works on good skills

**Input:** `check_skill.py` run on two real, good skills: the repo's own `orcinus-verify` SKILL.md and the creator's own `skill-creator` SKILL.md.

**Pass criteria:**

1. Both runs exit 0 with PASS and no violations.
2. Verdict is PASS.

**Fail criteria:**

- Either run exits 1 or reports a violation on a good skill.

## Case 3 — the authored skill catches bad skills

**Input:** `check_skill.py` run on two deliberately broken SKILL.md files: one with no description in the frontmatter, and one whose frontmatter name does not match its folder.

**Pass criteria:**

1. Both runs exit 1 with FAIL.
2. Each run names the violation (missing description; name does not match folder).
3. Verdict is PASS (the skill catches them).

**Fail criteria:**

- Either run exits 0 or fails to name the violation.

## Last run

- 2026-11-06: PASS. Case 1: 4/4. Case 2: 2/2. Case 3: 3/3. Real run, not simulated, following the creator's own workflow to author a new skill in a throwaway workspace (`/tmp/skill-lint-test/`). Intent captured first: **skill-lint** validates a `SKILL.md` against the Agent Skills spec, triggers whenever a skill is written or changed before committing, and outputs PASS or FAIL with each violation named. Case 1 (author by the workflow): the authored skill has `SKILL.md` (65 lines) plus `scripts/check_skill.py` (stdlib only); the creator's own `quick_validate.py` prints "Skill is valid!" and exits 0; the frontmatter name matches its folder (`skill-lint`) and the description is present; `package_skill.py` produced `/tmp/skill-lint-test/out/skill-lint.skill` (2,497 bytes, containing `SKILL.md` and `scripts/check_skill.py`). Case 2 (works on good skills): the authored checker passes the repo's own `orcinus-verify` SKILL.md ("PASS: orcinus-verify (90 lines)") and the creator's own `skill-creator` SKILL.md ("PASS: skill-creator (486 lines)"). Case 3 (catches bad skills): a SKILL.md with no description fails with "description: missing (must be 1-1024 characters)", and a SKILL.md whose name does not match its folder fails with "name: does not match folder ('totally-different-name' != 'bad-name-mismatch')". Two real findings during the run: (1) `package_skill.py` must be run as a module from the skill-creator directory (`python -m scripts.package_skill <skill> [out-dir]`); run as a bare script it fails with `ModuleNotFoundError: No module named 'scripts'`, and its own usage line (`python utils/package_skill.py ...`) would fail the same way. (2) The creator's `run_eval.py` / `run_loop.py` / `improve_description.py` invoke the Claude Code CLI (`claude -p`), which does not exist here — the scripted eval loop was not run; the eval above is the ORCINUS equivalent (real runs with scored cases). The authored skill-lint skill is a throwaway test artifact in /tmp, not added to this repo.
