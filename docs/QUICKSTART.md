# Try it on your own computer

You need Python 3.11 or newer and git. No account, no API key, no model: everything below runs offline.

## 1 · Install (2 minutes)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install git+https://gitlab.com/braynerssj26/caos-agent-harness.git
caos-harness demo        # the whole flow with two simulated agents: router, validation, review
caos-harness route       # which measured system each cost-of-error tier gets
```

`demo` ends with `PASS every task ends reviewed or with a person`. If it does not, open an issue with the output.

Before you trust a folder, ask it whether it is ready. `caos-harness doctor` answers `ready`, `warning` or `blocked`, says what to do next, and spends no tokens; with `--dry-run` it does not touch the network either:

```bash
caos-harness doctor --dry-run          # project, agents, board, keys, MCP, git, and a scan for leaked secrets
caos-harness doctor --json             # the same, as data (exit 0 ready or warning, 1 blocked; --strict also fails on warning)
```

## 2 · Your own board (5 minutes)

```bash
mkdir my-agents && cd my-agents
caos-harness init                                           # writes harness.toml
caos-harness task add "summarise this week's notes" --queue echo
caos-harness run                                            # `echo` is `cat`: it hands the task back
caos-harness review 1 ok "it is what I asked for"           # nothing closes without a verdict
caos-harness status                                         # add --watch to keep it on screen
caos-harness serve                                          # http://127.0.0.1:8791, same board in the browser
```

On a terminal the output is drawn with rounded panels and aligned tables; piped, or with `NO_COLOR`, it is the plain text scripts read, and `--json` gives data. Tab completion: `caos-harness completion bash` or `zsh` prints the script.

An agent is any command that reads the task on stdin and prints its result. Edit `harness.toml` to point one at a real tool:

```toml
[agents.local]
command = ["ollama", "run", "qwen2.5:7b"]      # or a script, or a CLI agent in non-interactive mode
system = "qwen2.5:7b"                           # the measured system the router may choose for --tier
timeout = 300
```

Then `caos-harness task add "…" --tier high` lets the router pick the agent, or a person if none is measured well enough.

## 3 · Add your own role skills

Put `my-skill/SKILL.md` (with `name` and `description` in the front matter) under `.harness/skills/` in your project, or point `CAOS_HARNESS_SKILLS` at a folder. `caos-harness skills` lists them and marks yours as local. They never leave your machine.

## 4 · Models: local first, and free tiers when you want a cloud

Ollama models on this machine need no key and no account. `caos-harness providers list` counts them and lists the cloud providers; on a terminal it also shows which model each intention (`rapido`, `codigo`, `razonar`, `local`) would use, and `--json` gives all of it as data. `--profile local-first|hybrid|cloud-max` bends that choice toward privacy or toward quality; `chat` takes it too, and `run` takes it together with `--intent`.

A cloud provider is only a variable name plus a key you keep out of the repository:

| Provider | Variable | Free models the dashboard offers as one click |
|---|---|---|
| OpenRouter | `OPENROUTER_API_KEY` | `openrouter/free` and the `:free` models |
| Google Gemini | `GEMINI_API_KEY` | `gemini-3.8-flash` and two others |
| Groq | `GROQ_API_KEY` | `openai/gpt-oss-120b`, `openai/gpt-oss-20b` and one more |
| NVIDIA NIM | `NVIDIA_API_KEY` | `deepseek-ai/deepseek-v4-flash` and four more |
| Anthropic, OpenAI, DeepSeek | `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `DEEPSEEK_API_KEY` | none listed by the dashboard |

```bash
# put NVIDIA_API_KEY=… in .harness/.env.local (gitignored), or use the Key button in Models & Providers,
# which writes it there (mode 0600) or into the system keyring if you have one
caos-harness providers test nvidia                        # does the key work?  `smoke nvidia` runs a real one-turn check (latency, JSON, tools)
```

A free tier has its own rate limits, and some providers say free content may improve their products: do not send client or private data through it. Each provider's hint is shown on its card. The **OpenCode CLI** (`opencode`) can be added as an agent with one of its `opencode/*-free` models; the dashboard lists the four it knows.

## 5 · Check the harness itself (needs a clone)

```bash
git clone https://gitlab.com/braynerssj26/caos-agent-harness && cd caos-agent-harness
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
make check               # 394 tests, thresholds, regression gate, demo, router table
make mutation            # optional and slow: injects 26 faults and counts how many the tests catch
cd web && npm test && npm run build     # 35 dashboard tests, then the bundle the server ships
```

