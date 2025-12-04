# Repository Guidelines

## Project Structure & Module Organization
The Incident-to-Insight Loop lives under the `evalforge/` tree with Python 3.11 modules in `src/`. Services are separated by concern: `src/ingestion` handles Datadog trace pulls, `src/extraction` performs Gemini-powered pattern work, `src/generators` emits eval, guardrail, and runbook artifacts, `src/api` exposes the approval REST surface, `src/dashboard` publishes Datadog widgets, and `src/common` houses shared helpers. Tests mirror this layout under `tests/`, `docs/` holds specs and runbooks, and `scripts/` packages recurring automation. Infrastructure ships alongside application code: Dockerfile plus `docker-compose.yml` define the local stack and `.github/workflows/` enforces CI gates.

## Build, Test, and Development Commands
- `python -m venv venv && source venv/bin/activate` sets up the interpreter; keep the venv active for tooling.
- `pip install -e ".[dev]"` installs runtime and dev extras so editable imports work across modules.
- `cp .env.example .env` seeds configuration; add Datadog, Firestore, and Vertex values before any run.
- `docker-compose up` boots ingestion, API, and Firestore emulator exactly as CI orchestrates them.
- `python -m src.ingestion.main` and `python -m src.api.main` run the ingestion worker and FastAPI surface independently for focused debugging.

## Coding Style & Naming Conventions
Follow PEP 8 with four-space indentation and type hints everywhere; files and modules use `snake_case.py`, classes use `PascalCase`, and env keys stay `UPPER_SNAKE_CASE`. Keep request/response schemas in Pydantic models inside their owning package and share utilities through `src/common`. Docstrings should describe intent, and FastAPI routers belong in `api/routes_<domain>.py` to keep discovery predictable.

## Testing Guidelines
Tests rely on `pytest`; name files `tests/<area>/test_<feature>.py` and functions `test_<condition>_<expected>()`. Use fixtures for Datadog sample traces and Firestore emulators so generators stay deterministic. Every ingestion or generator change needs a regression test plus a contract-style assertion covering the produced eval or guardrail artifact; aim for 85%+ module coverage before requesting review.

## Commit & Pull Request Guidelines
Write imperative commits ("Add ingestion retry jitter") and keep config edits documented in the body. PRs need a concise summary, reproduction steps, linked issues (or `#hackathon`), screenshots for dashboard tweaks, and confirmation that lint + tests ran locally.

## Security & Configuration Tips
Never commit `.env`, Google credentials, or Datadog keys. Reference secrets via Secret Manager in deployment manifests, and use `gcloud auth application-default login` only for local smoke tests. When sharing dashboards or Firestore snapshots, sanitize tenant data and store fixtures under `tests/data/`.
