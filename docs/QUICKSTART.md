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

## 2 · Your own board (5 minutes)

```bash
mkdir my-agents && cd my-agents
caos-harness init                                           # writes harness.toml
caos-harness task add "summarise this week's notes" --queue echo
caos-harness run                                            # `echo` is `cat`: it hands the task back
caos-harness review 1 ok "it is what I asked for"           # nothing closes without a verdict
caos-harness status
caos-harness serve                                          # http://127.0.0.1:8791, same board in the browser
```

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

## 4 · Check the harness itself (needs a clone)

```bash
git clone https://gitlab.com/braynerssj26/caos-agent-harness && cd caos-agent-harness
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
make check               # 133 tests, thresholds, regression gate, demo
make mutation            # injects 26 faults and counts how many the tests catch
```

## Things to know
- The dashboard listens on loopback only and refuses writes without its own header.
- Shell commands in the workstation console are **off** until you switch them on for the session, and they are not sandboxed: they run only after you approve each one.
- `eval`, `regress`, `mutation`, `benchmark`, `agent-eval` and `calibrate` write reports, so they run from a clone.
