# VITRA — Backend

A modular business API built with **FastAPI, asynchronous SQLAlchemy, and PostgreSQL**, with company-scoped authorization and database-enforced row-level security.

The implemented modules cover identity and access, companies, reference data, people, and product catalogs. The code emphasizes tenant isolation, explicit API contracts, and integration tests against a real database.

## Engineering highlights

- **Isolation across companies:** PostgreSQL row-level security (RLS), composite keys, and a runtime role with restricted privileges protect company-scoped records.
- **Transaction-scoped tenant context:** the application uses `set_config(..., true)` so a pooled connection does not retain the previous transaction's tenant.
- **Authorization before business operations:** authentication, company membership, and resource permissions are checked at the API boundary.
- **Contract consistency:** a versioned OpenAPI document supports consumers; CI checks that it matches the application.
- **Real-database testing:** Testcontainers provisions PostgreSQL and applies Alembic migrations before isolation and authorization tests.
- **Migration reversibility:** CI checks upgrade, downgrade, and a second upgrade, in addition to linting, type checking, and tests.

## Documentation

| Start here | Contents |
|---|---|
| [Local setup](docs/setup.md) | Prerequisites, environment, database roles, migration and test commands |
| [Architecture](docs/architecture.md) | Module boundaries, tenant isolation, authorization, contracts and trade-offs |
| [API guide](docs/api.md) | Authentication, active company, pagination, error responses and Postman |
| [OpenAPI contract](openapi.json) | Machine-readable API definition |
| [Integration tests](tests/) | Authorization, isolation, concurrency and domain behavior |
| [CI workflow](.github/workflows/ci.yml) | Quality, tests, migration and contract jobs |

## Stack and current scope

Python 3.12+, FastAPI, SQLAlchemy 2 async, asyncpg, PostgreSQL 17, Alembic, Pydantic, PyJWT and Argon2. Development tooling includes pytest, Testcontainers, Ruff, mypy, pre-commit and GitHub Actions. Dependency constraints are in [pyproject.toml](pyproject.toml).

This is a **modular monolith**: the domain modules share an application and database. The repository does not establish production deployment status, throughput guarantees, or a microservices deployment.

The audit module currently provides an append-only table and an explicit event-recording helper. It does **not** automatically audit every application mutation. See [the implementation and its scope](app/core/audit.py).

## Existing operational guide (Portuguese)

The original operational instructions are retained below. The English guides above provide an additional entry point into the implemented system.

---


Substituto do SoftLux 1.0.2.1521 para a Vertz. Python 3.12 + FastAPI + SQLAlchemy 2.0 async
sobre PostgreSQL 17. O plano completo está em [`plano-backend-vitra.md`](plano-backend-vitra.md);
as anotações de medição do bake-off, em [`notas-bakeoff.md`](notas-bakeoff.md).

## Estrutura do projeto

