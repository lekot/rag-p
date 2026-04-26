# Contributing to RAG-Platform

## Getting started

```bash
git clone https://github.com/lekot/rag-p.git
cd rag-p
# Prerequisites: Docker Desktop (or Docker Engine), kind, Tilt, kubectl, helm, uv, pnpm
tilt up
```

Tilt starts the full local stack (API, web, Postgres, Redis, Langfuse, Permify, MinIO) inside a local kind cluster. Changes to `apps/api` and `apps/web` trigger automatic hot-reload.

## Making a change

1. Create a feature branch from `main`.
2. Make your change.
3. Run `make test` — all tests must pass.
4. Run `make lint` and `make typecheck` — zero warnings.
5. Open a PR using the provided template.

## Commit style

This project uses [Conventional Commits](https://www.conventionalcommits.org/):

```
feat(api): add cost_estimate to Chunker base class
fix(web): correct score calculation display in leaderboard
docs(adr): add ADR 0006 for sampling strategy
```

Types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `ci`.

Scope: component name (`api`, `web`, `helm`, `adr`) or omit for cross-cutting changes.

Breaking changes: add `!` after type or `BREAKING CHANGE:` in the footer.

## Adding a plugin

1. Create a new Python package in `apps/api/plugins/` (or as a standalone package).
2. Subclass the relevant abstract base class from `apps/api/src/plugins/base.py`.
3. Implement `params_schema`, `cost_estimate`, and `health_check`.
4. Register via `[project.entry-points."rag_p.plugins"]` in your `pyproject.toml`.
5. Add tests covering `params_schema` validation and `health_check`.

## ADR process

Significant architectural changes require an ADR in `docs/adr/` (MADR format). Link the ADR in your PR description.

## CLA

No CLA required currently (single author). This will be revisited as the contributor base grows (TBD).

## Windows / WSL2

If running on Windows, use WSL2 with Docker Desktop. kind inside WSL2 + Docker Desktop is the tested configuration. Native Windows without WSL2 is not supported.
