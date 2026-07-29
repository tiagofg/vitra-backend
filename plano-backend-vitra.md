# Plano — Backend VITRA (substituto do SoftLux) em Python + FastAPI + SQLAlchemy

> **Escopo:** este documento cobre **apenas o servidor, em Python/FastAPI**, neste repositório.
> O **front** do VITRA já está decidido e em construção em TypeScript (Next.js 16, Tailwind +
> shadcn/ui, TanStack Query/Table, react-hook-form + Zod) — não é assunto daqui. Os protótipos
> .NET e Litestar do bake-off são de outros devs, em outros repositórios.
>
> O que o VITRA já decidiu sobre **dado e domínio** vale para nós independentemente de qual
> stack de servidor vencer. Está reunido em "O que herdamos do resto do VITRA".

## Contexto

A Vertz opera hoje no **SoftLux 1.0.2.1521** (Fácil IT Software), um ERP desktop Windows para
iluminação/decoração. Temos duas fontes: `~/Downloads/softlux-telas-transcricao.md` (transcrição
literal de 20 telas) e `~/Downloads/Telas Softlux.pdf` (12 páginas de capturas). O objetivo é
reconstruir as funções desse sistema como um backend HTTP próprio.

**Estado:** a S0 está entregue neste repositório. Em seguida entra o **bake-off**, que decide
qual stack leva o servidor do VITRA. Ele trouxe consigo uma mudança arquitetural que este plano
absorveu por inteiro: **multiempresa deixa de ser `empresa_id` filtrado no serviço e passa a ser
Row-Level Security com chave composta**. Ver "Multiempresa por RLS", "Bake-off" e "Retrabalho na
S0 já entregue".

Se a nossa stack **não** for a escolhida, o que sobrevive deste plano é o modelo de dados e as
decisões de domínio — as ~20 telas, os 5 mecanismos, o que o legado ensina. Vale para quem
implementar, em qualquer linguagem.

**Correção às fontes:** a transcrição lista `Movimentação`, `Financeiro`, `Relatórios`,
`Controle de Acesso` e `Sistema` como "menus inteiros não capturados". **Eles estão no PDF**
(páginas 10–12). Conteúdo real, que este plano já incorpora:

| Menu | Itens |
|---|---|
| `Movimentação` (p.10) | Liberar Separação e Entrega · Controle de Entrega · Estoque ▸ · Transferência para Filial · Requisição de Produtos · Gerenciamento de Entrega · Fechamento de Entrega |
| `Financeiro` (p.11) | Contas a Pagar ▸ · Contas a Receber ▸ (Lançamento, Quitação em Lote) · Caixa ▸ · Movimentos Bancários ▸ · Controle de Acerto com Eletricista · Controle de Crédito do Cliente / Junto ao Fornecedor (+ consultas) · Controle de Cheque Recebido / Emitido\Repassado · Controle de Crédito do RH · Participações · Controle de Crédito do Profissional · Controle de Duplicata e Recibo · Emissão de Boleto e Arquivo de Remessa |
| `Relatórios` (p.11) | Venda · Tabela de Preço · Estoque · Gerencial · Financeiro · Compras · CRM · Controle de Entrega · Etiquetas |
| `Controle de Acesso` (p.12) | Troca de Usuário · Alterar Senha · Grupo · Usuário · Permissões de Acesso |
| `Sistema` (p.12) | Configuração ▸ · Importação ▸ (Importar Produtos, Produtos via Planilha) · Exportação ▸ · Manutenção ▸ · Enviar E-mail · Gerador de Etiquetas · Carregar Chave de uso · Editor de Texto |

`Tabelas` e `CRM` continuam sem captura.

## O que herdamos do resto do VITRA

Fonte: espaço **VITRA** no Confluence — "Resumo Executivo para Devs" e "Guia de Engenharia"
(Partes 1–3 e Etapas de Desenvolvimento). Nada disso está em disputa no bake-off: é contrato,
e o servidor que vencer terá que respeitar. O estado vivo do projeto mora na memória do repo
`doutorferr0/projetos-claude` (pasta `vertz-erp`) e **vence** qualquer página, inclusive esta.

**Convenções de dado — vinculantes:**

| Regra | Detalhe |
|---|---|
| Dinheiro | inteiro em centavos (`bigint`). R$ 1.234,56 = `123456`. Nunca float |
| Quantidade | `numeric(14,3)` com `CHECK >= 0` |
| CNPJ/CPF | `varchar(14)`, **caixa alta, sem máscara**, já pronto para o CNPJ alfanumérico (regra vale a partir de 31/07/2026) |
| Atributos flexíveis | `JSONB` **tipado**, validado por schema na aplicação (specs de luminária, dados fiscais, endereços) |
| Estoque | `stock_qty` é saldo **derivado**; todo movimento grava o lançamento na **mesma transação** |
| Auditoria | append-only, gravada **na mesma transação** do dado que a originou. Não é fase futura |
| Banco | PostgreSQL 17 é o **único** armazenamento — negócio, sessão, auditoria, eventos e filas |

**Planos de dado.** O modelo separa o que é do grupo do que é de cada CNPJ:

- **Global:** identidade de funcionários, catálogo mestre de produtos, **fornecedores, clientes e
  profissionais**.
- **Por empresa (`tenant_id`):** preço, estoque, vínculo de papel, documentos.

Hierarquia: `organizations` → `tenants` (1 CNPJ = 1 tenant) → `employees` (identidade global) →
`employee_company` (N:N, papel por empresa). E `products` (mestre) → `product_variants`
(acabamento × tamanho) → `product_tenant` (preço/estoque/fiscal por empresa).

> ⚠️ **Divergência a resolver com o Henrique.** O Resumo Executivo põe o **catálogo mestre no
> plano global**; o DDL do bake-off cria `products` **com `tenant_id` e RLS**. São desenhos
> diferentes. No bake-off seguimos o DDL, que é fixo. Para o VITRA real, isso precisa de
> decisão — e ela muda onde clientes e fornecedores vivem também.

**Isolamento: dois desenhos em jogo.** O VITRA implementou isolamento na **camada de aplicação**,
com helpers tipados — `scoped(empresaAtiva)` para leitura/escrita, `groupScoped(vínculos)` para
leitura consolidada do grupo (somente-leitura *por tipo*, e auditada), com o acesso cru ao banco
**não exportado**. RLS aparece ali como "segunda camada opcional". O bake-off inverte: RLS é a
trava primária. Não é contradição a resolver por nós — é justamente uma das coisas que o
bake-off está medindo.

O que isso corrige neste plano: **leitura consolidada entre empresas não é impossível sob RLS.**
`groupScoped` é requisito real, e sob RLS ele vira um predicado que aceita lista
(`tenant_id = ANY(...)`) num caminho separado, somente-leitura e auditado — não um furo na
política. Escrita cruzada continua proibida.

