COMPOSE = docker compose -f infra/docker-compose.yml --env-file .env
DEV     = $(COMPOSE) -f infra/docker-compose.dev.yml

.PHONY: env up dev down logs ps test lint scrub migrate shell-api pull-model models-lock models-verify served-check

env:            ## create .env with fresh secrets (cpu profile)
	python scripts/gen_env.py

up:             ## build + start the full stack (profile from .env)
	$(COMPOSE) up --build --wait

dev:            ## start with hot reload
	$(DEV) up --build

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f --tail=200

ps:
	$(COMPOSE) ps

migrate:        ## apply alembic migrations inside the api container
	$(COMPOSE) exec api alembic upgrade head

shell-api:
	$(COMPOSE) exec api bash

pull-model:     ## cpu profile: pull the default Ollama model once
	$(COMPOSE) exec ollama ollama pull $${LLM_MODEL:-qwen2.5:7b-instruct}

models-lock:    ## gpu profile: record the model bundle, e.g. ARGS="--base Qwen/Qwen3.5-9B@REV --adapter reviewer-pilot-9b-v1"
	python scripts/models.py lock $(ARGS)

models-verify:  ## gpu profile: check data/models and .env against infra/models.lock.json (ARGS=--quick for sizes only)
	python scripts/models.py verify $(ARGS)

served-check:   ## release gate: replay an adapter's cluster evaluation against the running server, e.g. ADAPTER=reviewer-pilot-9b-v1 MODEL=reviewer
	python -m evaltrain.served_check --adapter-dir data/models/adapters/$(ADAPTER) --model $(MODEL) --base-url http://127.0.0.1:8001/v1

test:           ## unit tests (no database needed)
	$(COMPOSE) exec -T api python -m pytest -q

lint:
	$(COMPOSE) exec -T api ruff check . --select F
	cd apps/web && npm run lint

scrub:          ## denylist + secrets scan
	bash scripts/scrub-check.sh
