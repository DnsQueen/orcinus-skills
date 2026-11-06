# ATTRIBUTION — breaking-change

- **Source:** oasdiff/oasdiff — the oasdiff CLI, used as-is. The method in this SKILL.md is written in own words; no code was copied from oasdiff.
- **Licence:** Apache-2.0 — verified from the primary LICENSE file. A copy is in `LICENSE.txt` in this folder.
- **What changed:** nothing was copied, so nothing was changed. The skill instructs the agent to install oasdiff from the official releases (a prebuilt binary for the platform, or `go install github.com/oasdiff/oasdiff@latest`) and to run `oasdiff breaking --fail-on ERR` — the `--fail-on ERR` flag is what makes the command fail, a fact found by a real run during the eval (without it, oasdiff prints the errors and still exits 0).
- **Tool version used in the eval:** the official v1.35.0 linux/amd64 release binary, SHA256 verified against the release `checksums.txt`.
- **Evals:** the repo's own eval is `evals/breaking-change-01.md` — a real run on three spec pairs (identical, breaking, additive), all validated first with `oasdiff validate`.