**Fiscal.** Delegado ao **Focus NFe**; o sistema monta o documento e guarda o retorno, não emite.
E **nasce com os grupos IBS/CBS da Reforma** — NF-e sem eles passa a ser rejeitada em
**03/08/2026**. Continua fora do escopo do servidor nesta fase, mas o modelo de item precisa
guardar o que a emissão vai pedir.

**Qualidade.** Teste de isolamento roda contra **Postgres real**, nunca dublê, com fixtures de
sufixo único por execução — e prova o **caso positivo antes do negativo**, para que uma fixture
vazia *reprove* o teste em vez de deixá-lo passar por acidente. CI sobe Postgres efêmero, aplica
migrations e roda tudo; CI vermelho = sessão não terminou.

**Processo.** Cada decisão arquitetural relevante vira um **ADR**. Commits Conventional, curtos,
focados no *porquê*. Trunk único com feature flags. Segredo nunca entra no repositório.

**Produção** é self-hosted (VPS em São Paulo + Dokploy + Cloudflare), por soberania de dado e
LGPD. O Neon é **só** banco de desenvolvimento e do bake-off.

## Decisões travadas com o usuário

1. **Escopo desta entrega: núcleo comercial.** Cadastros, produtos com variantes, estoque com
   endereçamento, orçamento/pedido de venda, pedido e ordem de compra. Financeiro, CRM, metas,
   ganhos sobre vendas e relatórios ficam para fases seguintes — mas o modelo não os impede.
2. **Multiempresa imposta pelo banco, não pelo código.** Row-Level Security + chave primária
   composta `(tenant_id, id)` em toda tabela por empresa. A aplicação declara a empresa ativa
   no início da transação; a partir daí o Postgres só mostra e só aceita linhas daquela
   empresa. Ver "Multiempresa por RLS" — é a decisão mais estruturante do projeto e
   **substitui** o desenho anterior de `empresa_id` filtrado no serviço.
   Vínculo fornecedor↔empresa compradora continua **histórico com vigência**, não coluna.
3. **Fiscal fora de escopo.** `ncm`, `cest`, `origem` ficam como campos do produto para não
   perder o dado; **não** se constrói o motor de regra `NCM × Operação × CFOP × Consumidor
   Final × UF` nem emissão de NFe agora. Ver "Dívida assumida".
4. **RBAC granular recurso+ação**, espelhando `Grupo` / `Usuário` / `Permissões de Acesso`,
   mais autorização pontual por documento (o botão `Permissões` do orçamento).

## Princípio que dimensiona o trabalho

A transcrição (seção 9) já entrega a conclusão que importa: **não são 20 telas, são 8 padrões.**
No backend eles viram **5 mecanismos transversais**, escritos uma vez e reusados. É isso que faz
o projeto caber:

| Padrão da tela | Mecanismo no backend |
|---|---|
| `[combo +...]` — 19 ocorrências | **Uma** tabela de apoio genérica com discriminador `dominio` + um router CRUD genérico. Não 19 tabelas. |
| GRADE editável — 10 ocorrências | Coleções filhas com *replace-set* transacional no PUT do pai (diff por PK, não delete-all/insert-all). |
| `[busca +...]` / F4/F5/F6 — 10 ocorrências | Endpoints `/lookup` padronizados: `q`, `limit`, retorno `{id, codigo, label, extras}`. Busca **insensível a acento** — quem digita não põe acento. |
| Listagem com barra de 7 ações — 3 telas | Um `ListParams` comum: `busca_codigo`, filtros, ordenação, paginação. `Excluir` vira `DELETE`; `Cancelar` vira `POST /{id}/cancelar`. |
| Documento cabeçalho+itens+totais — 3 telas | Classe base de documento: numeração série+número, máquina de estados, recálculo de totais no serviço, nunca no cliente. |

Os outros três padrões resolvem-se por mixins (formulário com abas), por RLS (recorte por
empresa — o serviço **não** escreve filtro nenhum) e por rotas somente-GET.

## Stack

- Python 3.12, **FastAPI**, **SQLAlchemy 2.0 async** (`Mapped[...]` / `mapped_column`), asyncpg
- **PostgreSQL 17** — no bake-off hospedado no Neon (região São Paulo), com pooler e
  `sslmode=require`. Fora do bake-off, Postgres local. Nada no código depende do Neon
- **Alembic** para migrações, incluindo o RLS em SQL cru; extensão `unaccent` (busca sem
  acento) e `pgcrypto` (`gen_random_uuid`)
- Pydantic v2 (`pydantic-settings` para config)
- `argon2-cffi` para senha, JWT via `pyjwt`
- pytest + pytest-asyncio + httpx.AsyncClient; banco de teste **descartável via
  Testcontainers** — não mais um container fixo, porque cada suíte precisa recriar o RLS do zero
- ruff + mypy, docker-compose para dev

**Regras de tipo não negociáveis:**
- dinheiro: **`BIGINT` em centavos** (`price_cents`) — R$ 12,34 é `1234`. Nunca float, nunca
  `Numeric`. A conversão para reais é responsabilidade da borda (schema de saída), nunca do banco
- quantidade: `Numeric(14, 3)`, com `CHECK (>= 0)` onde o saldo não pode furar
- percentual: `Numeric(9, 4)` — o total do orçamento mostra `Desconto 0,0010 %`, são 4 casas
- CNPJ/CPF: `varchar(14)`, **caixa alta e sem máscara**. A S0 gravou `varchar(18)` com máscara;
  está errado e entra no retrabalho. Sem máscara também é o que o CNPJ alfanumérico exige
- tabela por empresa: **PK composta `(tenant_id, id)`**, e toda FK entre tabelas por empresa
  carrega o `tenant_id` junto — `FOREIGN KEY (tenant_id, product_id) REFERENCES products
  (tenant_id, id)`. É o que torna *fisicamente impossível* ligar o preço da empresa A ao
  produto da empresa B
- tabela global (sem `tenant_id`): PK `id` UUID simples
- toda busca textual (`?busca=` e `/lookup?q=`) passa por `vitra_unaccent` nos **dois** lados,
  para `sao` achar `São Paulo` e `são` achar `Sao`. É wrapper `IMMUTABLE` sobre `unaccent()`,
  justamente para poder virar índice funcional quando o volume pedir

**Idioma dos identificadores.** O schema compartilhado do bake-off é fixo e está em inglês
(`tenants`, `products`, `product_variants`). Como não se pode alterar DDL lá, **nome de tabela e
de coluna passa a ser em inglês** em todo o projeto — schema bilíngue seria pior que qualquer
uma das duas opções. Classe ORM, serviço, rota e mensagem de erro **continuam em português**:
é a língua do domínio e da equipe, e o mapeamento explícito do SQLAlchemy absorve a diferença
(`class Produto(...): __tablename__ = "products"`).

