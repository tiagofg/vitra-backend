# Plano — Backend VITRA (substituto do SoftLux) em Python + FastAPI + SQLAlchemy

## Contexto

A Vertz opera hoje no **SoftLux 1.0.2.1521** (Fácil IT Software), um ERP desktop Windows para
iluminação/decoração. Temos duas fontes: `~/Downloads/softlux-telas-transcricao.md` (transcrição
literal de 20 telas) e `~/Downloads/Telas Softlux.pdf` (12 páginas de capturas). O objetivo é
reconstruir as funções desse sistema como um backend HTTP próprio.

Não existe código ainda — é greenfield. O `/home/tiagofg` não contém nenhum projeto VITRA.

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

## Decisões travadas com o usuário

1. **Escopo desta entrega: núcleo comercial.** Cadastros, produtos com variantes, estoque com
   endereçamento, orçamento/pedido de venda, pedido e ordem de compra. Financeiro, CRM, metas,
   ganhos sobre vendas e relatórios ficam para fases seguintes — mas o modelo não os impede.
2. **Multiempresa por `empresa_id` em linha**, banco único PostgreSQL. Vínculo
   fornecedor↔empresa compradora é **histórico com vigência**, não coluna.
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

Os outros três padrões (formulário com abas, recorte por empresa, consulta somente-leitura)
resolvem-se por mixins e por `empresa_id`.

## Stack

- Python 3.12, **FastAPI**, **SQLAlchemy 2.0 async** (`Mapped[...]` / `mapped_column`), asyncpg
- PostgreSQL 16, **Alembic** para migrações, extensão `unaccent` para busca sem acento
- Pydantic v2 (`pydantic-settings` para config)
- `argon2-cffi` para senha, JWT via `pyjwt`
- pytest + pytest-asyncio + httpx.AsyncClient, banco de teste em container
- ruff + mypy, docker-compose para dev

**Regras de tipo não negociáveis** (vêm direto das capturas):
- dinheiro: `Numeric(15, 2)` — nunca float
- percentual: `Numeric(9, 4)` — o total do orçamento mostra `Desconto 0,0010 %`, são 4 casas
- quantidade: `Numeric(15, 4)` — unidade de entrada ≠ unidade de saída, com fator
- toda tabela: `id` UUID, `criado_em`, `atualizado_em`, `criado_por_id`
- toda busca textual (`?busca=` e `/lookup?q=`) passa por `vitra_unaccent` nos **dois** lados,
  para `sao` achar `São Paulo` e `são` achar `Sao`. É wrapper `IMMUTABLE` sobre `unaccent()`,
  justamente para poder virar índice funcional quando o volume pedir

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
│   │   └── permissions.py         # require(recurso, acao)
│   ├── common/
│   │   ├── mixins.py              # Timestamps, Ativo, EmpresaScoped, Endereco, Contatos, RedesSociais
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

### 1. Tabela de apoio genérica (`apoio`)

Cobre os 19 `[combo +...]`: Setor, Grau de Instrução, Profissão, Raça/Cor, Estado Civil,
Nacionalidade, Cargo, Vínculo, Categoria, Tipo de Produto, Tipo da Peça, Tipo da Linha,
Classificação, Designer\Modelo, Fábrica, Marca, Materiais, Unidade, Acabamento, Tamanho.

```
tabela_apoio(id, dominio Enum, codigo, descricao, ativo, empresa_id NULL, ordem)
  unique(dominio, codigo, empresa_id)
```

Router genérico `/api/v1/apoio/{dominio}` com GET (lista/lookup) e POST (criar na hora — é
literalmente o botão `...`). `Cidade` e `Banco` **não** entram aqui: têm campos próprios
(UF derivada, código IBGE / código do banco) e são `[busca +...]`, tabelas dedicadas.

### 2. Blocos reutilizáveis (mixins, não tabelas)

Endereço aparece igual em 4+ cadastros; telefones em 4 variações fixas; redes sociais em todos.
Viram **mixins de colunas** (`endereco_logradouro`, `endereco_numero`, …) — não tabelas
separadas, porque a tela trata como bloco inline e o join extra não paga.
`Comunicadores` (sempre 2 pares combo+texto) vira `JSONB` — é lista curta e sem consulta.

### 3. Produto e variante — o ponto mais importante do catálogo

**Preço e estoque mínimo vivem na variante, não no produto.** A variante é `Acabamento × Tamanho`.

