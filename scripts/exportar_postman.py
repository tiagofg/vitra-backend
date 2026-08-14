"""Gera a collection do Postman a partir do `openapi.json`.

    python scripts/exportar_postman.py     # ou: make postman

Por que gerar, e não versionar uma collection escrita à mão: uma collection com 99
requests é uma segunda descrição da API. Duas descrições divergem, e a que ninguém executa
é sempre a que apodrece — no dia em que uma rota nova entrar, quem editou o router não vai
lembrar de editar um JSON de 4 mil linhas. O `openapi.json` já é a fonte de verdade do
repositório (o front gera o cliente a partir dele, e o job `contrato` do CI reprova PR que o
deixe desatualizado); a collection passa a ser derivada dele, como o cliente do front.

O que o gerador acrescenta ao que o import de OpenAPI do próprio Postman já faria:

* **Uma pasta de preparo que deixa a collection executável de cima a baixo.** Login guarda
  o token, o lookup de empresas guarda a `empresa_id`, `trocar-empresa` troca o token por um
  com a empresa dentro. Sem isso, todo request por empresa responde `400` no Runner.
* **Encadeamento de `id`.** Todo `POST` que cria recurso guarda o `id` da resposta na
  variável que as rotas `{id}` daquele recurso consomem — criar um cliente deixa
  `GET/PUT/DELETE /clientes/{{cliente_id}}` prontos.
* **Corpos que passam na validação.** Os das rotas principais são os mesmos exemplos do
  README, conferidos contra os schemas Pydantic; o resto sai do schema do contrato, só com
  os campos obrigatórios e os que têm default — corpo enxuto que o servidor aceita, em vez
  de todos os campos anuláveis preenchidos com `null`.
* **Teste comum a todo request**: nada de 5xx, e resposta de erro no envelope
  `{"erro": {"codigo", "mensagem", "campos"}}` — a invariante de `app/core/errors.py`
  passa a ser verificada por qualquer varredura no Runner.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[1]
CONTRATO = RAIZ / "openapi.json"
DESTINO = RAIZ / "postman"
ARQ_COLLECTION = DESTINO / "vitra.postman_collection.json"
ARQ_AMBIENTE = DESTINO / "vitra.postman_environment.json"

SCHEMA_COLLECTION = "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"
# `uuid5` e não `uuid4`: o id precisa ser estável entre gerações, senão cada `make postman`
# sujaria o diff com um id novo — mesmo motivo de o `openapi.json` ser determinístico.
NAMESPACE = uuid.UUID("6f1b4d6c-9f3a-4a1e-8b2c-5d7e9f0a1b2c")

# Ordem das pastas. Declarada, e não alfabética: o Runner executa de cima para baixo, e
# "Preparo" precisa vir antes de qualquer coisa que dependa de token ou de empresa ativa.
ORDEM_TAGS = ["auth", "acesso", "empresa", "apoio", "produtos", "pessoas", "infra"]

ROTULOS = {
    "auth": "Autenticação",
    "acesso": "Acesso — usuários, grupos, permissões",
    "empresa": "Empresa, filial e centro de custo",
    "apoio": "Tabelas de apoio, UF, cidade e banco",
    "produtos": "Produtos",
    "pessoas": "Pessoas — parceiro (cliente/fornecedor/profissional), colaborador…",
    "estoque": "Estoque — locais, saldos e extrato de movimentos",
    "vendas": "Vendas — orçamento, ambientes e itens",
    "infra": "Infra",
}

# Primeiro segmento do path → nome da variável que guarda o `id` daquele recurso. O
# `crud_router` chama todo path param de `{item_id}`, então o nome do recurso é a única
# pista de qual `id` é qual; singularizar em português por regra dá errado o bastante
# (`filiais`, `profissionais-externos`, `centros-custo`) para não valer a esperteza.
RECURSOS = {
    # **Não** é `empresa_id`. Essa variável é a empresa *ativa* — vai no `X-Empresa-Id` de
    # 92 requests e no corpo do `trocar-empresa`. Se o `POST /empresas` gravasse nela, a
    # empresa ativa viraria a recém-criada, com a qual o usuário não tem vínculo, e todo
    # request seguinte responderia 403; o `DELETE` então desativaria a empresa da própria
    # sessão. São dois conceitos que só por acaso têm o mesmo nome no path.
    "empresas": "empresa_recurso_id",
    "filiais": "filial_id",
    "centros-custo": "centro_custo_id",
    "grupos": "grupo_id",
    "usuarios": "usuario_id",
    "permissoes": "permissao_id",
    "apoio": "apoio_id",
    "cidades": "cidade_id",
    "bancos": "banco_id",
    "ufs": "uf_id",
    "produtos": "produto_id",
    # Sem estes dois, a busca para trás em `/produtos/{produto_id}/grupos-relacionados/
    # {grupo_id}/itens/{item_id}` acha "produtos" antes de qualquer outra coisa e resolve
    # os três `{id}` para `{{produto_id}}` — a rota vira uma URL que nunca casa.
    "grupos-relacionados": "grupo_relacionado_id",
    "itens": "item_relacionado_id",
    "parceiros": "parceiro_id",
    "obras": "obra_id",
    "colaboradores": "colaborador_id",
    "transportadoras": "transportadora_id",
    "locais": "local_estoque_id",
    "movimentos": "movimento_id",
    "orcamentos": "orcamento_id",
}

# Corpos das rotas que alguém realmente exercita à mão. São os mesmos exemplos do README,
# conferidos um a um contra os schemas Pydantic — o gerador de schema abaixo produz corpo
# válido, mas não produz corpo *interessante* (nem sabe que `admin12345` é a senha do seed).
CORPOS = {
    ("post", "/api/v1/auth/login"): {"login": "admin", "senha": "admin12345"},
    ("post", "/api/v1/auth/trocar-empresa"): {"empresa_id": "{{empresa_id}}"},
    ("post", "/api/v1/auth/refresh"): {"refresh_token": "{{refresh_token}}"},
    ("post", "/api/v1/auth/alterar-senha"): {
        "senha_atual": "admin12345",
        "senha_nova": "outra-senha-forte",
    },
    ("post", "/api/v1/parceiros"): {
        "codigo": "PAR010",
        "razao_social": "Maria Andrade",
        "tipo_pessoa": "fisica",
        "e_cliente": True,
        "e_fornecedor": False,
        "e_profissional": False,
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
        "observacao": "Indicada pelo escritório ADR.",
    },
    ("post", "/api/v1/parceiros/{parceiro_id}/obras"): {
        "nome": "Residência Alphaville",
        "endereco_cep": "06474-000",
        "endereco_logradouro": "Alameda Rio Negro",
        "endereco_numero": "500",
        "endereco_bairro": "Alphaville",
    },
    ("post", "/api/v1/produtos"): {
        "codigo": "PEND010",
        "descricao": "Pendente Aurora 40cm",
        "descricao_complementar": "Cúpula em alumínio, cabo têxtil de 1,5 m",
        "codigo_reduzido": "PA40",
        "ncm": "94051100",
        "cest": "2110300",
        "origem": "0",
        "qtd_entrada": 1,
        "qtd_saida": 1,
        "fora_de_linha": False,
        "consultar_valor": False,
        "sobre_medida": False,
        "publicar_no_site": True,
        "especificacao": {
            "potencia_watts": 12.5,
            "tensao": "Bivolt",
            "fluxo_luminoso_lumens": 1100,
            "angulo_abertura_graus": 36,
            "temperatura_cor_kelvin": 3000,
            "ip": "IP20",
            "base_soquete": "GU10",
            "regulavel": True,
            "vida_util_horas": 25000,
            "comprimento_mm": 400,
            "largura_mm": 400,
            "altura_mm": 1200,
            "peso_kg": 2.4,
        },
    },
    ("put", "/api/v1/produtos/{item_id}"): {
        "descricao": "Pendente Aurora 40cm",
        "variantes": [
            {
                "acabamento_id": "{{acabamento_id}}",
                "tamanho_id": "{{tamanho_id}}",
                "ativo": True,
            }
        ],
        "fornecedores": [
            {
                "fornecedor_id": "{{fornecedor_id}}",
                "codigo_fornecedor": "LUM-AUR-40",
                "descricao_fornecedor": "Pendente Aurora 40 preto",
                "padrao": True,
            }
        ],
        "grupos_relacionados": [{"nome": "Acessórios sugeridos", "padrao": True, "ativo": True}],
    },
    ("post", "/api/v1/produtos/{produto_id}/grupos-relacionados/{grupo_id}/itens"): {
        "produto_id": "{{produto_id}}",
        "quantidade": "2.000",
        "padrao": True,
    },
    ("post", "/api/v1/apoio/{dominio}"): {
        "descricao": "Alumínio escovado",
        "codigo": "escovado",
        "ordem": 10,
    },
    ("post", "/api/v1/usuarios"): {
        "login": "ana.silva",
        "nome": "Ana Silva",
        "senha": "senha-forte-123",
        "email": "ana.silva@vertz.com.br",
        "superusuario": False,
        "limite_desconto_pct": "10.0000",
        "grupo_ids": ["{{grupo_id}}"],
    },
    ("post", "/api/v1/fornecedores/{fornecedor_id}/empresas-compradoras"): {
        "empresa_compradora_id": "{{empresa_id}}",
        "vigencia_inicio": "2026-08-01",
        "motivo": "Centralização de compras na matriz",
    },
}

# `{dominio}` não é id de recurso: é o discriminador dos 19 combos. Vale um default útil.
VALORES_PADRAO_PATH = {"dominio": "marca"}

TESTE_COMUM = [
    "// Vale para todo request da collection.",
    "pm.test('não é 5xx', function () {",
    "    pm.expect(pm.response.code).to.be.below(500);",
    "});",
    "",
    "// Uma variável de path vazia não deixa a URL inválida — ela some, e",
    "// `/produtos/{{produto_id}}` vira `/produtos/`, que é a *listagem* e responde 200.",
    "// Sem esta checagem, 'obter' e 'desativar' passariam verdes sem nunca terem sido",
    "// exercidos. Falhar aqui é o ponto: diz qual variável falta preencher.",
    "pm.test('nenhuma variável de path ficou vazia', function () {",
    "    const vazios = (pm.request.url.path || []).filter(function (s) {",
    "        return s === '' || s === null || s === undefined;",
    "    });",
    "    pm.expect(vazios.length, 'segmento vazio na URL — rode a pasta 00 — Preparo').to.eql(0);",
    "});",
    "",
    "// Envelope único de erro (app/core/errors.py). Se um dia um handler responder erro",
    "// fora deste formato, o front que gera cliente a partir do contrato quebra — e é",
    "// aqui que aparece primeiro.",
    "if (pm.response.code >= 400) {",
    "    pm.test('erro sai no envelope {erro:{codigo,mensagem,campos}}', function () {",
    "        const corpo = pm.response.json();",
    "        pm.expect(corpo).to.have.property('erro');",
    "        pm.expect(corpo.erro).to.have.property('codigo');",
    "        pm.expect(corpo.erro).to.have.property('mensagem');",
    "        pm.expect(corpo.erro).to.have.property('campos');",
    "    });",
    "}",
]


def carregar_contrato() -> dict[str, Any]:
    if not CONTRATO.exists():
        raise SystemExit(
            f"{CONTRATO} não existe — rode `make openapi` antes (a collection é derivada dele)."
        )
    return json.loads(CONTRATO.read_text(encoding="utf-8"))


# --- geração de exemplo a partir do schema ------------------------------------------


def resolver(schema: dict[str, Any], contrato: dict[str, Any]) -> dict[str, Any]:
    """Segue `$ref` até um schema concreto."""
    visto = 0
    while "$ref" in schema:
        visto += 1
        if visto > 20:  # ciclo de $ref: devolve algo inerte em vez de rodar para sempre
            return {}
        caminho = schema["$ref"].removeprefix("#/").split("/")
        alvo: Any = contrato
        for parte in caminho:
            alvo = alvo[parte]
        schema = alvo
    return schema


def _sem_nulo(schema: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """`anyOf: [X, null]` é como o Pydantic escreve `X | None`. Devolve X e se é anulável."""
    opcoes = schema.get("anyOf") or schema.get("oneOf")
    if not opcoes:
        return schema, False
    concretas = [o for o in opcoes if o.get("type") != "null"]
    anulavel = len(concretas) != len(opcoes)
    return (concretas[0] if concretas else {}), anulavel


def exemplo(nome: str, schema: dict[str, Any], contrato: dict[str, Any], nivel: int = 0) -> Any:
    """Um valor plausível para o campo `nome`, segundo o schema do contrato."""
    if nivel > 6:  # schema recursivo — corta antes de estourar a pilha
        return None

    schema = resolver(schema, contrato)
    schema, _ = _sem_nulo(schema)
    schema = resolver(schema, contrato)

    if "default" in schema and schema["default"] is not None:
        return schema["default"]
    if schema.get("examples"):
        return schema["examples"][0]
    if "const" in schema:
        return schema["const"]
    if schema.get("enum"):
        return schema["enum"][0]

    tipo = schema.get("type")
    formato = schema.get("format")

    if formato == "uuid" or (nome.endswith("_id") and tipo == "string"):
        # Vira variável em vez de UUID inventado: um UUID literal falha na FK, e o Postman
        # mostra a variável vazia em vermelho — o campo se anuncia como "preencha-me".
        return "{{" + nome + "}}"
    if formato == "date":
        return "2026-08-01"
    if formato == "date-time":
        return "2026-08-01T12:00:00Z"
    if formato == "email" or nome.startswith("email"):
        return "contato@vertz.com.br"

    if tipo == "string":
        return _exemplo_texto(nome, schema)
    if tipo == "integer":
        return schema.get("minimum", 0) or 0
    if tipo == "number":
        return 0
    if tipo == "boolean":
        return False
    if tipo == "array":
        itens = schema.get("items")
        if not itens:
            return []
        gerado = exemplo(nome.removesuffix("s"), itens, contrato, nivel + 1)
        return [gerado] if gerado is not None else []
    if tipo == "object" or "properties" in schema:
        return corpo_do_schema(schema, contrato, nivel + 1)
    return None


def _exemplo_texto(nome: str, schema: dict[str, Any]) -> str:
    por_nome = {
        "codigo": "COD001",
        "nome": "Exemplo",
        "descricao": "Descrição de exemplo",
        "razao_social": "Empresa Exemplo Ltda",
        "senha": "senha-forte-123",
        "login": "usuario.exemplo",
    }
    valor = por_nome.get(nome, "texto")
    limite = schema.get("maxLength")
    return valor[:limite] if isinstance(limite, int) else valor


def corpo_do_schema(
    schema: dict[str, Any], contrato: dict[str, Any], nivel: int = 0
) -> dict[str, Any]:
    """Corpo com o que é obrigatório mais o que tem default declarado.

    Não emite os opcionais anuláveis: um corpo com 30 chaves em `null` não ajuda quem vai
    testar, e o servidor trata ausente e `null` igual nesses campos.
    """
    schema = resolver(schema, contrato)
    propriedades = schema.get("properties", {})
    obrigatorios = set(schema.get("required", []))

    corpo: dict[str, Any] = {}
    for nome, sub in propriedades.items():
        sub_resolvido = resolver(sub, contrato)
        tem_default = "default" in sub_resolvido and sub_resolvido["default"] is not None
        if nome not in obrigatorios and not tem_default:
            continue
        valor = exemplo(nome, sub, contrato, nivel)
        if valor is not None:
            corpo[nome] = valor
    return corpo


# --- montagem dos requests ----------------------------------------------------------


def variavel_do_path(partes: list[str], indice: int, nome_param: str) -> str:
    """Qual variável preenche este `{param}`, olhando o segmento que vem antes dele."""
    if nome_param in VALORES_PADRAO_PATH:
        return VALORES_PADRAO_PATH[nome_param]
    for anterior in reversed(partes[:indice]):
        if not anterior.startswith("{") and anterior in RECURSOS:
            return "{{" + RECURSOS[anterior] + "}}"
    return "{{" + nome_param + "}}"


def montar_url(path: str, operacao: dict[str, Any]) -> tuple[dict[str, Any], set[str]]:
    partes = [p for p in path.split("/") if p]
    usadas: set[str] = set()

    segmentos: list[str] = []
    for i, parte in enumerate(partes):
        if parte.startswith("{") and parte.endswith("}"):
            nome = parte[1:-1]
            valor = variavel_do_path(partes, i, nome)
            if valor.startswith("{{"):
                usadas.add(valor[2:-2])
            segmentos.append(valor)
        else:
            segmentos.append(parte)

    query = []
    for parametro in operacao.get("parameters", []):
        if parametro.get("in") != "query":
            continue
        esquema, _ = _sem_nulo(parametro.get("schema", {}))
        padrao = esquema.get("default")
        query.append(
            {
                "key": parametro["name"],
                "value": "" if padrao is None else str(padrao),
                # Desabilitado: aparece no Postman como documentação do que dá para filtrar,
                # sem alterar o request de quem só quer ver a listagem inteira.
                "disabled": True,
                "description": parametro.get("description", ""),
            }
        )

    caminho = "/".join(segmentos)
    bruto = "{{base_url}}/" + caminho
    if query:
        bruto += "?" + "&".join(f"{q['key']}={q['value']}" for q in query)

    url: dict[str, Any] = {"raw": bruto, "host": ["{{base_url}}"], "path": segmentos}
    if query:
        url["query"] = query
    return url, usadas


def script_de_captura(metodo: str, path: str) -> list[str] | None:
    """`POST` que cria recurso guarda o `id` na variável que as rotas `{id}` consomem."""
    if metodo != "post":
        return None
    partes = [p for p in path.split("/") if p and not p.startswith("{")]
    if not partes:
        return None
    variavel = RECURSOS.get(partes[-1])
    if variavel is None:
        return None
    return [
        "if (pm.response.code === 201) {",
        "    const corpo = pm.response.json();",
        "    if (corpo && corpo.id) {",
        f"        pm.collectionVariables.set('{variavel}', corpo.id);",
        f"        console.log('{variavel} =', corpo.id);",
        "    }",
        "}",
    ]


def montar_request(
    metodo: str, path: str, operacao: dict[str, Any], contrato: dict[str, Any]
) -> tuple[dict[str, Any], set[str]]:
    url, usadas = montar_url(path, operacao)

    cabecalhos = []
    if any(p.get("name") == "x-empresa-id" for p in operacao.get("parameters", [])):
        cabecalhos.append(
            {
                "key": "X-Empresa-Id",
                "value": "{{empresa_id}}",
                "description": (
                    "Empresa ativa. Tem prioridade sobre o claim do token. Desligue este "
                    "cabeçalho se preferir operar pela empresa que está dentro do token "
                    "(POST /auth/trocar-empresa)."
                ),
            }
        )
        usadas.add("empresa_id")

    requisicao: dict[str, Any] = {
        "method": metodo.upper(),
        "header": cabecalhos,
        "url": url,
        "description": operacao.get("description", "") or operacao.get("summary", ""),
    }

    # Sem `security` na operação = rota pública (login, refresh, /saude). Herdar o Bearer
    # da collection mandaria um token possivelmente vencido para o próprio login.
    if not operacao.get("security"):
        requisicao["auth"] = {"type": "noauth"}

    corpo_bruto = CORPOS.get((metodo, path))
    if corpo_bruto is None:
        conteudo = operacao.get("requestBody", {}).get("content", {}).get("application/json")
        if conteudo:
            corpo_bruto = corpo_do_schema(conteudo["schema"], contrato)
    if corpo_bruto is not None:
        requisicao["header"] = [
            {"key": "Content-Type", "value": "application/json"},
            *cabecalhos,
        ]
        requisicao["body"] = {
            "mode": "raw",
            "raw": json.dumps(corpo_bruto, indent=2, ensure_ascii=False),
            "options": {"raw": {"language": "json"}},
        }
        usadas |= _variaveis_em(corpo_bruto)

    item: dict[str, Any] = {
        "name": operacao.get("summary") or f"{metodo.upper()} {path}",
        "request": requisicao,
    }

    captura = script_de_captura(metodo, path)
    if captura:
        item["event"] = [{"listen": "test", "script": {"type": "text/javascript", "exec": captura}}]
    return item, usadas


def _variaveis_em(valor: Any) -> set[str]:
    """Nomes de `{{variavel}}` usados dentro de um corpo, em qualquer profundidade."""
    encontradas: set[str] = set()
    if isinstance(valor, str):
        if valor.startswith("{{") and valor.endswith("}}"):
            encontradas.add(valor[2:-2])
    elif isinstance(valor, dict):
        for item in valor.values():
            encontradas |= _variaveis_em(item)
    elif isinstance(valor, list):
        for item in valor:
            encontradas |= _variaveis_em(item)
    return encontradas


# --- pasta de preparo ---------------------------------------------------------------


def _req(
    nome: str,
    metodo: str,
    caminho: str,
    *,
    corpo: dict[str, Any] | None = None,
    testes: list[str] | None = None,
    autenticado: bool = True,
    descricao: str = "",
) -> dict[str, Any]:
    segmentos = [p for p in caminho.split("/") if p]
    requisicao: dict[str, Any] = {
        "method": metodo,
        "header": [],
        "url": {
            "raw": "{{base_url}}/" + "/".join(segmentos),
            "host": ["{{base_url}}"],
            "path": segmentos,
        },
        "description": descricao,
    }
    if not autenticado:
        requisicao["auth"] = {"type": "noauth"}
    if corpo is not None:
        requisicao["header"] = [{"key": "Content-Type", "value": "application/json"}]
        requisicao["body"] = {
            "mode": "raw",
            "raw": json.dumps(corpo, indent=2, ensure_ascii=False),
            "options": {"raw": {"language": "json"}},
        }
    item: dict[str, Any] = {"name": nome, "request": requisicao}
    if testes:
        item["event"] = [{"listen": "test", "script": {"type": "text/javascript", "exec": testes}}]
    return item


# Cada entrada: (variável, caminho do lookup ou da listagem). Os `/lookup` devolvem lista
# crua; as listagens devolvem `Pagina`, com os registros em `itens` — o script trata os dois.
FONTES_DE_ID = [
    ("produto_id", "/api/v1/produtos/lookup"),
    ("cliente_id", "/api/v1/clientes/lookup"),
    ("fornecedor_id", "/api/v1/fornecedores/lookup"),
    ("colaborador_id", "/api/v1/colaboradores/lookup"),
    ("profissional_externo_id", "/api/v1/profissionais-externos/lookup"),
    ("transportadora_id", "/api/v1/transportadoras/lookup"),
    ("cidade_id", "/api/v1/cidades/lookup"),
    ("banco_id", "/api/v1/bancos/lookup"),
    ("acabamento_id", "/api/v1/apoio/acabamento/lookup"),
    ("tamanho_id", "/api/v1/apoio/tamanho/lookup"),
    ("marca_id", "/api/v1/apoio/marca/lookup"),
    ("apoio_id", "/api/v1/apoio/marca/lookup"),
    ("uf_id", "/api/v1/ufs"),
    ("employee_id", "/api/v1/usuarios"),
    ("permissao_id", "/api/v1/permissoes"),
    ("filial_id", "/api/v1/filiais"),
    ("centro_custo_id", "/api/v1/centros-custo"),
]

# Ficam de fora do preparo de propósito: `usuario_id`, `grupo_id` e `empresa_recurso_id`.
# O primeiro registro de cada uma dessas listagens é, respectivamente, o `admin`, o grupo
# `Administradores` e uma das empresas do seed — e cada recurso tem um `DELETE` nesta
# collection. Apontar a variável para eles é oferecer "desative o seu próprio acesso" a um
# clique de distância. Elas são preenchidas pelo `POST` do próprio recurso, que roda antes
# do `{id}` na ordem da pasta; quem pular o `POST` recebe o vermelho de path vazio, que é a
# resposta certa. Recurso cujo `DELETE` só desativa dado de exemplo (cliente, produto,
# fornecedor…) continua sendo pré-preenchido.

SCRIPT_CAPTURAR_IDS = [
    "// Um leque de sendRequest: um request só do Postman, várias consultas.",
    "const fontes = [",
    *[f"    ['{variavel}', '{caminho}']," for variavel, caminho in FONTES_DE_ID],
    "];",
    "",
    "const base = pm.collectionVariables.get('base_url');",
    "const token = pm.collectionVariables.get('token');",
    "const empresa = pm.collectionVariables.get('empresa_id');",
    "let pendentes = fontes.length;",
    "const faltando = [];",
    "",
    "fontes.forEach(function (par) {",
    "    const variavel = par[0];",
    "    const caminho = par[1];",
    "    pm.sendRequest({",
    "        url: base + caminho,",
    "        method: 'GET',",
    "        header: {",
    "            'Authorization': 'Bearer ' + token,",
    "            'X-Empresa-Id': empresa",
    "        }",
    "    }, function (erro, resposta) {",
    "        pendentes -= 1;",
    "        if (!erro && resposta && resposta.code === 200) {",
    "            const corpo = resposta.json();",
    "            // `/lookup` devolve lista; listagem devolve `Pagina` com `itens`.",
    "            const registros = Array.isArray(corpo) ? corpo : (corpo.itens || []);",
    "            if (registros.length > 0 && registros[0].id) {",
    "                pm.collectionVariables.set(variavel, registros[0].id);",
    "            } else {",
    "                faltando.push(variavel);",
    "            }",
    "        } else {",
    "            faltando.push(variavel);",
    "        }",
    "        if (pendentes === 0 && faltando.length > 0) {",
    "            console.warn('sem registro para: ' + faltando.join(', ') +",
    "                ' — crie um pelo POST do recurso, ou rode scripts/seed.py');",
    "        }",
    "    });",
    "});",
    "",
    "pm.test('preparo concluído', function () {",
    "    pm.response.to.have.status(200);",
    "});",
]


def pasta_de_preparo() -> dict[str, Any]:
    """Os quatro passos que tornam o resto da collection executável, na ordem certa."""
    return {
        "name": "00 — Preparo (rode primeiro)",
        "description": (
            "Executar esta pasta de cima para baixo deixa `token` e `empresa_id` "
            "preenchidos; sem isso, toda rota por empresa responde 400.\n\n"
            "No Collection Runner, rodar a collection inteira já começa por aqui."
        ),
        "item": [
            _req(
                "1. Login (guarda o token)",
                "POST",
                "/api/v1/auth/login",
                corpo={"login": "admin", "senha": "admin12345"},
                autenticado=False,
                descricao="Credenciais do seed. Troque a senha em qualquer ambiente real.",
                testes=[
                    "pm.test('login respondeu 200', function () {",
                    "    pm.response.to.have.status(200);",
                    "});",
                    "",
                    "const corpo = pm.response.json();",
                    "pm.collectionVariables.set('token', corpo.access_token);",
                    "pm.collectionVariables.set('refresh_token', corpo.refresh_token);",
                ],
            ),
            _req(
                "2. Empresas disponíveis (guarda a empresa_id)",
                "GET",
                "/api/v1/empresas/lookup",
                descricao=(
                    "`/empresas` é tabela global — responde sem empresa ativa, e é por isso "
                    "que este passo consegue vir antes de declarar qual empresa é a ativa."
                ),
                testes=[
                    "pm.test('lookup respondeu 200', function () {",
                    "    pm.response.to.have.status(200);",
                    "});",
                    "",
                    "const itens = pm.response.json();",
                    "if (itens.length > 0) {",
                    "    // O seed cria VERTZ e VIAHF; fica com a VERTZ quando ela aparece.",
                    "    const vertz = itens.find(function (i) { return i.codigo === 'VERTZ'; });",
                    "    const escolhida = vertz || itens[0];",
                    "    pm.collectionVariables.set('empresa_id', escolhida.id);",
                    "    console.log('empresa ativa =', escolhida.label, escolhida.id);",
                    "} else {",
                    "    console.warn('nenhuma empresa — rodou scripts/seed.py?');",
                    "}",
                ],
            ),
            _req(
                "3. Trocar empresa (token passa a carregar a empresa)",
                "POST",
                "/api/v1/auth/trocar-empresa",
                corpo={"empresa_id": "{{empresa_id}}"},
                descricao=(
                    "Opcional: com o token carregando a empresa, o cabeçalho `X-Empresa-Id` "
                    "deixa de ser necessário. A collection manda os dois — o cabeçalho tem "
                    "prioridade, e ambos passam pela mesma checagem de vínculo."
                ),
                testes=[
                    "pm.test('trocou de empresa', function () {",
                    "    pm.response.to.have.status(200);",
                    "});",
                    "",
                    "const corpo = pm.response.json();",
                    "pm.collectionVariables.set('token', corpo.access_token);",
                    "pm.collectionVariables.set('refresh_token', corpo.refresh_token);",
                ],
            ),
            _req(
                "4. Quem sou eu (confere permissões)",
                "GET",
                "/api/v1/auth/eu",
                descricao="Mostra grupos e permissões efetivas — o diagnóstico de todo 403.",
                testes=[
                    "pm.test('token vale', function () {",
                    "    pm.response.to.have.status(200);",
                    "});",
                ],
            ),
            _req(
                "5. Capturar ids de exemplo",
                "GET",
                "/saude",
                autenticado=False,
                descricao=(
                    "Preenche `produto_id`, `cliente_id`, `acabamento_id` e companhia com o "
                    "primeiro registro que já existe no banco, varrendo os `/lookup` num "
                    "leque de `pm.sendRequest`.\n\n"
                    "Sem isto, as rotas `{id}` saem com a variável vazia — e aí a URL "
                    "`/produtos/{{produto_id}}` colapsa para `/produtos/`, que é a listagem "
                    "e responde 200. O request passaria verde sem ter exercido nada."
                ),
                testes=SCRIPT_CAPTURAR_IDS,
            ),
        ],
    }


# --- montagem final ------------------------------------------------------------------


def construir(contrato: dict[str, Any]) -> tuple[dict[str, Any], int]:
    pastas: dict[str, list[dict[str, Any]]] = {}
    usadas: set[str] = set()
    total = 0

    for path, item in sorted(contrato["paths"].items()):
        for metodo, operacao in item.items():
            if metodo not in ("get", "post", "put", "delete", "patch"):
                continue
            requisicao, do_request = montar_request(metodo, path, operacao, contrato)
            usadas |= do_request
            tag = (operacao.get("tags") or ["outros"])[0]
            pastas.setdefault(tag, []).append(requisicao)
            total += 1

    itens: list[dict[str, Any]] = [pasta_de_preparo()]
    conhecidas = [t for t in ORDEM_TAGS if t in pastas]
    for tag in conhecidas + sorted(set(pastas) - set(ORDEM_TAGS)):
        itens.append(
            {
                "name": f"{ROTULOS.get(tag, tag)} ({len(pastas[tag])})",
                "item": pastas[tag],
            }
        )

    fixas = ["base_url", "token", "refresh_token", "empresa_id"]
    variaveis = [
        {"key": "base_url", "value": "http://localhost:8000", "type": "string"},
        {"key": "token", "value": "", "type": "string"},
        {"key": "refresh_token", "value": "", "type": "string"},
        {"key": "empresa_id", "value": "", "type": "string"},
    ]
    for nome in sorted(usadas - set(fixas)):
        variaveis.append({"key": nome, "value": "", "type": "string"})

    collection = {
        "info": {
            "_postman_id": str(uuid.uuid5(NAMESPACE, "vitra-backend")),
            "name": "VITRA API",
            "description": DESCRICAO_COLLECTION,
            "schema": SCHEMA_COLLECTION,
        },
        "auth": {
            "type": "bearer",
            "bearer": [{"key": "token", "value": "{{token}}", "type": "string"}],
        },
        "event": [{"listen": "test", "script": {"type": "text/javascript", "exec": TESTE_COMUM}}],
        "variable": variaveis,
        "item": itens,
    }
    return collection, total


DESCRICAO_COLLECTION = """\
Collection gerada a partir do `openapi.json` por `scripts/exportar_postman.py`
(`make postman`). **Não edite à mão** — a próxima geração desfaz.