## Multiempresa por RLS — o mecanismo

O recorte entre empresas deixa de ser um `WHERE empresa_id = ...` que alguém pode esquecer e
passa a ser política do Postgres. Duas peças:

**1. Toda transação declara a empresa ativa.**

```sql
SET LOCAL app.current_tenant = '<uuid da empresa>';
```

`SET LOCAL`, nunca `SET`: vale até o fim da transação e por isso é seguro com pool de conexão —
a conexão devolvida ao pool não carrega a empresa do request anterior.

**2. Cada tabela por empresa tem RLS ligado e quatro políticas** (SELECT/INSERT/UPDATE/DELETE),
todas sobre o mesmo predicado:

```sql
tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid
```

O `NULLIF` é obrigatório: sem ele, uma conexão de pool que ainda não recebeu `SET LOCAL` tenta
converter string vazia para uuid e **estoura**, em vez de simplesmente não casar. Com ele, o
predicado dá `NULL`, nada casa, e a consulta volta vazia.

Consequências que precisam ficar explícitas, porque mudam como se lê e se escreve o código:

- **Esquecer a empresa dá listagem vazia, nunca dado da empresa errada.** É a propriedade que
  se está comprando. Em troca, "voltou vazio do nada" passa a ser um sintoma comum em
  desenvolvimento, e a primeira hipótese é sempre a mesma: faltou o `SET LOCAL`.
- **`ENABLE` não basta, tem que ser `FORCE ROW LEVEL SECURITY`** — o dono da tabela ignora RLS
  por padrão. E a aplicação **nunca** conecta como dono: usuário de runtime separado, sem
  `BYPASSRLS`. Sem essas duas coisas o RLS é decorativo.
- **No SQLAlchemy, o `SET LOCAL` é emitido no evento `after_begin`, pela `Connection`, não pela
  `Session`.** Emitir pela Session pode disparar fora da transação certa. Isso vira uma peça de
  `app/core/tenancy.py` e um `Depends` que resolve a empresa do request (do JWT, do header ou
  do path) antes de qualquer query.
- **O serviço não escreve mais filtro de empresa.** `ListingSpec.tem_empresa` e o
  `EmpresaScopedMixin` perdem a razão de existir na forma atual — o filtro está no banco.

**O que isso não resolve:** RLS separa empresas, não autoriza operações. O RBAC recurso+ação
continua necessário e ortogonal — o banco garante *de qual empresa* é o dado; a aplicação
garante *se aquele usuário pode* criar, editar ou excluir.

## Estrutura de diretórios

```
vitra-backend/
├── alembic/versions/
├── app/
│   ├── main.py                    # app factory, routers, handlers de erro
│   ├── core/
│   │   ├── config.py  db.py  security.py  deps.py
│   │   ├── errors.py              # exceções de domínio → HTTP
│   │   ├── listing.py             # ListParams, paginação, ordenação
│   │   ├── numbering.py           # série + número por documento/empresa
│   │   ├── tenancy.py             # SET LOCAL app.current_tenant no after_begin + Depends
│   │   └── permissions.py         # require(recurso, acao)
│   ├── common/
│   │   ├── mixins.py              # Timestamps, Ativo, TenantScoped (PK composta), Endereco, Contatos
│   │   ├── base_model.py  base_service.py  child_set.py
│   └── modules/
│       ├── auth/        usuario, grupo, permissao, autorizacao_documento
│       ├── empresa/     empresa, filial, centro_custo
│       ├── apoio/       tabela_apoio (genérica), cidade, uf, banco
│       ├── pessoas/     cliente, obra, fornecedor, colaborador,
│       │                profissional_externo, transportadora, contador
│       ├── produtos/    produto, variante, produto_fornecedor, grupo_relacionado
│       ├── estoque/     deposito, localizacao, saldo, movimento, reserva
│       ├── compras/     pedido_compra, ordem_compra
│       └── vendas/      pasta, orcamento, ambiente, item, pedido_venda
├── tests/
├── scripts/seed.py
└── docker-compose.yml
```

Cada módulo: `models.py`, `schemas.py`, `service.py`, `router.py`. Router só orquestra; regra de
negócio mora no service; nenhum `select()` em router.

## Modelo de dados — o que não é óbvio

O CRUD trivial não precisa de plano. O que segue são as decisões onde errar custa retrabalho.

**Convenção que vale para todos os esboços abaixo:** tabela por empresa tem PK `(tenant_id, id)`
e toda FK interna leva o `tenant_id` junto; tabela global tem PK `id`. Onde se lê `empresa_id`
numa FK para `tenants`, é vínculo de negócio (qual empresa *compra* de um fornecedor), não
recorte de acesso — esse é do RLS.

### 1. Tabela de apoio genérica (`catalog_lookups`)

Cobre os 19 `[combo +...]`: Setor, Grau de Instrução, Profissão, Raça/Cor, Estado Civil,
Nacionalidade, Cargo, Vínculo, Categoria, Tipo de Produto, Tipo da Peça, Tipo da Linha,
Classificação, Designer\Modelo, Fábrica, Marca, Materiais, Unidade, Acabamento, Tamanho.

```
catalog_lookups(id, kind, name, active)          -- GLOBAL, sem tenant_id
  unique(kind, name)
```

O schema do bake-off resolveu uma dúvida que o plano deixava em aberto: a tabela de apoio é
**global**, não por empresa. Os 19 combos são vocabulário do grupo, não de cada loja — some o
`empresa_id NULL` que valeria "global" e some junto a unicidade de três colunas.

Router genérico `/api/v1/apoio/{dominio}` com GET (lista/lookup) e POST (criar na hora — é
literalmente o botão `...`). `Cidade` e `Banco` **não** entram aqui: têm campos próprios
(UF derivada, código IBGE / código do banco) e são `[busca +...]`, tabelas dedicadas.

### 2. Blocos reutilizáveis (mixins, não tabelas)

Endereço aparece igual em 4+ cadastros; telefones em 4 variações fixas; redes sociais em todos.
Viram **mixins de colunas** (`endereco_logradouro`, `endereco_numero`, …) — não tabelas
separadas, porque a tela trata como bloco inline e o join extra não paga.
`Comunicadores` (sempre 2 pares combo+texto) vira `JSONB` — é lista curta e sem consulta.

### 3. Produto e variante — o ponto mais importante do catálogo

**Preço e estoque não vivem no produto nem na variante — vivem numa terceira tabela.** A
variante é `Acabamento × Tamanho`; `product_tenant` pendura preço e estoque abaixo dela. O
bake-off já traz esse desenho pronto e o plano o adota inteiro, inclusive além das 7 tabelas.