```
produto(id, nosso_codigo, codigo_especial, codigo_reduzido, nossa_descricao,
        descricao_complementar, dt_vigencia, tipo_produto_id, tipo_peca_id, tipo_linha_id,
        classificacao_id, designer_id, fabrica_id, marca_id, empresa_compradora_id,
        unidade_entrada_id, qtd_entrada, unidade_saida_id, qtd_saida,
        fora_de_linha, consultar_valor, ativo, sobre_medida, publicar_no_site,
        ncm, cest, origem,                      -- guardados, sem motor fiscal
        especificacao JSONB)                    -- aba 2: watts, volts, lúmen, ângulo,
                                                -- temp. cor, dimensões produto/embalagem, etc.
produto_variante(id, produto_id, acabamento_id, tamanho_id, ativo,
                 valor_tabela, indice, tipo_valor, estoque_minimo)
  unique(produto_id, acabamento_id, tamanho_id)
produto_fornecedor(id, produto_id, fornecedor_id, codigo_fornecedor,
                   descricao_fornecedor, padrao bool)
```

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
deposito(id, empresa_id, filial_id, nome, ativo)
localizacao(id, deposito_id, predio, rua, numero, apto)
saldo(id, variante_id, deposito_id, localizacao_id NULL, quantidade, quantidade_reservada)
  unique(variante_id, deposito_id, localizacao_id)
movimento(id, variante_id, deposito_id, localizacao_id, tipo Enum, quantidade,
          documento_tipo, documento_id, data, usuario_id, observacao)
reserva(id, variante_id, deposito_id, quantidade, origem_tipo, origem_id, status)
```

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
- **Totais recalculados no serviço** a cada mutação de item. O cliente nunca envia total.
- **Máquina de estados** explícita por documento, transições validadas em um só lugar.
- **Exclusão**: cadastros usam `ativo` (desativação lógica, nunca DELETE). Documentos de venda
  **cancelam** (`POST /{id}/cancelar` com motivo) — a tela de orçamento troca `Excluir` por
  `Cancelar` de propósito.

### 7. Orçamento — a tela central

```
orcamento(id, empresa_id, serie, numero, pasta_id NULL, cliente_id, obra_id NULL,
          consultor_id, profissional_externo_id NULL,
          dt_emissao, dt_validade, dt_fechamento NULL,
          modo_desconto Enum('produto','geral'), desconto_geral_pct, desconto_geral_valor,
          subtotal, total, status Enum, observacao)
