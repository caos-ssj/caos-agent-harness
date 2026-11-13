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

import os
import re
import signal
import subprocess
import threading
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .board.core import Board, DispatchTimeout, SafeDispatchError
from .router.route import choose, load_profiles, load_tiers
from .skills import known
from .traces.store import Trace

CONFIG = "harness.toml"
PROMPT_SLOT = "{prompt}"     # in an agent's command: replaced by the task, as one argument
MAX_ARG_BYTES = 100_000      # Linux refuses a single argument over 128 KiB
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
    provider: str | None = None   # "anthropic" | "openai": an API agent, no command (see providers.py)
    model: str | None = None
    key_env: str | None = None    # the NAME of the environment variable that holds the key, never the key
    cost: str | None = None       # "free" | "cheap" | "paid": what a call costs; unset, the harness infers it (see scout.cost_tier)


@dataclass
class Project:
    root: Path
    db: Path
    trace_path: Path
    agents: dict[str, Agent]
    _board: Board | None = field(default=None, repr=False)
    _board_lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)
    _busy: set = field(default_factory=set, repr=False, compare=False)          # agents that are running something right now
    _agent_locks: dict = field(default_factory=dict, repr=False, compare=False)  # one lock per agent: the same agent never overlaps itself
    _reserved: set = field(default_factory=set, repr=False, compare=False)      # task ids an orchestration is running itself: `run` leaves them alone
    _mu: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def agent_lock(self, agent: str) -> threading.Lock:
        with self._mu:
            return self._agent_locks.setdefault(agent, threading.Lock())

    @property
    def board(self) -> Board:
        with self._board_lock:   # two request threads asking first must share one connection, not open two against the same file
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
        provider = a.get("provider")
        if provider is not None:
            from .providers import API, MODEL
            if provider not in API:
                raise ConfigError(f"agents.{name}.provider must be one of {', '.join(API)}")
            if not isinstance(a.get("model"), str) or not MODEL.fullmatch(a["model"]):
                raise ConfigError(f"agents.{name}.model must be a model name")
            if a.get("api_key") or a.get("key"):
                raise ConfigError(f"agents.{name}: keys are not stored in harness.toml; give key_env, the NAME of the environment variable")
            kenv = a.get("key_env")
            if kenv is not None and not (isinstance(kenv, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{2,63}", kenv)):
                raise ConfigError(f"agents.{name}.key_env must be an environment variable name, like ANTHROPIC_API_KEY")
            agents[name] = Agent(name, (), float(a.get("timeout", 300)), a.get("system"), provider, a["model"], kenv, a.get("cost"))
            continue
        if not isinstance(cmd, list) or not cmd or not all(isinstance(x, str) for x in cmd):
            raise ConfigError(f"agents.{name}.command must be a non-empty list of strings")
        agents[name] = Agent(name, tuple(cmd), float(a.get("timeout", 300)), a.get("system"), cost=a.get("cost"))
    b = raw.get("board") or {}
    return Project(root, root / b.get("db", ".harness/board.db"), root / b.get("trace", ".harness/trace.db"), agents)


def init(folder: Path) -> Path:
    path = folder / CONFIG
    if path.exists():
        raise ConfigError(f"{path} already exists")
    path.write_text(EXAMPLE, encoding="utf-8")
    (folder / ".harness").mkdir(exist_ok=True)
    return path


class ProcessGroup:
    """A callable runner that tracks started subprocesses and terminates them on cancel."""
    def __init__(self):
        self._procs: set[subprocess.Popen] = set()
        self._lock = threading.Lock()
        self._cancelled = False

    def __call__(self, cmd, input="", capture_output=True, text=True, timeout=None, cwd=None, **kwargs):
        with self._lock:
            if self._cancelled:
                raise RuntimeError("Process group is cancelled")
            p = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE if input is not None else None,
                stdout=subprocess.PIPE if capture_output else None,
                stderr=subprocess.PIPE if capture_output else None,
                text=text,
                cwd=cwd,
                start_new_session=True,
                **kwargs,
            )
            self._procs.add(p)
        try:
            stdout, stderr = p.communicate(input=input, timeout=timeout)
            return subprocess.CompletedProcess(cmd, p.returncode, stdout, stderr)
        except subprocess.TimeoutExpired:
            self._terminate_proc(p)
            raise
        except Exception:
            self._terminate_proc(p)
            raise
        finally:
            with self._lock:
                self._procs.discard(p)

    def _terminate_proc(self, p: subprocess.Popen) -> None:
        try:
            os.killpg(os.getpgid(p.pid), signal.SIGTERM)
        except Exception:
            try:
                p.terminate()
            except Exception:
                pass

    def cancel(self) -> None:
        with self._lock:
            self._cancelled = True
            procs = list(self._procs)
        for p in procs:
            self._terminate_proc(p)


class CommandDispatcher:
    """Runs the agent's command with the task on stdin. What it prints is kept until the board accepts the delivery."""
    def __init__(self, project: Project, runner=subprocess.run, transport=None, cwd: Path | None = None, override: dict | None = None):
        from .providers import http
        self.project, self.runner, self.outputs, self.transport = project, runner, {}, transport or http
        self.cwd = cwd   # where the command runs: the project folder, or an isolated checkout for a subtask that edits
        self.override = override or {}   # agent name -> Agent to run instead (the orchestrator asks its agent in a read-only form)

    def is_idle(self, agent: str) -> bool:
        """A known agent is idle unless it is running something right now; different agents are idle at the same time and run in parallel."""
        with self.project._mu:
            return agent in self.project.agents and agent not in self.project._busy

    def send(self, agent: str, text: str) -> None:
        with self.project.agent_lock(agent):   # the same agent never runs two things at once, even if two callers got here together
            with self.project._mu:
                self.project._busy.add(agent)
            try:
                self._send(agent, text)
            finally:
                with self.project._mu:
                    self.project._busy.discard(agent)

    def _send(self, agent: str, text: str) -> None:
        a = self.override.get(agent) or self.project.agents[agent]
        if a.provider:   # an API agent: call that provider, falling back cleanly if failover is enabled
            from . import providers
            try:
                try:
                    key, _ = providers.key_for(a.provider, a.key_env, root=self.project.root)
                except TypeError:
                    key, _ = providers.key_for(a.provider, a.key_env)
            except providers.ProviderError as e:
                raise SafeDispatchError(str(e)) from None
            env_label = a.key_env or providers.API[a.provider]["env"]
            if not key:
                fo = providers.load_failover(self.project.root)
                if fo.get("enabled") and fo.get("fallback_target"):
                    key = ""
                else:
                    raise SafeDispatchError(f"no key for {a.provider}: set {env_label} where `caos-harness` starts")
            try:
                if key:
                    self.outputs[agent] = providers.ask(a.provider, a.model, text, key, a.timeout, self.transport, root=self.project.root).strip()
                    return
                raise providers.ProviderError(f"no key for {a.provider}: set {env_label}")
            except providers.ProviderError as e:
                fo = providers.load_failover(self.project.root)
                fb_target = fo.get("fallback_target") if fo.get("enabled") else None
                fb_model = fo.get("fallback_model") or a.model
                if fb_target:
                    from .engines.llm import ProviderChat
                    try:
                        reply = ProviderChat(fb_target, fb_model, timeout=a.timeout, transport=self.transport, root=self.project.root).chat(
                            [{"role": "user", "content": text}], []
                        )
                        self.outputs[agent] = str(reply.get("content") or "").strip()
                        return
                    except Exception:
                        pass
                raise SafeDispatchError(str(e)) from None
        cmd, stdin = list(a.command), text
        if PROMPT_SLOT in cmd:   # a CLI that takes the prompt as an argument: it is one argv element, never parsed by a shell
            if len(text.encode("utf-8")) > MAX_ARG_BYTES:
                raise SafeDispatchError(f"the task is too long to pass as an argument to {agent}")
            cmd, stdin = [text if part == PROMPT_SLOT else part for part in cmd], ""
        try:
            r = self.runner(cmd, input=stdin, capture_output=True, text=True, timeout=a.timeout, cwd=self.cwd or self.project.root)
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


def run_pending(p: Project, only: str | None = None, dispatcher: CommandDispatcher | None = None, max_workers: int = 4) -> list[dict]:
    """Sends every pending task to its agent and stores what the agent printed as the delivery. Different agents work at the same time
    (up to `max_workers`); the tasks of one agent go one after the other, so an agent is never asked twice at once. A dispatcher that is
    not the harness's own may not be thread-safe, so it keeps the old one-at-a-time order."""
    d = dispatcher or CommandDispatcher(p)
    order, lanes = [], {}
    for t in p.board.pending():
        agent = t["queue"]
        if agent == PERSON or agent not in p.agents or (only and agent != only) or t["id"] in p._reserved:
            continue
        order.append(t["id"])
        lanes.setdefault(agent, []).append(t["id"])
    workers = max_workers if isinstance(d, CommandDispatcher) else 1

    def lane(agent: str) -> list[dict]:
        out = []
        for tid in lanes[agent]:
            dd = d
            wk = p.board.get(tid)["worktree_key"]   # a subtask returned for a fix goes back into the checkout it worked in
            if wk and isinstance(d, CommandDispatcher) and not d.cwd:
                from . import worktrees
                wt = worktrees.get(p.root, wk)
                if wt:
                    dd = CommandDispatcher(p, d.runner, d.transport, cwd=Path(wt["path"]))
            res = p.board.assign(tid, agent, dd)
            if res.ok:
                p.board.deliver(tid, dd.outputs.pop(agent, ""))
            out.append({"id": tid, "agent": agent, "ok": res.ok, "reason": res.reason})
        return out

    done: dict[int, dict] = {}
    if workers <= 1 or len(lanes) <= 1:
        for agent in lanes:
            for r in lane(agent):
                done[r["id"]] = r
    else:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=min(workers, len(lanes))) as pool:
            for rs in pool.map(lane, list(lanes)):
                for r in rs:
                    done[r["id"]] = r
    return [done[i] for i in order if i in done]


