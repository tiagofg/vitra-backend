# Local setup

[Back to the README](../README.md)

## Prerequisites

Use Python 3.12 or newer, Git, Make, Docker and Docker Compose. The commands below use a Linux/macOS shell and run from the repository root. Python 3.12 is the version configured in CI.

```bash
git clone https://github.com/tiagofg/vitra-backend.git
cd vitra-backend
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
cp .env.example .env
make hooks
```

The repository uses `.venv/bin` explicitly in its Make targets, so activating the virtual environment is optional for these commands.

## Configuration

Review [.env.example](../.env.example) and [Config](../app/core/config.py) before starting.

| Variable | Purpose |
|---|---|
| `VITRA_AMBIENTE` | `dev`, `teste` or `producao` |
| `VITRA_DATABASE_URL` | Application connection using the restricted runtime role |
| `VITRA_DATABASE_URL_ADMIN` | Administrative connection used by migrations |
| `VITRA_JWT_SECRET` | JWT signing secret; production configuration rejects the default or a short value |
| `VITRA_JWT_ACCESS_TTL_MINUTOS` | Access-token lifetime in minutes |
| `VITRA_JWT_REFRESH_TTL_DIAS` | Refresh-token lifetime in days |
| `VITRA_CORS_ORIGENS` | JSON array of allowed browser origins |

The example database credentials and seed account are for local development. Keep environment files and credentials out of version control. Do not use the development defaults for an externally exposed environment.

## Start the database and API

```bash
make db
```

Wait for the database to become healthy (`docker compose ps`), then run:

```bash
make migrar
make runtime
make seed
make api
```

The order matters: migrations create the schema and policies; `make runtime` grants the runtime role its group membership; the seed adds initial reference data and accounts.

- API: <http://localhost:8000>
- Local Swagger UI: <http://localhost:8000/docs>
- Health endpoint: <http://localhost:8000/saude>
- Development PostgreSQL: `localhost:5433`

The seed account and detailed operational examples are documented in the existing guide in [README.md](../README.md). Change the seed password before using the environment beyond disposable local development. See the [API guide](api.md) for authentication and company selection.

## Quality checks

```bash
make testes
make qualidade
```

`make testes` runs pytest against disposable PostgreSQL 17 instances managed by Testcontainers. Docker must be available. The suite applies Alembic migrations before testing database behavior. It can use `VITRA_TESTE_URL_EXTERNA`, but that mode recreates the target schema: use only a database dedicated to disposable tests.

`make qualidade` runs the configured pre-commit hooks. Some hooks can modify formatting, so review the resulting diff. The [CI workflow](../.github/workflows/ci.yml) separately runs quality, tests, migration reversibility and OpenAPI consistency checks.

`make migracoes` performs an upgrade, a **downgrade to base**, and another upgrade. It can destroy data in the configured database. Use it only with a disposable local database; never point it at a shared or production database. `make checar` includes this migration cycle as well as quality and tests. OpenAPI consistency remains a separate CI check.

## Generated API artifacts

```bash
make openapi
make postman
```

These commands update versioned documentation artifacts. Review and commit generated changes when intentionally changing the API contract. The Postman collection is generated from OpenAPI; edit the generator when changing its behavior.

## Troubleshooting

| Symptom | Check |
|---|---|
| Connection refused on port 5433 | Docker is running and the `db` service is healthy |
| Permission errors after a fresh migration | Run `make runtime`; use the runtime URL for the API and administrative URL for migrations |
| `400 empresa_nao_declarada` | Select an active company in the token or request header |
| `403` for company-scoped data | The caller needs an active company relationship and the required permissions |
| Empty list | Review filters and selected company; database RLS restricts visible rows |
| `/docs` unavailable in production mode | Swagger and the live OpenAPI endpoint are intentionally disabled in that mode |

To stop the development database while retaining its volume, use `docker compose stop db`.
