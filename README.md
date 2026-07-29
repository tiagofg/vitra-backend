# VITRA — Backend

Substituto do SoftLux 1.0.2.1521 para a Vertz. Python 3.12 + FastAPI + SQLAlchemy 2.0 async
sobre PostgreSQL 16. O plano completo está em [`plano-backend-vitra.md`](plano-backend-vitra.md).

**Estado: F0 (Fundação) entregue.** As demais fases estão descritas no plano.

## O que a F0 entrega

| Bloco | Onde |
|---|---|
| Config, sessão async, envelope de erro único | `app/core/config.py`, `db.py`, `errors.py` |
| `ListParams` — a barra de 7 ações das listagens | `app/core/listing.py` |
| Numeração série+número por empresa, com `FOR UPDATE` | `app/core/numbering.py` |
| RBAC granular recurso+ação | `app/core/permissions.py` |
| Mixins de endereço, contatos, redes sociais, empresa | `app/common/mixins.py` |
| *Replace-set* das GRADEs editáveis (diff por PK) | `app/common/child_set.py` |
| Busca sem acento (`vitra_unaccent`, wrapper `IMMUTABLE`) | `app/core/listing.py` |
| Auth JWT (access + refresh), argon2 | `app/modules/auth/` |
| Empresa, filial, centro de custo | `app/modules/empresa/` |
| Tabela de apoio genérica (19 combos) + cidade/banco/UF | `app/modules/apoio/` |

Os cinco mecanismos transversais do plano existem e estão testados — é o que faz F1–F5
serem, em boa parte, composição em vez de código novo.

## Subir o ambiente

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
cp .env.example .env

docker compose up -d db          # Postgres em localhost:5433 (cria vitra e vitra_teste)
.venv/bin/alembic upgrade head
.venv/bin/python scripts/seed.py # permissões, UFs, empresas, usuário admin
.venv/bin/uvicorn app.main:app --reload
```

OpenAPI em <http://localhost:8000/docs>. O seed cria `admin` / `admin12345` — **troque a senha.**

Se o `docker` pedir permissão, ou você entra no grupo (`sudo usermod -aG docker $USER`, exige
relogar) ou roda com `sudo docker compose up -d db`.

## Testes

```bash
.venv/bin/pytest -q
```

Rodam contra o banco `vitra_teste` (criado pelo `scripts/init-db.sql` no primeiro start do
container). Cada teste roda dentro de uma transação desfeita no fim; o teste de concorrência da
numeração abre transações reais de propósito.

## Convenções que valem para todas as fases

- **Router só orquestra.** Regra de negócio no service; nenhum `select()` em router.
- **Dinheiro** `Numeric(15,2)`, **percentual** `Numeric(9,4)`, **quantidade** `Numeric(15,4)`.
  Nunca `float`.
- **Toda tabela** tem `id` UUID, `criado_em`, `atualizado_em`, `criado_por_id`.
- **Cadastro não se apaga** — `DELETE /recurso/{id}` desativa (`ativo = false`). Documentos de
  venda vão **cancelar** (`POST /{id}/cancelar`), a partir da F4.
- **Erro sai sempre no mesmo envelope**: `{"erro": {"codigo", "mensagem", "campos"}}`.
- **Toda rota mutante** passa por `Depends(require(recurso, acao))`, e o par precisa estar no
  catálogo de `app/core/permissions.py` — errar o nome estoura na importação, não em produção.
- **`ordenar_por` é whitelist** por recurso, declarada no `ListingSpec`.
- **Busca textual ignora acento** — use `contem_sem_acento()` de `app/core/listing.py`, nunca
  `.ilike()` cru: `?busca=sao` precisa achar "São Paulo".

## Fora de escopo (decisão registrada no plano)

Sem motor fiscal e sem NFe — `ncm`/`cest`/`origem` serão apenas gravados no produto (F2).
Financeiro, CRM, metas, ganhos sobre vendas e relatórios ficam para depois desta entrega.