## Como usar

1. Suba a API (`make api`) com o banco migrado e semeado (`make migrar`, `make runtime`,
   `make seed`).
2. Importe também `vitra.postman_environment.json` e selecione o ambiente, ou use os
   valores default das variáveis da própria collection.
3. Rode a pasta **00 — Preparo** de cima para baixo. Ela guarda `token` e `empresa_id`;
   sem isso, toda rota por empresa responde `400 empresa_nao_declarada`.

## O que já vem resolvido

- **Autenticação**: Bearer `{{token}}` na collection inteira. Login, refresh e `/saude` são
  os únicos sem auth, como no contrato.
- **Empresa ativa**: as rotas por empresa mandam `X-Empresa-Id: {{empresa_id}}`. Se preferir
  operar pela empresa que está dentro do token, desligue o cabeçalho — os dois caminhos
  passam pela mesma checagem de vínculo.
- **Encadeamento de id**: todo `POST` que cria guarda o `id` na variável do recurso, então
  criar um cliente já deixa `GET/PUT/DELETE /clientes/{{cliente_id}}` prontos.
- **Filtros de listagem** (`busca`, `pagina`, `ordenar_por`…) vêm como query params
  desabilitados: ficam à vista sem alterar o request.

## Antes de rodar a collection inteira

Ela **escreve**: são 53 requests `POST`/`PUT`/`DELETE` de 99. Rodar tudo cria cadastros de
exemplo e desativa o que acabou de criar (`DELETE` aqui é `ativo = false`, não apaga).
Aponte para um banco de desenvolvimento, nunca para dado que importa.

