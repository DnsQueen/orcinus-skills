# Contributing to ORCINUS

ORCINUS is a verification-first project. Contributions are welcome if
they meet the same standard the collection demands of its users.

## The rules

1. **A claim without evidence is not a claim.** A new skill, a fix,
   or a change to a skill ships with a real run: the commands, their
   exit codes, and the numbers. Put the evidence in the skill's eval
   file under `evals/`, and record the raw log in `evals/results/`
   when it matters.
2. **The implementer is never the final judge.** A change is verified
   by someone (or something) other than the person who wrote it, with
   the requirements and the diff — not with the author's conclusions.
   If a test looks wrong, say why and get agreement before changing it.
   Never weaken, skip, delete, or rewrite a test to make code pass,
   and never special-case code just to satisfy a specific test.
3. **A gate that cannot fail is not a gate.** If a check passes on
   empty or missing input, it is broken. Checkers must fail when the
   expected files are missing, and a scan that covered nothing is
   INCOMPLETE, never clean.
4. **Use the ready skill.** If a skill already exists that answers
   the need, use that one — do not rewrite it. Verify its primary
   LICENSE first, copy it verbatim with attribution, adapt only the
   frontmatter to the Agent Skills spec, and record the change in the
   skill's `ATTRIBUTION.md`. If the licence blocks verbatim copying,
   find the best open-source alternative or rewrite it in your own
   words.
5. **Licences are checked, not assumed.** Every upstream source is
   verified from its primary LICENSE file before it is copied. The
   central index is `THIRD_PARTY_NOTICES.md`; `scripts/validate_repo.py`
   checks it against every skill.
6. **Dates are UTC** in new entries (CHANGELOG, MAP, evals). Older
   entries are Asia/Tehran local time, as recorded at the time.

## How to add or change a skill

1. Read the router (`skills/orcinus/SKILL.md`) and `docs/MAP.md` first.
   A skill answers one stage; the router is the only entry point.
2. If the skill is injected from upstream, follow rule 4 above and
   write the `ATTRIBUTION.md` (source, licence, upstream commit or
   version, what changed, scope notes) and copy the upstream
   `LICENSE.txt` into the skill folder.
3. If the skill is written from scratch, put `license: MIT` in the
   frontmatter and note in the MAP that it is from scratch.
4. Wire it into the router's stage table and into `docs/MAP.md`.
5. Write an eval in `evals/` and run it for real. The eval records
   the commands, the exit codes, the numbers, and the defects found.
6. Run the checks before opening a PR:
   `python3 scripts/validate_repo.py` and `python3 -m pytest -q`.
   CI runs both, plus the waza harness-smoke suite.

## How to report a bug

Open an issue with the skill name, the file and line (or function),
the exact command you ran, and the output. If the bug is in a
verification tool (a false pass or a false fail), say so explicitly —
that is the highest-priority class of bug in this project.
