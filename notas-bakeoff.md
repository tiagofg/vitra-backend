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
| Atrito com assistente de IA | **3 correções** + 2 lacunas de segurança na revisão | anotadas abaixo, na hora |
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

**O que o critério não pega, e é o mais caro.** Nenhuma das três correções acima chega perto
do que a revisão do PR #1 encontrou: quatro rotas sem autenticação e um tenant escolhido
pelo cliente. Não foi erro de API — foi um raciocínio errado escrito com convicção num
docstring, justificando a ausência do RBAC como se cobrisse a autenticação. Lint, tipos e
102 testes verdes passaram por cima disso sem piscar.

Vale para a comparação: "atrito com IA" mede quantas vezes o assistente erra a chamada de
uma biblioteca. Não mede quantas vezes ele erra o desenho de forma plausível — e é a
segunda que custa revisão humana. Nenhuma das três stacks vai pontuar diferente aqui.

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

## A fronteira do que o RLS prova — e a lacuna que ele escondeu

Registrado porque a primeira versão desta entrega confundiu as duas coisas, e a confusão é
fácil de repetir em qualquer stack.

**O RLS entrega imunidade a `WHERE` esquecido no serviço.** É real, é o que o bake-off
mede, e é o que os 4 testes de isolamento provam. Nenhum desenvolvedor consegue vazar dado
entre empresas escrevendo uma query descuidada — o banco não deixa.

**O RLS não entrega imunidade a chamador malicioso.** Ele confia no GUC, o GUC vinha do
cabeçalho `X-Empresa-Id`, e o cabeçalho vem do cliente. Na primeira versão nada conferia se
quem pediu tinha vínculo com a empresa pedida, e as quatro rotas do módulo não exigiam
credencial nenhuma — eram as únicas 4 operações sem `security` num contrato de 55. Quem
soubesse um `tenant_id` lia e escrevia naquela empresa.

Fechado em `app/modules/bakeoff/deps.py`: token obrigatório (401), empresa declarada (400),
vínculo conferido em `employee_company` (403), nessa ordem, antes de qualquer query de
negócio. A checagem roda **sob a própria política** — a empresa é declarada primeiro, então
a consulta a `employee_company` já sai recortada, sem `WHERE tenant_id` escrito à mão.

**O que isso diz para a comparação entre as três stacks:** o trabalho de RLS não termina no
banco. Qualquer uma delas vai precisar de uma camada equivalente na borda, e o custo dela
não aparece em "linhas do `tenancy.py`". Se os outros dois protótipos declararem o tenant
por header sem verificar vínculo, estarão medindo a mesma metade que eu medi primeiro — e a
coluna de linhas de código estará comparando entregas diferentes.

**Ressalva de latência, se a comparação incluir tempo de resposta.** A checagem de vínculo
custa uma consulta a mais por request, `GET /produtos` incluído — que é justamente o
endpoint que o bake-off cronometra. Ela faz `lower(employees.email)`, o que impede o uso do
índice único da coluna e força varredura:

```
com lower()   Seq Scan on employees        (cost=0.00..11.65)
coluna crua   Index Scan using uq_employees_email  (cost=0.14..8.16)
```

Fica assim de propósito. A correção seria um índice funcional em `lower(email)`, e
`employees` faz parte do schema **fixo** do banco compartilhado, onde a regra é não criar
índice. Criá-lo só na migração local resolveria o número e estragaria a medida: mediríamos
um schema que o Neon não tem. A tabela é pequena — pessoas do grupo, não documentos —,
então o custo real é ruído; o que não seria ruído é comparar latência sem que os três
protótipos façam a mesma checagem. **No VITRA real, onde o schema é nosso, o índice entra.**

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
