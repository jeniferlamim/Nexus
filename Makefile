ENGINE := services/engine
WEB    := apps/web
PY     := $(ENGINE)/.venv/bin/python

.PHONY: setup api web dev test test-db build

setup:            ## install backend + frontend dependencies
	python3 -m venv $(ENGINE)/.venv && $(PY) -m pip install -q -r $(ENGINE)/requirements-dev.txt
	cd $(WEB) && npm ci

api:              ## run the API on :8000 (SQLite in services/engine/data, AUTH_MODE=dev)
	cd $(ENGINE) && .venv/bin/uvicorn nexus_engine.api.app:app --reload --port 8000

web:              ## run the web app on :5173 (proxies /api to :8000)
	cd $(WEB) && npm run dev

dev:              ## API + web together
	$(MAKE) -j2 api web

test:             ## engine/API tests + frontend typecheck
	cd $(ENGINE) && .venv/bin/python -m pytest -q
	cd $(WEB) && npx tsc -b

test-db:          ## migrations + RLS tests on a PostgreSQL given by PGHOST/PGPORT/PGUSER
	./supabase/tests/run.sh

build:
	cd $(WEB) && npm run build
