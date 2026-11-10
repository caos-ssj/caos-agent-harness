"""Using the harness on real work: a project folder with a `harness.toml`, agents that are commands, and a persistent board.

    caos-harness init                         # writes harness.toml and .harness/
    caos-harness task add "…" --queue local   # or --tier high: the router picks the agent, or a person
    caos-harness run                          # sends what is pending to idle agents and stores what they deliver
    caos-harness review 3 ok "ran the tests"  # nothing is closed without a verdict

An agent is any command that reads the task on stdin and writes its result on stdout (`ollama run <model>`, a script,
a CLI agent in non-interactive mode). The harness adds what the command does not have: the queue, the claim before
sending, the timeout, the review step and the trace.
"""
from __future__ import annotations

import subprocess
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .board.core import Board, DispatchTimeout
from .router.route import choose, load_profiles, load_tiers
from .skills import known
from .traces.store import Trace

CONFIG = "harness.toml"
PERSON = "person"
EXAMPLE = '''# caos-agent-harness project file. Paths are relative to this file.
[board]
db = ".harness/board.db"
trace = ".harness/trace.db"

# An agent is a command: the task arrives on stdin, the result is whatever it prints.
# `system` names the measured system the agent runs (see `caos-harness route`); the router uses it for --tier.
[agents.echo]
command = ["cat"]
timeout = 30

# [agents.local]
# command = ["ollama", "run", "qwen2.5:7b"]
# system = "qwen2.5:7b"
# timeout = 300
'''


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Agent:
    name: str
    command: tuple
    timeout: float = 300.0
    system: str | None = None


@dataclass
class Project:
    root: Path
    db: Path
    trace_path: Path
    agents: dict[str, Agent]
    _board: Board | None = field(default=None, repr=False)

    @property
    def board(self) -> Board:
        if self._board is None:
            self.db.parent.mkdir(parents=True, exist_ok=True)
            self._board = Board(self.db, trace=Trace(self.trace_path))
        return self._board


def find_config(start: Path | None = None) -> Path:
    here = (start or Path.cwd()).resolve()
    for d in (here, *here.parents):
        if (d / CONFIG).is_file():
            return d / CONFIG
    raise ConfigError(f"no {CONFIG} here or above: run `caos-harness init`")


def load(path: Path | None = None) -> Project:
    path = path or find_config()
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: {e}") from e
    root = path.parent
    agents = {}
    for name, a in (raw.get("agents") or {}).items():
        cmd = a.get("command")
        if name == PERSON:
            raise ConfigError(f"'{PERSON}' is the queue of the human reviewer; name the agent something else")
        if not isinstance(cmd, list) or not cmd or not all(isinstance(x, str) for x in cmd):
            raise ConfigError(f"agents.{name}.command must be a non-empty list of strings")
        agents[name] = Agent(name, tuple(cmd), float(a.get("timeout", 300)), a.get("system"))
    b = raw.get("board") or {}
    return Project(root, root / b.get("db", ".harness/board.db"), root / b.get("trace", ".harness/trace.db"), agents)


def init(folder: Path) -> Path:
    path = folder / CONFIG
    if path.exists():
        raise ConfigError(f"{path} already exists")
    path.write_text(EXAMPLE, encoding="utf-8")
    (folder / ".harness").mkdir(exist_ok=True)
    return path


class CommandDispatcher:
    """Runs the agent's command with the task on stdin. What it prints is kept until the board accepts the delivery."""
    def __init__(self, project: Project, runner=subprocess.run):
        self.project, self.runner, self.outputs = project, runner, {}

    def is_idle(self, agent: str) -> bool:
        return agent in self.project.agents  # commands run one at a time in `run`, so a known agent is free between tasks

    def send(self, agent: str, text: str) -> None:
        a = self.project.agents[agent]
        try:
            r = self.runner(list(a.command), input=text, capture_output=True, text=True, timeout=a.timeout, cwd=self.project.root)
        except subprocess.TimeoutExpired as e:
            raise DispatchTimeout(f"{agent} did not finish in {a.timeout:g}s") from e
        if r.returncode != 0:
            raise RuntimeError(f"{agent} exited with {r.returncode}: {(r.stderr or '').strip()[:200]}")
        self.outputs[agent] = r.stdout.strip()


def add_task(p: Project, text: str, queue: str | None = None, skill: str | None = None, tier: str | None = None) -> tuple[int, str, str]:
    """Returns (task id, queue, why). With `tier`, the router decides: the agent that runs the chosen system, or a person."""
    if skill and not known(skill):
        raise ConfigError(f"unknown skill: {skill}")
    why = "queue given"
    decision = None
    if tier:
        tiers = load_tiers()
        if tier not in tiers:
            raise ConfigError(f"unknown tier: {tier} (one of {', '.join(tiers)})")
        decision = choose(load_profiles(), tiers[tier])
        runs = [a.name for a in p.agents.values() if a.system and a.system == decision.system]
        if decision.action != "route":
            queue, why = PERSON, decision.reason
        elif not runs:
            queue, why = PERSON, f"router chose {decision.system}, and no agent in {CONFIG} runs it"
        else:
            queue, why = runs[0], f"router chose {decision.system}: {decision.reason}"
    elif queue is None:
        raise ConfigError("give --queue or --tier")
    elif queue != PERSON and queue not in p.agents:
        raise ConfigError(f"unknown agent: {queue} (agents: {', '.join(p.agents) or 'none'})")
    tid = p.board.add(text, queue=queue, skill=skill)
    if decision and p.board.trace:
        p.board.trace.event(f"task:{tid}", "router", "decision", decision.system or "", "route" if queue != PERSON else "human_review", why, tier=tier)
    return tid, queue, why


def run_pending(p: Project, only: str | None = None, dispatcher: CommandDispatcher | None = None) -> list[dict]:
    """Sends every pending task to its agent, one at a time, and stores what the agent printed as the delivery."""
    d = dispatcher or CommandDispatcher(p)
    done = []
    for t in p.board.pending():
        agent = t["queue"]
        if agent == PERSON or agent not in p.agents or (only and agent != only):
            continue
        res = p.board.assign(t["id"], agent, d)
        if res.ok:
            p.board.deliver(t["id"], d.outputs.pop(agent, ""))
        done.append({"id": t["id"], "agent": agent, "ok": res.ok, "reason": res.reason})
    return done