## 5b · Multi-agent orchestration (`orchestrate` & `Orquestar`)

```bash
# Inspect the proposed subtask plan and acceptance criteria without sending to workers
caos-harness orchestrate "Audit endpoints and expand tests" --plan-only

# Execute with an explicit orchestrator and parallel subagent pool
caos-harness orchestrate "Audit endpoints and expand tests" --orchestrator claude --agents opencode,agy,qwen
```

In the Console's **Orquestar** mode, you can pick the orchestrator (`claude` by default, or any configured agent such as `agy`, `codex`, `opencode`, `llama`, `qwen`), review and edit every subtask's agent, skill, mode (`Lectura (paralelo)` vs `Edición (worktree)`), prompt and critical acceptance criterion before launching, watch parallel runs stream over SSE (`EventSource`), and review the final synthesis alongside grouped parent/child tasks on the Board.

`make check` also writes `reports/validation/regress.json`, which is what the dashboard's *Gates repo* figure reads: until it has run, the dashboard says `sin verificar` rather than guess.

## Things to know
- The dashboard listens on loopback only and refuses writes without its own header.
- Shell commands in the workstation console are **off** until you switch them on for the session, and they are not sandboxed: they run only after you approve each one.
- `eval`, `regress`, `mutation`, `benchmark`, `agent-eval` and `calibrate` write reports, so they run from a clone.

## The dashboard in two minutes

`caos-harness serve`, then open http://127.0.0.1:8791. Six views, one header, one `Proyecto | Global` switch:

| View | What it is for |
|---|---|
| **Console** | A conversation in `Plan` (reads and asks) or `Act` (changes files; each write shows its diff and waits for you). `Ctrl+M` chooses the engine: the router's intentions, every Ollama model, and the cloud free tiers with their key form inline. `/` picks a skill. The Inspector holds files, diff (unified or split, with review comments sent together), the steps of the run and the isolated worktrees. |
| **Board** | Tasks and their verdicts. With nothing selected it shows what waits for you and what happened since your last visit; under `Global` it lists the open tasks of every registered project, read only, and a click opens that project. |
| **Models & Providers** | Every installed model with its measured precision, the cloud providers with their keys, the CLI agents, the router and failover, and a side-by-side comparison of two engines (local against local runs directly; a cloud side asks first). |
| **Metrics** | Success, human returns, p50, tokens and the repository gates; a trend drawn from real runs (it says so when there are fewer than five); which model answers each risk tier; degrade or restore a model. |
| **Skills & Tools** | Skills by category, with a Markdown preview. A bundled skill is read only: *Clonar a Proyecto* copies it to `.harness/skills/` so you can edit it. MCP servers and harness tools are on their own tab. |
| **Share / Team** | A preview of exactly what a Share Pack would hold (included, generated, left out and why, private paths rewritten), the Doctor, and the commands a teammate runs. |

Isolated worktrees (`Worktree` in Console) never merge into your branch: read what changed, export it as a `.patch`, or let *Limpiar integrados* remove the ones whose work is already in the base. The sidebar footer shows the preflight; its drawer lists each check and takes you to the key that is missing.

A new project shows a *Primeros pasos* guide on the Board: add a task, run it, review what came back. Each step is checked off by what the board holds, not by what you clicked. Press `⌘K` to jump anywhere, `n` to write a task, `j` / `k` to move through them. To look around without any model, build the sample project (`python3 tools/seed_demo.py /tmp/harness-demo`) and serve that folder: the header shows a `demo` chip.

## The terminal session

`cd <your project> && caos-harness` opens a full-screen conversation with five tabs, `F1` to `F5`: Chat, Board, Providers, Metrics, Skills and Share. Type a prompt for the chosen agent (or a local model), `Ctrl-P` chooses another, `@file` attaches a file, `Ctrl-A` starts accepting the delivery (you give the reason), `Ctrl-B` opens the board, `?` lists every key. In `Plan`, when the agent asks alignment questions, `1` to `4` answer them: each press moves that question to its next option and writes the picks into the composer for you to read and send. From 120 columns the Board shows the list and the open task side by side, and Skills shows the skill in full beside the Doctor and the Share Pack.

`/skin night|ember|mono` changes the colours (`night` is the same copper palette as the dashboard). For one-off use from a script: `caos-harness run "…" --agent <name>` prints the delivery. `CAOS_TUI=0 caos-harness` opens the line-mode session instead; inside it `/doctor`, `/pack zip|dir|tar.gz`, `/probe` and `/help` match the commands above.
