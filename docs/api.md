# API guide

[Back to the README](../README.md) · [Local setup](setup.md)

The default business API prefix is `/api/v1`. Inspect [openapi.json](../openapi.json) for the full contract, or use the Swagger UI at <http://localhost:8000/docs> in local development.

## Authentication and active company

1. Send the local account's `login` and `senha` to `POST /api/v1/auth/login`.
2. Use the returned access token as `Authorization: Bearer <access_token>`.
3. Find a company available to your account through `GET /api/v1/empresas/lookup`.
4. Send its ID to `POST /api/v1/auth/trocar-empresa` using `{"empresa_id":"<company-uuid>"}` and use the newly returned token, or supply `X-Empresa-Id: <company-uuid>` on each company-scoped request.

The header takes precedence over the token's company claim. The caller must have an active relationship with the selected company; choosing an ID does not grant access. Resource permissions are also enforced.

`POST /api/v1/auth/refresh` accepts a `refresh_token`. `GET /api/v1/auth/eu` describes the authenticated user. Treat tokens as credentials, including in exported API-client environments.

## Lists and lookups

List endpoints use `busca`, `busca_codigo`, `pagina`, `tamanho`, `ordenar_por`, `ordem` and `ativo`. Sorting fields are controlled per resource. Text search supports accent-insensitive matching.

Example with your own local token and selected company:

```http
GET /api/v1/produtos?pagina=1&tamanho=20&ordem=asc
Authorization: Bearer <access_token>
X-Empresa-Id: <company-uuid>
```

A paginated response contains `itens`, `total`, `pagina`, `tamanho` and `paginas`. Lookup routes, such as `/api/v1/produtos/lookup?q=pend&limit=20`, return compact items with `id`, `codigo`, `label` and `extras`.

## Error contract

Errors follow this shape:

```json
{
  "erro": {
    "codigo": "empresa_nao_declarada",
    "mensagem": "Nenhuma empresa ativa no pedido.",
    "campos": {}
  }
}
```

This is an illustrative envelope; exact messages and field details depend on the error. The versioned OpenAPI contract contains route-specific responses and examples.

| Status | Typical cause |
|---|---|
| 400 | Missing company context, invalid sorting or a domain rule |
| 401 | Missing, invalid or expired authentication |
| 403 | Missing permission or company relationship |
| 404 | Requested record not found |
| 409 | Conflicting data |
| 422 | Input validation failure |

## Write semantics

The product catalog uses integer cents for monetary price fields. For replace-set collections, omitted or null fields retain their existing contents, `[]` clears them, items without IDs are new, and existing IDs identify updates. Omitted existing members of a supplied collection are removed. Review [product schemas](../app/modules/produtos/schemas.py) before sending updates.

Deletion behavior varies by resource. Many primary CRUD records are deactivated, while nested collections can remove members. Consult each route's contract and service rather than assuming every DELETE is reversible.

## Postman

Import [the collection](../postman/vitra.postman_collection.json) and [the local environment](../postman/vitra.postman_environment.json). Select the local environment and execute the preparation folder first so later requests have a token, company ID and resource IDs.

The collection includes write operations. Run it against a disposable development database, not a shared or production target. Generated scripts populate dependent IDs and check error envelopes and unexpected 5xx responses.

Regenerate the collection with `make postman`; its source is the versioned OpenAPI contract and [generator](../scripts/exportar_postman.py).
