"""Shell completion scripts for `caos-harness`, generated from the command tables so they cannot drift from the CLI.

    caos-harness completion bash > ~/.local/share/bash-completion/completions/caos-harness
    caos-harness completion zsh  > "${fpath[1]}/_caos_harness"
"""
from __future__ import annotations

SUBCOMMANDS = {
    "task": ["add", "list", "show"],
    "providers": ["list", "add", "test", "smoke", "failover", "ollama-hosts"],
    "share": ["doctor", "preview", "pack", "upload"],
    "worktree": ["list", "diff", "discard"],
    "completion": ["bash", "zsh"],
}
VERDICTS = ["ok", "redo", "verify", "superseded"]
# What each flag takes, when it takes one of a known set.
VALUES = {
    "--format": ["zip", "dir", "tar.gz"],
    "--profile": ["local-first", "hybrid", "cloud-max"],
    "--intent": ["rapido", "codigo", "razonar", "local"],
    "--strategy": ["sequential", "local_fallback"],
    "--kind": ["openai", "anthropic"],
}
FLAGS = {
    "task": ["--queue", "--tier", "--skill", "--all", "--json", "--watch", "--interval"],
    "run": ["--agent", "--tier", "--skill", "--intent", "--profile", "--provider", "--model", "--json"],
    "chat": ["--intent", "--profile", "--skill", "--provider", "--model", "--act", "--json"],
    "review": ["--json"],
    "discard": ["--json"],
    "status": ["--json", "--watch", "--interval"],
    "metrics": ["--project", "--global", "--md", "--json", "--watch", "--interval"],
    "orchestrate": ["--orchestrator", "--agents", "--plan-only", "--json"],
    "providers": ["--json", "--profile", "--url", "--kind", "--model", "--env", "--name", "--target", "--strategy", "--label"],
    "share": ["--format", "--dry-run", "--no-code", "--no-docs", "--no-skills", "--parent-id", "--json"],
    "doctor": ["--dry-run", "--strict", "--json"],
    "worktree": ["--json"],
    "skills": ["--json"],
    "tui": ["--resume"],
    "repl": ["--emblem"],
}


def commands() -> list[str]:
    from .__main__ import COMMANDS, WORK
    return sorted({*COMMANDS, *WORK, "skills", "trace", "help", "completion", "doctor"})


def bash() -> str:
    top = " ".join(commands())
    cases = []
    for cmd in sorted({*SUBCOMMANDS, *FLAGS}):
        subs = " ".join(SUBCOMMANDS.get(cmd, []))
        flags = " ".join(FLAGS.get(cmd, []))
        pos, first = (3, " ".join(VERDICTS)) if cmd == "review" else (2, subs or flags)   # `review <id> <verdict>`: the verdict is the third word
        cases.append(f'    {cmd}) if [[ $COMP_CWORD -eq {pos} ]]; then COMPREPLY=($(compgen -W "{first}" -- "$cur")); else COMPREPLY=($(compgen -W "{flags}" -- "$cur")); fi ;;')
    values = "\n".join(f'    {flag}) COMPREPLY=($(compgen -W "{" ".join(vals)}" -- "$cur")); return ;;' for flag, vals in VALUES.items())
    return f'''# bash completion for caos-harness (generated: caos-harness completion bash)
_caos_harness() {{
  local cur prev cmd
  cur="${{COMP_WORDS[COMP_CWORD]}}"
  prev="${{COMP_WORDS[COMP_CWORD-1]}}"
  cmd="${{COMP_WORDS[1]}}"
  COMPREPLY=()
  if [[ $COMP_CWORD -eq 1 ]]; then
    COMPREPLY=($(compgen -W "{top}" -- "$cur"))
    return
  fi
  case "$prev" in
{values}
  esac
  case "$cmd" in
{chr(10).join(cases)}
  esac
}}
complete -F _caos_harness caos-harness
'''


def zsh() -> str:
    top = " ".join(commands())
    cases = []
    for cmd in sorted({*SUBCOMMANDS, *FLAGS}):
        subs = " ".join(SUBCOMMANDS.get(cmd, []))
        flags = " ".join(FLAGS.get(cmd, []))
        pos, first = (4, " ".join(VERDICTS)) if cmd == "review" else (3, subs or flags)
        cases.append(f"    {cmd}) if (( CURRENT == {pos} )); then compadd -- {first}; else compadd -- {flags}; fi ;;")
    values = "\n".join(f"    {flag}) compadd -- {' '.join(vals)}; return ;;" for flag, vals in VALUES.items())
    return f'''#compdef caos-harness
# zsh completion for caos-harness (generated: caos-harness completion zsh)
_caos_harness() {{
  if (( CURRENT == 2 )); then
    compadd -- {top}
    return
  fi
  case "$words[CURRENT-1]" in
{values}
  esac
  case "$words[2]" in
{chr(10).join(cases)}
  esac
}}
compdef _caos_harness caos-harness
'''


def script(shell: str) -> str:
    if shell == "bash":
        return bash()
    if shell == "zsh":
        return zsh()
    raise ValueError("usage: completion bash|zsh")
