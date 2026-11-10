# Unit tests, the validation eval and the regression gate need only Python 3.10+ and pytest.
# The agent eval needs Ollama and a checkout of caos-cerebro with its .venv (CEREBRO=/path).
CEREBRO ?= $(HOME)/repos/caos-cerebro-producto
PY ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
AGENT_PY ?= .venv/bin/python   # needs mcp (and langgraph for ENGINE=langgraph): python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
ENGINE ?= native
MODEL ?= qwen2.5:7b
export CEREBRO_DIR := $(CEREBRO)

test:
	$(PY) -m pytest -q
eval:            ## validation pipeline against acceptance thresholds (exits 1 if they fail)
	$(PY) -m caos_harness.validation.evaluate
regress:         ## regression gate against reports/validation/baseline.json
	$(PY) -m caos_harness.validation.regress
mutation:        ## do the tests catch injected faults?
	$(PY) -m caos_harness.validation.mutation
demo:            ## board end to end with synthetic tasks and simulated agents (no model needed)
	$(PY) -m caos_harness.board.demo
route:           ## which measured system each cost-of-error tier gets (router.json)
	$(PY) -m caos_harness.router.route
check: test eval regress demo route
benchmark:
	$(PY) -m caos_harness.validation.benchmark $(MODELS) --hybrid
agent-eval:      ## agent over a real MCP server vs plain retrieval
	$(AGENT_PY) -m caos_harness.agent_eval.evaluate --model $(MODEL) --engine $(ENGINE) --n 20
calibrate:
	$(AGENT_PY) -m caos_harness.agent_eval.calibrate
web:             ## build the web dashboard (React + TS + Vite to caos_harness/web/dist)
	cd web && npm run build
serve:           ## launch the local control plane dashboard on 127.0.0.1:8791
	$(PY) -m caos_harness serve
.PHONY: route demo chart test eval regress mutation check benchmark agent-eval calibrate web serve
chart:           ## redraw docs/agent-results.svg from reports/agent/*.json
	$(PY) tools/chart.py reports/agent docs/agent-results.svg
