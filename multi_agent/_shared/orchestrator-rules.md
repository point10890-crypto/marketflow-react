# Orchestrator Rules

## Session Re-entry

On every new session:

1. Read repository-level `AGENTS.md`.
2. Check `git status --short`.
3. Identify whether the user is asking for research, implementation, deploy, or
   production operation.
4. Preserve unrelated dirty work.
5. Use focused tests before broad builds.

## Worker Brief Contract

Every worker brief must include:

- objective
- relevant files
- data constraints
- forbidden actions
- expected artifact
- validation command

## Result Contract

Every worker result must include:

- changed or reviewed files
- evidence found
- tests run
- risks and unknowns
- follow-up recommendation
