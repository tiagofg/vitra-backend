# Notas do bake-off — coluna FastAPI

> A comparação entre as três stacks é do Henrique. O que cabe a nós é **preencher a nossa
> coluna com honestidade**. Este arquivo existe porque um dos seis critérios — atrito com
> assistente de IA — não dá para recuperar depois: se não for anotado na hora, vira chute.

Stack: Python 3.12 · FastAPI 0.140 · SQLAlchemy 2.0 async · asyncpg · Alembic · Pydantic v2.
**Sem `advanced-alchemy`** — ver "Confundidor", no fim.

---

## Critérios

| Critério | Medida | Como foi obtido |
|---|---|---|
| Tempo até os 4 testes verdes | **1 sessão** | sessão única, do `tenancy.py` ao verde |
| Linhas de código (sem testes) | **2.580** no `app/` inteiro, das quais **315** no módulo do bake-off + **76** de `tenancy.py` + **241** de migração | linhas não-vazias e não-comentário |
| Clareza da listagem server-side | — | é o outro que julga; ver `app/modules/bakeoff/service.py` |
| Atrito com assistente de IA | **3 correções** | anotadas abaixo, na hora |
| Salvar pai+filhos | já existia | `substituir_conjunto` da S0 |
| Experiência subjetiva | **4/5** | ver no fim |

O número que mais importa para a comparação: **o trabalho de RLS inteiro custou 317 linhas**
(`tenancy.py` + a migração), e dessas, só **76** são a aplicação. O resto é SQL. É o piso que
as outras duas stacks também vão pagar — nem o Litestar nem o `advanced-alchemy` trazem RLS
pronto.

---

## Atrito com assistente de IA

Três correções, todas de código que *parecia* certo:

1. **`SET LOCAL` com parâmetro ligado.** A primeira versão saiu como
   `SET LOCAL app.current_tenant = :empresa`. Não existe: `SET` não aceita bind param, e a
   única saída seria interpolar o UUID na string. O correto é `set_config(..., true)`, que é
   o `SET LOCAL` em forma de função e aceita parâmetro. Erro plausível e silencioso — teria
   virado interpolação de string sem ninguém reparar.
2. **`str(URL)` do SQLAlchemy mascara a senha.** A URL do papel de runtime saía com `***` no
   lugar da senha e o teste falhava com "password authentication failed", apontando para o
   lugar errado (papel inexistente? grant faltando?). O certo é
   `render_as_string(hide_password=False)`. Custou o maior tempo de depuração da sessão.
3. **Nome de `CheckConstraint` duplicado.** `ck_product_tenant_stock_qty_nao_negativo` com a
   convenção de nomes do projeto virou
   `ck_product_tenant_ck_product_tenant_stock_qty_nao_negativo`. Cosmético, pego na hora.

Nenhuma alucinação de API do FastAPI ou do SQLAlchemy — o que era o palpite do plano
("FastAPI tende a ganhar neste critério, por estar mais presente no material de treino").
As três correções são de canto de biblioteca, não de framework.

**Um viés a declarar para o Henrique:** este critério só é comparável se as três colunas
forem preenchidas com o mesmo assistente e o mesmo nível de familiaridade prévia. Medido de
outro jeito, ele mede o dev, não a stack.

---

## O que efetivamente deu trabalho

Em ordem de custo, e nenhum deles é sobre o framework HTTP:

1. **Provar que o teste de isolamento testa alguma coisa.** Escrever os quatro é fácil;
   garantir que reprovam quando o RLS quebra, não. Foi preciso desligar o RLS de propósito e
   conferir que eles ficavam vermelhos — sem isso, "4 testes verdes" não significa nada. O
   modo de falha é traiçoeiro: rodar como dono ou superusuário faz os quatro passarem contra
   um banco sem trava nenhuma.
2. **A identidade de quem conecta.** Metade do RLS não é código: é `FORCE ROW LEVEL
   SECURITY` + papel de runtime que não é dono e não tem `BYPASSRLS`. Isso obrigou a separar
   URL de migração (dono) de URL de aplicação (runtime), o que respinga em `.env`,
   `docker-compose`, `alembic/env.py` e no conftest.
3. **`SET LOCAL` no `after_begin`, pela `Connection`.** Conceitualmente simples, com dois
   detalhes que só aparecem na prática: a transação pode já estar aberta quando a empresa é
   resolvida (autenticar já consultou o banco), então é preciso um segundo caminho que emite
   na hora; e `Session.info` é melhor âncora que `ContextVar`, porque o evento já recebe a
   sessão e não há como o valor pertencer à sessão errada.

Nada disso muda entre FastAPI e Litestar. **É tudo SQLAlchemy puro.**

---

## O confundidor

Este protótipo é **FastAPI cru**, sem `advanced-alchemy`. Comparar isto contra
"Litestar + advanced-alchemy" mede duas variáveis ao mesmo tempo e provavelmente elege a
biblioteca, não o framework — o `list_and_count()` dele resolve sozinho boa parte do que
`ListParams` + `paginar` fazem à mão aqui.

Combinar com o Henrique **antes de comparar**: ou os dois usam, ou nenhum usa. A mistura,
não. (Lembrando que `advanced_alchemy.extensions.fastapi` existe — a biblioteca não é
exclusiva do Litestar, o que torna "os dois usam" uma opção real.)

---

## Experiência subjetiva — 4/5

Não atrapalhou em nada que importasse. O `Depends` deu conta de injetar a empresa ativa sem
cerimônia, e o `Pagina[T]` genérico saiu direto no OpenAPI, que é o que o front consome.

O ponto que tira a nota: **autorização e injeção passam pelo mesmo `Depends`**. `require()`
e `sessao_da_empresa` são conceitos diferentes — um decide *se pode*, o outro *o que é
visível* — e no FastAPI viram a mesma coisa sintaticamente. O `guards=[...]` separado do
Litestar é honestamente mais limpo aqui.

O que **não** pesou: desempenho. Num ERP dominado por I/O de banco o gargalo é o Postgres, e
a diferença de serialização é ruído. Não deveria entrar na decisão.
