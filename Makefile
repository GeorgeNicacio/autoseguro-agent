# Atalhos do avaliador. Sem `make` (Windows): rode os comandos da direita de dentro de agent/.
UV ?= uv
AGENT = cd agent &&

.PHONY: setup up down demo golden test unit contract chaos chaos-report api chat lint fmt typecheck check

setup:        ## instala dependências do agente (uv + lockfile)
	$(AGENT) $(UV) sync

up:           ## sobe o quote-service
	docker compose up --build -d quote-api

demo:         ## conversa completa com timeout, 5xx e retry visíveis (só precisa de Docker)
	docker compose up --build -d
	docker compose --profile demo up --build -d quote-api-demo
	docker compose --profile demo restart quote-api-demo
	docker compose exec agent python -m autoseguro_agent.evaluation.demo --url http://quote-api-demo:8000

golden:       ## golden set (20 cenários) contra a API sem falha simulada
	docker compose --profile golden up --build -d quote-api-stable
	$(AGENT) $(UV) run pytest -q -m golden tests/scenarios/test_golden.py

down:
	docker compose down

test: up      ## unit + contrato (contrato pula se a API estiver fora)
	$(AGENT) $(UV) run pytest -q

unit:
	$(AGENT) $(UV) run pytest -q tests/unit

contract: up
	$(AGENT) $(UV) run pytest -q tests/contract

chaos:       ## sobe a API com 60% de falha + 20% lenta (seed 42) e roda o teste de caos
	docker compose --profile chaos up --build -d quote-api-chaos
	docker compose --profile chaos restart quote-api-chaos
	$(AGENT) $(UV) run pytest -q -m chaos tests/chaos

chaos-report: ## mesmo caos, gravando o relatório em docs/evidence
	docker compose --profile chaos restart quote-api-chaos
	$(AGENT) $(UV) run python -m autoseguro_agent.evaluation.chaos --out ../docs/evidence/chaos_report.json

api: up       ## webhook WhatsApp + linha do tempo em http://localhost:8080
	$(AGENT) $(UV) run uvicorn autoseguro_agent.api:app --port 8080

chat: up      ## chat no terminal (sem chave: make chat ARGS=--fake-llm)
	$(AGENT) $(UV) run python -m autoseguro_agent.cli --events $(ARGS)

lint:
	$(AGENT) $(UV) run ruff check . && $(UV) run ruff format --check .

fmt:
	$(AGENT) $(UV) run ruff format . && $(UV) run ruff check --fix .

typecheck:
	$(AGENT) $(UV) run mypy

check: lint typecheck test   ## o que roda antes de cada commit
