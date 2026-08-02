.PHONY: ajuda hooks db migrar migracao migracoes runtime seed api testes postman \
        lint tipos formatar qualidade checar openapi atualizar

VENV ?= .venv
PY := $(VENV)/bin/python

ajuda:
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) | sed 's/:.*## /\t/'

hooks: ## Instala os hooks de pre-commit (uma vez por clone)
	$(VENV)/bin/pre-commit install --install-hooks

db: ## Sobe o Postgres de desenvolvimento
	docker compose up -d db

migrar: ## Aplica as migrações
	$(VENV)/bin/alembic upgrade head

migracao: ## Gera migração: make migracao m="descrição"
	$(VENV)/bin/alembic revision --autogenerate -m "$(m)"

migracoes: ## Ida e volta das migrações — prova que o downgrade desfaz de verdade
	$(PY) scripts/checar_migracoes.py
	$(VENV)/bin/alembic upgrade head
	$(VENV)/bin/alembic downgrade base
	$(VENV)/bin/alembic upgrade head

runtime: ## Põe vitra_runtime no papel vitra_app (uma vez, após a primeira migração)
	docker compose exec -T db psql -U vitra -d vitra -f - < scripts/conceder_runtime.sql

seed: ## Popula permissões, UFs, empresas e o usuário admin
	$(PY) scripts/seed.py

openapi: ## Publica o contrato em openapi.json — é por ele que o front gera o cliente
	$(PY) scripts/exportar_openapi.py

# Depende do contrato, e não do app: a collection é derivada do `openapi.json`, do mesmo
# jeito que o cliente do front. Regenerar sem republicar o contrato produziria uma
# collection da API de ontem.
postman: openapi ## Gera a collection do Postman em postman/ a partir do contrato
	$(PY) scripts/exportar_postman.py

api: ## Sobe a API em http://localhost:8000/docs
	$(VENV)/bin/uvicorn app.main:app --reload

testes: ## Roda a suíte (sobe Postgres 17 descartável)
	$(VENV)/bin/pytest -q

lint: ## ruff
	$(VENV)/bin/ruff check app tests scripts
	$(VENV)/bin/ruff format --check app tests scripts

tipos: ## mypy
	$(VENV)/bin/mypy app

formatar: ## Aplica ruff format e corrige o que dá
	$(VENV)/bin/ruff check --fix app tests scripts
	$(VENV)/bin/ruff format app tests scripts

# `pytest` não entra: está no estágio pre-push, e `run --all-files` só roda os de commit.
qualidade: ## Todos os hooks de pre-commit, em todos os arquivos — igual ao CI
	$(VENV)/bin/pre-commit run --all-files

atualizar: ## Sobe as dependências para a última estável e reconfere tudo
	$(VENV)/bin/pip install -U -e ".[dev]"
	$(VENV)/bin/pre-commit autoupdate
	$(MAKE) checar

# `qualidade` no lugar de `lint tipos`: é a mesma checagem que o CI roda, pela mesma
# configuração. Duas listas parecidas divergem, e aí o CI reprova o que passou aqui.
checar: qualidade testes migracoes ## Tudo que o CI checaria