```
vitra-backend/
├── app/
│   ├── main.py                  # criar_app(): CORS, handlers de erro, montagem dos routers
│   ├── models.py                # índice de importação dos modelos (o Alembic lê daqui)
│   ├── core/                    # o que não é de nenhum domínio
│   │   ├── config.py            # Settings (pydantic-settings), prefixo /api/v1
│   │   ├── db.py                # engine async e SessionLocal
│   │   ├── deps.py              # HTTPBearer, usuário atual, sessão
│   │   ├── errors.py            # EnvelopeErro + pode_falhar()
│   │   ├── openapi.py           # documentar_erros(): respostas de erro no contrato
│   │   ├── listing.py           # ListParams, ListingSpec, Pagina, LookupItem, busca sem acento
│   │   ├── numbering.py         # numeração série+número por empresa (FOR UPDATE)
│   │   ├── permissions.py       # catálogo de permissões + require(recurso, acao)
│   │   ├── audit.py             # trilha append-only, na mesma transação da escrita
│   │   ├── security.py          # argon2, emissão e leitura de JWT
│   │   └── tenancy.py           # SET LOCAL app.current_tenant no after_begin
│   ├── common/                  # peças reaproveitadas por todos os módulos
│   │   ├── base_model.py        # ModeloBase / ModeloTenant (PK composta)
│   │   ├── base_service.py      # CRUD genérico: criar, obter, atualizar, desativar
│   │   ├── crud_router.py       # fábrica das 6 rotas repetidas por recurso
│   │   ├── child_set.py         # substituir_conjunto(): replace-set das grades, diff por PK
│   │   ├── mixins.py            # endereço, contatos, redes sociais, ativo
│   │   └── schemas.py           # Cnpj/Cpf/CpfCnpj, EnderecoCampos, ContatosCampos…
│   └── modules/                 # um pacote por domínio: models, schemas, service, router
│       ├── auth/                # login, refresh, trocar-empresa, usuários, grupos, permissões
│       │   └── deps.py          # empresa do pedido: token ou X-Empresa-Id + prova de vínculo
│       ├── empresa/             # empresa, filial, centro de custo
│       ├── apoio/               # tabela de apoio genérica (19 domínios), UF, cidade, banco
│       ├── pessoas/             # cliente/obra, fornecedor, colaborador, profissional, transportadora
│       └── produtos/            # produto, variante, preço, fornecedor do produto, relacionados
├── alembic/
│   ├── env.py
│   └── versions/                # migrações — RLS e políticas em SQL cru
├── tests/
│   ├── conftest.py              # Postgres 17 descartável (Testcontainers) + migrações
│   ├── banco.py                 # motores: dono e papel de runtime
│   ├── cenario.py               # fixtures de empresa, usuário, produto…
│   └── test_*.py
├── scripts/
│   ├── seed.py                  # permissões, UFs, cidades, bancos, empresas, admin, exemplos
│   ├── conceder_runtime.sql     # põe vitra_runtime no papel vitra_app
│   ├── init-db.sql              # papéis criados na primeira subida do container
│   ├── exportar_openapi.py      # make openapi → openapi.json
│   ├── exportar_postman.py      # make postman → postman/ (derivado do contrato)
│   └── checar_migracoes.py      # cabeça única do Alembic
├── postman/                     # gerado — não editar à mão
│   ├── vitra.postman_collection.json
│   └── vitra.postman_environment.json
├── .github/workflows/ci.yml     # qualidade, testes, migracoes, contrato
├── docker-compose.yml           # Postgres de desenvolvimento em localhost:5433
├── Makefile                     # make ajuda lista todos os alvos
├── openapi.json                 # contrato publicado — é por ele que o front gera o cliente
└── pyproject.toml
```

## Subir o ambiente

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
cp .env.example .env
make hooks                        # hooks de pre-commit — uma vez por clone