def task_state(r) -> str:
    """The state a row is in, in the words the dashboard uses (see `web.server.task_row`)."""
    if r["status"] == "sent":
        return r["review"] if r["review"] in ("ok", "superseded", "verify") else ("to_review" if r["result"] is not None else "sent")
    if r["status"] == "pending":
        return "person" if r["queue"] == PERSON else ("returned" if r["review"] == "redo" else "pending")
    return r["status"]


def summary(p: Project) -> dict:
    """What the operator needs to know at a glance: counts only, no task text."""
    rows = p.board.rows()
    states = [task_state(r) for r in rows]
    return {"tasks": len(rows), "needs_you": sum(s in ("to_review", "verify", "person") for s in states),
            "to_review": sum(s in ("to_review", "verify") for s in states), "with_person": states.count("person"),
            "runnable": sum(s in ("pending", "returned") for s in states), "agents": len(p.agents)}


def run_task(p: Project, tid: int, dispatcher: CommandDispatcher | None = None) -> dict:
    """Sends one task to its agent and stores what the agent printed. A task in the person's queue is not sent: it waits."""
    t = p.board.get(tid)
    agent = t["queue"]
    if agent == PERSON or agent not in p.agents:
        return {"id": tid, "agent": agent, "ok": False, "person": agent == PERSON, "reason": "waiting for a person" if agent == PERSON else f"no agent {agent}", "result": None}
    d = dispatcher or CommandDispatcher(p)
    res = p.board.assign(tid, agent, d)
    out = None
    if res.ok:
        out = d.outputs.pop(agent, "")
        p.board.deliver(tid, out)
    return {"id": tid, "agent": agent, "ok": res.ok, "person": False, "reason": res.reason, "result": out}