```
products(tenant_id, id, code, description, active,
         -- o VITRA real acrescenta:
         codigo_especial, codigo_reduzido, descricao_complementar, dt_vigencia,
         tipo_produto_id, tipo_peca_id, tipo_linha_id, classificacao_id,
         designer_id, fabrica_id, marca_id, empresa_compradora_id,
         unidade_entrada_id, qtd_entrada, unidade_saida_id, qtd_saida,
         fora_de_linha, consultar_valor, sobre_medida, publicar_no_site,
         ncm, cest, origem,                     -- guardados, sem motor fiscal
         especificacao JSONB)                   -- aba 2: watts, volts, lúmen, ângulo,
  PK (tenant_id, id) · unique (tenant_id, code)
product_variants(tenant_id, id, product_id, finish, size, active)
  PK (tenant_id, id) · FK (tenant_id, product_id) → products
  unique (tenant_id, product_id, finish, size)
product_tenant(tenant_id, id, variant_id,
               price_cents BIGINT,              -- centavos, nunca Numeric
               stock_qty NUMERIC(14,3) CHECK (>= 0), min_stock NUMERIC(14,3),
               indice, tipo_valor)
  PK (tenant_id, id) · FK (tenant_id, variant_id) → product_variants
produto_fornecedor(tenant_id, id, product_id, fornecedor_id, codigo_fornecedor,
                   descricao_fornecedor, padrao bool)
  PK (tenant_id, id) · FK (tenant_id, product_id) → products
```

Repare no que a FK composta compra: `product_tenant` só consegue apontar para uma variante **da
mesma empresa**. Não é convenção nem validação de serviço — o `INSERT` falha. Era exatamente o
tipo de erro que o desenho antigo (`empresa_id` solto em cada tabela) deixava passar.

A aba 2 (`Outros Dados`) tem ~25 campos luminotécnicos que são **especificação de catálogo, não
regra de negócio** → `JSONB` validado por um schema Pydantic. Se virarem colunas, cada novo
atributo é migração.

**Produtos relacionados** — grupos + itens, com a semântica já decidida na transcrição:
`quantidade` preenchida = kit; `quantidade` nula = sugestão de venda cruzada.

```
grupo_relacionado(id, produto_id, nome, padrao, ativo)
item_relacionado(id, grupo_id, produto_id, variante_id NULL, quantidade NULL, padrao)
```

### 4. Fornecedor ↔ empresa compradora é histórico

O legado tem `Empresa compradora` **e** aba `Histórico Emp. Comp.` — o vínculo muda no tempo.

```
fornecedor_empresa(id, fornecedor_id, empresa_id, vigencia_inicio, vigencia_fim NULL, motivo)
```

Serviço `empresa_compradora_em(fornecedor_id, data)` resolve a vigente. Escrever o "atual" como
coluna no fornecedor é o erro que a tela avisa para não cometer.

### 5. Estoque — endereçamento estruturado

```
deposito(tenant_id, id, filial_id, nome, ativo)
localizacao(tenant_id, id, deposito_id, predio, rua, numero, apto)
saldo(tenant_id, id, variante_id, deposito_id, localizacao_id NULL,
      quantidade NUMERIC(14,3) CHECK (>= 0), quantidade_reservada NUMERIC(14,3))
  unique(tenant_id, variante_id, deposito_id, localizacao_id)
movimento(tenant_id, id, variante_id, deposito_id, localizacao_id, tipo Enum, quantidade,
          documento_tipo, documento_id, data, employee_id, observacao)
reserva(tenant_id, id, variante_id, deposito_id, quantidade, origem_tipo, origem_id, status)
```

Todas com PK `(tenant_id, id)` e FKs internas levando `tenant_id`. O `CHECK (quantidade >= 0)`
no saldo é a segunda linha de defesa contra estoque negativo — a primeira é o `FOR UPDATE`.

**`movimento` é livro-razão append-only**; `saldo` é projeção mantida na mesma transação, com
`SELECT ... FOR UPDATE` na linha de saldo. Nunca recalcular saldo somando movimentos em request.
Tipos: `entrada`, `saida`, `ajuste`, `transferencia_saida`, `transferencia_entrada`,
`reserva`, `liberacao_reserva`. Isso já dá base para `Movimentação → Transferência para Filial`
e `Requisição de Produtos` na fase seguinte.

### 6. Documento base — cabeçalho + itens + totais

Compartilhado por orçamento, pedido de compra e ordem de compra:

- **Numeração**: `serie` + `numero` inteiro sequencial por (empresa, tipo, série), atribuída na
  criação. A transcrição observa que **não é cronológica** — número na criação, emissão depois.
  Sequência obtida com `SELECT ... FOR UPDATE` numa tabela `contador_documento`, dentro da
  transação. Não usar `SEQUENCE` do Postgres: precisa ser por empresa+série e sem buracos.
  Com RLS o contador fica ainda mais simples: a empresa já está na transação, então a chave
  efetiva vira `(tipo, série)` sob o recorte do banco.
- **Totais recalculados no serviço** a cada mutação de item. O cliente nunca envia total.
- **Máquina de estados** explícita por documento, transições validadas em um só lugar.
- **Exclusão**: cadastros usam `ativo` (desativação lógica, nunca DELETE). Documentos de venda
  **cancelam** (`POST /{id}/cancelar` com motivo) — a tela de orçamento troca `Excluir` por
  `Cancelar` de propósito.

### 7. Orçamento — a tela central

```
orcamento(tenant_id, id, serie, numero, pasta_id NULL, cliente_id, obra_id NULL,
          consultor_id, profissional_externo_id NULL,
          dt_emissao, dt_validade, dt_fechamento NULL,
          modo_desconto Enum('produto','geral'), desconto_geral_pct, desconto_geral_cents,
          subtotal_cents, total_cents, status Enum, observacao)
orcamento_ambiente(tenant_id, id, orcamento_id, nome, ordem)     -- Ambiente F5
orcamento_item(tenant_id, id, orcamento_id, ambiente_id NULL, ordem,
               product_id NULL, variante_id NULL,         -- NULL = Pré Produto
               pre_produto JSONB NULL,                    -- descrição livre do item a definir
               fornecedor_id, codigo_fornecedor, descricao_fornecedor,
               quantidade NUMERIC(14,3), unidade_id,
               valor_unitario_cents, desconto_pct, valor_item_cents,
               grupo_produto_id, tipo_peca_id)
```

Pontos que a tela força:
- **Itens agrupados por ambiente** (`Ambiente F5`) — `ambiente_id` nulo = itens sem ambiente.
- **`Pré Produto`** = item sem produto no catálogo. `produto_id` nulo com `pre_produto` JSONB.
  Constraint: exatamente um dos dois preenchido.
- **Desconto em 3 níveis** — por produto (no item), por grupo (aplicação em lote sobre itens de
  um grupo, materializada nos itens) e geral (no cabeçalho). Os dois primeiros são mutuamente
  exclusivos por radio → `modo_desconto` no cabeçalho.
