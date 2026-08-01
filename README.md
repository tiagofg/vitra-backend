# VITRA — Backend

Substituto do SoftLux 1.0.2.1521 para a Vertz. Python 3.12 + FastAPI + SQLAlchemy 2.0 async
sobre PostgreSQL 17. O plano completo está em [`plano-backend-vitra.md`](plano-backend-vitra.md).

**Estado: S0 (Fundação), SB (Bake-off), S0.5 (Unificação) e S1 (Cadastros de pessoas)
entregues.** As demais fases estão no plano.
As anotações de medição do bake-off ficam em [`notas-bakeoff.md`](notas-bakeoff.md).

## O que a S0 entrega

| Bloco | Onde |
|---|---|
| Config, sessão async, envelope de erro único | `app/core/config.py`, `db.py`, `errors.py` |
| Contrato OpenAPI com as respostas de erro declaradas | `app/core/openapi.py` |
| `ListParams` — a barra de 7 ações das listagens | `app/core/listing.py` |
| Numeração série+número por empresa, com `FOR UPDATE` | `app/core/numbering.py` |
| RBAC granular recurso+ação | `app/core/permissions.py` |
| Auditoria append-only, na mesma transação da escrita | `app/core/audit.py` |
| Mixins de endereço, contatos, redes sociais, empresa | `app/common/mixins.py` |
| *Replace-set* das GRADEs editáveis (diff por PK) | `app/common/child_set.py` |
| Busca sem acento (`vitra_unaccent`, wrapper `IMMUTABLE`) | `app/core/listing.py` |
| Auth JWT (access + refresh), argon2 | `app/modules/auth/` |
| Empresa, filial, centro de custo | `app/modules/empresa/` |
| Tabela de apoio genérica (19 combos) + cidade/banco/UF | `app/modules/apoio/` |

## O que a SB entrega

| Bloco | Onde |
|---|---|
| As 7 tabelas do schema compartilhado, PK composta `(tenant_id, id)` | `app/modules/produtos/`, `empresa/`, `auth/`, `apoio/` — índice em `app/models.py` |
| `SET LOCAL app.current_tenant` no `after_begin` | `app/core/tenancy.py` |
| Borda HTTP da empresa ativa: token, cabeçalho e vínculo | `app/modules/auth/deps.py` |
| Migração das 7 tabelas + RLS em SQL cru (4 políticas por tabela) | `alembic/versions/b1c2d3e4f5a6_rls_multiempresa.py` |
| Testes de isolamento, contra Postgres real e como papel de runtime | `tests/test_rls_isolamento.py` |
| Concorrência: pedidos simultâneos de empresas diferentes | `tests/test_bakeoff_concorrencia.py` |
| Quem pode pedir por qual empresa (401 / 400 / 403) | `tests/test_bakeoff_autorizacao.py` |
| Listagem de produtos server-side (busca, ordenação, paginação) | `app/modules/produtos/service.py` |
| OpenAPI publicado | `make openapi` → `openapi.json` |

O módulo `bakeoff`, que era um pacote à parte, foi dissolvido nos módulos de domínio: as 7
tabelas moram onde o assunto delas mora (`products`/`product_variants`/`product_tenant` em
`produtos`, `tenants` em `empresa`, `employees`/`employee_company` em `auth`,
`catalog_lookups` em `apoio`). Os testes mantêm o nome `test_bakeoff_*` porque continuam
provando os entregáveis do bake-off.

## O que a S1 entrega

| Bloco | Onde |
|---|---|
| Cliente (com `obra`, subrecurso), fornecedor (com histórico de empresa compradora), colaborador, profissional externo, transportadora | `app/modules/pessoas/` |
| Fábrica de router CRUD — as seis rotas repetidas (listar, lookup, criar, obter, atualizar, desativar) por recurso | `app/common/crud_router.py` |
| Migração das 7 tabelas + RLS (mesma forma da migração do bake-off) | `alembic/versions/af281e86c3d5_pessoas_*.py` |
| `Cpf`/`CpfCnpj` — mesma normalização de `Cnpj`, para PF | `app/common/schemas.py` |

