# AGENTS.md — `caos-agent-harness`

## Overview
This is a deterministic multi-agent orchestration, isolated Git worktree execution, cross-family blind review, anti-reward-hacking landing gate, and mutation-tested verification harness (`Python 3.11+` + `React/TypeScript/Vite`).

## Quick Commands (Build, Test, Lint, Gate)
```bash
# Run full Python test suite (472 tests)
.venv/bin/pytest -q

# Run landing, branch integration, and autonomous cycle gate tests
.venv/bin/pytest -q tests/test_landing.py tests/test_landed.py tests/test_cycle.py

# Run mutation testing suite (26/26 mutations killed)
.venv/bin/python -m caos_harness.validation.mutation

# Build frontend UI
cd web && npm test -- --run && npm run build
```

## Architecture & Module Map
- `caos_harness/app.py` & `orchestrator.py` — Project config (`harness.toml`), DAG planner (`waves`), worker dispatch, and synthesis.
- `caos_harness/worktrees.py` — Isolated `git worktree` lifecycle, `lock_eval_paths` / `unlock_eval_paths`, `audit_reward_hacking` (blocks config tampering, test skipping, and assertion weakening with `WHAT / WHY / FIX` diagnostics), and uncommitted folder landing gate (`land`).
- `caos_harness/landed.py` — In-memory 3-way merge (`git merge-tree --write-tree`), isolated staging verification, compare-and-swap integration onto `harness/landed`, and cryptographic tree trailer audit (`audit`).
- `caos_harness/cycle.py` — Autonomous cross-review cycle (`pick_verifier` selects a different model family first, blind to test execution; `verifier_stats` tracks Wilson 95% CI catch rate).
- `caos_harness/board/core.py` — SQLite transactional task board with atomic claim and review state machine (`ok` / `redo`).
- `caos_harness/router/route.py` — Cost-of-error model router using the lower bound of the 95% Wilson confidence interval (`precision_lo`).
- `caos_harness/policy/guard.py` — Tool allow-list, path traversal guard, and relevance threshold gate.
- `caos_harness/validation/` — Fault-injection pipeline (`evaluate.py`), regression check (`regress.py`), and mutation testing (`mutation.py`).
- `web/` — React + TypeScript + Vite workstation UI (`RunView`, `Board`, `DiffViewer`, `MetricsView`, `SkillLoop`).

## Guardrails & Invariants (Do Not Violate)
1. **Evidence before "done"**: Never bypass `verify` in `worktrees.land()` or `landed.integrate()`.
2. **Anti-Reward Hacking**: Workers must never weaken assertions, inject `@pytest.mark.skip`/`xfail`, delete test files, or tamper with `harness.toml` / `thresholds.json`.
3. **Secrets & Privacy**: Never commit `.env`, API keys, or `.harness/` runtime state.
4. **Human Commit Governance**: Leave changes uncommitted unless the operator explicitly requests a commit.
