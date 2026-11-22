# shelfmark

A keyboard-first personal reading desk: RSS/Atom subscriptions with a triage Inbox,
a deliberate Saved queue, clean article extraction, on-demand YouTube embeds, tags,
archive/restore, and a three-pane desk driven by the keyboard (`?` lists the keys).

## Getting Started

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- [just](https://just.systems/)
- [Docker](https://www.docker.com/) (for dependencies)
- [Node.js](https://nodejs.org/) 20+ and [pnpm](https://pnpm.io/) (for frontend)

### Installation

```sh
# Backend
uv sync --dev
cp .env.example .env

# Frontend
cd src/shelfmark/web/frontend && pnpm install
```

### Running

```sh
# Start both backend and frontend dev servers
just dev

# Or start separately
just dev-be   # Backend only
just dev-fe   # Frontend only
```

The API will be available at `http://localhost:8000`. The frontend dev server runs on its own port with API proxying.

## Development

```sh
# Check formatting and linting (backend + frontend)
just fmt
just lint

# Fix formatting and linting
just fmt-fix
just lint-fix

# Run type checker
just typecheck

# Backend-only or frontend-only variants
just fmt-be
just lint-fe
```

## Testing

```sh
# Run unit tests (backend + frontend)
just test-unit

# Run all tests
just test-all

# Full pre-push check
just gate
```

`.env.example` runs locally as one development user (`SHELFMARK_AUTH=local`), with data
in `.data/`.

## Deployment (Amp Box)

`.amp/box.yaml` builds a self-contained release (`scripts/box-build.sh`: relocatable
CPython, dependencies, built frontend) and runs `python -m shelfmark` on `$PORT`. Data
lives in Neon Postgres: store the `DATABASE_URL` secret on the deployment before the
first deploy, in the form
`postgresql+psycopg://USER:PASSWORD@HOST/shelfmark?sslmode=verify-full&sslrootcert=/etc/ssl/certs/ca-certificates.crt`.
Neon's console URL works once its scheme is changed to `postgresql+psycopg://`.
Migrations run on startup. Without `DATABASE_URL` the app falls back to SQLite at
`$AMP_DEPLOYMENT_DATA_DIRECTORY/shelfmark.sqlite3`.

```sh
amp boxes deploy --on <namespace>/<box> --name shelfmark
```

Then register Sign in with Amp with redirect URI `<deployment url>/auth/callback` and
store `AMP_OAUTH_CLIENT_ID`, `AMP_OAUTH_CLIENT_SECRET`, and `APP_SESSION_SECRET`
(32+ random characters) on the deployment, optionally `SHELFMARK_ALLOWED_USER_IDS`,
and redeploy. Until then the app serves health checks and the desk shell, and `/api/*`
answers 503.

## Architecture

See [docs/architecture.md](docs/architecture.md) for project structure and design decisions.

## API

See [docs/api.md](docs/api.md) for endpoint reference.

## License

[MIT](LICENSE)
