# Atalhos do avaliador. Sem `make` (Windows): rode os comandos da direita de dentro de agent/.
UV ?= uv
AGENT = cd agent &&

.PHONY: setup up down test unit contract lint fmt typecheck check

setup:        ## instala dependências do agente (uv + lockfile)
	$(AGENT) $(UV) sync

up:           ## sobe o quote-service
	docker compose up --build -d quote-api

down:
	docker compose down

test: up      ## unit + contrato (contrato pula se a API estiver fora)
	$(AGENT) $(UV) run pytest -q

unit:
	$(AGENT) $(UV) run pytest -q tests/unit

contract: up
	$(AGENT) $(UV) run pytest -q tests/contract

lint:
	$(AGENT) $(UV) run ruff check . && $(UV) run ruff format --check .

fmt:
	$(AGENT) $(UV) run ruff format . && $(UV) run ruff check --fix .

typecheck:
	$(AGENT) $(UV) run mypy

check: lint typecheck test   ## o que roda antes de cada commit