orcamento_ambiente(id, orcamento_id, nome, ordem)          -- Ambiente F5
orcamento_item(id, orcamento_id, ambiente_id NULL, ordem,
               produto_id NULL, variante_id NULL,          -- NULL = Pré Produto
               pre_produto JSONB NULL,                     -- descrição livre do item a definir
               fornecedor_id, codigo_fornecedor, descricao_fornecedor,
               quantidade, unidade_id, valor_unitario, desconto_pct, valor_item,
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
pedido_compra(id, empresa_id, numero, serie, data, orcamento_id NULL, pedido_venda_id NULL,
              observacao, total, status)
pedido_compra_fornecedor(id, pedido_id, fornecedor_id)     -- N fornecedores por pedido
pedido_compra_item(id, pedido_id, fornecedor_id, produto_id, variante_id,
                   codigo_fornecedor, descricao_fornecedor, quantidade, unidade_id,
                   valor_unitario, destino Enum('estoque','obra'), obra_id NULL)
ordem_compra(id, empresa_id, numero, fornecedor_id, empresa_compradora_id,
             dt_ordem, dt_envio, dt_prevista, dt_reagendamento, faturamento_minimo,
             transportadora_id NULL, subtotal, desconto, acrescimo, total, observacao, status)
ordem_compra_item(id, ordem_id, pedido_compra_item_id NULL, produto_id, variante_id,
                  quantidade, unidade_id, valor_unitario, valor_total, data)
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
| Apoio | `GET|POST /apoio/{dominio}`, `GET /cidades/lookup`, `GET /bancos/lookup` |
| Cadastros | CRUD + `/lookup` para clientes, fornecedores, colaboradores, profissionais-externos, transportadoras |
| Produtos | CRUD `/produtos`, subrecursos `/variantes`, `/fornecedores`, `/grupos-relacionados`, `GET /produtos/lookup` |
| Estoque | `GET /estoque/saldos`, `POST /estoque/movimentos`, `POST /estoque/transferencias`, `POST /estoque/reservas` |
| Vendas | CRUD `/orcamentos` (+ `/itens`, `/ambientes`), `POST /{id}/cancelar`, `POST /{id}/fechar`, `POST /{id}/revisar`, `POST /{id}/desconto-grupo` |
| Compras | CRUD `/pedidos-compra`, `/ordens-compra`, `POST /ordens-compra/{id}/receber` |
| Autorizações | `POST /autorizacoes`, `POST /autorizacoes/{id}/aprovar|rejeitar` |

Todas as listagens aceitam `?busca=&pagina=&tamanho=&ordenar_por=&ordem=&ativo=&empresa_id=`.
Toda rota mutante passa por `Depends(require("recurso", "acao"))`.

## Fases de implementação

**F0 — Fundação.** ✅ *Entregue.* Projeto, docker-compose, config, sessão async, Alembic,
`main.py`, handlers de erro, `ListParams`, mixins, `substituir_conjunto` (replace-set das
grades), serviço de numeração, auth JWT + RBAC granular, `empresa`/`filial`/`centro_custo`,
tabela de apoio genérica + `cidade`/`uf`/`banco`, busca sem acento.
*Entregue quando:* login funciona, `/apoio/{dominio}` cria e lista, permissão bloqueia rota.

Duas notas de execução, decididas durante a implementação:

- A tabela `autorizacao_documento` **entra já na migração inicial**, sem endpoints. O serviço
  que a consome é da F4; antecipar só a tabela evita uma migração extra e não custa nada.
- As FKs de `criado_por_id` fecham o ciclo `usuario → empresa → cidade → uf → usuario` e usam
  `use_alter`. O `op.create_table` do Alembic **descarta essas FKs em silêncio**: elas precisam
  de `create_foreign_key` explícito no fim do `upgrade()`. Pelo mesmo motivo os testes aplicam
  a migração em vez de `Base.metadata.create_all` — senão o schema de teste e o de produção
  divergem sem ninguém perceber. Vale para toda migração das fases seguintes.

**F1 — Cadastros de pessoas.** Cliente (com `obra`), fornecedor (com contatos e
`fornecedor_empresa` histórico), colaborador, profissional externo, transportadora. Reusa
mixins de F0; cada um é ~1 modelo + schemas + service herdando `BaseService`.

**F2 — Produtos.** Produto, variantes, `produto_fornecedor`, grupos relacionados,
especificação JSONB. Endpoint de lookup por código próprio **e** por código do fornecedor.

**F3 — Estoque.** Depósito, localização, saldo, movimento append-only, reserva. Testes de
concorrência no saldo (duas saídas simultâneas não podem furar).

**F4 — Orçamento.** Documento base, ambientes, itens, pré-produto, desconto em 3 níveis,
totais, ciclo de vida, revisão, autorização por documento.

**F5 — Compras.** Pedido (N fornecedores) → ordem (1 fornecedor) → recebimento que gera
movimento de entrada. Ligação `orçamento/pedido de venda → pedido de compra`, com `destino`.

**F6 — Endurecimento.** Auditoria (quem mudou o quê), importação de produtos por planilha
(`Sistema → Importação`), seeds realistas, testes e2e do fluxo completo, OpenAPI revisado.

## Verificação

```bash
docker compose up -d db
alembic upgrade head
python scripts/seed.py          # empresas Vertz/Via HF, apoio, ~50 produtos, clientes, fornecedores
uvicorn app.main:app --reload   # OpenAPI em /docs
pytest -q                       # unit + integração contra Postgres de teste
pytest tests/e2e -q             # fluxo ponta a ponta
```

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
negativo; dois orçamentos criados em paralelo na mesma série não podem repetir número.

## Dívida assumida e lacunas

**Assumido por decisão do usuário:**
- Sem motor fiscal e sem NFe. `ncm`/`cest`/`origem` ficam gravados. Quando entrar, é tabela de
  regra `NCM × Operação × CFOP × Consumidor Final × UF` + cálculo no documento — o modelo de
  item já guarda o que ela precisa. Nada no legado indica IBS/CBS (é pré-Reforma).
- Financeiro, CRM, metas, ganhos sobre vendas e relatórios fora desta entrega.

**Lacunas reais das fontes** — resolvidas com decisão de projeto, a confirmar com o usuário
quando houver novas capturas:
- `Cliente → Obra` nunca foi capturada. Modelo mínimo assumido:
  `obra(id, cliente_id, nome, endereco*, ativo)` com ambientes vivendo no orçamento.
- `Profissional Externo → Participação` (comissão/rateio) sem captura. Fica **fora de F1**;
  a FK do orçamento para profissional já existe, então adicionar depois não quebra nada.
- `Orçamento → Serviços` e `→ Pagamento` sem captura. Serviços tem cadastro próprio no menu,
  então provavelmente é uma segunda coleção de itens no orçamento. Não modelado agora.
- `Descrição da Obra` no legado está preenchida com **nomes de pessoas** (MARIANA, ANA ELIZA,
  MALU…) — uso desviado do campo, na prática registra o arquiteto. Este plano separa os
  conceitos: `obra_id` para obra, `profissional_externo_id` para o arquiteto. **A migração de
  dados vai precisar decidir para onde vai cada valor legado.**
- `VIA HF ILUMINAÇÃO` aparece como fornecedor de um pedido — uma empresa do grupo vende para a
  outra. O `empresa_id` + `fornecedor_empresa` suportam isso, mas se for **transferência entre
  empresas** com regra própria, precisa confirmação.