- **O item fala a língua do fornecedor**: guarda `codigo_fornecedor` e `descricao_fornecedor`
  como **snapshot desnormalizado**, não só FK. O que foi orçado não pode mudar quando o cadastro
  do fornecedor mudar.
- **Ciclo de vida**: `dt_emissao`, `dt_validade`, `dt_fechamento` são distintas.
  Status: `rascunho → aberto → fechado | cancelado | expirado`.
- **Revisão**: dois orçamentos do mesmo cliente no mesmo dia (21638/21639) são caso real →
  `orcamento_origem_id` para encadear revisões.
- **`Alterar Limites` + `Permissões`** = autorização por documento para desconto acima do limite.
  Modelado em `autorizacao_documento(id, documento_tipo, documento_id, tipo, solicitante_id,
  autorizador_id, valor_solicitado, status, motivo)`. O service de desconto consulta o limite do
  usuário e exige autorização aprovada quando estoura.

### 8. Compras — pedido e ordem são documentos distintos e ligados

```
pedido_compra(tenant_id, id, numero, serie, data, orcamento_id NULL, pedido_venda_id NULL,
              observacao, total_cents, status)
pedido_compra_fornecedor(tenant_id, id, pedido_id, fornecedor_id)  -- N fornecedores por pedido
pedido_compra_item(tenant_id, id, pedido_id, fornecedor_id, product_id, variante_id,
                   codigo_fornecedor, descricao_fornecedor, quantidade NUMERIC(14,3),
                   unidade_id, valor_unitario_cents,
                   destino Enum('estoque','obra'), obra_id NULL)
ordem_compra(tenant_id, id, numero, fornecedor_id, empresa_compradora_id,
             dt_ordem, dt_envio, dt_prevista, dt_reagendamento, faturamento_minimo_cents,
             transportadora_id NULL, subtotal_cents, desconto_cents, acrescimo_cents,
             total_cents, observacao, status)
ordem_compra_item(tenant_id, id, ordem_id, pedido_compra_item_id NULL, product_id, variante_id,
                  quantidade NUMERIC(14,3), unidade_id,
                  valor_unitario_cents, valor_total_cents, data)
```

Fatos estruturais que a listagem 7.3 revela e que o modelo obedece:
- **Pedido tem N fornecedores** (coluna concatena por ` - `). Não é 1:1 — daí a tabela de
  vínculo e o `fornecedor_id` no item.
- **Ordem é por fornecedor único** (listagem 7.1 mostra um fornecedor por linha). A ordem é o que
  efetivamente se manda para um fornecedor; o pedido é a necessidade agregada.
- **`Pedido de Venda` no pedido de compra** = compra puxada pela venda. Campo vazio = compra para
  estoque. Daí `pedido_venda_id` nulável e `destino` no item.
- **Pedido ↔ Ordem navegam mutuamente** por botão → `ordem_compra_item.pedido_compra_item_id`.

## Superfície da API

`/api/v1`, JSON, erros em envelope único `{erro: {codigo, mensagem, campos}}`.

| Grupo | Endpoints |
|---|---|
| Auth | `POST /auth/login`, `POST /auth/refresh`, `POST /auth/alterar-senha`, `GET /auth/eu` |
| Acesso | CRUD `/grupos`, `/usuarios`, `GET/PUT /grupos/{id}/permissoes` |
| Apoio | `GET` e `POST /apoio/{dominio}`, `GET /cidades/lookup`, `GET /bancos/lookup` |
| Cadastros | CRUD + `/lookup` para clientes, fornecedores, colaboradores, profissionais-externos, transportadoras |
| Produtos | CRUD `/produtos`, subrecursos `/variantes`, `/fornecedores`, `/grupos-relacionados`, `GET /produtos/lookup` |
| Estoque | `GET /estoque/saldos`, `POST /estoque/movimentos`, `POST /estoque/transferencias`, `POST /estoque/reservas` |
| Vendas | CRUD `/orcamentos` (+ `/itens`, `/ambientes`), `POST /{id}/cancelar`, `POST /{id}/fechar`, `POST /{id}/revisar`, `POST /{id}/desconto-grupo` |
| Compras | CRUD `/pedidos-compra`, `/ordens-compra`, `POST /ordens-compra/{id}/receber` |
| Autorizações | `POST /autorizacoes`, `POST /autorizacoes/{id}/aprovar` e `/rejeitar` |

Todas as listagens aceitam `?busca=&pagina=&tamanho=&ordenar_por=&ordem=&ativo=`. **`empresa_id`
sai da query string**: a empresa vem da transação (RLS), não de um parâmetro que o cliente
escolhe — deixá-lo seria reabrir por fora a porta que o RLS fecha.
Toda rota mutante passa por `Depends(require("recurso", "acao"))`.

**Quem consome isto é o front Next.js.** Duas consequências:

- A listagem responde **linhas + total** (`{itens, total, pagina, tamanho, paginas}`), que é
  exatamente o contrato que o TanStack Table server-side espera. Já é o formato do `Pagina[T]`.
- Um servidor Python **não** pode usar tRPC, que é o mecanismo TypeScript de contrato do front
  hoje. Daí "OpenAPI publicado" ser entregável do bake-off e não detalhe: é o substituto do
  contrato tipado, e é por ele que o front geraria o cliente.

## Bake-off — escolha da stack

Antes de seguir com S1, o servidor do VITRA é decidido por comparação: **três protótipos que
fazem a mesma coisa**, sobre o mesmo banco e os mesmos dados, avaliados lado a lado.

> **Escopo deste documento: o protótipo FastAPI, e só ele.** Os protótipos .NET e Litestar são
> de outros devs, em outros repositórios. Nada aqui os descreve, os prescreve ou depende deles —
> o que aparece do bake-off é o contrato comum (banco, schema, entregáveis, critérios), porque
> é o que torna as três entregas comparáveis.

### Banco compartilhado — o que não se faz

`vitra_bakeoff`, PostgreSQL 17 no Neon, duas empresas fictícias (ABACAXI e UVA).

**Compartilhado significa compartilhado:** os devs das outras duas stacks apontam para este
mesmo banco, ao mesmo tempo. Daí as regras não serem burocracia.

- **Não criar, alterar ou apagar tabela lá.** A estrutura é fixa. A migração da nossa stack se
  testa **localmente**, em Postgres descartável (Testcontainers), recriando a mesma estrutura.
- Só ler e escrever dados, sempre com a empresa declarada na transação.
- **Nossos testes não escrevem no banco compartilhado.** Suíte inteira roda local; contra o
  Neon vai só a listagem server-side, que é leitura. Escrita lá é manual e pontual — um teste
  que suja o dado sujou para os outros dois times também.
- Bagunçou o dado: avisar o Henrique, que reseta em ~1 min.
- A string de conexão vive **só no `.env`** — traz senha real e não entra no repositório.
  O `.env.example` documenta a variável, nunca o valor.
