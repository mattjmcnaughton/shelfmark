# Shelfmark

Shelfmark puts your "read/watch/try later" in one calm, private queue, so you can
triage, read, tag, and archive what matters without the noise.

![The Inbox: new entries from your subscriptions, with the selected article open in the reading pane](docs/images/inbox.png)

## What it does

- **Triage an Inbox.** Follow RSS and Atom feeds; new entries land in the Inbox, where
  each one gets a glance and a decision: save it or archive it. You can follow a
  site's address or its feed.
- **Read in a Saved queue.** Links you save, and entries you keep, go to Saved. Articles
  are extracted to clean, plain text, and YouTube links play in place on demand.
- **Keep a To try list.** Tools, repos, skills, and ideas: a name, an optional link, a
  short description, labels, and a note on why it is worth trying. It is a list of
  links, not reading, so nothing in it is read as an article.
- **Tag and archive.** A few tags for finding things again; archive when you are done,
  and restore anything later.
- **Keyboard first.** `j`/`k` to move, `s` to save, `i` to add something to try, `t` to
  tag, `a` to archive, `f` for a distraction-free focus view, and `?` for the full list.
- **Private.** One person's library behind its own sign-in, with an allowlist of who
  may use it.

![The Saved queue, with an extracted article, its tags, and a note](docs/images/saved.png)

![To try: an idea with no link and a note on why to try it](docs/images/try.png)

![Every action has a key; ? shows them](docs/images/keys.png)

The screenshots use invented sample content.

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
lives in Neon Postgres: store the `DATABASE_URL` secret on the deployment (secrets
need the deployment to exist, so set it after the first deploy and redeploy), in the form
`postgresql+psycopg://USER:PASSWORD@HOST/shelfmark?sslmode=verify-full&sslrootcert=/etc/ssl/certs/ca-certificates.crt`.
Neon's console URL works once its scheme is changed to `postgresql+psycopg://`.
Migrations run on startup. Without `DATABASE_URL` the app falls back to SQLite at
`$AMP_DEPLOYMENT_DATA_DIRECTORY/shelfmark.sqlite3`.

```sh
amp boxes deploy --on <namespace>/<box> --name shelfmark
```

Add `--domain <hostname>` to serve it on a custom domain that is Active on the Box
owner's account; the sign-in callback follows `AMP_DEPLOYMENT_URL` automatically.

Until sign-in is configured the app serves health checks and the desk shell, and
`/api/*` answers 503.

### Sign in with Auth0

1. In an Auth0 tenant, create an application of type **Regular Web Application**.
2. In its settings, with `<url>` the deployment URL (such as
   `https://shelfmark--<namespace>.onamp.dev`):
   - Allowed Callback URLs: `<url>/auth/callback`
   - Allowed Logout URLs: `<url>/`
   - Allowed Web Origins: leave empty
3. Under Credentials, set the authentication method to **Client Secret (Basic)**.
   Keep Advanced Settings → Grant Types at Authorization Code and
   Advanced Settings → OAuth at **RS256**, OIDC Conformant.
4. Under the application's Connections, enable only the connection your account uses
   (for example Username-Password-Authentication or Google). To keep strangers from
   creating accounts, turn off sign-ups on database connections, and set the
   allowlist below.
5. Store these on the deployment, then redeploy. From your own machine:
   `amp secrets set <NAME> --box <namespace>/<box> --deployment shelfmark --secret --data-file <file>`;
   an Amp thread can instead open a masked dialog for each value.
   - `AUTH0_DOMAIN`: the tenant domain, such as `your-tenant.us.auth0.com`
   - `AUTH0_CLIENT_ID` and `AUTH0_CLIENT_SECRET`: from the application's settings
   - `APP_SESSION_SECRET`: 32+ random characters, such as `openssl rand -base64 48`
   - optional `SHELFMARK_ALLOWED_USER_IDS`: comma-separated Auth0 user IDs (`sub`),
     such as `google-oauth2|1234...`. Sign in once and the 403 page shows your ID.

Deploy without `--private`: Shelfmark does its own sign-in, and Amp's access gate
would redirect the desk's background `fetch` calls, which looks like being signed out.

The redirect URI defaults to `$AMP_DEPLOYMENT_URL/auth/callback`; set
`AUTH0_REDIRECT_URI` to override it (for example
`http://localhost:8000/auth/callback` when testing against a real tenant locally).

## Architecture

See [docs/architecture.md](docs/architecture.md) for project structure and design decisions.

## API

See [docs/api.md](docs/api.md) for endpoint reference.

## License

[MIT](LICENSE)