Dentro de cada pasta o `POST` vem antes do `{id}`, então o alvo de `PUT`/`DELETE` é o
registro que a própria execução criou — não o do seed. As três variáveis cujo `DELETE`
faria estrago (`usuario_id` → `admin`, `grupo_id` → `Administradores`, `empresa_recurso_id`
→ empresa do seed) **não** são pré-preenchidas: só o `POST` do recurso as define. Pular o
`POST` e ir direto no `DELETE` dá vermelho de path vazio, que é o comportamento desejado.

## O que você ainda precisa preencher

O resto das variáveis `*_id` é preenchido pelo passo 5 do preparo. Sobra o que não tem
lookup nem `POST` na frente — nesses casos o vermelho de "variável de path vazia" diz qual
é. Os UUIDs de apoio saem de `GET /api/v1/apoio/{dominio}/lookup`.
"""


def construir_ambiente() -> dict[str, Any]:
    return {
        "id": str(uuid.uuid5(NAMESPACE, "vitra-ambiente-local")),
        "name": "VITRA — local",
        "values": [
            {"key": "base_url", "value": "http://localhost:8000", "enabled": True},
            {"key": "token", "value": "", "enabled": True},
            {"key": "refresh_token", "value": "", "enabled": True},
            {"key": "empresa_id", "value": "", "enabled": True},
        ],
        "_postman_variable_scope": "environment",
    }


def main() -> None:
    contrato = carregar_contrato()
    collection, total = construir(contrato)

    DESTINO.mkdir(exist_ok=True)
    ARQ_COLLECTION.write_text(
        json.dumps(collection, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    ARQ_AMBIENTE.write_text(
        json.dumps(construir_ambiente(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    pastas = len(collection["item"])
    variaveis = len(collection["variable"])
    print(f"{ARQ_COLLECTION.relative_to(RAIZ)}: {total} requests em {pastas} pastas")
    print(f"{ARQ_AMBIENTE.relative_to(RAIZ)}: ambiente local")
    print(f"variáveis declaradas: {variaveis}")


if __name__ == "__main__":
    main()