- O Neon suspende o banco após alguns minutos ociosos: a primeira conexão depois disso leva
  1–2 s. Não é queda, e o pool precisa tolerar isso.

| Empresa | `tenant_id` |
|---|---|
| ABACAXI | `11111111-1111-1111-1111-111111111111` |
| UVA | `22222222-2222-2222-2222-222222222222` |

### As 7 tabelas

```
GLOBAIS (sem tenant_id, sem RLS)
├─ tenants           as 2 empresas (id, name, cnpj, active)
├─ employees         pessoas — identidade única no grupo (id, name, email, active)
└─ catalog_lookups   listas genéricas (id, kind, name, active) — os 19 kinds

POR EMPRESA (PK composta, RLS FORCE)
├─ products          200 itens (tenant_id, id, code, description, active)
│    └─ product_variants   3 por produto (tenant_id, id, product_id, finish, size, active)
│         └─ product_tenant   preço/estoque (tenant_id, id, variant_id,
│                              price_cents BIGINT, stock_qty NUMERIC(14,3), min_stock)
└─ employee_company  papel por empresa (tenant_id, employee_id, role)
                     roles: owner | admin | operator-full | operator-sales | viewer
```

Duas coisas que este schema confirma e que o plano já previa, agora com nome diferente:
`catalog_lookups` **é** a tabela de apoio genérica (`kind` = `dominio`), e `product_tenant`
**é** preço e estoque vivendo abaixo da variante, não do produto.

E uma que ele contraria: `employee_company` dá **papel fixo por empresa** (5 valores), não o
RBAC recurso+ação do plano. Para o bake-off, o papel basta. Para o VITRA real, o RBAC granular
continua valendo — `employee_company.role` vira o *grupo* a que a pessoa pertence naquela
empresa, e as permissões seguem penduradas no grupo.

### Nossos entregáveis

Os sete itens abaixo são o que **este repositório** precisa entregar. Os outros dois times
entregam o equivalente na stack deles; comparabilidade é o único motivo de a lista ser a mesma.

1. Modelos SQLAlchemy 2.0 (`Mapped[]`) das 7 tabelas, **com a chave composta declarada**.
2. Migração Alembic recriando o schema completo — **incluindo o RLS em SQL cru** — em Postgres
   descartável. Nunca no banco compartilhado.
3. **4 testes de isolamento**, no banco local:
   - gravar preço da empresa A apontando para produto da B → o banco recusa (FK composta);
   - consulta **sem filtro no código**, com empresa X declarada → só linhas de X;
   - consulta **sem empresa declarada** → zero linhas, **sem erro** — testando também a conexão
     que *já teve* empresa antes, que é o caso do pool e onde o `NULLIF` prova seu valor;
   - a conexão da aplicação não consegue desligar nem burlar a política.
4. **Teste de concorrência:** dois requests simultâneos de empresas diferentes não se misturam.
5. **Listagem de produtos server-side** — busca textual, ordenação e paginação no servidor —
   apontando para o banco compartilhado. Reusa `ListParams` da S0 direto.
6. **OpenAPI publicado.**
7. **CI verde:** lint + tipos + testes.

Casos de borda que estão nos dados **de propósito** e a listagem tem que aguentar: produto com
preço `0`, estoque `0`, e registros `active = false`. ANA SILVA (`ana@grupo.dev`) é `admin` na
ABACAXI **e** `operator-sales` na UVA — mesma pessoa, papel por empresa; é o caso que prova a
autorização.

### O que precisamos medir da nossa parte

A comparação entre as três stacks é do Henrique. O que cabe a nós é **preencher a nossa coluna
com honestidade** — e isso exige anotar durante o trabalho, não reconstruir de memória no fim:

| Critério | Como medir | Anotar quando |
|---|---|---|
| Tempo até os 4 testes verdes | horas de sessão | a cada sessão, ao parar |
| Linhas de código (sem testes) | `cloc` ou `tokei` | no fim, comando único |
| Clareza da listagem server-side | leitura lado a lado | nada a fazer — é o outro que julga |
| Atrito com assistente de IA | nº de correções por código alucinado | na hora em que acontece |
| Salvar pai+filhos (só esboço) | 1 endpoint de grade rascunhado | já existe |
| Experiência subjetiva | nota 1–5 + 3 linhas de motivo | no fim |

"Atrito com IA" é o único que não dá para recuperar depois: se não for registrado na hora,
vira chute. Vale um arquivo solto de notas durante a FB.

Empate técnico desempata por: velocidade de entrega das ~20 telas reais, facilidade do ETL de
importação, ecossistema de IA.

**Dois dos sete itens já estão prontos desde a S0:** "salvar pai+filhos" é o
`substituir_conjunto`, e "listagem server-side" é o `ListParams`. O trabalho real da FB é o RLS
— e é justamente onde as três stacks vão divergir mais.

## FastAPI × Litestar — o que de fato difere

Duas das três stacks do bake-off são Python. Vale saber onde elas realmente divergem, para não
medir a coisa errada. Versões conferidas no PyPI em **29/07/2026**:

| | FastAPI | Litestar |
|---|---|---|
| Versão | `0.140.13` | `2.24.0` (11/06/2026) |
| Python | ≥ 3.10 | ≥ 3.8, < 4.0 |
| Base | Starlette ≥ 0.46 + Pydantic ≥ 2.9 | camada ASGI própria; **msgspec ≥ 0.18.2 é dependência de núcleo** |
| Adoção | ~80 mil estrelas, ~4,5 mi downloads/dia | ~5,9 mil estrelas |
| Extras | ecossistema de terceiros | `sqlalchemy`, `jwt`, `opentelemetry`, `redis`/`valkey`, 4 UIs de OpenAPI |

São o mesmo tipo de coisa — ASGI, async, rotas por type hint, OpenAPI automático. A diferença é
de **escopo**: FastAPI é deliberadamente pequeno e você monta o resto; Litestar traz guards de
autorização, caching, rate limiting, channels, DTOs e integração de ORM como parte do framework.

### O que pesa para este projeto

**1. `advanced-alchemy` — de longe o maior fator.** Versão `1.11.0`, mantida pela **Litestar
Organization**. Entrega pronto: repositórios sync e async com CRUD e operações em lote, camada de
serviço, classes base com **colunas de auditoria** e PK UUID/BigInt, configuração de Alembic com
CLI, e filtros de listagem (`LimitOffset`, `SearchFilter`, `BeforeAfter`, `CollectionFilter`) com
um `list_and_count()` que devolve **linhas e total numa chamada**.

Compare com o que a S0 escreveu à mão: `base_model.py`, `base_service.py`, `listing.py` inteiro e
os mixins. É quase tudo biblioteca do outro lado. E "listagem server-side" é o entregável nº 5,
julgado por **clareza** e por **linhas de código** — dois dos seis critérios.

