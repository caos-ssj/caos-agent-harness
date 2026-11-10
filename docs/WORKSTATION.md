# Local workstation

The web console and `caos-harness chat` use the same Ollama workstation engine.
Select an installed Ollama model. Plan mode does not expose command tools. Act is
**off by default**: switch "shell commands" on for the session you are in (the switch
lives in the server's memory and resets on restart; `chat --act` is the CLI equivalent
for one invocation). In Act,
the model may propose a command; the operator sees the exact command and decides
whether to run it. Commands run with the server's operating-system privileges in
the project directory. The directory is **not a sandbox**: shell commands can
access other paths and the network. Review commands before approval.

Example: `caos-harness chat --model qwen3.5:4b --act "Inspect the project"`.
The terminal requests approval for each proposed command; a noninteractive
terminal rejects proposals. The browser polls the current run and can reconnect
while the server remains running. Restarting the server loses in-progress run
state; do not automatically retry a command whose result is unknown.

Only Ollama is wired to this console. Cloud providers, automatic failover,
cross-repository execution, streaming tokens and autonomous routing are not
implemented. The conversation retains a bounded recent text history; command
results are stored in the local session file. Do not place credentials in prompts
or tool output. The project board's router measurements are not evidence of
command-execution accuracy.

## Skills and publication

The workstation injects the body of the packaged role skill for an explicitly
selected role. This is context for the model, not an enforcement mechanism; the
command approval gate is independent. The packaged skills are portable drafts
adapted from CAOS practices, not an export of private vault notes. Additional
skills are listed by `caos-harness skills` and are not automatically loaded by
the workstation. Review their wording, ownership, license and current business
policy before publishing; this change does not publish anything. Benchmarks for
the existing classification router do not validate the new workstation roles.
