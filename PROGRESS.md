# PROGRESS.md — `caos-agent-harness`

## Current State (2026-11-14)
- **Status:** Active (Ola 3 — Anti-Reward Hacking Gate & Cross-Verifier Cycle)
- **Python Test Suite:** `472 passed` (`.venv/bin/pytest -q`)
- **Mutation Suite:** `26/26` injected mutations detected (`caos_harness/validation/mutation.py`)
- **Verification Gate:** `worktrees.land()` and `landed.integrate()` enforce secret scanning, clean staging verification, tree-hash comparison, and anti-reward-hacking diff auditing (`WHAT / WHY / FIX` structured diagnostics).

## Completed Milestones
- [x] Transactional SQLite task board (`caos_harness/board/core.py`) with atomic assignment and human/automated review loop.
- [x] Cost-of-error router (`caos_harness/router/route.py`) using Wilson 95% CI lower bound (`precision_lo`).
- [x] Isolated Git worktrees (`caos_harness/worktrees.py`) and compare-and-swap branch integration (`caos_harness/landed.py`).
- [x] Cross-family blind review cycle (`caos_harness/cycle.py`) with empirical verifier catch-rate tracking.
- [x] Ola 3 Anti-Reward Hacking Guardrail (`audit_reward_hacking`, `lock_eval_paths`, `unlock_eval_paths`, `format_diagnostic`).

## Next Steps
- [ ] Export real cycle and landing traces as interactive AG-UI micro-demos for `caosautomation.com`.
- [ ] Evaluate minimal `/.well-known/agent.json` (A2A Agent Card) descriptor for worker discovery.