Dois detalhes que mudam a conversa:

- Ele **suporta chave primária composta** em repositórios e operações em lote. É exatamente o
  nosso `(tenant_id, id)`, que costuma ser onde camadas de repositório genéricas quebram.
- Ele tem **extensão oficial para FastAPI** (`advanced_alchemy.extensions.fastapi`), com
  `provide_session()`, `provide_service()` e `commit_mode`. Não é exclusivo do Litestar.

**2. DTOs.** O Litestar deriva entrada e saída direto do modelo SQLAlchemy, com include/exclude e
relações aninhadas. No FastAPI se escreve um schema Pydantic paralelo por modelo — foi o que os
`schemas.py` da S0 fizeram. Para as 7 tabelas do bake-off, é bastante repetição.

**3. Guards.** O Litestar separa autorização (`guards=[...]`) de injeção de dependência. No
FastAPI as duas passam pelo mesmo `Depends` — foi assim que o `require("recurso", "acao")` saiu.
Funciona, mas mistura os conceitos.

**4. Camadas.** Litestar permite declarar dependências, guards e middleware em quatro níveis
(app → router → controller → handler), com merge. FastAPI é mais plano.

**5. Desempenho.** O Litestar anuncia vantagem via msgspec, e benchmarks de terceiros repetem
isso. Num ERP dominado por I/O de banco, é ruído: o gargalo será o Postgres, não a serialização.
**Não deveria pesar na decisão.**

### O que não difere

Para o que o bake-off está realmente testando — RLS, `SET LOCAL` no `after_begin`, PK composta,
FK composta — **a escolha é indiferente**. É tudo SQLAlchemy puro, e os 4 testes de isolamento
sairão praticamente idênticos.

Nem o Litestar nem o `advanced-alchemy` trazem RLS pronto: `tenancy.py` é código nosso nos dois
casos. Existe prior art de terceiros (`sqlalchemy-tenants`, com decorator `@with_rls` e session
manager por tenant; `fastapi-rowsecurity`) — vale olhar como referência, não adotar sem avaliar.

### O confundidor que precisa ser combinado antes

Como o `advanced-alchemy` roda em FastAPI também, comparar **"FastAPI cru" contra "Litestar +
advanced-alchemy"** mede duas variáveis ao mesmo tempo — e provavelmente elege a biblioteca, não
o framework. Duas saídas honestas, a combinar com o Henrique:

- **os dois usam** `advanced-alchemy` → compara-se framework;
- **nenhum usa** → compara-se o que cada um traz de fábrica.

Qualquer uma serve; a mistura, não.

### Palpite honesto

Litestar tende a ganhar em linhas de código e clareza da listagem. FastAPI tende a ganhar no
critério **"atrito com assistente de IA"**, e não por mérito técnico: está muito mais presente no
material de treino dos assistentes, então o Litestar deve render mais alucinação de API. Como
esse é um critério declarado do bake-off, é justo que apareça — só não deve ser confundido com
qualidade do framework.

## Retrabalho na S0 já entregue

A S0 foi construída com `empresa_id` em coluna, dinheiro em `Numeric(15,2)` e nomes em
português. A decisão por RLS muda isso. O que precisa mexer, em ordem de dependência:

| Peça | Mudança |
|---|---|
| `app/core/tenancy.py` | **Novo.** `SET LOCAL` no `after_begin` da Connection + `Depends` que resolve a empresa do request |
| `app/core/db.py` | Registrar o evento na engine; garantir que o usuário de runtime não é dono das tabelas |
| `app/common/mixins.py` | `EmpresaScopedMixin` → `TenantScopedMixin`, com PK composta `(tenant_id, id)` |
| `app/common/base_model.py` | `ModeloBase` deixa de assumir PK `id` simples |
| `app/core/listing.py` | Some `ListingSpec.tem_empresa` e o filtro por `empresa_id` — o banco faz |
| `app/modules/empresa/` | `Empresa` → `tenants` (tabela global); `filial`/`centro_custo` viram por-empresa |
| `app/modules/apoio/` | `TabelaApoio` → `catalog_lookups`, `dominio` → `kind` |
| `app/modules/auth/` | `Usuario` → `employees` (global) + `employee_company` (papel por empresa) |
| `Empresa.cnpj` / `Filial.cnpj` | `String(18)` com máscara → `String(14)`, caixa alta, sem máscara |
| Auditoria | Sai da S6 e vira transversal: append-only, na mesma transação da escrita |
| Migrações | O RLS entra em migração própria, em SQL cru, com `FORCE` e as 4 políticas por tabela |
| Testes | `conftest` passa de banco fixo para Testcontainers; some `create_all`, fica `alembic upgrade` |

**Não é reescrita.** Os cinco mecanismos transversais — apoio genérica, replace-set, lookup,
`ListParams`, numeração — não dependem de como o recorte por empresa é feito e sobrevivem
inteiros. O que muda é a camada de identidade e o formato da chave.

## Fases de implementação

**Por que `S` e não `F`.** O VITRA tem as suas próprias `FASE 0 / 1 / 2` (Fundação, Identidade
e Empresas, Catálogo — as três já concluídas ou em curso no front) e mais 12 `Etapas` no Guia de
Engenharia. Chamar as nossas de `F0…F6` criava duas "Fundação" diferentes na mesma conversa — e
colidia até com as teclas `F4`/`F5`/`F6` do legado citadas neste plano. Aqui é `S` de **servidor**.

**S0 — Fundação.** ✅ *Entregue.* Projeto, docker-compose, config, sessão async, Alembic,
`main.py`, handlers de erro, `ListParams`, mixins, `substituir_conjunto` (replace-set das
grades), serviço de numeração, auth JWT + RBAC granular, `empresa`/`filial`/`centro_custo`,
tabela de apoio genérica + `cidade`/`uf`/`banco`, busca sem acento.
*Entregue quando:* login funciona, `/apoio/{dominio}` cria e lista, permissão bloqueia rota.

Duas notas de execução, decididas durante a implementação:

- A tabela `autorizacao_documento` **entra já na migração inicial**, sem endpoints. O serviço
  que a consome é da S4; antecipar só a tabela evita uma migração extra e não custa nada.
- As FKs de `criado_por_id` fecham o ciclo `usuario → empresa → cidade → uf → usuario` e usam
  `use_alter`. O `op.create_table` do Alembic **descarta essas FKs em silêncio**: elas precisam
  de `create_foreign_key` explícito no fim do `upgrade()`. Pelo mesmo motivo os testes aplicam
  a migração em vez de `Base.metadata.create_all` — senão o schema de teste e o de produção
  divergem sem ninguém perceber. Vale para toda migração das fases seguintes.