Todas por empresa (`ModeloTenant`, PK composta), com nome físico de tabela em
**português** — `cliente`, `obra`, `fornecedor`, `colaborador` — ao contrário das 7 tabelas
herdadas do bake-off, cujo DDL compartilhado era fixo. Ver "Convenções que valem para todas
as fases" abaixo.

`fornecedor_empresa` é histórico com vigência, não coluna: `POST
/fornecedores/{id}/empresas-compradoras` abre uma vigência e fecha a anterior na mesma
transação; um índice único parcial (`WHERE vigencia_fim IS NULL`) impede duas vigências
abertas ao mesmo tempo. FKs para `catalog_lookups` (`profissao_id`, `cargo_id`, …) são
conferidas contra o domínio esperado em `_antes_de_criar`/`_antes_de_atualizar` — a FK do
banco garante só que o `id` existe em `catalog_lookups`, não que é do domínio certo.

## Multiempresa: quem recorta é o banco

O recorte entre empresas **não** é um `WHERE empresa_id = ...` que alguém pode esquecer. Toda
tabela por empresa tem `FORCE ROW LEVEL SECURITY` e quatro políticas sobre o mesmo predicado;
a transação declara a empresa ativa e o Postgres faz o resto.

Três consequências que mudam como se lê e se escreve o código aqui:

- **O serviço não escreve filtro de empresa.** Se você viu um `WHERE tenant_id` numa query,
  ou é bug ou é tabela global. Ver `app/modules/produtos/service.py`.
- **Esquecer a empresa dá listagem vazia, nunca dado da empresa errada.** É a propriedade que
  se está comprando. Em troca, "voltou vazio do nada" vira sintoma comum em desenvolvimento —
  e a primeira hipótese é sempre a mesma: faltou declarar a empresa. Nas rotas, isso falha
  com `400` na borda em vez de devolver lista vazia.
- **A aplicação nunca conecta como dono do banco.** `vitra` roda as migrações; `vitra_runtime`
  roda a API, sem ser dono e sem `BYPASSRLS`. Conectar como dono ou superusuário faz o
  Postgres ignorar as políticas, e aí o RLS é decorativo.

### Declarar não é autorizar

As rotas por empresa pedem token **e** uma empresa ativa, nesta ordem de checagem
(`app/modules/auth/deps.py`):

| Pergunta | Falha com |
|---|---|
| Quem é? | `401` sem token |
| Qual empresa? | `400` sem claim `tenant` no token e sem `X-Empresa-Id` |
| Pode essa empresa? | `403` sem vínculo em `employee_company` |

A terceira não é redundante com o RLS — é o que separa duas defesas diferentes:

- o **RLS** entrega imunidade a `WHERE` esquecido no serviço;
- a **borda HTTP** entrega imunidade a chamador malicioso.

Sem a checagem de vínculo, o encadeamento seria *RLS confia no GUC → GUC confia no cabeçalho
→ cabeçalho vem do cliente*: a política do Postgres protegeria um recorte escolhido por quem
chama. A checagem roda **sob a própria política** — a empresa é declarada antes, então a
consulta a `employee_company` já sai recortada, sem filtro escrito à mão.

A decisão que estava aberta no plano — *claim no JWT* em vez de cabeçalho — está tomada e
implementada: o token carrega a empresa ativa (`ClaimsToken.tenant_id`), obtida em
`POST /auth/trocar-empresa`, e o cliente opera sem enviar cabeçalho nenhum. O `X-Empresa-Id`
sobrevive e **tem prioridade** quando presente, para quem opera em mais de uma empresa (o
caso da ANA SILVA) e quer trocar sem trocar de token. Os dois caminhos passam pela mesma
checagem de vínculo: um cabeçalho forjado não vale mais que um claim forjado, porque nenhum
dos dois é aceito sem prova em `employee_company`.

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

OpenAPI em <http://localhost:8000/docs>. O seed cria `admin` / `admin12345` — **troque a senha.**

Se o `docker` pedir permissão, ou você entra no grupo (`sudo usermod -aG docker $USER`, exige
relogar) ou roda com `sudo docker compose up -d db`.

### O banco compartilhado do bake-off

`vitra_bakeoff` (PostgreSQL 17 no Neon) é usado **ao mesmo tempo** pelos devs das outras duas
stacks. Daí as regras não serem burocracia:

