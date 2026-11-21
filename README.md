# shelfmark

A keyboard-first personal reading desk

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

# Frontend (after scaffolding with frontend-react template)
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

## Deployment

```sh
# Build Docker image
docker build -t shelfmark .

# Run container
docker run -p 8000:8000 shelfmark
```

## Frontend

The frontend lives in `src/shelfmark/web/frontend/`. Scaffold it using the `frontend-react` Copier template. See `src/shelfmark/web/frontend/README.md` for details.

## Architecture

See [docs/architecture.md](docs/architecture.md) for project structure and design decisions.

## API

See [docs/api.md](docs/api.md) for endpoint reference.

## License

[Proprietary](LICENSE)