**SB — Bake-off.** ⏭ *Próxima.* Entra **entre S0 e S1**: as 7 tabelas com chave composta, RLS
com as 4 políticas, os 4 testes de isolamento, o de concorrência, listagem server-side contra o
banco compartilhado, OpenAPI e CI. Carrega junto o retrabalho da seção anterior — não dá para
fazer os testes de isolamento sem `tenancy.py`. *Entregue quando:* os 4 testes de isolamento
passam e a listagem responde apontando para o Neon.

**S1 — Cadastros de pessoas.** Cliente (com `obra`), fornecedor (com contatos e
`fornecedor_empresa` histórico), colaborador, profissional externo, transportadora. Reusa
mixins de S0; cada um é ~1 modelo + schemas + service herdando `BaseService`.

**S2 — Produtos.** Produto, variantes, `produto_fornecedor`, grupos relacionados,
especificação JSONB. Endpoint de lookup por código próprio **e** por código do fornecedor.

**S3 — Estoque.** Depósito, localização, saldo, movimento append-only, reserva. Testes de
concorrência no saldo (duas saídas simultâneas não podem furar).

**S4 — Orçamento.** Documento base, ambientes, itens, pré-produto, desconto em 3 níveis,
totais, ciclo de vida, revisão, autorização por documento.

**S5 — Compras.** Pedido (N fornecedores) → ordem (1 fornecedor) → recebimento que gera
movimento de entrada. Ligação `orçamento/pedido de venda → pedido de compra`, com `destino`.

**S6 — Endurecimento.** ~~Auditoria~~ — a auditoria **saiu daqui**: o contrato do VITRA a exige
append-only e na mesma transação da escrita, desde a primeira tabela, então ela é transversal e
não um endurecimento posterior. Restam: importação de produtos por planilha
(`Sistema → Importação`), seeds realistas, testes e2e do fluxo completo, OpenAPI revisado.

## Verificação

```bash
docker compose up -d db
alembic upgrade head
python scripts/seed.py          # empresas Vertz/Via HF, apoio, ~50 produtos, clientes, fornecedores
uvicorn app.main:app --reload   # OpenAPI em /docs
pytest -q                       # unit + integração; sobe Postgres descartável (Testcontainers)
pytest tests/e2e -q             # fluxo ponta a ponta
```

O `pytest` **não** usa mais o banco do docker-compose: cada execução sobe um Postgres
descartável e aplica as migrações, RLS incluído. É o único jeito de testar política de
segurança sem deixar resíduo — e de garantir que o RLS realmente está na migração, não só
no banco de alguém.

O teste e2e que define "pronto" — é o fluxo real da Vertz:

1. login → criar cliente com obra → criar produto com 2 variantes (acabamento × tamanho) e um
   fornecedor com código próprio dele
2. criar orçamento com 2 ambientes, 3 itens (um deles Pré Produto), desconto por produto
3. tentar desconto acima do limite → **espera 403** → criar autorização, aprovar → aplicar
4. fechar orçamento → gerar pedido de compra com 2 fornecedores, `destino=obra`
5. gerar ordem de compra do fornecedor A a partir do pedido → receber → **conferir que o saldo
   subiu na localização certa e que existe exatamente 1 movimento de entrada**
6. reservar variante para a obra → conferir `quantidade_reservada` e que a saída disponível caiu
7. cancelar o orçamento → conferir que ele **não sumiu**, só mudou de status

Testes de concorrência à parte: duas saídas simultâneas da mesma variante não podem deixar saldo
negativo; dois orçamentos criados em paralelo na mesma série não podem repetir número; e dois
requests simultâneos **de empresas diferentes** não podem se misturar — este último é o teste
que o RLS torna possível escrever e que o desenho antigo não tinha como provar.

## Dívida assumida e lacunas

**Assumido por decisão do usuário:**
- Sem motor fiscal e sem NFe **neste servidor**. `ncm`/`cest`/`origem` ficam gravados; o modelo
  de item guarda o que a emissão vai pedir. **Correção importante:** o legado é pré-Reforma e
  não menciona IBS/CBS, mas isso **não** significa que o VITRA possa nascer sem eles — NF-e sem
  os grupos IBS/CBS passa a ser rejeitada em **03/08/2026**, e a emissão é delegada ao Focus
  NFe, não construída aqui. A versão anterior deste plano tratava o silêncio do legado como
  permissão; era leitura errada.
- Financeiro, CRM, metas, ganhos sobre vendas e relatórios fora desta entrega.

**Lacunas reais das fontes** — resolvidas com decisão de projeto, a confirmar com o usuário
quando houver novas capturas:
- `Cliente → Obra` nunca foi capturada. Modelo mínimo assumido:
  `obra(id, cliente_id, nome, endereco*, ativo)` com ambientes vivendo no orçamento.
- `Profissional Externo → Participação` (comissão/rateio) sem captura. Fica **fora de S1**;
  a FK do orçamento para profissional já existe, então adicionar depois não quebra nada.
- `Orçamento → Serviços` e `→ Pagamento` sem captura. Serviços tem cadastro próprio no menu,
  então provavelmente é uma segunda coleção de itens no orçamento. Não modelado agora.
- `Descrição da Obra` no legado está preenchida com **nomes de pessoas** (MARIANA, ANA ELIZA,
  MALU…) — uso desviado do campo, na prática registra o arquiteto. Este plano separa os
  conceitos: `obra_id` para obra, `profissional_externo_id` para o arquiteto. **A migração de
  dados vai precisar decidir para onde vai cada valor legado.**
- `VIA HF ILUMINAÇÃO` aparece como fornecedor de um pedido — uma empresa do grupo vende para a
  outra. `fornecedor_empresa` suporta isso, mas se for **transferência entre empresas** com
  regra própria, precisa confirmação. Sob RLS, a **escrita** cruzada continua proibida: modela-se
  como duas operações espelhadas (saída em A, entrada em B), cada uma na sua transação, ligadas
  por um identificador comum. A **leitura** consolidada, essa sim, é caso previsto — é o
  `groupScoped` do VITRA, e sob RLS vira predicado com lista, somente-leitura e auditado.

**Aberto pelo bake-off, a decidir quando ele terminar:**
- **Papel fixo × RBAC granular.** `employee_company.role` tem 5 valores; o plano prevê
  permissões recurso+ação. A ponte proposta (papel = grupo, permissões no grupo) precisa ser
  validada contra o que as ~20 telas realmente exigem.
- **Migração de `Numeric(15,2)` para centavos.** A S0 já gravou `limite_desconto_pct` e o
  modelo previa dinheiro em `Numeric`. Nada em produção ainda, então a conversão é barata
  agora e cara depois — é motivo para não adiar a virada.
- **Onde a empresa ativa vem no request.** JWT, header ou path. O bake-off não decide; o VITRA
  precisa, e a escolha muda o `Depends` de `tenancy.py`. Recomendação: claim no JWT, com header
  só para usuário que opera nas duas empresas (o caso da ANA SILVA).
