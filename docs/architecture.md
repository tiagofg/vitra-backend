# Architecture

[Back to the README](../README.md)

## Application boundaries

VITRA is organized as a modular monolith. [app/main.py](../app/main.py) creates the FastAPI application and mounts routers. Each domain under [app/modules](../app/modules/) groups models, schemas, services and HTTP routes.

| Area | Responsibility |
|---|---|
| `auth` | Login, refresh, users, groups, permissions and company selection |
| `empresa` | Companies, branches and cost centers |
| `apoio` | Reference and lookup data |
| `pessoas` | Customers, suppliers and related people records |
| `produtos` | Products, variants, prices, suppliers and related groups |
| `core` | Configuration, database access, authentication infrastructure, tenancy, errors and contracts |
| `common` | Shared models, schemas, CRUD behavior and collection updates |

Domain code can reuse [BaseService](../app/common/base_service.py) and the [CRUD router factory](../app/common/crud_router.py). This reduces repeated endpoint behavior, while domain services own their additional validation and relationships. The trade-off is that a change to common behavior affects multiple modules and needs corresponding regression coverage.

## Tenant isolation and authorization

Company selection is an authorization decision as well as a query context. The API authenticates the caller, verifies their company relationship and enforces resource permissions before allowing company-scoped operations.

[auth/deps.py](../app/modules/auth/deps.py) resolves the company from the access token or `X-Empresa-Id`. [tenancy.py](../app/core/tenancy.py) stores it on the SQLAlchemy session and sets the PostgreSQL transaction context using `set_config(..., true)`.

PostgreSQL policies then restrict company-scoped rows. Composite keys and foreign keys also constrain cross-company relationships. The application connects through a runtime role; schema migrations use an administrative connection. The relevant policies and grants live in [the RLS migration](../alembic/versions/b1c2d3e4f5a6_rls_multiempresa.py).

Transaction-local configuration matters because connections are pooled. A session-level tenant setting could survive reuse; the transaction-local setting is cleared when the transaction ends. Missing context returns no company-scoped rows at the database layer, while the HTTP boundary reports missing company selection explicitly.

RLS complements application authorization. It does not replace membership checks, permission checks, or protection of administrative credentials.

## API contracts and data conventions

- Pydantic schemas define request and response shapes.
- Errors use a shared `erro` envelope with `codigo`, `mensagem`, and `campos`.
- List and lookup helpers provide consistent pagination, search and sorting controls.
- Monetary price fields use integer cents rather than floating-point currency values.
- Nested product collections use replace-set semantics: omitted or null collections remain unchanged; an empty array clears the collection.
- The [OpenAPI export](../scripts/exportar_openapi.py) and [Postman generator](../scripts/exportar_postman.py) keep consumer-facing artifacts tied to the API contract.

## Audit foundation

[audit.py](../app/core/audit.py) defines the audit record model and `registrar_evento()`. The helper flushes within the caller's transaction, and the runtime role is restricted to reading and inserting audit records. Automatic interception of all mutations is not implemented; consumers must explicitly record relevant events.

## Verification strategy

| Risk | Evidence in the repository |
|---|---|
| Cross-company reads, writes or references | [RLS isolation tests](../tests/test_rls_isolamento.py) |
| Tenant state leaking through pooled connections | [Concurrent request tests](../tests/test_concorrencia_multiempresa.py) and pool reuse cases in the isolation suite |
| Unauthorized cross-company actions | [Company authorization tests](../tests/test_autorizacao_por_empresa.py) |
| Privilege escalation | [Escalation tests](../tests/test_escalada_privilegio.py) |
| Documented error responses diverging from runtime | [OpenAPI contract tests](../tests/test_contrato_openapi.py) |
| Migration leftovers | Upgrade → downgrade → upgrade in [CI](../.github/workflows/ci.yml) |

Testcontainers creates a disposable PostgreSQL database and applies migrations, including RLS. Isolation tests use the runtime role instead of a table owner or superuser, and relevant scenarios include a positive case before asserting denial.

## Limits and trade-offs

The code demonstrates these design choices and test scenarios; it does not establish a security certification, production load capacity, or completed future business modules. Runtime dependencies mostly use minimum versions, so a future dependency resolution can differ from a previous installation. The Docker Compose file provisions the development database; it is not a complete deployment stack for the API.
