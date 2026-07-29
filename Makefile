.PHONY: ajuda db migrar migracao seed api testes lint tipos formatar checar

VENV ?= .venv
PY := $(VENV)/bin/python

ajuda:
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) | sed 's/:.*## /\t/'

db: ## Sobe o Postgres de desenvolvimento
	docker compose up -d db

migrar: ## Aplica as migrações
	$(VENV)/bin/alembic upgrade head

migracao: ## Gera migração: make migracao m="descrição"
	$(VENV)/bin/alembic revision --autogenerate -m "$(m)"

seed: ## Popula permissões, UFs, empresas e o usuário admin
	$(PY) scripts/seed.py

api: ## Sobe a API em http://localhost:8000/docs
	$(VENV)/bin/uvicorn app.main:app --reload

testes: ## Roda a suíte contra o banco de teste
	$(VENV)/bin/pytest -q

lint: ## ruff
	$(VENV)/bin/ruff check app tests scripts
	$(VENV)/bin/ruff format --check app tests scripts

tipos: ## mypy
	$(VENV)/bin/mypy app

formatar: ## Aplica ruff format e corrige o que dá
	$(VENV)/bin/ruff check --fix app tests scripts
	$(VENV)/bin/ruff format app tests scripts

checar: lint tipos testes ## Tudo que o CI checaria