- **Não criar, alterar ou apagar tabela lá.** A estrutura é fixa. A migração se testa
  localmente, em Postgres descartável, recriando a mesma estrutura.
- **Nenhum teste escreve lá.** Hoje nenhum teste da suíte sequer aponta para lá: tudo roda
  contra o Postgres descartável. Teste novo que dependa do Neon é só leitura, e precisa ser
  pulável sem a variável — no CI ela vem vazia (`VITRA_BAKEOFF_DATABASE_URL: ""`). Um teste
  que suja o dado sujou para os outros dois times.
- A string de conexão traz senha real e vive **só no `.env`**. O `.env.example` documenta a
  variável (`VITRA_BAKEOFF_DATABASE_URL`), nunca o valor.
- O Neon suspende o banco após alguns minutos ocioso: a primeira conexão depois disso leva
  1–2 s. Não é queda.
- Bagunçou o dado: avisar o Henrique, que reseta em ~1 min.

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
.venv/bin/pytest -q
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

## Convenções que valem para todas as fases

- **Router só orquestra.** Regra de negócio no service; nenhum `select()` em router.
- **Tabela por empresa tem PK composta `(tenant_id, id)`**, e toda FK entre tabelas por
  empresa carrega o `tenant_id` junto. É o que torna *fisicamente impossível* ligar o preço
  da empresa A ao produto da empresa B — o `INSERT` falha, não é validação de serviço.
- **Nome de tabela e de coluna em português** para o que nasce neste projeto (`cliente`,
  `filial`, `centro_custo`…). As 7 tabelas herdadas do bake-off (`products`,
  `product_variants`, `product_tenant`, `tenants`, `employees`, `employee_company`,
  `catalog_lookups`) continuam em inglês — o DDL do banco compartilhado do Neon era fixo
  quando elas nasceram, e reescrevê-lo não paga. Classe ORM, serviço, rota e mensagem de
  erro **sempre em português**, que é a língua do domínio.
- **Dinheiro é `BIGINT` em centavos** (`price_cents`): R$ 12,34 é `1234`. Nunca float, nunca
  `Numeric`. Converter para reais é da borda que apresenta, nunca do banco. Nenhuma tabela
  guarda dinheiro em `Numeric` desde a S0.5.
- **Quantidade** `Numeric(14,3)` com `CHECK >= 0`; **percentual** `Numeric(9,4)`.
- **CNPJ/CPF** `varchar(14)`, caixa alta e **sem máscara** — já pronto para o CNPJ
  alfanumérico, que vale a partir de 31/07/2026. `Cnpj`/`Cpf`/`CpfCnpj`
  (`app/common/schemas.py`) tiram a máscara e sobem a caixa na borda.
- **Cadastro não se apaga** — `DELETE /recurso/{id}` desativa (`ativo = false`). Documentos de
  venda vão **cancelar** (`POST /{id}/cancelar`), a partir da S4.
- **Erro sai sempre no mesmo envelope**: `{"erro": {"codigo", "mensagem", "campos"}}` —
  modelado em `EnvelopeErro` (`app/core/errors.py`) e publicado no contrato, porque o front
  gera o cliente a partir do OpenAPI e precisa conhecer também os caminhos de erro.
- **Falha se declara onde ela nasce.** A dependência que exige token, empresa ou permissão
  declara a sua com `pode_falhar(...)`, e a rota herda pelo grafo do FastAPI; a rota só
  declara o que apenas o serviço sabe (404, 409, regra de negócio). Nenhuma rota escreve
  `responses=` à mão — 55 listas paralelas divergiriam na primeira rota nova.
- **Toda rota mutante** passa por `Depends(require(recurso, acao))`, e o par precisa estar no
  catálogo de `app/core/permissions.py` — errar o nome estoura na importação, não em produção.
- **`ordenar_por` é whitelist** por recurso, declarada no `ListingSpec`.
- **Busca textual ignora acento** — use `contem_sem_acento()` de `app/core/listing.py`, nunca
  `.ilike()` cru: `?busca=sao` precisa achar "São Paulo".

## Fora de escopo (decisão registrada no plano)

Sem motor fiscal e sem NFe — `ncm`/`cest`/`origem` serão apenas gravados no produto (S2).
Financeiro, CRM, metas, ganhos sobre vendas e relatórios ficam para depois desta entrega.
