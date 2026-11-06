# ATTRIBUTION — mutation-testing-python

- **Source:** boxed/mutmut — the mutmut CLI, used as-is. The method in this SKILL.md is written in ORCINUS's own words; no code was copied from mutmut.
- **Licence:** BSD-3-Clause — stated in the skill (boxed/mutmut, BSD-3-Clause). No mutmut code is in this repo; a copy of the tool's licence text is in `LICENSE.txt` in this folder.
- **What changed:** nothing was copied, so nothing was changed. The skill instructs the agent to install mutmut and pytest in a virtual environment and to run `mutmut run` with the current config keys (`source_paths`, `pytest_add_cli_args_test_selection`) — the deprecated keys (`paths_to_mutate`, `tests_dir`) and `test_command` are not set, because mutmut 3.x ignores them.
- **Tool version used in the eval:** mutmut 3.8.1 (see `evals/mutation-testing-python-01.md`).
- **Evals:** the repo's own eval is `evals/mutation-testing-python-01.md` — a real run on a small Python demo (34 mutants, 34 killed, 0 survived), with the gate proven able to fail (the first run, with 8 tests, left 4 survived, all named).
