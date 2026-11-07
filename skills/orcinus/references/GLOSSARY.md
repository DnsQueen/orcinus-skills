# GLOSSARY

Shared vocabulary for ORCINUS. A term means what is written here, nowhere else.

- **ORCINUS**: one integrated nervous system, one install, one entry (`orcinus`), routing to focused sub-skills from idea (0) to publish (100).
- **Router**: the `orcinus` skill. Detects the stage from evidence and routes to the right sub-skill. It does not do the work itself.
- **Sub-skill**: a focused skill for one stage or need, under 500 lines, with its own `SKILL.md`. The user never picks one directly mid-work.
- **Focused sub-skill**: every skill except the router — 35 of the 36 skills, including the verifier (`orcinus-verify`). "Router + N focused sub-skills" counts N = skills − 1; "all N skills" counts N = skills.
- **Stage**: a named phase with an entry condition and an exit gate. Example: Idea, Architecture, Build, Verify, Finalize.
- **Gate**: a check that must pass before moving to the next stage. Major gates (idea → code, code → done) need explicit human confirmation.
- **Done**: a claim that a feature works. It is accepted only with evidence: the acceptance criteria, the commands run, their real outputs, and the changed files.
- **Evidence bundle**: the recorded proof for a claim: commands, exit codes, outputs, test results, git diff, and unresolved risks.
- **Implementer**: the agent that writes the code. It is never the final judge of its own work.
- **Verifier**: an independent check (skill, reviewer, or harness) that reads code and evidence, not the implementer's summary.
- **Test integrity**: tests are evidence. Never delete, weaken, skip, or modify a test merely to make the suite pass. If a test looks wrong, explain why with evidence and get agreement first.
- **Reward hacking**: changing the measure instead of the work — deleting a failing test, weakening an assertion, disabling CI — to look successful.
- **False completion**: claiming done without running the checks, or misreading their output.
- **Silent failure**: catching an error and hiding it, so the user sees "Generating..." while nothing works.
- **Scope creep**: changing files outside the requested change.
- **One-shot implementation**: trying to build the whole product in one step, exhausting context and leaving the work half-done.
- **Context loss**: losing decisions, progress, or constraints across sessions or context windows. Countered by a progress file, git history, and small steps.
- **Harness**: the environment around the model — rules, tools, tests, and controls that make the agent's work checkable. A prompt alone is not a harness.
- **Eval**: a scenario with a known failing case and a pass criterion, used to measure whether a skill actually works.
