PY      ?= python3.11
VENV    := backend/.venv
BIN     := $(VENV)/bin
API_PORT ?= 8000

.PHONY: help install dev dev-fixtures api api-fixtures web test refresh refresh-dev fixtures build serve clean

help:
	@echo "make install       - create venv + install backend and frontend deps"
	@echo "make dev           - run API (real data DB) + Vite dev server"
	@echo "make dev-fixtures  - same, but offline with the synthetic fixture dataset"
	@echo "make refresh       - full-universe refresh (slow; see README)"
	@echo "make refresh-dev   - refresh ~50 well-known tickers (fast)"
	@echo "make test          - backend pytest + frontend type-check"
	@echo "make build serve   - build the frontend and serve it from FastAPI on :$(API_PORT)"

$(BIN)/python:
	$(PY) -m venv $(VENV)
	$(BIN)/pip install -q --upgrade pip

install: $(BIN)/python
	$(BIN)/pip install -q -r backend/requirements.txt
	cd frontend && npm install

api:
	cd backend && .venv/bin/uvicorn app.main:app --reload --port $(API_PORT)

api-fixtures:
	cd backend && DIVSCREEN_FIXTURES=1 .venv/bin/uvicorn app.main:app --reload --port $(API_PORT)

web:
	cd frontend && npm run dev

dev:
	@trap 'kill 0' INT TERM; $(MAKE) -s api & $(MAKE) -s web & wait

dev-fixtures:
	@trap 'kill 0' INT TERM; $(MAKE) -s api-fixtures & $(MAKE) -s web & wait

refresh:
	cd backend && .venv/bin/python -m app.refresh

refresh-dev:
	cd backend && .venv/bin/python -m app.refresh --tickers KO,JNJ,PG,MMM,T,O,AAPL,PEP,MCD,XOM,CVX,ABBV,MO,PM,VZ,IBM,MSFT,HD,LOW,TGT,WMT,CL,KMB,CAT,ADP,ITW,NEE,DUK,SO,ED,ABT,MDT,INTC,TSLA,AMZN,GOOGL,BRK-B,JPM,BAC,PFE,MRK,KHC,DOW,LYB,EPD,ENB,TROW,BEN,SWK,GPC

fixtures:
	cd backend && .venv/bin/python tests/fixtures/generate.py && .venv/bin/python -m app.refresh --fixtures

test:
	cd backend && .venv/bin/python -m pytest -q
	cd frontend && npx tsc -b

build:
	cd frontend && npm run build

serve:
	cd backend && .venv/bin/uvicorn app.main:app --port $(API_PORT)

clean:
	rm -rf backend/data/*.db* frontend/dist