docker compose up -d db           # Postgres 17 de desenvolvimento, em localhost:5433
.venv/bin/alembic upgrade head    # roda como dono (VITRA_DATABASE_URL_ADMIN)
make runtime                      # põe vitra_runtime no papel vitra_app — uma vez por banco
.venv/bin/python scripts/seed.py  # permissões, UFs, empresas, grupos, usuário admin
.venv/bin/uvicorn app.main:app --reload
```

Ou, pelos alvos do `Makefile` (`make ajuda` lista todos):

```bash
make db && make migrar && make runtime && make seed && make api
```

A API sobe em <http://localhost:8000>, com o Swagger em <http://localhost:8000/docs> e o
health check em <http://localhost:8000/saude>. O seed cria `admin` / `admin12345` —
**troque a senha.**

Se o `docker` pedir permissão, ou você entra no grupo (`sudo usermod -aG docker $USER`, exige
relogar) ou roda com `sudo docker compose up -d db`.

## Testar a API

Todas as rotas vivem sob `/api/v1`. Duas coisas valem para praticamente todas elas:

1. **Token JWT** no `Authorization: Bearer <access_token>`, obtido em `POST /api/v1/auth/login`.
2. **Empresa ativa**, porque as tabelas por empresa são recortadas pelo Postgres (RLS) a partir
   dela. Vem de um claim no token (`POST /api/v1/auth/trocar-empresa`) **ou** do cabeçalho
   `X-Empresa-Id`, que tem prioridade quando presente. Sem nenhum dos dois, a resposta é `400`;
   com uma empresa sem vínculo, `403`.

Erro sai sempre no mesmo envelope:

```json
{
  "erro": {
    "codigo": "empresa_nao_declarada",
    "mensagem": "Nenhuma empresa ativa foi declarada no pedido.",
    "campos": {}
  }
}
```

### Pelo Swagger (`/docs`)

Com a API de pé, o Swagger UI está em <http://localhost:8000/docs> — em produção ele sai do
ar de propósito (`/docs` e `/openapi.json` são `None` quando `VITRA_AMBIENTE=producao`; o
contrato é consumido pelo `openapi.json` versionado).

1. Abra `POST /api/v1/auth/login`, **Try it out**, e envie:

   ```json
   { "login": "admin", "senha": "admin12345" }
   ```

   A resposta traz `access_token` e `refresh_token`.

2. Clique em **Authorize** (cadeado no topo), cole **só** o `access_token` — o esquema é
   `HTTPBearer`, o Swagger põe o `Bearer ` na frente — e confirme.

3. Descubra o `id` da empresa em `GET /api/v1/empresas/lookup` (o seed cria `VERTZ` e
   `VIAHF`). Copie o `id` da VERTZ.

4. Escolha a empresa ativa, de um dos dois jeitos:

   - **Token com a empresa dentro** (recomendado no Swagger): `POST /api/v1/auth/trocar-empresa`
     com `{ "empresa_id": "<id-da-vertz>" }`, e refaça o **Authorize** com o `access_token`
     novo. A partir daí nenhuma rota precisa de cabeçalho.
   - **Cabeçalho por pedido**: deixe o token como está e preencha o campo `x-empresa-id`, que
     aparece no formulário de toda rota por empresa.

5. Agora `GET /api/v1/produtos`, `GET /api/v1/clientes`, `POST /api/v1/produtos` etc.
   respondem. Se vier `400 empresa_nao_declarada`, o passo 4 não pegou; se vier `403`, o
   usuário não tem vínculo com aquela empresa.

**Listagem vazia sem erro é sintoma conhecido:** ou o filtro não casou, ou a empresa ativa é a
errada — o RLS nunca devolve dado da outra empresa, devolve nada.

### Pelo Postman

A collection já vem pronta no repositório, com as 99 rotas:

```bash
make postman   # regenera a partir do openapi.json
```

No Postman: **Import → File** → `postman/vitra.postman_collection.json` e
`postman/vitra.postman_environment.json`. Selecione o ambiente **VITRA — local** e rode a
pasta **00 — Preparo** de cima para baixo; ela guarda `token` e `empresa_id` e preenche os
`*_id` de exemplo. Sem isso, toda rota por empresa responde `400`.

O que já vem resolvido, e que o import cru do `openapi.json` não daria:

| | |
|---|---|
| Autenticação | Bearer `{{token}}` na collection inteira; login, refresh e `/saude` sem auth, como no contrato |
| Empresa ativa | `X-Empresa-Id: {{empresa_id}}` nas 92 rotas que aceitam — desligue o cabeçalho para operar pela empresa que está dentro do token |
| Encadeamento de `id` | todo `POST` guarda o `id` criado na variável que as rotas `{id}` daquele recurso consomem |
| Corpos | os das rotas principais são os exemplos deste README, conferidos contra os schemas Pydantic |
| Filtros | `busca`, `pagina`, `ordenar_por`… vêm como query params desabilitados, à vista sem alterar o request |
| Testes | nenhum 5xx, envelope de erro conferido, e path com variável vazia **falha** em vez de colapsar para a listagem e passar verde |

**A collection é gerada, não editada à mão** (`scripts/exportar_postman.py`) — o
`openapi.json` é a fonte, como para o cliente do front. Editar o JSON direto perde na
próxima geração; o que precisa mudar, muda no gerador.

**Rodar a collection inteira escreve**: 53 dos 99 requests são `POST`/`PUT`/`DELETE`. Aponte
para banco de desenvolvimento. Dentro de cada pasta o `POST` vem antes do `{id}`, então
`PUT`/`DELETE` operam sobre o registro que a própria execução criou; e as três variáveis cujo
`DELETE` faria estrago (`usuario_id` → `admin`, `grupo_id` → `Administradores`,
`empresa_recurso_id` → empresa do seed) não são pré-preenchidas de propósito.

Se preferir montar à mão, o essencial é: environment com `base_url`, `token` e `empresa_id`;
**Authorization → Bearer Token** com `{{token}}` na coleção; e no login, aba **Tests**:

```javascript
pm.environment.set("token", pm.response.json().access_token);
```

#### 1. Login — `POST {{base_url}}/api/v1/auth/login`

```json
{ "login": "admin", "senha": "admin12345" }
```

Resposta:

```json
{
  "access_token": "<jwt-de-acesso>",
  "refresh_token": "<jwt-de-refresh>",
  "token_type": "bearer"
}
```

#### 2. Empresa ativa — `POST {{base_url}}/api/v1/auth/trocar-empresa`

```json
{ "empresa_id": "3f2b8c1e-9a4d-4e5f-8b7c-1d2e3f4a5b6c" }
```

Devolve um par de tokens novo, com a empresa dentro. Alternativa sem trocar de token: mandar
`X-Empresa-Id: 3f2b8c1e-9a4d-4e5f-8b7c-1d2e3f4a5b6c` em cada pedido.

Quem sou eu e o que posso: `GET {{base_url}}/api/v1/auth/eu`.

#### 3. Listagens — `GET {{base_url}}/api/v1/produtos`

Sete parâmetros, os mesmos em todo recurso: `busca` (texto livre, **ignora acento** — `sao`
acha "São Paulo"), `busca_codigo` (exata), `pagina`, `tamanho`, `ordenar_por` (whitelist por
recurso), `ordem` (`asc`/`desc`) e `ativo` (omitido = todos).

```
GET {{base_url}}/api/v1/produtos?busca=pendente&pagina=1&tamanho=20&ordenar_por=codigo&ordem=asc&ativo=true
```

```json
{
  "itens": [
    {
      "id": "8c1e3f2b-4d5e-4a6f-9b7c-2d3e4f5a6b7c",
      "codigo": "PEND001",
      "descricao": "Pendente Aurora",
      "ativo": true,
      "preco_minimo_cents": 45900,
      "variantes": [],
      "fornecedores": [],
      "grupos_relacionados": []
    }
  ],
  "total": 1,
  "pagina": 1,
  "tamanho": 20,
  "paginas": 1
}
```

Os combos das telas (`[busca +...]`, F4/F5/F6) usam `/lookup`, que devolve sempre a mesma
forma enxuta — `GET {{base_url}}/api/v1/produtos/lookup?q=pend&limit=20`:

```json
[
  {
    "id": "8c1e3f2b-4d5e-4a6f-9b7c-2d3e4f5a6b7c",
    "codigo": "PEND001",
    "label": "Pendente Aurora",
    "extras": {}
  }
]
```

#### 4. Criar cliente — `POST {{base_url}}/api/v1/clientes`

```json
{
  "codigo": "CLI010",
  "nome": "Maria Andrade",
  "tipo_pessoa": "fisica",
  "cpf_cnpj": "123.456.789-00",
  "rg_ie": "34.567.890-1",
  "dt_nascimento": "1985-04-17",
  "telefone": "1133334444",
  "celular": "11988887777",
  "email": "maria.andrade@example.com",
  "endereco_cep": "01310-100",
  "endereco_logradouro": "Avenida Paulista",
  "endereco_numero": "1000",
  "endereco_complemento": "Conjunto 82",
  "endereco_bairro": "Bela Vista",
  "observacao": "Indicada pelo escritório ADR."
}
```

`cpf_cnpj` pode ir com máscara — a borda tira a pontuação e sobe a caixa antes de gravar.
`tipo_pessoa` é `fisica` (CPF, 11 dígitos) ou `juridica` (CNPJ, 14); mandar um documento do
tamanho errado dá `422`.

Pessoa jurídica, mesma rota:

```json
{
  "codigo": "CLI011",
  "nome": "Studio ADR Arquitetura Ltda",
  "tipo_pessoa": "juridica",
  "cpf_cnpj": "12.345.678/0001-90",
  "email": "contato@studioadr.example.com"
}
```

Obra do cliente — `POST {{base_url}}/api/v1/clientes/{cliente_id}/obras`:

```json
{
  "nome": "Residência Alphaville",
  "endereco_cep": "06474-000",
  "endereco_logradouro": "Alameda Rio Negro",
  "endereco_numero": "500",
  "endereco_bairro": "Alphaville"
}
```

#### 5. Criar produto — `POST {{base_url}}/api/v1/produtos`

O `POST` cria só o produto; as grades (variantes, fornecedores, grupos relacionados) entram
no `PUT`. Note que **não existe `tenant_id` no corpo** — a empresa vem da transação.

```json
{
  "codigo": "PEND010",
  "descricao": "Pendente Aurora 40cm",
  "descricao_complementar": "Cúpula em alumínio, cabo têxtil de 1,5 m",
  "codigo_reduzido": "PA40",
  "ncm": "94051100",
  "cest": "2110300",
  "origem": "0",
  "qtd_entrada": 1,
  "qtd_saida": 1,
  "fora_de_linha": false,
  "consultar_valor": false,
  "sobre_medida": false,
  "publicar_no_site": true,
  "especificacao": {
    "potencia_watts": 12.5,
    "tensao": "Bivolt",
    "fluxo_luminoso_lumens": 1100,
    "angulo_abertura_graus": 36,
    "temperatura_cor_kelvin": 3000,
    "ip": "IP20",
    "base_soquete": "GU10",
    "regulavel": true,
    "vida_util_horas": 25000,
    "comprimento_mm": 400,
    "largura_mm": 400,
    "altura_mm": 1200,
    "peso_kg": 2.4
  }
}
```

`especificacao` é validada campo a campo e recusa nome desconhecido (`extra="forbid"`) — um
`potencia_wats` digitado errado estoura `422` em vez de virar chave morta no JSONB. Os campos
`*_id` (`marca_id`, `tipo_produto_id`, `unidade_saida_id`, `acabamento_id`, `tamanho_id`…)
apontam para a tabela de apoio: pegue os UUIDs em
`GET {{base_url}}/api/v1/apoio/{dominio}/lookup`, com `dominio` em `marca`, `tipo_produto`,
`tipo_peca`, `unidade`, `acabamento`, `tamanho`, `classificacao`, `profissao`, `cargo`,
`setor`, `estado_civil`, … (`GET {{base_url}}/api/v1/apoio/dominios` lista os 19).

#### 6. Grades do produto — `PUT {{base_url}}/api/v1/produtos/{id}`

As três coleções são *replace-set*: a lista enviada passa a ser a lista inteira. Item **sem
`id`** é novo; **com `id`** é o existente sendo atualizado; ausente da lista, é removido.
Omitir a chave (ou mandar `null`) **não mexe** na coleção; mandar `[]` limpa.

```json
{
  "descricao": "Pendente Aurora 40cm",
  "variantes": [
    {
      "acabamento_id": "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d",
      "tamanho_id": "2b3c4d5e-6f7a-4b8c-9d0e-1f2a3b4c5d6e",
      "ativo": true
    },
    {
      "id": "9d0e1f2a-3b4c-4d5e-6f7a-8b9c0d1e2f3a",
      "acabamento_id": "3c4d5e6f-7a8b-4c9d-0e1f-2a3b4c5d6e7f",
      "tamanho_id": "2b3c4d5e-6f7a-4b8c-9d0e-1f2a3b4c5d6e",
      "ativo": true
    }
  ],
  "fornecedores": [
    {
      "fornecedor_id": "4d5e6f7a-8b9c-4d0e-1f2a-3b4c5d6e7f8a",
      "codigo_fornecedor": "LUM-AUR-40",
      "descricao_fornecedor": "Pendente Aurora 40 preto",
      "padrao": true
    }
  ],
  "grupos_relacionados": [
    { "nome": "Acessórios sugeridos", "padrao": true, "ativo": true }
  ]
}
```

Itens dentro de um grupo relacionado têm rota própria —
`POST {{base_url}}/api/v1/produtos/{produto_id}/grupos-relacionados/{grupo_id}/itens`
(`quantidade` preenchida = kit; nula = sugestão de venda cruzada):

```json
{
  "produto_id": "7f8a9b0c-1d2e-4f3a-4b5c-6d7e8f9a0b1c",
  "variante_id": "9d0e1f2a-3b4c-4d5e-6f7a-8b9c0d1e2f3a",
  "quantidade": "2.000",
  "padrao": true
}
```

Dinheiro é sempre **inteiro em centavos** (`preco_cents: 45900` é R$ 459,00) — nunca float,
nunca string com vírgula. Converter para reais é da borda que apresenta.

#### 7. Outros corpos úteis

`POST {{base_url}}/api/v1/apoio/{dominio}` — cria um valor de combo na hora (`codigo` é opcional):

```json
{ "descricao": "Alumínio escovado", "codigo": "escovado", "ordem": 10 }
```

`POST {{base_url}}/api/v1/usuarios`:

```json
{
  "login": "ana.silva",
  "nome": "Ana Silva",
  "senha": "senha-forte-123",
  "email": "ana.silva@vertz.com.br",
  "superusuario": false,
  "limite_desconto_pct": "10.0000",
  "grupo_ids": ["5e6f7a8b-9c0d-4e1f-2a3b-4c5d6e7f8a9b"]
}
```

`POST {{base_url}}/api/v1/auth/alterar-senha` (o próprio usuário; responde `204`):

```json
{ "senha_atual": "admin12345", "senha_nova": "outra-senha-forte" }
```

`POST {{base_url}}/api/v1/fornecedores/{fornecedor_id}/empresas-compradoras` — abre uma vigência e
fecha a anterior na mesma transação:

```json
{
  "empresa_compradora_id": "3f2b8c1e-9a4d-4e5f-8b7c-1d2e3f4a5b6c",
  "vigencia_inicio": "2026-08-01",
  "motivo": "Centralização de compras na matriz"
}
```

`vigencia_inicio` não pode ser futura, e um índice único parcial impede duas vigências
abertas ao mesmo tempo.

`POST {{base_url}}/api/v1/auth/refresh`, quando o access expirar:

```json
{ "refresh_token": "<jwt-de-refresh>" }
```

Cadastro não se apaga: `DELETE /recurso/{id}` desativa (`ativo = false`) e devolve o registro.

### Pela linha de comando (newman)

A mesma collection roda sem abrir o Postman. Útil para varrer a API inteira depois de mexer
em algo transversal — uma dependência do FastAPI, um handler de erro, o RBAC — e ver o que
mudou de comportamento em 99 rotas de uma vez.

```bash
npx newman run postman/vitra.postman_collection.json
```

Além dos testes de cada request, a collection aplica dois a **todos** eles: nada de 5xx, e
resposta de erro no envelope `{"erro": {…}}`. É uma checagem barata de uma invariante que
nenhum teste unitário cobre de ponta a ponta.

**Isto escreve no banco** — 53 dos 99 requests são `POST`/`PUT`/`DELETE`. Aponte para um
Postgres descartável, ou rode só o que lê:

```bash
jq '.item |= map(if (.name | startswith("00")) then .
                 else (.item |= map(select(.request.method == "GET"))) end)
    | .item |= map(select(.item | length > 0))' \
   postman/vitra.postman_collection.json > /tmp/vitra-leitura.json

