# Architecture

## Overview

shelfmark is a Python web application using FastAPI for the backend and a separately-scaffolded frontend.

## Project Structure

```
src/shelfmark/
  app.py               # FastAPI app factory
  config.py            # Pydantic-settings config from env vars
  logging.py           # structlog setup
  routers/             # HTTP endpoint definitions
    health.py          # /healthz, /readyz
  controllers/         # Request orchestration
  services/            # Business logic
  dtos/                # Pydantic request/response models
  web/                 # Frontend integration
    serve.py           # Static file serving for production
    frontend/          # Frontend app (scaffolded separately)
  clients/             # External API/service clients
  db.py                # Async engine/session factory
  models/              # SQLAlchemy async models
  repositories/        # Data access layer
tests/
  unit/                # Fast, isolated unit tests
  integration/         # Tests with real dependencies
  e2e/                 # End-to-end tests
```

## Layering

```
routers (HTTP endpoints, parse requests into DTOs)
  -> controllers (orchestrate across services)
    -> services (business logic, framework-agnostic)
      -> clients (external API calls)
      -> repositories (data access, return SQLAlchemy models)
        -> models (SQLAlchemy)
```

DTOs (Pydantic models) are used at the router and controller level for API I/O. They are always separate from database models.

## Frontend

The frontend is scaffolded separately into `src/shelfmark/web/frontend/` using the `frontend-react` Copier template. In development, the frontend dev server runs independently with API proxying. In production, built static files are served by FastAPI via `web/serve.py`.

## Shelfmark design

- **Composition root.** `app.build_app` reads `Settings` and builds the real
  collaborators (`Database`, `PublicWebFetcher`, the auth provider) and passes them to
  `create_app`. Nothing below it reads global settings; tests call `create_app` with a
  fresh migrated database (SQLite, or Postgres in CI), `tests/fakes.FakeFetcher`, a `FakeClock`, and `LocalAuth` or
  `Auth0Auth` backed by a fake Auth0 tenant.
- **Domain.** `services/library.LibraryService` owns triage: the feed Inbox
  (reading items not saved, unarchived), the deliberate Saved queue, To try (things:
  tools, repos, skills, and ideas kept as a name, optional link, description, note,
  and tags; never read as articles and never promoted from the Inbox),
  Archive/restore (restore returns a saved item to Saved), tags, saving links
  (article extraction with link-only fallback, YouTube as one canonical video item),
  and following/refreshing feeds (RSS/Atom, sites that advertise a
  feed; summary-only entries fetch their full article).
  `services/refresher` refreshes all users' feeds every `SHELFMARK_REFRESH_MINUTES`.
- **Persistence.** `models` (SQLAlchemy 2, portable types, named constraints, UTC
  timestamps), `repositories/library` (portable Core/ORM queries only), Alembic
  migrations in `src/shelfmark/migrations` (shipped with the package; applied on
  startup). SQLite (aiosqlite) is the local default; production uses Neon Postgres
  through psycopg, selected by `DATABASE_URL`. `SHELFMARK_TEST_DATABASE_URL` runs
  the database tests against Postgres, as CI does.
- **Identity boundary.** `auth.AuthProvider` answers "who is this?" and contributes its
  own routes. `auth.auth0.Auth0Auth` implements Sign in with Auth0 as a confidential
  web app (PKCE S256 plus client secret, RS256 ID token verified against the tenant
  JWKS with iss/nonce/aud/azp/exp, AES-GCM sealed HttpOnly cookies, no tokens stored;
  sign-out also ends the Auth0 session). `LocalAuth` is allowed only with
  `SHELFMARK_ENV=development`. Production is the default and fails closed: missing
  OAuth settings make `/api/*` return 503. `SHELFMARK_ALLOWED_USER_IDS` restricts access.
- **Untrusted content.** `clients/fetcher.PublicWebFetcher` only fetches http(s) on
  default ports, rejects IP literals and internal names, resolves once and refuses any
  non-global address, pins the connection to the checked addresses, re-validates each
  redirect, and caps size (2 MB) and time (12 s). `services/content` turns HTML into
  plain-text blocks; the API and the desk never carry or render HTML. A strict CSP
  allows only the youtube-nocookie player frame.

## Toolchain

| Tool | Purpose |
| ---- | ------- |
| uv | Package management, virtual environments |
| hatchling | Build backend |
| ruff | Formatting and linting |
| ty | Type checking |
| pytest | Testing |
| FastAPI | Async web framework |
| uvicorn | ASGI server |
| structlog | Structured logging |
| pydantic-settings | Configuration |
| pnpm | Frontend package management |
| SQLAlchemy | Async ORM |
| Alembic | Database migrations |

## Conventions

- All configuration is in `pyproject.toml`.
- Version is the single source of truth in `pyproject.toml`, read via `importlib.metadata`.
- `py.typed` marker enables downstream type checking (PEP 561).
- Health endpoints are always available at `/healthz` and `/readyz`.
- Just targets have `-be`/`-fe` variants for backend/frontend (e.g. `just fmt-be`, `just fmt-fe`).
