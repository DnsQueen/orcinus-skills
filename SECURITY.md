# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| 0.12.x | Yes |
| 0.11.x | No |
| 0.10.x | No |
| < 0.10 | No |

## Reporting a vulnerability

If you find a security issue in ORCINUS — in a skill, in a bundled
script, or in the repo itself — do not open a public issue. Report it
privately to the repository owner (DnsQueen) through GitHub's private
vulnerability reporting, or by opening a draft security advisory.

Please include:

- the skill or file and the exact line or function,
- the input that triggers it,
- what an attacker (or a careless user) could do with it,
- whether it needs the victim to run a command or just to load a skill.

We will acknowledge the report, fix it, add a regression test, and
record the fix in `CHANGELOG.md`.

## What counts as a security issue here

- A skill or script that executes untrusted input (a file, a handoff,
  a prompt, an idea id, a URL) without validating or confining it —
  for example a path traversal, a command injection, or a frontmatter
  injection.
- A verification tool that can be made to report a false pass (for
  example by a crafted input that makes a checker skip the real files
  or scan nothing and still say OK).
- A bundled script that writes outside its declared directory, or
  that follows a symlink out of the project.
- A secret (a token, a password, a key) that a skill asks for in chat
  instead of through the provider's own secure flow.

## Scope notes

- ORCINUS skills run with the agent's full permissions. A skill's
  instructions are not a sandbox. Do not load a skill from an
  untrusted source, and do not paste untrusted content into a skill
  prompt.
- The bundled tools (oasdiff, Stryker, mutmut, Playwright, waza) are
  third-party software. Their own security issues belong to their
  upstream projects; report them there, and tell us so we can pin or
  replace the version.
