# Workstation console & orchestration

The web console, `caos-harness chat`, and `caos-harness orchestrate` share the same project guardrails and SQLite trace store.

## Plan, Act, and Orquestar

- **Plan** reads files and asks alignment questions without modifying the workspace or exposing shell execution tools.
- **Act** enables edits and shell commands **only** when turned on explicitly for the current session ("shell commands" switch in the browser, `chat --act` in the CLI). Every proposed write shows a diff preview first, and every shell command runs with the operator's OS permissions in the workspace folder only after explicit confirmation. The workspace is **not a container sandbox**: commands can access paths reachable by your user account.
- **Orquestar** lets a chosen orchestrator (`claude` by default, or any configured orchestrator-capable agent such as `agy`, `codex`, `opencode`, `llama`, or `qwen`) split a goal into subtasks with per-subtask acceptance criteria and isolation mode:
  - `readonly` subtasks execute in parallel inside the project workspace.
  - `isolated` subtasks execute in separate temporary `git worktree` checkouts, and the orchestrator synthesises the final answer without merging worktrees into your active branch automatically.

## Live updates, models, and providers

- The web dashboard subscribes to Server-Sent Events (`GET /api/events` and `GET /api/runs/<id>/events` backed by `EventBus`) with automatic polling fallback when `EventSource` is unavailable. Restarting the server still discards in-progress run state held in memory.
- Supported targets include local Ollama models (single or multi-host LAN), cloud API/free-tier providers configured via environment variable names or the system keyring (`OPENROUTER_API_KEY`, `GEMINI_API_KEY`, `GROQ_API_KEY`, `NVIDIA_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `DEEPSEEK_API_KEY`), CLI agents (`claude`, `codex`, `opencode`, `agy`), and sequential/local failover policies.
- Benchmarks for the classification router (`make benchmark`) measure classification precision on synthetic datasets; they do not score general shell or orchestration runs.

## Skills and publication

The workstation injects the body of the selected role skill as context for the model, not as an enforcement boundary; the policy layer and approval gates remain independent. Packaged skills under `caos_harness/skills/` are portable role instructions, and local project skills live under `.harness/skills/` or `CAOS_HARNESS_SKILLS` without entering the repository.