npx newman run /tmp/vitra-leitura.json
```

Mantém a pasta de preparo inteira (precisa dos dois `POST` de login e troca de empresa, que
não tocam em cadastro) e descarta todo o resto que não é `GET`.

Para outro alvo, `--env-var`:

```bash
npx newman run postman/vitra.postman_collection.json --env-var base_url=http://staging.local
```

Vermelho de **"nenhuma variável de path ficou vazia"** não é falha da API: é o recurso não
ter nenhum registro para a rota `{id}` mirar. Numa varredura só de leitura isso é esperado
para o que o seed não cria (colaborador, obra, centro de custo, profissional externo) e para
`usuario_id`/`grupo_id`/`empresa_recurso_id`, que só o `POST` do recurso preenche — ver a
descrição da collection.

## Qualidade — pre-commit e CI

O CI (`.github/workflows/ci.yml`) roda **os mesmos hooks** do pre-commit, pela mesma
configuração. Não é uma segunda lista de comandos parecida: duas listas divergem, e o dia em
que divergirem o CI vai reprovar código que o hook local acabou de aprovar — que é o jeito
mais rápido de ensinar o time a usar `--no-verify`.

```bash
make hooks       # instala os hooks (uma vez por clone)
make qualidade   # roda todos eles em todos os arquivos, igual ao CI
make checar      # qualidade + suíte + ida e volta das migrações
```

| Quando | O que roda |
|---|---|
| `commit` | higiene de arquivo, ruff (check + format), mypy, gitleaks, cabeça única do Alembic |
| `commit-msg` | Conventional Commits |
| `push` | a suíte inteira (sobe Postgres, ~35 s) |

`pytest` fora do commit é decisão: um hook de 35 s a cada commit ensina o time a pular o
hook, e aí nenhum deles roda. No push o custo é aceitável e a proteção é a mesma.

**ruff e mypy são hooks `local`**, rodando as ferramentas do próprio ambiente do projeto, em
vez do `astral-sh/ruff-pre-commit`. Dois motivos: o `rev` do hook e o pin do
`pyproject.toml` são dois lugares que divergem no dia em que alguém atualiza um e esquece o
outro — e um bump de patch do ruff reformata a árvore inteira; e o mypy precisa das
dependências instaladas, senão não enxerga os stubs do SQLAlchemy nem o plugin do Pydantic e
passa a aprovar o que o CI reprova. Por isso `ruff` e `mypy` vão **pinados** no
`pyproject.toml`, enquanto o resto usa piso.

Quatro jobs no CI, cada um cobrindo uma falha diferente:

| Job | O que pega |
|---|---|
| `qualidade` | tudo que o pre-commit pega, para quem passou `--no-verify` |
| `testes` | a suíte, com Postgres 17 descartável e migrações aplicadas |
| `migracoes` | cabeça única e **ida → volta → ida**: o `downgrade` que esquece de apagar política ou tipo `ENUM` só falha na segunda ida |
| `contrato` | `openapi.json` desatualizado no repositório — é por ele que o front gera o cliente |

## Dependências

Pisos alinhados à última estável, com `ruff` e `mypy` pinados. O Dependabot
(`.github/dependabot.yml`) abre PR semanal do ferramental e mensal do runtime, das actions,
da imagem do Postgres e dos hooks de terceiros — dependência não envelhece por esquecimento.

```bash
make atualizar   # sobe tudo para a última estável e reconfere
```

## Testes

```bash
.venv/bin/pytest -q      # ou: make testes
```

Cada execução **sobe um Postgres 17 descartável** (Testcontainers) e aplica as migrações,
RLS incluído. É o único jeito de testar política de segurança sem deixar resíduo — e de
garantir que o RLS está *na migração*, não só no banco de alguém. `Base.metadata.create_all`
não serviria: ele não cria política nenhuma, e a suíte de isolamento inteira passaria contra
um banco sem trava.

Os testes de isolamento conectam como **papel de runtime**, não como dono. Rodá-los como dono
ou superusuário faz todos passarem sem provar nada.

Precisa de Docker. Para iterar sem subir container a cada rodada, aponte
`VITRA_TESTE_URL_EXTERNA` para um Postgres já de pé — o schema continua sendo recriado a
partir das migrações.

