# CLAUDE.md

A keyboard-first personal reading desk

Python web application using FastAPI, uvicorn, uv, ruff, ty, and pytest. Frontend lives in `src/shelfmark/web/frontend/`.

## Quick Reference

| Command | Purpose |
| ------- | ------- |
| `just fmt` | Check formatting (backend + frontend) |
| `just fmt-fix` | Fix formatting (backend + frontend) |
| `just lint` | Check linting (backend + frontend) |
| `just lint-fix` | Fix linting (backend + frontend) |
| `just typecheck` | Run type checker (backend + frontend) |
| `just test-unit` | Run unit tests (backend + frontend) |
| `just test-integration` | Run integration tests |
| `just test-e2e` | Run e2e tests |
| `just test-all` | Run all tests |
| `just test-external` | Run tests hitting external services |
| `just gate` | Fast pre-push check (fmt + lint + typecheck + test-unit) |
| `just gate-expensive` | Full check (gate + integration + e2e) |
| `just gate-external` | Everything (gate-expensive + external) |
| `just dev` | Start backend and frontend dev servers |
| `just dev-be` | Start backend dev server only |
| `just dev-fe` | Start frontend dev server only |

All formatting, linting, typecheck, test-unit, and gate targets have `-be` and `-fe` variants (e.g. `just fmt-be`, `just fmt-fe`).

## Project Structure

```
src/shelfmark/
  app.py                    # FastAPI app factory
  config.py                 # Pydantic-settings based config
  logging.py                # structlog setup
  routers/                  # HTTP endpoint definitions
    health.py               # /healthz, /readyz
  controllers/              # Request orchestration
  services/                 # Business logic
  dtos/                     # Pydantic request/response models
  web/                      # Frontend integration
    serve.py                # Static file serving for production
    frontend/               # Frontend application
  clients/                  # External API/service clients
  __main__.py               # Production entry point (python -m shelfmark)
  auth/                     # Identity boundary: AuthProvider, LocalAuth, Sign in with Auth0
  db.py                     # Database (engine/sessions) and migrate()
  migrations/               # Alembic environment and versions
  models/                   # SQLAlchemy models
  repositories/             # Data access layer
tests/
  unit/                     # Unit tests
  integration/              # Integration tests
  e2e/                      # End-to-end tests
```

## Key Conventions

- Source code lives in `src/shelfmark/` (src layout).
- **Layering:** routers -> controllers -> services -> repositories.
- **DTOs** are Pydantic models for API I/O, always separate from DB models.
- **Frontend** is scaffolded separately into `src/shelfmark/web/frontend/` using the `frontend-react` template.
- Tests are organized by type in `tests/unit/`, `tests/integration/`, `tests/e2e/`.
- Use `@pytest.mark.external` for tests that hit external services.
- All config is in `pyproject.toml` — no separate config files.
- Dependencies are injected through `create_app`; tests use fakes (`tests/fakes.py`), not mocks, and a real migrated SQLite file.
- Keep schema and queries portable (SQLite now, Postgres later); add schema changes as Alembic revisions.
- Fetched content is untrusted: fetch only through `PublicWebFetcher`, store and return plain-text blocks, never HTML.
- Backend: `just dev-be`. Frontend: `just dev-fe`. Both: `just dev`.

## More Information

- `docs/architecture.md` — read before adding new modules or changing project structure
- `docs/development.md` — read for environment setup, debugging, or common tasks
- `docs/api.md` — API endpoint reference
